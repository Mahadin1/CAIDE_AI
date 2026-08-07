"""DataScope backend — FastAPI service (adaptive EDA platform).

Responsibilities:
  * /analyze          — validate + queue an analysis job (returns job_id now)
  * /analyze/plan     — synchronous fingerprint + proposed plan preview
  * /jobs/{id}        — poll job status/progress for the async worker
  * /reports/{id}/*   — PDF/HTML/cleaned-data exports + drill-down subset
  * /webhooks/paddle  — subscription webhooks (unchanged)
  * /health           — liveness

Async model: the worker (worker.py) consumes an in-process asyncio queue.
Jobs are `uploads` rows advanced through explicit stages that the frontend
polls. No request ever blocks on analysis compute.
"""
from __future__ import annotations

import asyncio
import logging
import uuid as uuid_lib
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import agent
import db as db_ops
import pdf
from clean import clean_dataframe, dataframe_to_csv_bytes, subset_rows
from config import settings
from storage_utils import download_source
from eda.errors import FriendlyError, error_status
from export_html import build_html
from webhooks import router as paddle_router
from worker import worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("datascope")

_KNOWN_FORMATS = {
    "csv", "tsv", "xlsx", "xls", "ods", "json", "jsonl", "parquet",
    "feather", "txt",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Recover interrupted jobs, then start consuming.
    await worker.recover()
    worker.start()
    logger.info("EDA worker started (jobs running: %s)", worker.running_jobs)
    yield
    await worker.stop()


app = FastAPI(title="DataScope API", version="2.0.0", lifespan=lifespan)
app.include_router(paddle_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # narrowed at deploy time via env if needed
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AnalyzePlanRequest(BaseModel):
    user_id: str
    upload_id: str
    storage_path: str
    filename: str = ""
    overrides: dict[str, Any] | None = None


class AnalyzeRequest(BaseModel):
    user_id: str
    upload_id: str
    overrides: dict[str, Any] | None = None


class UploadSaveRequest(BaseModel):
    user_id: str
    upload_id: str
    storage_path: str
    filename: str = ""
    file_size_bytes: int | None = None


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str


class RetryRequest(BaseModel):
    user_id: str
    upload_id: str


class AccountDeleteRequest(BaseModel):
    user_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_config() -> None:
    if not settings.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backend is not configured (missing SUPABASE / OPENROUTER vars)",
        )


def _check_ownership(upload: dict[str, Any], user_id: str) -> None:
    if upload["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This upload does not belong to you",
        )


def _check_quota(client, user_id: str) -> None:
    """Server-side credit enforcement (never trust the UI).

    Every plan is credit-based and finite: one analysis consumes one credit.
    Credits reset monthly per the plan's allowance (see config.plan_monthly_credits).
    """
    profile = db_ops.get_profile(client, user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    credits = int(profile.get("credits") or 0)
    if credits <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "You're out of analysis credits for this month. "
                "Upgrade to a larger plan, or wait for your monthly credit "
                "reset."
            ),
        )


def _check_pro(client, user_id: str) -> None:
    profile = db_ops.get_profile(client, user_id)
    if profile is None or profile.get("plan") != "pro":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This feature requires a Pro subscription",
        )


def _parse_upload_id(raw: str) -> str:
    try:
        return str(uuid_lib.UUID(raw))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="upload_id must be a valid UUID",
        ) from None


def _friendly_response(exc: FriendlyError) -> JSONResponse:
    return JSONResponse(status_code=error_status(exc.kind), content=exc.to_dict())


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "worker_running": worker._consumer is not None and not worker._consumer.done(),
        "jobs_running": worker.running_jobs,
    }


# ---------------------------------------------------------------------------
# Plan preview (synchronous) + analyze (async job)
# ---------------------------------------------------------------------------

@app.post("/uploads", response_model=dict)
async def save_upload(req: UploadSaveRequest) -> dict[str, Any]:
    """Register a newly uploaded file in the Files section (status='ready').

    This is a *save only* operation: nothing is profiled or queued here. The
    user opens the file and decides what to do with it on its own page.
    """
    _require_config()
    client = db_ops.get_client()
    upload_id = _parse_upload_id(req.upload_id)

    prefix = f"uploads/{req.user_id}/"
    if not req.storage_path.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="storage_path does not belong to this user",
        )
    existing = db_ops.get_upload(client, str(upload_id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This file has already been saved.",
        )
    fmt = req.filename.rsplit(".", 1)[-1].lower() if req.filename else None
    row = db_ops.insert_upload_file(
        client,
        upload_id,
        req.user_id,
        req.filename or req.storage_path.rsplit("/", 1)[-1],
        req.storage_path,
        file_size_bytes=req.file_size_bytes,
        source_format=fmt if fmt in _KNOWN_FORMATS else None,
    )
    return {
        "id": row["id"],
        "status": row["status"],
        "filename": row["filename"],
        "storage_path": row["storage_path"],
        "created_at": row["created_at"],
    }


@app.post("/analyze/plan", response_model=dict)
async def analyze_plan(req: AnalyzePlanRequest) -> dict[str, Any]:
    """Download the file, profile it, and produce an LLM analysis plan for
    user review. Creates the upload row in 'review' state so the plan is
    persisted and the follow-up /analyze call does not re-plan."""
    _require_config()
    client = db_ops.get_client()

    upload_id = _parse_upload_id(req.upload_id)
    prefix = f"uploads/{req.user_id}/"
    if not req.storage_path.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="storage_path does not belong to this user",
        )
    _check_quota(client, req.user_id)

    content = download_source(client, req.storage_path)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found in storage",
        )

    prepared = await asyncio.to_thread(
        agent.prepare, content, req.filename or "", req.storage_path
    )
    try:
        # Prior-report context so the planner can propose distribution_drift.
        prior_report = db_ops.get_most_recent_report(
            client, req.user_id, exclude_upload_id=str(upload_id)
        )
        await asyncio.to_thread(
            agent.attach_prior_context, prepared, prior_report
        )
        await agent.plan_file(prepared, req.overrides)

        overrides = req.overrides or {}
        # The upload row already exists when the file was saved first (status
        # 'ready'); plan again just updates its metadata. Otherwise insert.
        existing = db_ops.get_upload(client, str(upload_id))
        if existing is None:
            db_ops.insert_upload(
                client, upload_id, req.user_id,
                req.filename or req.storage_path.rsplit("/", 1)[-1],
                req.storage_path, "ready",
            )
        db_ops.set_upload_meta(
            client, upload_id,
            stage="review",
            stage_label="Ready to analyze",
            progress=40,
            file_size_bytes=len(content),
            source_format=prepared.loaded.fmt,
            detected_encoding=prepared.loaded.encoding,
            row_estimate=prepared.loaded.total_rows,
            column_count=int(prepared.loaded.df.shape[1]),
            analysis_mode=prepared.mode,
            analysis_plan_json={
                "tasks": prepared.plan_tasks,
                "source": prepared.plan_source,
                "cache_key": prepared.plan_cache_key,
            },
            overrides_json=overrides or None,
        )

        return {
            "job_id": upload_id,
            "fingerprint": prepared.fingerprint,
            "plan": {
                "tasks": prepared.plan_tasks,
                "source": prepared.plan_source,
            },
            "column_types": agent.column_type_map(prepared),
            "overview": {
                "format": prepared.loaded.fmt,
                "encoding": prepared.loaded.encoding,
                "mode": prepared.mode,
                "sample_info": prepared.sample_info,
                "shape": {
                    "rows": int(len(prepared.loaded.df)),
                    "total_rows": prepared.loaded.total_rows,
                    "columns": int(prepared.loaded.df.shape[1]),
                },
            },
        }
    except FriendlyError as exc:
        return _friendly_response(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("plan preview failed upload=%s", upload_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not prepare an analysis plan. Please try again.",
        ) from exc
    finally:
        await asyncio.to_thread(agent.dispose, prepared)


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """Queue an analysis job. Returns immediately with the job_id.

    The upload row must already exist (created by /analyze/plan) OR the
    caller supplies storage_path-style flow via a plan preview. For
    backward compatibility we accept a plain insert when no row exists.
    """
    _require_config()
    client = db_ops.get_client()

    upload_id = _parse_upload_id(req.upload_id)
    upload = db_ops.get_upload(client, upload_id)

    if upload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found. Start from the upload step first.",
        )
    _check_ownership(upload, req.user_id)
    _check_quota(client, req.user_id)

    if upload["status"] == "done":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This upload has already been analyzed.",
        )

    if req.overrides:
        db_ops.set_upload_meta(client, upload_id, overrides_json=req.overrides)

    db_ops.set_upload_status(client, upload_id, "pending")
    db_ops.set_upload_stage(client, upload_id, "queued",
                            "Queued for analysis…", 5)
    await worker.submit(upload_id)
    logger.info("job queued upload=%s", upload_id)
    return AnalyzeResponse(job_id=upload_id, status="pending")


@app.post("/analyze/retry", response_model=AnalyzeResponse)
async def analyze_retry(req: RetryRequest) -> AnalyzeResponse:
    """Re-queue a failed analysis. The upload row is reset and pushed to the
    worker; the file is not re-uploaded."""
    _require_config()
    client = db_ops.get_client()
    upload_id = _parse_upload_id(req.upload_id)
    upload = db_ops.get_upload(client, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    _check_ownership(upload, req.user_id)

    if upload["status"] != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only failed analyses can be retried.",
        )

    db_ops.reset_upload_failed(client, upload_id)
    await worker.submit(upload_id)
    logger.info("job retried upload=%s", upload_id)
    return AnalyzeResponse(job_id=upload_id, status="pending")


# ---------------------------------------------------------------------------
# Job status (polling)
# ---------------------------------------------------------------------------

@app.get("/jobs/{upload_id}")
async def job_status(
    upload_id: str, user_id: str = Query(...)
) -> dict[str, Any]:
    _require_config()
    client = db_ops.get_client()
    upload = db_ops.get_upload(client, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Job not found")
    _check_ownership(upload, user_id)

    report = None
    if upload["status"] == "done":
        res = (
            client.table("reports")
            .select("id")
            .eq("upload_id", upload_id)
            .maybe_single()
            .execute()
        )
        report = res.data if res is not None else None

    return {
        "job_id": upload_id,
        "status": upload["status"],
        "stage": upload.get("stage"),
        "stage_label": upload.get("stage_label"),
        "progress": upload.get("progress", 0),
        "error_message": upload.get("error_message"),
        "source_format": upload.get("source_format"),
        "analysis_mode": upload.get("analysis_mode"),
        "report_id": report["id"] if report else None,
    }


# ---------------------------------------------------------------------------
# Exports + drill-down (all Pro + ownership gated)
# ---------------------------------------------------------------------------

def _get_report_owned(client, report_id: str, user_id: str) -> dict[str, Any]:
    row = db_ops.get_report_with_upload(client, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if row["uploads"]["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your report")
    return row


@app.get("/reports/{report_id}/export/html")
async def export_report_html(
    report_id: str, user_id: str = Query(...)
) -> Response:
    _require_config()
    client = db_ops.get_client()
    _check_pro(client, user_id)
    row = _get_report_owned(client, report_id, user_id)

    summary = row["summary_json"] or {}
    upload = row["uploads"]
    html = build_html(
        upload["filename"],
        summary,
        row["narrative"] or "",
        plan_tasks=(row.get("analysis_plan_json") or {}).get("tasks")
        if isinstance(row.get("analysis_plan_json"), dict) else None,
        sample_info=row.get("sample_info_json"),
        findings=summary.get("findings") or None,
        source_format=row.get("source_format") or upload.get("source_format"),
    )
    safe = upload["filename"].replace("/", "_").replace("\\", "_")
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="report_{safe}.html"'},
    )


@app.get("/reports/{report_id}/export/pdf")
async def export_report_pdf(report_id: str, user_id: str = Query(...)) -> Response:
    """Pro-only, ownership-checked PDF export. Returns application/pdf."""
    _require_config()
    client = db_ops.get_client()
    _check_pro(client, user_id)
    row = _get_report_owned(client, report_id, user_id)

    upload = row["uploads"]
    content = pdf.build_pdf(
        filename=upload["filename"],
        summary=row["summary_json"] or {},
        narrative=row["narrative"] or "",
    )
    safe = upload["filename"].replace("/", "_").replace("\\", "_")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report_{safe}.pdf"'},
    )


@app.get("/reports/{report_id}/download/clean")
async def download_clean(
    report_id: str, user_id: str = Query(...)
) -> Response:
    """Pro-only: re-parse the source file and export the cleaned CSV."""
    _require_config()
    client = db_ops.get_client()
    _check_pro(client, user_id)
    row = _get_report_owned(client, report_id, user_id)
    upload = row["uploads"]

    content = download_source(client, upload["storage_path"])
    if content is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    loaded = None
    try:
        loaded = await asyncio.to_thread(
            agent.load_and_classify, content, upload["filename"],
            upload["storage_path"],
        )
        cleaned = await asyncio.to_thread(
            clean_dataframe, loaded["df"], loaded["classification"]
        )
        csv_bytes = await asyncio.to_thread(dataframe_to_csv_bytes, cleaned)
    except FriendlyError as exc:
        return _friendly_response(exc)
    finally:
        if loaded and loaded.get("loaded"):
            await asyncio.to_thread(agent.dispose, loaded["loaded"])

    safe = upload["filename"].replace("/", "_").replace("\\", "_")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="clean_{safe}"'},
    )


@app.delete("/reports/{report_id}")
async def delete_report(
    report_id: str, user_id: str = Query(...)
) -> Response:
    """Delete a report, its upload history entry, and the stored source file."""
    _require_config()
    client = db_ops.get_client()
    _get_report_owned(client, report_id, user_id)
    db_ops.delete_report_and_upload(client, report_id)
    logger.info("report deleted report=%s", report_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete("/uploads/{upload_id}")
async def delete_upload(
    upload_id: str, user_id: str = Query(...)
) -> Response:
    """Delete an upload history entry (and any report + source file)."""
    _require_config()
    client = db_ops.get_client()
    upload = db_ops.get_upload(client, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    _check_ownership(upload, user_id)

    res = (
        client.table("reports")
        .select("id")
        .eq("upload_id", upload_id)
        .maybe_single()
        .execute()
    )
    if res is not None and res.data:
        db_ops.delete_report_and_upload(client, res.data["id"])
    else:
        sp = upload.get("storage_path") or ""
        if sp.startswith("uploads/"):
            try:
                client.storage.from_("uploads").remove([sp[len("uploads/"):]])
            except Exception:  # noqa: BLE001
                pass
        client.table("uploads").delete().eq("id", upload_id).execute()
    logger.info("upload deleted upload=%s", upload_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/account/delete")
async def delete_account(req: AccountDeleteRequest) -> dict[str, str]:
    """Self-serve account deletion: removes all data and the auth user."""
    _require_config()
    client = db_ops.get_client()
    profile = db_ops.get_profile(client, req.user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    db_ops.delete_user_data(client, req.user_id)
    try:
        client.auth.admin.delete_user(req.user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin delete user %s failed: %s", req.user_id, exc)
    logger.info("account deleted user=%s", req.user_id)
    return {"status": "deleted"}


@app.get("/reports/{report_id}/subset")
async def report_subset(
    report_id: str,
    user_id: str = Query(...),
    column: str = Query(...),
    value: str = Query(""),
    limit: int = Query(500, ge=1, le=2000),
) -> dict[str, Any]:
    """Pro-only drill-down: rows behind a chart bar (column == value)."""
    _require_config()
    client = db_ops.get_client()
    _check_pro(client, user_id)
    row = _get_report_owned(client, report_id, user_id)
    upload = row["uploads"]

    content = download_source(client, upload["storage_path"])
    if content is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    loaded = None
    try:
        loaded = await asyncio.to_thread(
            agent.load_and_classify, content, upload["filename"],
            upload["storage_path"],
        )
        if column not in loaded["df"].columns:
            raise HTTPException(status_code=422, detail="Unknown column")
        rows = await asyncio.to_thread(
            subset_rows, loaded["df"], column, value, limit
        )
    except FriendlyError as exc:
        return _friendly_response(exc)
    finally:
        if loaded and loaded.get("loaded"):
            await asyncio.to_thread(agent.dispose, loaded["loaded"])

    return {"column": column, "value": value, "rows": rows, "count": len(rows)}
