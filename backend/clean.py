"""Cleaned-dataset export and drill-down subsetting.

The cleaned export re-applies the transformations the report recommended:

  * numeric columns  → coerced to numbers where they parse cleanly
  * date-as-text     → parsed to ISO 8601 datetime strings
  * text-ish columns → whitespace trimmed (empty strings become null)

It never imputes and never drops rows. `subset_rows` powers the frontend's
"view the rows behind this chart bar" drill-down.

All functions are deterministic and operate on an already-loaded DataFrame
(never on the raw file).
"""
from __future__ import annotations

import io
from typing import Any

import pandas as pd


def clean_dataframe(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    """Return a cleaned copy of `df` according to the classification."""
    out = df.copy()
    for col, info in classification.items():
        kind = info["kind"]
        if kind == "numeric":
            out[col] = pd.to_numeric(out[col], errors="coerce")
        elif kind == "date_like" and info.get("date_parse_rate", 1.0) < 1.0:
            out[col] = (
                pd.to_datetime(out[col], errors="coerce")
                .dt.strftime("%Y-%m-%d %H:%M:%S")
            )
        elif kind in ("categorical", "identifier", "free_text", "mixed", "boolean"):
            out[col] = out[col].astype("string").str.strip().replace({"": None})
    return out


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def subset_rows(
    df: pd.DataFrame,
    column: str,
    value: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return up to `limit` rows where `column` equals `value` (string match)."""
    if column not in df.columns:
        return []
    target = str(value)
    try:
        mask = df[column].astype("string").str.strip() == target
    except (TypeError, ValueError):
        mask = df[column].astype(str) == target
    selected = df[mask].head(limit)
    return selected.astype(object).where(pd.notna(selected), None).to_dict(
        orient="records"
    )
