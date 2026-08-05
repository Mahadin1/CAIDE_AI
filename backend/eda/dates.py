"""Date/time column analysis — temporal features + seasonality.

For each `date_like` column the pipeline extracts standard temporal features
(year, month, day of week, hour) and a month-of-year *seasonality profile*
(how far each calendar month's row count sits above/below the mean). Trend
strength comes from the backbone `time_trends`; a proper Mann-Kendall test is
available via eda/tests.py for series long enough to be meaningful.

Nothing here forecasts or imputes — all outputs are descriptions of the data.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

TREND_MIN_PERIODS = 4


def _as_datetime(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dropna()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(series, errors="coerce").dropna()


def temporal_features(series: pd.Series, max_rows: int = 100_000) -> dict[str, Any]:
    """Summaries of extracted year/month/weekday/hour features."""
    s = _as_datetime(series)
    if s.empty:
        return {}
    if len(s) > max_rows:
        s = s.sample(n=max_rows, random_state=42)

    def _counts(values: pd.Series) -> list[dict[str, int]]:
        counts = values.value_counts().sort_index()
        return [{"value": str(k), "count": int(v)} for k, v in counts.items()]

    features: dict[str, Any] = {
        "range": {
            "min": s.min().isoformat() if not pd.isna(s.min()) else None,
            "max": s.max().isoformat() if not pd.isna(s.max()) else None,
            "span_days": int((s.max() - s.min()).days) if not pd.isna(s.min()) and not pd.isna(s.max()) else None,
        },
        "years": _counts(s.dt.year),
        "months": _counts(s.dt.month),
        "weekdays": _counts(s.dt.dayofweek),
    }
    if (s.dt.hour.nunique() > 1) and not all(s.dt.hour == 0):
        features["hours"] = _counts(s.dt.hour)
    features["interpretation"] = (
        "Derived from the parsed datetime. Peaks in months/weekdays point to "
        "seasonal or weekly patterns in record creation."
    )
    return features


def seasonality_profile(series: pd.Series, min_months: int = 8) -> dict[str, Any] | None:
    """Month-of-year row counts with deviations from the monthly mean.

    Requires at least `min_months` of coverage so the profile isn't a single
    spike from a short date range.
    """
    s = _as_datetime(series)
    if s.empty:
        return None
    monthly = s.dt.to_period("M").value_counts().sort_index()
    if len(monthly) < min_months:
        return None
    month_counts = np.zeros(12, dtype=float)
    for period, count in monthly.items():
        month_counts[period.month - 1] += count
    mean = float(month_counts.mean())
    if mean <= 0:
        return None
    deviations = (month_counts - mean) / mean
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    peak = int(np.argmax(month_counts))
    trough = int(np.argmin(month_counts))
    amplitude = float(max(month_counts) - min(month_counts))
    return {
        "months_covered": int(len(monthly)),
        "monthly_deviations": [
            {"month": names[i], "count": int(month_counts[i]),
             "deviation": round(float(deviations[i]), 4)}
            for i in range(12)
        ],
        "peak_month": names[peak],
        "trough_month": names[trough],
        "amplitude": round(amplitude, 2),
        "has_seasonality": bool(amplitude > mean * 0.2),
        "interpretation": (
            f"Row counts peak in {names[peak]} and dip in {names[trough]}; "
            f"the swing is {amplitude:.0f} records ({amplitude / mean * 100:.0f}% "
            "of the average month)."
        ),
    }


def compute_temporal_summary(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Run temporal feature extraction + seasonality for every date-like
    column. Never raises — a column that fails is skipped."""
    out: dict[str, Any] = {}
    for col, info in classification.items():
        if info["kind"] != "date_like":
            continue
        try:
            entry: dict[str, Any] = {"features": temporal_features(df[col])}
            seasonal = seasonality_profile(df[col])
            if seasonal:
                entry["seasonality"] = seasonal
            out[col] = entry
        except Exception:
            continue
    return out
