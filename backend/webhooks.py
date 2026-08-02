"""Paddle webhook handler with mandatory signature verification.

Paddle v2 signs every notification with a `Paddle-Signature` header of the
form `ts=<unix-seconds>;h1=<hex-hmac>`. The signed payload is
`ts + ":" + <raw request body>`; the HMAC-SHA256 key is the webhook secret.

Verification MUST run against the raw body exactly as received — re-parsing
or re-serialising the JSON breaks the signature, so we read the body bytes
ourselves. Replay window: reject events with a timestamp older than 5 minutes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from config import settings
from db import (
    get_client,
    set_plan,
    set_plan_by_subscription,
    upsert_subscription,
)

router = APIRouter()

# Paddle statuses that map to our "active" plan state.
_ACTIVE_STATUSES = {"active", "trialing"}


def _verify_signature(raw_body: bytes, paddle_signature: str | None) -> bool:
    """Return True only if the request carries a valid, fresh signature."""
    if not settings.paddle_webhook_secret or not paddle_signature:
        return False

    # Parse header: `ts=...;h1=...;h1=...` (multiple h1 during rotation).
    pairs: dict[str, list[str]] = {}
    for part in paddle_signature.split(";"):
        if "=" in part:
            key, _, value = part.partition("=")
            pairs.setdefault(key.strip(), []).append(value.strip())

    timestamps = pairs.get("ts")
    hashes = pairs.get("h1")
    if not timestamps or not hashes:
        return False

    ts = timestamps[0]
    try:
        if abs(int(ts) - int(time.time())) > 300:
            return False  # replay / stale event
    except ValueError:
        return False

    signed_payload = f"{ts}:".encode() + raw_body
    expected = hmac.new(
        settings.paddle_webhook_secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return any(hmac.compare_digest(expected, h) for h in hashes)


def _status_from_event(event_type: str, data: dict[str, Any]) -> str:
    if event_type in ("subscription.cancelled", "subscription.canceled"):
        return "cancelled"
    if event_type in ("subscription.paused",):
        return "inactive"
    if event_type in (
        "subscription.activated",
        "subscription.created",
        "subscription.resumed",
    ):
        return "active"
    if event_type in ("subscription.updated", "subscription.past_due"):
        paddle_status = (data.get("status") or "").lower()
        if paddle_status in _ACTIVE_STATUSES:
            return "active"
        if paddle_status == "paused":
            return "inactive"
        if paddle_status == "canceled" or paddle_status == "cancelled":
            return "cancelled"
        return "active"
    return "active"


def _extract_user_id(data: dict[str, Any]) -> str | None:
    custom = data.get("custom_data") or {}
    user_id = custom.get("user_id")
    return str(user_id) if user_id else None


@router.post("/webhooks/paddle")
async def paddle_webhook(request: Request) -> Response:
    raw_body = await request.body()
    paddle_signature = request.headers.get("paddle-signature")

    # If a secret is configured we demand a valid signature.
    if settings.paddle_webhook_secret and not _verify_signature(
        raw_body, paddle_signature
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        ) from exc

    event_type = payload.get("event_type", "")
    data = payload.get("data") or {}

    user_id = _extract_user_id(data)

    # Some events carry user_id on a nested subscription object.
    if not user_id:
        subscription_data = data.get("subscription") or {}
        user_id = _extract_user_id(subscription_data)
        if not user_id:
            subscription_id = data.get("id")
            if subscription_id:
                client = get_client()
                res = (
                    client.table("subscriptions")
                    .select("user_id")
                    .eq("paddle_subscription_id", subscription_id)
                    .maybe_single()
                    .execute()
                )
                if res.data:
                    user_id = res.data["user_id"]

    if not user_id:
        # Cannot map this event to a user; acknowledge it so Paddle does not
        # retry forever. Log nothing sensitive.
        return Response(status_code=status.HTTP_200_OK)

    if not event_type.startswith("subscription."):
        # Acknowledged but not acted on (e.g. transaction.* events).
        return Response(status_code=status.HTTP_200_OK)

    client = get_client()
    subscription_id = data.get("id")
    new_status = _status_from_event(event_type, data)

    upsert_subscription(client, user_id, subscription_id, new_status)
    set_plan(client, user_id, "pro" if new_status == "active" else "free")

    if new_status in ("cancelled", "inactive") and subscription_id:
        # The event references a (possibly different) subscription id; make
        # sure any lingering active row for this user is flipped too.
        set_plan_by_subscription(client, subscription_id, "free")

    return Response(status_code=status.HTTP_200_OK)
