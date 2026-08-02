"""DataScope backend — FastAPI service.

Responsibilities:
  * receive the "analyze" trigger for an uploaded CSV
  * enforce the free-tier monthly limit server-side
  * run the EDA agent (pandas stats -> rules -> one LLM narration)
  * persist results to Supabase, never leaving an upload stuck
  * verify Paddle webhooks
"""
from __future__ import annotations

import io
import logging
import uuid as uuid_lib
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

import agent
import db as db_ops
import pdf
from config import settings
from webhooks import router as paddle_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("datascope")

app = FastAPI(title="DataScope API", version="1.0.0")
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

class AnalyzeRequest(BaseModel):
    user_id: str
    upload_id: str
    storage_path: str
    filename: str = ""


class AnalyzeResponse(BaseModel):
    report_id: str
    upload_id: str


class ErrorResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_config() -> None:
    if not settings.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backend is not configured (missing SUPABASE / OPENROUTER vars)",
        )


def _parse_csv(content: bytes, filename: str = "") -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(content))
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(content), encoding="latin-1")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/reports/{report_id}/pdf")
async def export_report_pdf(report_id: str, user_id: str = Query(...)) -> Response:
    """Pro-only, ownership-checked PDF export. Returns application/pdf."""
    _require_config()
    client = db_ops.get_client()

    res = (
        client.table("reports")
        .select("*, uploads!inner(*)")
        .eq("id", report_id)
        .maybe_single()
        .execute()
    )
    row = res.data
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")

    upload = row["uploads"]
    if upload["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your report")

    profile = db_ops.get_profile(client, user_id)
    if profile is None or profile.get("plan") != "pro":
        raise HTTPException(
            status_code=403, detail="PDF export requires a Pro subscription"
        )

    content = pdf.build_pdf(
        filename=upload["filename"],
        summary=row["summary_json"],
        narrative=row["narrative"],
    )
    safe = upload["filename"].replace("/", "_").replace("\\", "_")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report_{safe}.pdf"'},
    )


@app.post(
    "/analyze",
    response_model=AnalyzeResponse,
    responses={402: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    _require_config()

    client = db_ops.get_client()

    # ---- ownership check: storage path must live under this user's folder
    prefix = f"uploads/{req.user_id}/"
    if not req.storage_path.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="storage_path does not belong to this user",
        )

    # ---- parse upload id up front so we never write a malformed row
    try:
        upload_id = str(uuid_lib.UUID(req.upload_id))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="upload_id must be a valid UUID",
        )

    # ---- server-side plan enforcement (never trust the UI)
    profile = db_ops.get_profile(client, req.user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    if profile.get("plan") == "free":
        used = int(profile.get("reports_this_month") or 0)
        if used >= settings.free_monthly_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    "You've used all your free reports for this month. "
                    "Upgrade to Pro for unlimited analyses."
                ),
            )

    # ---- create the upload row in 'processing' (the running state)
    filename = req.filename or req.storage_path.rsplit("/", 1)[-1]
    db_ops.insert_upload(
        client, upload_id, req.user_id, filename, req.storage_path, "processing"
    )

    # ---- run the pipeline inside one guard so status always terminates
    try:
        content = client.storage.from_("uploads").download(req.storage_path)
        if content is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found in storage",
            )

        df = _parse_csv(content, filename)
        summary = agent.run_eda(df)
        findings = agent.select_findings(summary)
        narrative = await agent.narrate(findings)

        report = db_ops.insert_report(client, upload_id, summary, narrative)
        db_ops.set_upload_status(client, upload_id, "done")

        # The counter is advisory; a failure here must not re-flag a
        # successfully completed upload.
        try:
            db_ops.increment_reports_used(client, req.user_id)
        except Exception:  # noqa: BLE001
            logger.warning("failed to increment usage for user=%s", req.user_id)

        logger.info("analysis done upload=%s report=%s", upload_id, report["id"])
        return AnalyzeResponse(report_id=report["id"], upload_id=upload_id)

    except HTTPException as exc:
        db_ops.set_upload_status(client, upload_id, "failed")
        raise exc
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        logger.warning("csv parse failed upload=%s", upload_id)
        db_ops.set_upload_status(client, upload_id, "failed")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The file could not be read as a CSV. Check the format and try again.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("analysis failed upload=%s", upload_id)
        db_ops.set_upload_status(client, upload_id, "failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Analysis failed. Please try again.",
        ) from exc
