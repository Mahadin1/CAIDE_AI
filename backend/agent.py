"""The EDA agent.

Division of labour is strict and intentional:

  * pandas computes every statistic deterministically (run_eda)
  * rule-based code decides which statistics are worth narrating (select_findings)
  * the LLM is called EXACTLY ONCE, only to turn those findings into
    plain-English prose (narrate). It never sees the raw CSV and never
    computes a number itself.

This keeps the report accurate and the token bill tiny.
"""
from __future__ import annotations

import json
import logging
import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
import httpx

from config import settings

logger = logging.getLogger("datascope.agent")

# ---------------------------------------------------------------------------
# Rule thresholds (deterministic — the narrative never computes these)
# ---------------------------------------------------------------------------

# A column whose single most-common value covers >= this share of rows is
# treated as constant rather than as a meaningful categorical / numeric column.
CONSTANT_TOP_SHARE = 0.99
# A text column is reclassified as "date-like" when at least this share of its
# non-null values parse as datetimes AND it is not essentially numeric.
DATE_PARSE_MIN_SHARE = 0.8
# Caps a "mixed" column: some-but-not-all values must be numeric, and numeric
# values must stay under this share to still be considered mixed (all-numeric
# text columns are handled by other rules instead of date detection).
MIXED_NUMERIC_CAP = 0.95
# A categorical column whose values are unique in more than this share of rows
# is treated as an identifier (ID-like) column, not a chartable category.
# The cardinality floor avoids false positives on tiny samples.
IDENTIFIER_UNIQUE_RATIO = 0.9
IDENTIFIER_MIN_CARDINALITY = 10
# |skew| above this means the mean is likely misleading for that column.
SKEW_THRESHOLD = 1.0

# ---------------------------------------------------------------------------
# JSON-safe conversion (numpy types are not JSON serialisable)
# ---------------------------------------------------------------------------

def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if math.isnan(float(value)):
            return None
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (float,)):
        if math.isnan(value):
            return None
        return float(value)
    if isinstance(value, str):
        if value in ("nan", "NaT"):
            return None
        return value
    return value


def _finite_round(value: float, ndigits: int = 4) -> float | None:
    """Round, but return None for NaN / inf so JSON serialisation never breaks."""
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
    except TypeError:
        return value
    return round(float(value), ndigits)


# ---------------------------------------------------------------------------
# Statistics (deterministic, pandas-only)
# ---------------------------------------------------------------------------

def detect_outliers(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """IQR method per numeric column. Returns count, share, low/high bounds
    and a bounded sample of the outlier values (for charting)."""
    outliers: dict[str, dict[str, Any]] = {}
    numeric = df.select_dtypes(include=[np.number])
    for col in numeric.columns:
        series = numeric[col].dropna()
        if len(series) == 0:
            continue
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            outliers[col] = {
                "count": 0,
                "share": 0.0,
                "low_bound": None,
                "high_bound": None,
                "outlier_sample": [],
            }
            continue
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        mask = (series < low) | (series > high)
        count = int(mask.sum())
        sample = _jsonable(series[mask].head(50).tolist())
        outliers[col] = {
            "count": count,
            "share": round(count / len(series), 4),
            "low_bound": _finite_round(low),
            "high_bound": _finite_round(high),
            "outlier_sample": sample,
        }
    return outliers


def summarize_categoricals(df: pd.DataFrame, top_n: int = 5) -> dict[str, Any]:
    """Cardinality + top values for object/category columns."""
    out: dict[str, Any] = {}
    for col in df.select_dtypes(include=["object", "category"]).columns:
        series = df[col].dropna()
        if series.empty:
            continue
        counts = series.value_counts(dropna=False)
        total = int(len(series))
        top = []
        for value, count in counts.head(top_n).items():
            top.append(
                {
                    "value": str(value),
                    "count": int(count),
                    "share": round(float(count) / total, 4) if total else 0,
                }
            )
        out[col] = {
            "cardinality": int(series.nunique()),
            "total": total,
            "top": top,
        }
    return out


def _numeric_parse_share(series: pd.Series) -> float:
    """Fraction of non-null values that parse as numbers (text columns only)."""
    cleaned = series.astype("string").str.strip().replace({"": None})
    total = int(cleaned.notna().sum())
    if total == 0:
        return 0.0
    converted = pd.to_numeric(cleaned, errors="coerce")
    return float(converted.notna().sum()) / total


def _date_parse_share(series: pd.Series) -> float:
    """Fraction of non-null values that parse as datetimes."""
    cleaned = series.astype("string").str.strip().replace({"": None})
    total = int(cleaned.notna().sum())
    if total == 0:
        return 0.0
    try:
        with warnings.catch_warnings():
            # pandas warns "Could not infer format" per unparseable column; the
            # coerce fallback is intentional, so keep logs clean.
            warnings.simplefilter("ignore", UserWarning)
            parsed = pd.to_datetime(cleaned, errors="coerce")
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return float(parsed.notna().sum()) / total


def classify_columns(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Reclassify every column so findings and the chart selector treat
    constant, date-like, mixed-type and identifier columns correctly instead
    of as ordinary categoricals.

    Order matters: constant first (an all-identical column could otherwise
    look like anything), then date-like (before mixed), then mixed, then
    identifier (high-cardinality categories), then plain categorical.
    """
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

        # Phase 1: constant / near-constant columns (single value in 99%+ rows)
        if top_value_share >= CONSTANT_TOP_SHARE:
            out[col] = {"kind": "constant", **base}
            continue

        if pd.api.types.is_numeric_dtype(series):
            out[col] = {"kind": "numeric", **base}
            continue

        numeric_share = _numeric_parse_share(series)
        date_share = _date_parse_share(series)

        # Phase 1: dates parsed as text — most values look like dates and the
        # column is not essentially a number (avoids reclassifying e.g. years).
        if date_share >= DATE_PARSE_MIN_SHARE and numeric_share < MIXED_NUMERIC_CAP:
            out[col] = {
                "kind": "date_like",
                "date_parse_rate": round(date_share, 4),
                **base,
            }
            continue

        # Phase 1: mixed-type columns — some-but-not-all values are numeric.
        if 0 < numeric_share < 1:
            out[col] = {
                "kind": "mixed",
                "numeric_share": round(numeric_share, 4),
                **base,
            }
            continue

        # Phase 2: high-cardinality ID-like columns (unique in >90% of rows).
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

        out[col] = {"kind": "categorical", **base}
    return out


def run_eda(df: pd.DataFrame) -> dict[str, Any]:
    """Compute the full statistical summary with pandas only."""
    numeric = df.select_dtypes(include=[np.number])
    describe: dict[str, Any] = {}
    if not numeric.empty:
        describe = _jsonable(numeric.describe().to_dict())
        # Phase 2: skewness per numeric column (|skew| > 1 => mean may mislead).
        for col, s in numeric.skew().items():
            describe.setdefault(col, {})["skew"] = _finite_round(float(s))

    corr = {}
    if numeric.shape[1] > 1:
        corr = _jsonable(numeric.corr().round(4).to_dict())

    total_rows = int(len(df))
    duplicate_count = int(df.duplicated().sum())

    return {
        "shape": {"rows": total_rows, "columns": int(df.shape[1])},
        "dtypes": df.dtypes.astype(str).to_dict(),
        "column_classification": classify_columns(df),
        # Phase 1: exact duplicate rows.
        "duplicate_count": duplicate_count,
        "duplicate_share": (
            round(duplicate_count / total_rows * 100, 2) if total_rows else 0.0
        ),
        "missing": {str(k): int(v) for k, v in df.isnull().sum().items()},
        "missing_pct": {
            str(k): round(float(v / total_rows) * 100, 2) if total_rows else 0
            for k, v in df.isnull().sum().items()
        },
        "numeric_stats": describe,
        "correlations": corr,
        "outliers": detect_outliers(df),
        "categorical_summary": summarize_categoricals(df),
    }


# ---------------------------------------------------------------------------
# Findings (deterministic rules — no LLM involved)
# ---------------------------------------------------------------------------

def select_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Rule-based selection of what the narrative should mention."""
    findings: list[dict[str, Any]] = []

    rows = summary["shape"]["rows"]
    cols = summary["shape"]["columns"]
    classification = summary.get("column_classification", {})
    non_categorical_kinds = {"date_like", "mixed", "identifier", "constant", "empty"}

    # 0. Duplicate rows (Phase 1)
    dup_count = int(summary.get("duplicate_count", 0))
    if dup_count:
        dup_share = float(summary.get("duplicate_share") or 0)
        findings.append(
            {
                "type": "duplicates",
                "severity": "high" if dup_share > 5 else "medium",
                "count": dup_count,
                "share": round(dup_share, 1),
                "message": (
                    f"{dup_count} duplicate row{'s' if dup_count != 1 else ''} "
                    f"detected ({dup_share:.1f}% of rows)."
                ),
            }
        )

    # 0b. Column classification findings (Phase 1 + Phase 2)
    for col, info in classification.items():
        kind = info["kind"]
        if kind == "constant":
            findings.append(
                {
                    "type": "constant",
                    "severity": "medium",
                    "column": col,
                    "top_value_share": info["top_value_share"],
                    "message": (
                        f"'{col}' is constant (single value in "
                        f"{info['top_value_share'] * 100:.0f}% of rows)."
                    ),
                }
            )
        elif kind == "date_like":
            findings.append(
                {
                    "type": "date_text",
                    "severity": "medium",
                    "column": col,
                    "date_parse_rate": info["date_parse_rate"],
                    "message": (
                        f"'{col}' looks like a date but is stored as text."
                    ),
                }
            )
        elif kind == "mixed":
            findings.append(
                {
                    "type": "mixed_type",
                    "severity": "medium",
                    "column": col,
                    "numeric_share": info["numeric_share"],
                    "message": (
                        f"'{col}' mixes numbers and text — likely a "
                        "data entry issue."
                    ),
                }
            )
        elif kind == "identifier":
            findings.append(
                {
                    "type": "identifier",
                    "severity": "low",
                    "column": col,
                    "unique_ratio": info["unique_ratio"],
                    "message": (
                        f"'{col}' looks like an identifier "
                        f"({info['unique_ratio'] * 100:.0f}% of values are "
                        "unique) — it is excluded from the category charts."
                    ),
                }
            )

    # 1. High-missingness columns (>20%)
    for col, pct in summary["missing_pct"].items():
        if pct > 20:
            findings.append(
                {
                    "type": "missing",
                    "severity": "high" if pct > 50 else "medium",
                    "column": col,
                    "percent_missing": pct,
                    "message": (
                        f"'{col}' is missing {pct:.1f}% of its values."
                    ),
                }
            )

    # 2. Strong correlations (|r| > 0.7)
    for col_a, targets in summary["correlations"].items():
        for col_b, r in targets.items():
            if col_a >= col_b:
                continue  # keep each pair once
            if r is not None and abs(r) > 0.7:
                findings.append(
                    {
                        "type": "correlation",
                        "severity": "high",
                        "column_a": col_a,
                        "column_b": col_b,
                        "r": _finite_round(float(r), 3),
                        "message": (
                            f"'{col_a}' and '{col_b}' are strongly correlated "
                            f"(r = {_finite_round(float(r), 3)})."
                        ),
                    }
                )

    # 3. Outliers (>1% of rows flagged in any column)
    for col, info in summary["outliers"].items():
        if info["count"] and info["share"] > 0.01:
            findings.append(
                {
                    "type": "outliers",
                    "severity": "high" if info["share"] > 0.05 else "medium",
                    "column": col,
                    "count": info["count"],
                    "share": round(info["share"] * 100, 1),
                    "message": (
                        f"'{col}' has {info['count']} outliers "
                        f"({info['share'] * 100:.1f}% of rows)."
                    ),
                }
            )

    # 3b. Heavily skewed numeric columns (Phase 2)
    for col, stats in summary["numeric_stats"].items():
        skew = stats.get("skew")
        if skew is None:
            continue
        skew = float(skew)
        if abs(skew) <= SKEW_THRESHOLD:
            continue
        findings.append(
            {
                "type": "skew",
                "severity": "high" if abs(skew) > 2 else "medium",
                "column": col,
                "skew": _finite_round(skew, 3),
                "message": (
                    f"'{col}' is heavily skewed (skew = {_finite_round(skew, 3)}) "
                    "— the mean may be misleading here; the median is a safer "
                    "summary."
                ),
            }
        )

    # 4. Dominant categorical values (>90% of rows in one category), but only
    #    for columns the classifier still treats as real categoricals.
    for col, info in summary["categorical_summary"].items():
        if classification.get(col, {}).get("kind") in non_categorical_kinds:
            continue
        if info["cardinality"] <= 1:
            continue
        if info["top"] and info["top"][0]["share"] > 0.9:
            top = info["top"][0]
            findings.append(
                {
                    "type": "categorical_dominance",
                    "severity": "medium",
                    "column": col,
                    "dominant_value": top["value"],
                    "share": round(top["share"] * 100, 1),
                    "message": (
                        f"'{col}' is dominated by '{top['value']}' "
                        f"({top['share'] * 100:.1f}% of rows)."
                    ),
                }
            )

    # 5. Data-quality notice if the file was tiny or had no numeric columns
    if rows == 0:
        findings.append(
            {
                "type": "empty",
                "severity": "high",
                "message": "The file contains no rows.",
            }
        )
    if not summary["correlations"] and not any(
        k for k in summary["numeric_stats"]
    ):
        findings.append(
            {
                "type": "no_numeric",
                "severity": "medium",
                "message": (
                    "No numeric columns were detected, so no correlations "
                    "or outlier analysis is available."
                ),
            }
        )

    return findings


# ---------------------------------------------------------------------------
# Narration (the single LLM call)
# ---------------------------------------------------------------------------

NARRATE_SYSTEM_PROMPT = (
    "You are a data analyst writing for a non-technical reader. "
    "Given the findings below, write a short plain-English EDA summary. "
    "Write one short paragraph per finding, in the order given. "
    "Interpret what each finding means for the reader. "
    "Do not restate raw numbers that are already shown in charts. "
    "No fluff, no headers, no bullet lists, no markdown. "
    "Use plain prose sentences. Keep the whole response under 300 words."
)


async def narrate(findings: list[dict[str, Any]]) -> str:
    """ONE OpenRouter call: findings -> prose. Never reads the CSV."""
    if not findings:
        return (
            "This dataset is in good shape: no columns are missing large "
            "numbers of values, no numeric columns show extreme outliers or "
            "strong correlations, and no category dominates the others. "
            "You can read the charts below for the full picture."
        )

    if not settings.openrouter_api_key:
        # Graceful fallback so the pipeline still completes when the LLM is
        # not configured (e.g. local dev). Narratives are still deterministic.
        return _fallback_prose(findings)

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": NARRATE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Findings as JSON:\n"
                    + json.dumps(findings, default=_jsonable)
                ),
            },
        ],
        "temperature": 0.3,
        "max_tokens": 500,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://datascope.app",
                    "X-Title": "DataScope",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = (data["choices"][0]["message"]["content"] or "").strip()
            if content:
                return content
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        logger.warning("OpenRouter narration failed; using deterministic prose")

    # A narration outage must never fail a completed analysis — fall back to
    # the deterministic finding sentences.
    return _fallback_prose(findings)


def _fallback_prose(findings: list[dict[str, Any]]) -> str:
    lines = [f["message"] for f in findings]
    return " ".join(lines)
