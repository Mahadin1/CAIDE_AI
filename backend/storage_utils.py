"""Storage helpers shared by the HTTP API and the worker.

Handles two source layouts in the `uploads` bucket:

  * Single object at `storage_path` (files <= 50 MiB uploaded directly).
  * Multi-part upload: a folder at `storage_path` containing `part-NNNNNN`
    objects plus a `manifest.json`. The manifest records the original file
    name, part count and total size; `download_source` reassembles the parts
    in order.

Multi-part reassembly streams every part straight to a spooled temp file and
discards each part's bytes immediately, so RAM cost is independent of the
upload size. :class:`SourceFile` wraps the result: small files arrive as
in-memory ``data`` bytes, larger ones as a ``path`` on disk. The caller owns
the temp file and must call :meth:`SourceFile.cleanup` (usually in a
``finally``).
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from storage3.utils import StorageException

# Aligned with eda.loader.SPOOL_THRESHOLD: beyond this we keep the source on
# disk instead of as a bytes object in RAM.
DOWNLOAD_SPOOL_THRESHOLD = 100 * 1024 * 1024  # 100 MiB


@dataclass
class SourceFile:
    """A downloaded source file: either in-memory bytes or a temp-file path.

    Exactly one of ``data`` / ``path`` is set. ``cleanup()`` removes the temp
    file (idempotent) and is safe to call even when the loader already
    claimed and removed the path via ``LoadedData.temp_path``.
    """

    data: bytes | None = None
    path: str | None = None

    @property
    def size(self) -> int:
        if self.data is not None:
            return len(self.data)
        if self.path is not None:
            return os.path.getsize(self.path)
        return 0

    def is_bytes(self) -> bool:
        return self.data is not None

    def is_path(self) -> bool:
        return self.path is not None

    def cleanup(self) -> None:
        if self.path:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.path = None
        self.data = None


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


def _from_single(client: Any, storage_path: str) -> SourceFile | None:
    """Download a single object, spooling it to disk when it is large."""
    data = download_object(client, storage_path)
    if data is None:
        return None
    if len(data) > DOWNLOAD_SPOOL_THRESHOLD:
        fd, path = tempfile.mkstemp(prefix="datascope-", suffix=".src")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
        return SourceFile(path=path)
    return SourceFile(data=data)


def download_source(
    client: Any,
    storage_path: str,
) -> SourceFile | None:
    """Download a source file, streaming multi-part uploads to disk.

    Returns a :class:`SourceFile`, or None when the file is missing. The
    caller is responsible for calling ``cleanup()`` on the result.
    """
    manifest = download_object(client, f"{storage_path}/manifest.json")
    if manifest is None:
        return _from_single(client, storage_path)
    try:
        meta = json.loads(manifest)
    except (ValueError, TypeError):
        return _from_single(client, storage_path)
    try:
        part_count = int(meta.get("part_count", 0))
    except (TypeError, ValueError):
        part_count = 0
    if part_count <= 0:
        return _from_single(client, storage_path)

    fd, path = tempfile.mkstemp(prefix="datascope-", suffix=".src")
    try:
        with os.fdopen(fd, "wb") as fh:
            for i in range(part_count):
                part = download_object(client, f"{storage_path}/part-{i:06d}")
                if part is None:
                    raise _MissingPartsError()
                fh.write(part)
                # Release each part's buffer before fetching the next one.
                del part
    except _MissingPartsError:
        _cleanup_on_error(path)
        return None
    except Exception:
        _cleanup_on_error(path)
        raise
    return SourceFile(path=path)


class _MissingPartsError(Exception):
    """Internal: a multi-part upload was incomplete (some part was missing)."""


def _cleanup_on_error(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
