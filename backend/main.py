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
from eda.gating import credit_cost, meets_tier, required_tier, qa_credits_for_plan
from eda import initiated, joinskill, qa as qa_skill
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


class SkillRunRequest(BaseModel):
    user_id: str
    params: dict[str, Any] | None = None


class QaRequest(BaseModel):
    user_id: str
    question: str


class JoinQualityRequest(BaseModel):
    user_id: str
    storage_path: str
    params: dict[str, Any] | None = None


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
    """Exports and drill-down require a paid plan (any tier)."""
    profile = db_ops.get_profile(client, user_id)
    if profile is None or profile.get("plan") == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This feature requires a paid plan (Starter, Pro or Scale)",
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
    column: str = Query(""),
    value: str = Query(""),
    limit: int = Query(500, ge=1, le=2000),
    indices: str = Query(""),
) -> dict[str, Any]:
    """Pro-only drill-down: rows behind a chart bar (column == value) OR an
    explicit list of positional row indices (auto_segmentation clusters,
    multivariate anomaly flags)."""
    _require_config()
    client = db_ops.get_client()
    _check_pro(client, user_id)
    row = _get_report_owned(client, report_id, user_id)
    upload = row["uploads"]

    content = download_source(client, upload["storage_path"])
    if content is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    indices_list: list[int] | None = None
    if indices.strip():
        try:
            indices_list = [int(x) for x in indices.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(
                status_code=422, detail="indices must be a comma-separated list of integers"
            ) from None

    loaded = None
    try:
        loaded = await asyncio.to_thread(
            agent.load_and_classify, content, upload["filename"],
            upload["storage_path"],
        )
        if indices_list is None:
            if column not in loaded["df"].columns:
                raise HTTPException(status_code=422, detail="Unknown column")
        rows = await asyncio.to_thread(
            subset_rows, loaded["df"], column, value, limit, indices_list
        )
    except FriendlyError as exc:
        return _friendly_response(exc)
    finally:
        if loaded and loaded.get("loaded"):
            await asyncio.to_thread(agent.dispose, loaded["loaded"])

    return {"column": column, "value": value, "rows": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# User-initiated skills (#9-#15) + report Q&A (#8)
# ---------------------------------------------------------------------------

_SKILL_HANDLERS = {
    "predictive_baseline": initiated.predictive_baseline,
    "psm": initiated.psm_analysis,
    "key_driver": initiated.key_driver_analysis,
    "what_if": initiated.what_if_scenario,
    "segment_comparison": initiated.segment_comparison,
    "decompose": initiated.decompose_change,
}


def _check_skill_gate(client, user_id: str, skill: str) -> dict[str, Any]:
    """Server-side tier + credit gate for a user-initiated skill.

    Gating lives here (the API layer), never in the frontend: the required
    tier and per-use credit cost come from eda/gating.py. A skipped skill run
    is never charged.
    """
    required = required_tier(skill)
    profile = db_ops.get_profile(client, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    plan = profile.get("plan") or "free"
    if required and not meets_tier(plan, required):
        raise HTTPException(
            status_code=403,
            detail=f"'{skill}' requires the {required.title()} plan or higher.",
        )
    cost = credit_cost(skill)
    if cost > 0 and int(profile.get("credits") or 0) < cost:
        raise HTTPException(
            status_code=402,
            detail=(
                f"'{skill}' costs {cost} credits and you have "
                f"{int(profile.get('credits') or 0)}. Upgrade or wait for the "
                "monthly credit reset."
            ),
        )
    return profile


def _load_source(client, storage_path: str, filename: str) -> dict[str, Any]:
    """Download + load + classify a stored source file (blocking)."""
    content = download_source(client, storage_path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found in storage")
    return agent.load_and_classify(content, filename, storage_path)


@app.post("/reports/{report_id}/skills/{skill}")
async def run_skill(
    report_id: str, skill: str, req: SkillRunRequest
) -> dict[str, Any]:
    """Run a user-initiated analysis skill against a finished report.

    Tier + credits are enforced server-side before any compute. Results are
    persisted to skill_runs; credits are only charged on a completed run
    (skipped/failed runs are free).
    """
    _require_config()
    client = db_ops.get_client()
    if skill not in _SKILL_HANDLERS and skill != "join_quality":
        raise HTTPException(status_code=404, detail=f"Unknown skill '{skill}'")
    _check_skill_gate(client, req.user_id, skill)
    row = _get_report_owned(client, report_id, req.user_id)
    upload = row["uploads"]

    params = req.params or {}
    run = db_ops.insert_skill_run(
        client, report_id, req.user_id, skill, params, credit_cost(skill)
    )
    loaded = None
    try:
        loaded = await asyncio.to_thread(
            _load_source, client, upload["storage_path"], upload["filename"]
        )
        if skill == "what_if":
            baseline = db_ops.get_completed_baseline(client, report_id, req.user_id)
            result = await asyncio.to_thread(
                _SKILL_HANDLERS[skill], loaded["df"],
                loaded["classification"], params, baseline,
            )
        else:
            result = await asyncio.to_thread(
                _SKILL_HANDLERS[skill], loaded["df"],
                loaded["classification"], params,
            )
    except FriendlyError as exc:
        db_ops.finish_skill_run(client, run["id"], exc.to_dict(), "failed")
        return _friendly_response(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("skill %s failed report=%s", skill, report_id)
        db_ops.finish_skill_run(
            client, run["id"],
            {"error": "Something went wrong while running this skill. "
                      "Please try again.", "detail": str(exc)},
            "failed",
        )
        raise HTTPException(
            status_code=500, detail="The skill run failed. Please try again."
        ) from exc
    finally:
        if loaded and loaded.get("loaded"):
            await asyncio.to_thread(agent.dispose, loaded["loaded"])

    if result.get("skipped"):
        db_ops.finish_skill_run(client, run["id"], result, "skipped")
        return {"run_id": run["id"], "status": "skipped", "reason": result["reason"]}

    db_ops.finish_skill_run(client, run["id"], result, "done")
    try:
        db_ops.decrement_credits(client, req.user_id, credit_cost(skill))
    except Exception:  # noqa: BLE001
        logger.warning("credit decrement failed after skill=%s", skill)
    logger.info("skill %s done report=%s run=%s", skill, report_id, run["id"])
    return {"run_id": run["id"], "status": "done", "result": result}


@app.post("/reports/{report_id}/join")
async def run_join_quality(
    report_id: str, req: JoinQualityRequest
) -> dict[str, Any]:
    """#15 — attach a second file and assess join quality before merging."""
    _require_config()
    client = db_ops.get_client()
    _check_skill_gate(client, req.user_id, "join_quality")
    row = _get_report_owned(client, report_id, req.user_id)
    upload = row["uploads"]

    prefix = f"uploads/{req.user_id}/"
    if not req.storage_path.startswith(prefix):
        raise HTTPException(
            status_code=403, detail="storage_path does not belong to this user"
        )

    run = db_ops.insert_skill_run(
        client, report_id, req.user_id, "join_quality",
        {**req.params, "second_storage_path": req.storage_path},
        credit_cost("join_quality"),
    )
    loaded_left = loaded_right = None
    try:
        loaded_left = await asyncio.to_thread(
            _load_source, client, upload["storage_path"], upload["filename"]
        )
        second_name = req.storage_path.rsplit("/", 1)[-1]
        loaded_right = await asyncio.to_thread(
            _load_source, client, req.storage_path, second_name
        )
        result = await asyncio.to_thread(
            joinskill.join_quality, loaded_left["df"], loaded_right["df"],
            req.params or {},
        )
    except FriendlyError as exc:
        db_ops.finish_skill_run(client, run["id"], exc.to_dict(), "failed")
        return _friendly_response(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("join_quality failed report=%s", report_id)
        db_ops.finish_skill_run(client, run["id"], {"error": str(exc)}, "failed")
        raise HTTPException(
            status_code=500, detail="The join assessment failed. Please try again."
        ) from exc
    finally:
        if loaded_left and loaded_left.get("loaded"):
            await asyncio.to_thread(agent.dispose, loaded_left["loaded"])
        if loaded_right and loaded_right.get("loaded"):
            await asyncio.to_thread(agent.dispose, loaded_right["loaded"])

    if result.get("skipped"):
        db_ops.finish_skill_run(client, run["id"], result, "skipped")
        return {"run_id": run["id"], "status": "skipped", "reason": result["reason"]}

    db_ops.finish_skill_run(client, run["id"], result, "done")
    try:
        db_ops.decrement_credits(client, req.user_id, credit_cost("join_quality"))
    except Exception:  # noqa: BLE001
        logger.warning("credit decrement failed after join_quality")
    return {"run_id": run["id"], "status": "done", "result": result}


@app.get("/reports/{report_id}/skills")
async def report_skills(
    report_id: str, user_id: str = Query(...)
) -> dict[str, Any]:
    """History of skill runs for a report (own rows only)."""
    _require_config()
    client = db_ops.get_client()
    _get_report_owned(client, report_id, user_id)
    runs = db_ops.list_skill_runs(client, report_id, user_id)
    return {"runs": runs}


@app.post("/reports/{report_id}/qa")
async def report_qa(report_id: str, req: QaRequest) -> dict[str, Any]:
    """#8 — ask a question about a finished report.

    Answers come only from the stored report (summary_json + findings +
    narrative + column_glossary). Metered against the separate qa_credits
    meter; Pro+ only. Turns are persisted.
    """
    _require_config()
    client = db_ops.get_client()
    profile = db_ops.get_profile(client, req.user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    plan = profile.get("plan") or "free"
    qa_limit = qa_credits_for_plan(plan)
    if qa_limit <= 0:
        raise HTTPException(
            status_code=403,
            detail="Live Q&A requires the Pro or Scale plan.",
        )
    if int(profile.get("qa_credits") or 0) <= 0:
        raise HTTPException(
            status_code=402,
            detail="You're out of Q&A credits for this month.",
        )
    row = _get_report_owned(client, report_id, req.user_id)

    previous = db_ops.list_qa_turns(client, report_id, req.user_id, limit=10)
    answer = await qa_skill.answer_question(row, req.question, previous)

    db_ops.insert_qa_turn(
        client, report_id, req.user_id, req.question,
        answer["answer"], answer["answered"],
    )
    try:
        db_ops.decrement_qa_credit(client, req.user_id)
    except Exception:  # noqa: BLE001
        logger.warning("qa_credit decrement failed report=%s", report_id)
    return {"answer": answer["answer"], "answered": answer["answered"]}


@app.get("/reports/{report_id}/qa")
async def report_qa_history(
    report_id: str, user_id: str = Query(...)
) -> dict[str, Any]:
    """Q&A turn history for a report (own rows only)."""
    _require_config()
    client = db_ops.get_client()
    _get_report_owned(client, report_id, user_id)
    turns = db_ops.list_qa_turns(client, report_id, user_id)
    return {"turns": turns}
