"""Data fingerprint — the ONLY view of the data the LLM planner gets.

The fingerprint is compact by design: column names, inferred kinds, dtypes,
cardinality, missingness, parse shares and up to three example values per
column. It deliberately excludes full distributions, raw row counts of the
sample, and any values that would let the LLM compute (or invent) numbers.
The planner uses it to decide *what* to analyse; the executor computes
everything deterministically.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from eda.loader import LoadedData
from eda.classification import classify_columns

MAX_EXAMPLE_VALUES = 3


def _example_values(series: pd.Series, n: int = MAX_EXAMPLE_VALUES) -> list[str]:
    values: list[str] = []
    for value in series.dropna().drop_duplicates().head(50).tolist():
        text = str(value)
        if len(text) > 80:
            text = text[:77] + "..."
        if text not in values:
            values.append(text)
        if len(values) >= n:
            break
    return values


def build_fingerprint(
    df: pd.DataFrame,
    loaded: LoadedData | None = None,
    classification: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the compact fingerprint used by the planner and plan preview."""
    classification = classification or classify_columns(df)
    columns: list[dict[str, Any]] = []
    for col in df.columns:
        series = df[col]
        info = classification.get(col, {})
        numeric_share = None
        date_share = None
        if info.get("kind") in ("mixed",):
            numeric_share = info.get("numeric_share")
        elif info.get("kind") == "date_like" and "date_parse_rate" in info:
            date_share = info.get("date_parse_rate")
        entry: dict[str, Any] = {
            "name": str(col),
            "dtype": str(df[col].dtype),
            "kind": info.get("kind", "categorical"),
            "cardinality": info.get("cardinality"),
            "missing_pct": round(float(series.isnull().mean() * 100), 1),
            "samples": _example_values(series),
        }
        if numeric_share is not None:
            entry["numeric_share"] = numeric_share
        if date_share is not None:
            entry["date_parse_rate"] = date_share
        if "avg_word_count" in info:
            entry["avg_word_count"] = info["avg_word_count"]
        columns.append(entry)

    fingerprint: dict[str, Any] = {
        "source_format": loaded.fmt if loaded else None,
        "encoding": loaded.encoding if loaded else None,
        "columns_in_analysis": int(df.shape[1]),
        "analysis_rows": int(df.shape[0]),
        "total_rows": (loaded.total_rows if loaded else int(df.shape[0])),
        "is_sample": bool(loaded and not loaded.fully_loaded),
        "estimated_memory_kb": int(df.memory_usage(deep=True).sum() / 1024),
        "columns": columns,
    }
    return fingerprint
