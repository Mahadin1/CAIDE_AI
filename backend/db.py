"""Thin Supabase access layer using the service role key.

The service key bypasses RLS, so every query here explicitly scopes
by user_id — never trust the caller to stay inside their own rows.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from supabase import Client, create_client

from config import settings


def get_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Supabase is not configured")
    return create_client(settings.supabase_url, settings.supabase_service_key)


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------

def get_profile(client: Client, user_id: str) -> dict[str, Any] | None:
    res = (
        client.table("profiles")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data


def get_or_create_profile(client: Client, user_id: str, email: str) -> dict[str, Any]:
    res = (
        client.table("profiles")
        .insert({"id": user_id, "email": email})
        .execute()
    )
    return res.data[0]


def increment_reports_used(client: Client, user_id: str) -> None:
    client.rpc("increment_reports_used", {"uid": user_id}).execute()


# ---------------------------------------------------------------------------
# uploads
# ---------------------------------------------------------------------------

def get_upload(client: Client, upload_id: str) -> dict[str, Any] | None:
    res = client.table("uploads").select("*").eq("id", upload_id).maybe_single().execute()
    return res.data


def insert_upload(
    client: Client,
    upload_id: str,
    user_id: str,
    filename: str,
    storage_path: str,
    status: str = "pending",
) -> dict[str, Any]:
    res = (
        client.table("uploads")
        .insert(
            {
                "id": upload_id,
                "user_id": user_id,
                "filename": filename,
                "storage_path": storage_path,
                "status": status,
                "stage": "queued",
                "progress": 5,
                "attempts": 0,
            }
        )
        .execute()
    )
    return res.data[0]


def set_upload_status(client: Client, upload_id: str, status: str) -> None:
    client.table("uploads").update({"status": status}).eq("id", upload_id).execute()


def set_upload_stage(
    client: Client,
    upload_id: str,
    stage: str,
    label: str,
    progress: int,
) -> None:
    client.table("uploads").update(
        {
            "stage": stage,
            "stage_label": label,
            "progress": progress,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", upload_id).execute()


def set_upload_failed(client: Client, upload_id: str, message: str) -> None:
    client.table("uploads").update(
        {
            "status": "failed",
            "stage": "failed",
            "stage_label": "Failed",
            "progress": 100,
            "error_message": message[:1000],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", upload_id).execute()


def set_upload_meta(client: Client, upload_id: str, **fields: Any) -> None:
    """Patch arbitrary upload fields (format, plan, overrides, sizes, ...)."""
    payload = dict(fields)
    for key in ("analysis_plan_json", "overrides_json"):
        if key in payload:
            payload[key] = _jsonable(payload[key])
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    client.table("uploads").update(payload).eq("id", upload_id).execute()


def mark_upload_done(client: Client, upload_id: str) -> None:
    client.table("uploads").update(
        {
            "status": "done",
            "stage": "done",
            "stage_label": "Done",
            "progress": 100,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", upload_id).execute()


def get_stale_processing(client: Client, stale_seconds: int) -> list[dict[str, Any]]:
    """Uploads stuck in 'processing' past the stale window (for recovery)."""
    import time
    cutoff = time.time() - stale_seconds
    res = (
        client.table("uploads")
        .select("id")
        .eq("status", "processing")
        .lt("updated_at", datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat())
        .execute()
    )
    return res.data


def get_upload_with_user(client: Client, upload_id: str) -> dict[str, Any] | None:
    """Upload plus its owning profile, used to enforce limits before processing."""
    res = (
        client.table("uploads")
        .select("*, profiles(*)")
        .eq("id", upload_id)
        .maybe_single()
        .execute()
    )
    return res.data


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

def _jsonable(value: Any) -> Any:
    """Recursively convert numpy scalars/arrays to JSON-native types.

    All dicts written to json/jsonb columns pass through here so the HTTP
    layer never has to deal with numpy types in inserts.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def insert_report(
    client: Client,
    upload_id: str,
    summary_json: dict,
    narrative: str,
    *,
    analysis_plan_json: dict | None = None,
    overrides_json: dict | None = None,
    sample_info_json: dict | None = None,
    analysis_mode: str | None = None,
    source_format: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "upload_id": upload_id,
        "summary_json": _jsonable(summary_json),
        "narrative": narrative,
    }
    if analysis_plan_json is not None:
        payload["analysis_plan_json"] = _jsonable(analysis_plan_json)
    if overrides_json is not None:
        payload["overrides_json"] = _jsonable(overrides_json)
    if sample_info_json is not None:
        payload["sample_info_json"] = _jsonable(sample_info_json)
    if analysis_mode is not None:
        payload["analysis_mode"] = analysis_mode
    if source_format is not None:
        payload["source_format"] = source_format
    res = (
        client.table("reports")
        .insert(payload)
        .execute()
    )
    return res.data[0]


def get_report(client: Client, report_id: str) -> dict[str, Any] | None:
    res = (
        client.table("reports")
        .select("*")
        .eq("id", report_id)
        .maybe_single()
        .execute()
    )
    return res.data


def get_report_with_upload(client: Client, report_id: str) -> dict[str, Any] | None:
    res = (
        client.table("reports")
        .select("*, uploads!inner(*)")
        .eq("id", report_id)
        .maybe_single()
        .execute()
    )
    return res.data


def set_report_export_urls(
    client: Client, report_id: str, *, export_html_url: str | None = None,
    export_pdf_url: str | None = None, cleaned_data_url: str | None = None,
) -> None:
    payload: dict[str, Any] = {}
    if export_html_url is not None:
        payload["export_html_url"] = export_html_url
    if export_pdf_url is not None:
        payload["export_pdf_url"] = export_pdf_url
    if cleaned_data_url is not None:
        payload["cleaned_data_url"] = cleaned_data_url
    if payload:
        client.table("reports").update(payload).eq("id", report_id).execute()


# ---------------------------------------------------------------------------
# subscriptions
# ---------------------------------------------------------------------------

def get_subscription(client: Client, user_id: str) -> dict[str, Any] | None:
    res = (
        client.table("subscriptions")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data


def upsert_subscription(
    client: Client,
    user_id: str,
    paddle_subscription_id: str | None,
    status: str,
) -> None:
    client.table("subscriptions").upsert(
        {
            "user_id": user_id,
            "paddle_subscription_id": paddle_subscription_id,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id",
    ).execute()


def set_plan(client: Client, user_id: str, plan: str) -> None:
    client.table("profiles").update({"plan": plan}).eq("id", user_id).execute()


def set_plan_by_subscription(
    client: Client, paddle_subscription_id: str, plan: str
) -> None:
    """Find the user via their subscription row and update their plan."""
    res = (
        client.table("subscriptions")
        .select("user_id")
        .eq("paddle_subscription_id", paddle_subscription_id)
        .maybe_single()
        .execute()
    )
    if res.data:
        set_plan(client, res.data["user_id"], plan)
