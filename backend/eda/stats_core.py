"""Backbone statistics — deterministic, pandas/numpy only.

Everything in this module is the *base* layer every report gets, regardless
of the adaptive plan. Multi-column comparisons, associations, trends and
histograms are ADDITIVE on top of the classic single-column stats (missing,
outliers, correlations, categorical dominance).

No LLM code lives here and nothing here ever touches the narrative.
"""
from __future__ import annotations

import math
import warnings
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

# --- thresholds ----------------------------------------------------------
GROUP_COMPARISON_MIN_CARDINALITY = 2
GROUP_COMPARISON_MAX_CARDINALITY = 8
MAX_GROUP_CATEGORIES_TO_LIST = 6
CRAMERS_V_MAX_PAIRS = 15
TREND_MIN_PERIODS = 4
TREND_SERIES_MAX_POINTS = 36
HISTOGRAM_BIN_COUNT = 10
MAX_CHART_SPECS = 25
CORRELATION_SIGNIFICANCE_ALPHA = 0.05


# ---------------------------------------------------------------------------
# JSON-safe conversion
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
    if isinstance(value, pd.Period):
        return str(value)
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


def _finite_round(value: float | None, ndigits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
    except TypeError:
        return value
    return round(float(value), ndigits)


# ---------------------------------------------------------------------------
# Single-column stats
# ---------------------------------------------------------------------------

def numeric_stats(df: pd.DataFrame) -> dict[str, Any]:
    """describe() plus per-column skewness, for numeric columns."""
    numeric = df.select_dtypes(include=[np.number])
    describe: dict[str, Any] = {}
    if numeric.empty:
        return describe
    describe = _jsonable(numeric.describe().to_dict())
    for col, s in numeric.skew().items():
        describe.setdefault(col, {})["skew"] = _finite_round(float(s))
    for col, s in numeric.kurtosis().items():
        describe.setdefault(col, {})["kurtosis"] = _finite_round(float(s))
    return describe


def correlations(df: pd.DataFrame) -> dict[str, Any]:
    if df.select_dtypes(include=[np.number]).shape[1] <= 1:
        return {}
    return _jsonable(df.select_dtypes(include=[np.number]).corr().round(4).to_dict())


def detect_outliers(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """IQR method per numeric column. count/share + bounds + bounded sample."""
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
        out[col] = {"cardinality": int(series.nunique()), "total": total, "top": top}
    return out


def compute_histograms(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Pre-computed histograms for numeric columns (bin edges + counts)."""
    results: dict[str, Any] = {}
    for col, info in classification.items():
        if info["kind"] != "numeric":
            continue
        series = df[col].dropna()
        if series.empty or series.nunique() < 2:
            continue
        counts, edges = np.histogram(
            series.to_numpy(dtype=float), bins=HISTOGRAM_BIN_COUNT
        )
        results[col] = {
            "bin_edges": [_finite_round(float(e), 4) for e in edges],
            "counts": [int(c) for c in counts],
        }
    return results


# ---------------------------------------------------------------------------
# Multi-column comparisons
# ---------------------------------------------------------------------------

def compare_numeric_by_category(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Per-group mean/median/count of each numeric column by each categorical
    column with 2..8 groups, with an effect size (top-vs-bottom gap in
    overall standard deviations)."""
    results: dict[str, Any] = {}
    numeric_cols = [c for c, info in classification.items() if info["kind"] == "numeric"]
    cat_cols = [
        c
        for c, info in classification.items()
        if info["kind"] == "categorical"
        and GROUP_COMPARISON_MIN_CARDINALITY <= info["cardinality"] <= GROUP_COMPARISON_MAX_CARDINALITY
    ]
    for num_col in numeric_cols:
        for cat_col in cat_cols:
            sub = df[[num_col, cat_col]].dropna()
            if sub.empty or sub[cat_col].nunique() < 2:
                continue
            overall_std = sub[num_col].std()
            if overall_std is None or overall_std == 0 or math.isnan(overall_std):
                continue
            grouped = sub.groupby(cat_col)[num_col].agg(["mean", "median", "count"])
            grouped = grouped.sort_values("mean", ascending=False)
            group_records = []
            for cat_value, row in grouped.head(MAX_GROUP_CATEGORIES_TO_LIST).iterrows():
                group_records.append(
                    {
                        "group": str(cat_value),
                        "mean": _finite_round(float(row["mean"])),
                        "median": _finite_round(float(row["median"])),
                        "count": int(row["count"]),
                    }
                )
            if len(group_records) < 2:
                continue
            effect = (group_records[0]["mean"] - group_records[-1]["mean"]) / float(overall_std)
            results[f"{num_col}__by__{cat_col}"] = {
                "numeric_column": num_col,
                "category_column": cat_col,
                "groups": group_records,
                "effect_size_std": _finite_round(float(effect), 3),
            }
    return results


def _cramers_v(observed: np.ndarray) -> float | None:
    n = observed.sum()
    if n == 0:
        return None
    row_sums = observed.sum(axis=1, keepdims=True)
    col_sums = observed.sum(axis=0, keepdims=True)
    expected = row_sums @ col_sums / n
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(expected > 0, (observed - expected) ** 2 / expected, 0.0)
    chi2 = float(terms.sum())
    r, k = observed.shape
    denom = min(r - 1, k - 1)
    if denom <= 0:
        return None
    phi2 = chi2 / float(n)
    return math.sqrt(max(phi2, 0.0) / denom)


def compute_categorical_associations(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Cramér's V between categorical column pairs (bounded for speed)."""
    cat_cols = [
        c for c, info in classification.items()
        if info["kind"] == "categorical" and info["cardinality"] >= 2
    ]
    results: dict[str, Any] = {}
    if len(cat_cols) < 2:
        return results
    for col_a, col_b in list(combinations(cat_cols, 2))[:CRAMERS_V_MAX_PAIRS]:
        sub = df[[col_a, col_b]].dropna()
        if sub.empty:
            continue
        table = pd.crosstab(sub[col_a], sub[col_b])
        if table.shape[0] < 2 or table.shape[1] < 2:
            continue
        v = _cramers_v(table.to_numpy(dtype=float))
        if v is None:
            continue
        results[f"{col_a}__vs__{col_b}"] = {
            "column_a": col_a,
            "column_b": col_b,
            "cramers_v": _finite_round(v, 3),
        }
    return results


def compute_time_trends(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Monthly row-count trend for each date-like column (counts only)."""
    results: dict[str, Any] = {}
    for col, info in classification.items():
        if info["kind"] != "date_like":
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            series = df[col].dropna()
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                series = pd.to_datetime(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        counts = series.dt.to_period("M").value_counts().sort_index()
        if len(counts) < TREND_MIN_PERIODS:
            continue
        y = counts.to_numpy(dtype=float)
        if np.std(y) == 0:
            continue
        x = np.arange(len(counts), dtype=float)
        corr = float(np.corrcoef(x, y)[0, 1])
        tail = counts.tail(TREND_SERIES_MAX_POINTS)
        series_out = [
            {"period": str(period), "count": int(count)}
            for period, count in tail.items()
        ]
        results[col] = {
            "periods": int(len(counts)),
            "start": str(counts.index[0]),
            "end": str(counts.index[-1]),
            "trend_correlation": _finite_round(corr, 3),
            "direction": "increasing" if corr > 0 else "decreasing",
            "series": series_out,
        }
    return results


# ---------------------------------------------------------------------------
# Missing-value machinery
# ---------------------------------------------------------------------------

def missing_patterns(df: pd.DataFrame, max_cols: int = 20) -> dict[str, Any]:
    """Missingness relationships: pairwise missing-correlation and per-column
    conditional means (how a numeric column behaves when another column is
    missing vs present). Helps reason about MCAR/MAR/MNAR."""
    missing_pct = (df.isnull().mean() * 100).round(2).to_dict()
    # Pairwise co-missingness of the most-missing columns.
    cols = [c for c, pct in sorted(missing_pct.items(), key=lambda kv: kv[1], reverse=True)
            if pct > 0 and pct < 100][:max_cols]
    co_missing: dict[str, Any] = {}
    if len(cols) >= 2:
        indicator = df[cols].isnull()
        for a, b in combinations(cols, 2):
            both = float(indicator[a].astype(int).mul(indicator[b].astype(int)).mean())
            if both > 0.01:
                co_missing[f"{a}__and__{b}"] = {
                    "column_a": a,
                    "column_b": b,
                    "share_both_missing": round(both, 4),
                    "share_a_missing": round(float(indicator[a].mean()), 4),
                    "share_b_missing": round(float(indicator[b].mean()), 4),
                }
    # Conditional numeric means: for each numeric col, mean when another col
    # is missing vs present (a big difference hints the missingness is MAR).
    conditional: dict[str, Any] = {}
    numeric_cols = list(df.select_dtypes(include=[np.number]).columns)
    for missing_col in cols[:10]:
        if missing_col in numeric_cols:
            continue
        for num_col in numeric_cols[:8]:
            is_missing = df[missing_col].isnull()
            if is_missing.sum() == 0 or (~is_missing).sum() == 0:
                continue
            mean_missing = df.loc[is_missing, num_col].mean()
            mean_present = df.loc[~is_missing, num_col].mean()
            if pd.isna(mean_missing) or pd.isna(mean_present):
                continue
            diff = float(mean_missing - mean_present)
            if abs(diff) > 0.01:
                conditional[f"{missing_col}__vs__{num_col}"] = {
                    "missing_column": missing_col,
                    "numeric_column": num_col,
                    "mean_when_missing": _finite_round(float(mean_missing)),
                    "mean_when_present": _finite_round(float(mean_present)),
                    "mean_difference": _finite_round(diff),
                }
    return {
        "missing_percent": {str(k): float(v) for k, v in missing_pct.items()},
        "co_missing": co_missing,
        "conditional_means": conditional,
    }


# ---------------------------------------------------------------------------
# The full backbone
# ---------------------------------------------------------------------------

def run_backbone(df: pd.DataFrame, classification: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compute all backbone statistics for a (possibly sampled) frame."""
    total_rows = int(len(df))
    duplicate_count = int(df.duplicated().sum())
    numeric = df.select_dtypes(include=[np.number])
    corr = correlations(df)
    missing = {str(k): int(v) for k, v in df.isnull().sum().items()}

    summary: dict[str, Any] = {
        "shape": {"rows": total_rows, "columns": int(df.shape[1])},
        "dtypes": df.dtypes.astype(str).to_dict(),
        "column_classification": classification,
        "duplicate_count": duplicate_count,
        "duplicate_share": (
            round(duplicate_count / total_rows * 100, 2) if total_rows else 0.0
        ),
        "missing": missing,
        "missing_pct": {
            str(k): round(float(v / total_rows) * 100, 2) if total_rows else 0
            for k, v in missing.items()
        },
        "numeric_stats": numeric_stats(df),
        "correlations": corr,
        "outliers": detect_outliers(df),
        "categorical_summary": summarize_categoricals(df),
        "histograms": compute_histograms(df, classification),
        "numeric_by_categorical": compare_numeric_by_category(df, classification),
        "categorical_associations": compute_categorical_associations(df, classification),
        "time_trends": compute_time_trends(df, classification),
        "missing_patterns": missing_patterns(df),
    }
    return summary


def build_chart_specs(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic chart suggestions with optional drill-down metadata."""
    specs: list[dict[str, Any]] = []
    classification = summary.get("column_classification", {})
    outliers = summary.get("outliers", {})

    for col, info in classification.items():
        kind = info["kind"]
        if kind == "numeric":
            specs.append({
                "type": "histogram", "columns": [col],
                "title": f"Distribution of {col}",
                "drill_down": {"column": col, "route": "histogram"},
            })
            if outliers.get(col, {}).get("count"):
                specs.append({
                    "type": "boxplot", "columns": [col],
                    "title": f"{col} — outlier spread",
                })
        elif kind == "categorical":
            specs.append({
                "type": "bar", "columns": [col],
                "title": f"Top values of {col}",
                "drill_down": {"column": col, "route": "category"},
            })

    for col in summary.get("time_trends", {}):
        specs.append({
            "type": "line", "columns": [col], "title": f"{col} over time",
        })

    correlations = summary.get("correlations") or {}
    if correlations:
        specs.append({
            "type": "heatmap", "columns": list(correlations.keys()),
            "title": "Correlation heatmap",
        })
        pairs = []
        for col_a, targets in correlations.items():
            for col_b, r in targets.items():
                if col_a < col_b and r is not None:
                    pairs.append((abs(r), col_a, col_b))
        pairs.sort(reverse=True)
        for _, col_a, col_b in pairs[:3]:
            specs.append({
                "type": "scatter", "columns": [col_a, col_b],
                "title": f"{col_a} vs {col_b}",
            })

    for cmp in summary.get("numeric_by_categorical", {}).values():
        specs.append({
            "type": "grouped_bar",
            "columns": [cmp["numeric_column"], cmp["category_column"]],
            "title": f"{cmp['numeric_column']} by {cmp['category_column']}",
            "drill_down": {
                "column": cmp["category_column"],
                "route": "category",
            },
        })

    return specs[:MAX_CHART_SPECS]


def apply_overrides(df: pd.DataFrame, overrides: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    """Apply user overrides from the plan-preview step.

    Returns (df_without_excluded_columns, classification_merged_with_overrides).
    Overrides are raw kind strings supplied by the UI; anything unknown is
    ignored so a malformed client can never crash the pipeline.
    """
    df = df.copy()
    overrides = overrides or {}
    column_types = overrides.get("column_types") or {}
    exclude = set(overrides.get("exclude_columns") or [])

    # Exclusion happens first.
    drop = [c for c in exclude if c in df.columns]
    if drop:
        df = df.drop(columns=drop)

    # Column-type overrides are merged into the classification later by the
    # pipeline; here we only validate them against the frame's columns.
    valid_kinds = {"numeric", "categorical", "date_like", "mixed", "constant",
                   "identifier", "empty", "free_text", "boolean"}
    validated = {
        col: kind for col, kind in (column_types or {}).items()
        if col in df.columns and kind in valid_kinds
    }
    return df, validated
