"""Storage helpers shared by the HTTP API and the worker.

Handles two source layouts in the `uploads` bucket:

  * Single object at `storage_path` (files <= 50 MiB uploaded directly).
  * Multi-part upload: a folder at `storage_path` containing `part-NNNNNN`
    objects plus a `manifest.json`. The manifest records the original file
    name, part count and total size; `download_source` reassembles the parts
    in order into the original bytes.
"""
from __future__ import annotations

import json
from typing import Any

from storage3.utils import StorageException


def _is_not_found(exc: StorageException) -> bool:
    """True when the storage gateway reported a missing object.

    The gateway reports missing objects as statusCode 400 with code
    ``NoSuchKey`` / ``not_found`` (and sometimes 404), so match on the
    error code rather than the HTTP status alone.
    """
    args = exc.args
    if not args or not isinstance(args[0], dict):
        return False
    payload = args[0]
    code = str(payload.get("code") or "").lower()
    message = str(payload.get("message") or "").lower()
    return payload.get("statusCode") == 404 or code in ("nosuchkey", "not_found") or "object not found" in message


def download_object(client: Any, storage_path: str) -> bytes | None:
    """Download a single object, returning None when it does not exist."""
    try:
        content = client.storage.from_("uploads").download(storage_path)
        return content
    except StorageException as exc:
        if _is_not_found(exc):
            return None
        raise


def download_source(client: Any, storage_path: str) -> bytes | None:
    """Download a source file, reassembling multi-part uploads when present."""
    manifest = download_object(client, f"{storage_path}/manifest.json")
    if manifest is not None:
        try:
            meta = json.loads(manifest)
        except (ValueError, TypeError):
            return download_object(client, storage_path)
        try:
            part_count = int(meta.get("part_count", 0))
        except (TypeError, ValueError):
            part_count = 0
        parts = [
            download_object(client, f"{storage_path}/part-{i:06d}")
            for i in range(part_count)
        ]
        if parts and all(p is not None for p in parts):
            return b"".join(parts)
        return None
    return download_object(client, storage_path)
