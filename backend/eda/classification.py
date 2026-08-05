"""Column classification — the first thing every report does.

Each column is assigned one kind that decides how everything downstream
treats it:

  constant   — a single value in >= CONSTANT_TOP_SHARE of rows
  numeric    — pandas-inferred numeric dtype
  date_like  — datetime dtype, or text where >= DATE_PARSE_MIN_SHARE of
               non-null values parse as dates (and it is not essentially
               numeric, so years like "2023" stay numeric)
  mixed      — some-but-not-all values are numeric (numbers + text)
  boolean    — cardinality <= 2 and all values are boolean-ish
  free_text  — long-form text (avg > FREE_TEXT_AVG_WORDS words) — analysed
               with word counts, never as a category with thousands of levels
  identifier — nearly-unique high-cardinality values (join keys, ids)
  empty      — no non-null values
  categorical — everything else (a real, chartable category)

The check order matters: constant first, then date-like before mixed, then
boolean/free-text, then identifier, then categorical.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

# --- thresholds ----------------------------------------------------------
CONSTANT_TOP_SHARE = 0.99
DATE_PARSE_MIN_SHARE = 0.8
MIXED_NUMERIC_CAP = 0.95
IDENTIFIER_UNIQUE_RATIO = 0.9
IDENTIFIER_MIN_CARDINALITY = 10
FREE_TEXT_AVG_WORDS = 5.0
BOOLEAN_LIKE = {
    "true": True, "false": False, "yes": True, "no": False,
    "t": True, "f": False, "1": True, "0": False,
    "y": True, "n": False,
}

# Kinds that are NOT chartable as ordinary categories.
NON_CHARTABLE_KINDS = {"date_like", "mixed", "identifier", "constant", "empty", "free_text"}


def _numeric_parse_share(series: pd.Series) -> float:
    cleaned = series.astype("string").str.strip().replace({"": None})
    total = int(cleaned.notna().sum())
    if total == 0:
        return 0.0
    converted = pd.to_numeric(cleaned, errors="coerce")
    return float(converted.notna().sum()) / total


def _date_parse_share(series: pd.Series) -> float:
    cleaned = series.astype("string").str.strip().replace({"": None})
    total = int(cleaned.notna().sum())
    if total == 0:
        return 0.0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            parsed = pd.to_datetime(cleaned, errors="coerce")
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return float(parsed.notna().sum()) / total


def _avg_word_count(series: pd.Series) -> float:
    cleaned = series.astype("string").dropna().astype(str)
    cleaned = cleaned[cleaned.str.len() > 0]
    if cleaned.empty:
        return 0.0
    words = cleaned.str.split(r"\s+").str.len()
    return float(words.mean())


def _is_boolean(series: pd.Series, cardinality: int) -> bool:
    if cardinality > 2:
        return False
    cleaned = series.astype("string").str.strip().str.lower()
    non_null = cleaned.dropna()
    if non_null.empty:
        return False
    return non_null.isin(set(BOOLEAN_LIKE)).all()


def classify_columns(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Classify every column of `df`. See module docstring for the order."""
    out: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        series = df[col].dropna()
        base: dict[str, Any] = {
            "cardinality": int(series.nunique()),
            "total": int(len(series)),
        }
        if series.empty:
            out[col] = {"kind": "empty", **base}
            continue

        counts = series.value_counts(normalize=True)
        top_value_share = float(counts.iloc[0]) if len(counts) else 0.0
        base["top_value_share"] = round(top_value_share, 4)

        # 1. constant
        if top_value_share >= CONSTANT_TOP_SHARE:
            out[col] = {"kind": "constant", **base}
            continue

        # 2. real datetime dtype
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            out[col] = {"kind": "date_like", "date_parse_rate": 1.0, **base}
            continue

        # 3. real numeric dtype
        if pd.api.types.is_numeric_dtype(series):
            out[col] = {"kind": "numeric", **base}
            continue

        numeric_share = _numeric_parse_share(series)
        date_share = _date_parse_share(series)

        # 4. date stored as text
        if date_share >= DATE_PARSE_MIN_SHARE and numeric_share < MIXED_NUMERIC_CAP:
            out[col] = {
                "kind": "date_like",
                "date_parse_rate": round(date_share, 4),
                **base,
            }
            continue

        # 5. mixed numbers and text
        if 0 < numeric_share < 1:
            out[col] = {
                "kind": "mixed",
                "numeric_share": round(numeric_share, 4),
                **base,
            }
            continue

        # 6. boolean
        if _is_boolean(series, base["cardinality"]):
            out[col] = {"kind": "boolean", **base}
            continue

        # 7. free text (long values) — checked before identifier/categorical
        avg_words = _avg_word_count(series)
        if avg_words > FREE_TEXT_AVG_WORDS:
            out[col] = {
                "kind": "free_text",
                "avg_word_count": round(avg_words, 2),
                **base,
            }
            continue

        # 8. identifier-like
        unique_ratio = (
            base["cardinality"] / base["total"] if base["total"] else 0.0
        )
        if (
            unique_ratio > IDENTIFIER_UNIQUE_RATIO
            and base["cardinality"] >= IDENTIFIER_MIN_CARDINALITY
        ):
            out[col] = {
                "kind": "identifier",
                "unique_ratio": round(unique_ratio, 4),
                **base,
            }
            continue

        # 9. plain categorical
        out[col] = {"kind": "categorical", **base}
    return out
