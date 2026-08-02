"""Thin Supabase access layer using the service role key.

The service key bypasses RLS, so every query here explicitly scopes
by user_id — never trust the caller to stay inside their own rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
    status: str,
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
            }
        )
        .execute()
    )
    return res.data[0]


def set_upload_status(client: Client, upload_id: str, status: str) -> None:
    client.table("uploads").update({"status": status}).eq("id", upload_id).execute()


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

def insert_report(
    client: Client, upload_id: str, summary_json: dict, narrative: str
) -> dict[str, Any]:
    res = (
        client.table("reports")
        .insert(
            {
                "upload_id": upload_id,
                "summary_json": summary_json,
                "narrative": narrative,
            }
        )
        .execute()
    )
    return res.data[0]


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
