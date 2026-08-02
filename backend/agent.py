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
import math
from typing import Any

import numpy as np
import pandas as pd
import httpx

from config import settings

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


def run_eda(df: pd.DataFrame) -> dict[str, Any]:
    """Compute the full statistical summary with pandas only."""
    numeric = df.select_dtypes(include=[np.number])
    describe: dict[str, Any] = {}
    if not numeric.empty:
        describe = _jsonable(numeric.describe().to_dict())

    corr = {}
    if numeric.shape[1] > 1:
        corr = _jsonable(numeric.corr().round(4).to_dict())

    return {
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "dtypes": df.dtypes.astype(str).to_dict(),
        "missing": {str(k): int(v) for k, v in df.isnull().sum().items()},
        "missing_pct": {
            str(k): round(float(v / len(df)) * 100, 2) if len(df) else 0
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

    # 4. Dominant categorical values (>90% of rows in one category)
    for col, info in summary["categorical_summary"].items():
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
        lines = [f["message"] for f in findings]
        return " ".join(lines)

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
        return (data["choices"][0]["message"]["content"] or "").strip()
