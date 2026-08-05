"""User-friendly error types for the EDA pipeline.

Every failure point in the pipeline raises a `FriendlyError` carrying a
message safe to show to a user (no stack traces, no internals). The API layer
maps these to HTTP responses.
"""
from __future__ import annotations

from typing import Any


class FriendlyError(Exception):
    """A user-actionable error with a safe message and a machine kind.

    kind values and their meaning:

      * bad_file        — the file could not be parsed as the detected format
      * bad_csv         — CSV/TSV could not be read (encoding, delimiter, quotes)
      * bad_excel       — Excel/OOXML file corrupt or unreadable
      * bad_json        — JSON malformed or not an array/NDJSON of objects
      * bad_parquet     — parquet/feather corrupt
      * empty_file      — the file has no data rows
      * unsupported     — format not supported
      * too_many_cols   — exceeds column limit
      * too_many_rows   — exceeds row limit and sampling was declined
      * out_of_memory   — could not fit the file in memory
      * storage         — could not download the file from storage
      * internal        — unexpected internal failure (still user-safe)
    """

    def __init__(
        self,
        user_message: str,
        kind: str = "bad_file",
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.kind = kind
        self.detail = detail or {}

    def to_dict(self) -> dict[str, Any]:
        return {"detail": self.user_message, "kind": self.kind, **self.detail}


# HTTP status per error kind. 422 = the user's file/input is at fault;
# 500 = something unexpected inside the service.
ERROR_STATUS: dict[str, int] = {
    "bad_file": 422,
    "bad_csv": 422,
    "bad_excel": 422,
    "bad_json": 422,
    "bad_parquet": 422,
    "empty_file": 422,
    "unsupported": 422,
    "too_many_cols": 422,
    "too_many_rows": 413,
    "out_of_memory": 507,
    "storage": 502,
    "internal": 500,
}


def error_status(kind: str) -> int:
    return ERROR_STATUS.get(kind, 422)


class TransientError(Exception):
    """A temporary failure (network blip, storage timeout, LLM 5xx/429).

    The worker retries jobs that raise this; it is never shown to the user
    verbatim on the final attempt.
    """

