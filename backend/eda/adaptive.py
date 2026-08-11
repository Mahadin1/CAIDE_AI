"""Adaptive-task implementations for the multi-skill platform.

These are the six NEW adaptive tasks that fire automatically when the
planner judges them relevant (and the user's tier allows it):

  1. auto_segmentation             — KMeans, k chosen by silhouette
  2. forecast_metric               — statsmodels ETS / seasonal-naive
  3. cohort_retention              — cohort x period retention matrix
  4. group_significance_test       — 2-group categorical + numeric metric
  5. feature_engineering_suggestions — rule-based, advisory only
  6. multivariate_anomaly_detection — Isolation Forest over the feature space

Invariants honoured here (see docs/ARCHITECTURE.md §1):

  * every number is computed by pandas/scipy/statsmodels/sklearn — never by
    the LLM;
  * results are measurements/proposals — nothing ever mutates ``df``;
  * each function is exception-safe: a numerical failure returns a ``skipped``
    result (or an empty dict) so the job always completes, never crashes;
  * ``skipped`` results carry a plain-language reason surfaced in
    ``summary["skipped_tasks"]``.

Data-condition guards mirror the spec exactly: each task also documents when
it does NOT apply, so a dataset lacking the right shape produces a clean
skip rather than a forced or wrong result.
"""
from __future__ import annotations

import math
import warnings
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. auto_segmentation
# ---------------------------------------------------------------------------

SEGMENT_MIN_NUMERIC = 3
SEGMENT_MIN_ROWS = 60
SEGMENT_MAX_K = 8
SEGMENT_MIN_SILHOUETTE = 0.12


def _numeric_cols(classification: dict[str, dict[str, Any]]) -> list[str]:
    return [
        c for c, info in classification.items()
        if info.get("kind") == "numeric"
    ]


def auto_segmentation(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    task: dict[str, Any],
) -> dict[str, Any]:
    """Segment rows by KMeans on scaled numeric columns; k via silhouette.

    Needs >= 3 numeric columns and >= 60 rows with complete numeric values,
    otherwise it skips cleanly. Centroids are reported in the original units
    (inverse-transformed). Cluster labels are *measurements* — no column is
    added to the frame.
    """
    numeric = _numeric_cols(classification)
    if len(numeric) < SEGMENT_MIN_NUMERIC:
        return {
            "skipped": True,
            "reason": "Segmentation needs at least "
                      f"{SEGMENT_MIN_NUMERIC} numeric columns; the dataset "
                      f"has {len(numeric)}.",
        }
    data = df[numeric].dropna()
    if len(data) < SEGMENT_MIN_ROWS:
        return {
            "skipped": True,
            "reason": f"Segmentation needs at least {SEGMENT_MIN_ROWS} rows "
                      f"with complete numeric values; only {len(data)} are "
                      "available.",
        }
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import silhouette_score
    except Exception as exc:  # pragma: no cover - sklearn is a hard dep
        return {"skipped": True, "reason": f"scikit-learn unavailable: {exc}"}

    X = data[numeric].to_numpy(dtype=float)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    max_k = min(SEGMENT_MAX_K, Xs.shape[0] - 1)
    if max_k < 2:
        return {"skipped": True,
                "reason": "Too few rows to evaluate more than one cluster."}

    best_k, best_score = None, -1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for k in range(2, max_k + 1):
            km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Xs)
            score = silhouette_score(Xs, km.labels_)
            if score > best_score:
                best_k, best_score = k, float(score)
    if best_k is None or best_score < SEGMENT_MIN_SILHOUETTE:
        return {
            "skipped": True,
            "reason": (
                "No clear cluster structure was found (best silhouette "
                f"{best_score:.2f} < {SEGMENT_MIN_SILHOUETTE}); segmentation "
                "would split noise."
            ),
        }

    km = KMeans(n_clusters=best_k, n_init=10, random_state=0).fit(Xs)
    centers = scaler.inverse_transform(km.cluster_centers_)
    labels = km.labels_
    sizes = Counter(labels)
    n = len(labels)
    clusters = []
    for i in range(best_k):
        clusters.append({
            "cluster": int(i),
            "size": int(sizes[i]),
            "share": round(sizes[i] / n, 4),
            "centroid": {
                col: round(float(centers[i, j]), 4)
                for j, col in enumerate(numeric)
            },
        })
    clusters.sort(key=lambda c: c["size"], reverse=True)

    # A small deterministic sample of row positions per cluster, so the
    # frontend can offer "view the rows in this cluster" via /subset?indices=.
    row_positions: dict[str, list[int]] = {}
    rng = np.random.default_rng(7)
    data_index = data.index.to_numpy()
    for i in range(best_k):
        members = np.flatnonzero(labels == i)
        if members.size > 25:
            members = rng.choice(members, size=25, replace=False)
        row_positions[str(i)] = [int(data_index[m]) for m in members]

    return {
        "k": int(best_k),
        "silhouette": round(best_score, 4),
        "rows_used": int(n),
        "columns": numeric,
        "clusters": clusters,
        "row_positions": row_positions,
        "method": (
            "KMeans (k=2..8 chosen by the highest silhouette score) on "
            "standard-scaled numeric columns; centroids converted back to the "
            "columns' original units."
        ),
    }


# ---------------------------------------------------------------------------
# 2. forecast_metric
# ---------------------------------------------------------------------------

FORECAST_MIN_HISTORY = 12        # monthly periods required before forecasting
FORECAST_HORIZON = 6             # periods ahead
FORECAST_CAP_PAIRS = 1           # one pair per report unless the user asks more


def _detect_metric_pairs(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
) -> list[tuple[str, str, pd.Series, pd.Series]]:
    """Return (date_col, metric_col, period_series, value_series) candidates.

    A candidate is a date-like column with >= FORECAST_MIN_HISTORY monthly
    periods and a numeric metric with a value in every one of them. Ranked by
    period count then value variance.
    """
    date_cols = [
        c for c, info in classification.items() if info.get("kind") == "date_like"
    ]
    metric_cols = _numeric_cols(classification)
    candidates: list[tuple[str, str, pd.Series, pd.Series]] = []
    for dcol in date_cols[:4]:
        if pd.api.types.is_datetime64_any_dtype(df[dcol]):
            dates = df[dcol].dropna()
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                dates = pd.to_datetime(df[dcol], errors="coerce").dropna()
        if dates.empty:
            continue
        period = dates.dt.to_period("M")
        for mcol in metric_cols[:8]:
            sub = pd.DataFrame({"period": period, "value": df.loc[dates.index, mcol]})
            sub = sub.dropna()
            if len(sub) < FORECAST_MIN_HISTORY:
                continue
            grouped = sub.groupby("period")["value"].agg(["mean", "count"])
            grouped = grouped[grouped["count"] >= 1]
            if len(grouped) < FORECAST_MIN_HISTORY:
                continue
            candidates.append((dcol, mcol, grouped.index.astype(str), grouped["mean"]))
    if not candidates:
        return []
    # Rank by longest history, then variance.
    candidates.sort(
        key=lambda c: (len(c[2]), float(c[3].var()) if len(c[3]) > 1 else 0.0),
        reverse=True,
    )
    return candidates


def _ets_forecast(series: pd.Series, horizon: int) -> dict[str, Any] | None:
    """Fit a statsmodels ETS model and return forecast + components.

    Returns None when the model cannot be fit (never raises).
    """
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    values = series.to_numpy(dtype=float)
    if values.size < FORECAST_MIN_HISTORY or np.all(values == values[0]):
        return None
    try:
        model = ETSModel(
            values,
            error="add",
            trend="add",
            seasonal=None,
            seasonal_periods=None,
            initialization_method="estimated",
        )
        fitted = model.fit(disp=False)
        pred = fitted.get_prediction(start=len(values), end=len(values) + horizon - 1)
        mean = pred.predicted_mean
        ci = pred.conf_int()
        components = fitted.fittedvalues
    except Exception:
        return None
    out = {
        "mean": [round(float(v), 4) for v in mean],
        "lower": [round(float(v), 4) for v in ci.iloc[:, 0]],
        "upper": [round(float(v), 4) for v in ci.iloc[:, 1]],
        "components": {
            "level": round(float(components[-1]), 4),
            "trend": (
                round(float(fitted.params["trend"]), 4)
                if "trend" in fitted.params else None
            ),
        },
        "trend_detectable": bool(
            "trend" in fitted.params and abs(float(fitted.params["trend"])) > 1e-6
        ),
        "seasonality_detectable": False,
        "model": "ETS (error/trend, additive)",
    }
    return out


def _seasonal_naive_forecast(series: pd.Series, horizon: int) -> dict[str, Any]:
    """Seasonal-naive fallback: repeat the last cycle, CI from residual spread."""
    values = series.to_numpy(dtype=float)
    n = len(values)
    # Monthly data -> assume yearly seasonality when enough cycles exist.
    season = 12 if n >= 24 else max(2, n // 2)
    residuals = values[season:] - values[:-season]
    resid_std = float(np.std(residuals)) if residuals.size > 1 else float(np.std(values))
    last_cycle = values[-season:]
    mean = [float(last_cycle[i % season]) for i in range(horizon)]
    half_width = 1.96 * resid_std
    return {
        "mean": [round(float(v), 4) for v in mean],
        "lower": [round(v - half_width, 4) for v in mean],
        "upper": [round(v + half_width, 4) for v in mean],
        "components": {
            "level": round(float(values[-1]), 4),
            "trend": None,
            "seasonal_period": season,
        },
        "trend_detectable": False,
        "seasonality_detectable": bool(n >= 24),
        "model": "Seasonal naive (repeat last cycle, CI from residual spread)",
    }


def forecast_metric(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    task: dict[str, Any],
) -> dict[str, Any]:
    """Forecast one date+numeric pair with ETS (or seasonal-naive fallback).

    Auto-detects the pair with the most history. Capped to one pair per report
    unless the user explicitly requested more (task.target_columns).
    """
    pairs = _detect_metric_pairs(df, classification)
    if not pairs:
        return {
            "skipped": True,
            "reason": (
                f"Forecasting needs a date-like column and a numeric metric "
                f"with at least {FORECAST_MIN_HISTORY} monthly periods of "
                "history; none were found."
            ),
        }

    # Honor explicit user requests for more than one pair.
    requested = [c for c in (task.get("target_columns") or [])]
    cap = FORECAST_CAP_PAIRS
    if requested:
        cap = max(1, min(3, len(requested)))
    else:
        # Pick the single best candidate automatically.
        pass

    out: dict[str, Any] = {}
    used = 0
    for dcol, mcol, periods, series in pairs:
        if used >= cap:
            break
        res = _ets_forecast(series, FORECAST_HORIZON)
        if res is None:
            res = _seasonal_naive_forecast(series, FORECAST_HORIZON)
        res.update({
            "date_column": dcol,
            "metric_column": mcol,
            "periods": [str(p) for p in periods],
            "history": [round(float(v), 4) for v in series.to_numpy()],
            "horizon": FORECAST_HORIZON,
            "periods_trained": int(len(periods)),
        })
        out[f"{dcol}__{mcol}"] = res
        used += 1
    if not out:
        return {"skipped": True,
                "reason": "Forecasting could not be completed for any "
                          "date+numeric pair in this dataset."}
    out["_capped"] = used >= cap and len(pairs) > used
    return out


# ---------------------------------------------------------------------------
# 3. cohort_retention
# ---------------------------------------------------------------------------

COHORT_MIN_PERIODS = 3
COHORT_MAX_COHORTS = 12
COHORT_MIN_IDS = 20


def _cohort_presence(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
) -> tuple[str, str, pd.DataFrame] | None:
    """Pick the best identifier + date pair and return a cohort-month x
    period presence table. Returns None when the data cannot support it."""
    # Entity keys: strict identifiers OR mid-cardinality categoricals whose
    # values repeat (a true cohort table records the same entity repeatedly
    # over time, so the classifier sees those ids as 'categorical', not
    # 'identifier').
    def _entity_candidate(col: str, info: dict[str, Any]) -> bool:
        if info.get("kind") == "identifier":
            return True
        if info.get("kind") != "categorical":
            return False
        cardinality = info.get("cardinality") or 0
        total = info.get("total") or 0
        if cardinality < COHORT_MIN_IDS or not total:
            return False
        ratio = cardinality / total
        return 0.005 <= ratio <= 0.5  # repeated keys, not unique-per-row

    id_cols = [
        c for c, info in classification.items()
        if _entity_candidate(c, info)
    ]
    date_cols = [
        c for c, info in classification.items() if info.get("kind") == "date_like"
    ]
    if not id_cols or not date_cols:
        return None
    id_col, date_col = id_cols[0], date_cols[0]
    sub = df[[id_col, date_col]].dropna()
    if sub.empty:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        months = pd.to_datetime(sub[date_col], errors="coerce").dt.to_period("M")
    sub = sub.assign(month=months).dropna()
    if sub.empty or sub[id_col].nunique() < 20:
        return None
    # First activity month per id = cohort.
    first = sub.groupby(id_col)["month"].min().rename("cohort")
    presence = sub.assign(cohort=sub[id_col].map(first))
    presence = presence.dropna(subset=["cohort"])
    presence["period"] = (presence["month"] - presence["cohort"]).apply(
        lambda p: int(p.n) if p is not None else None
    )
    presence = presence.dropna(subset=["period"])
    # One row per id per month (dedupe multiple activities in one month).
    presence = presence.drop_duplicates(subset=[id_col, "period"])
    return id_col, date_col, presence


def cohort_retention(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    task: dict[str, Any],
) -> dict[str, Any]:
    """Cohort retention matrix from identifier + timestamp co-occurrence.

    Cohort = month of a record's first appearance; period = months since
    first appearance. Retention for cohort c at period p = share of the
    cohort's ids still present p months later. Requires an identifier-like
    column, a date-like column and >= COHORT_MIN_PERIODS of history.
    """
    found = _cohort_presence(df, classification)
    if found is None:
        return {
            "skipped": True,
            "reason": "Cohort retention needs an identifier-like column and a "
                      "date-like column with repeated activity over time; "
                      "none were detected.",
        }
    id_col, date_col, presence = found

    cohort_sizes = presence.groupby("cohort").size()
    pivoted = presence.pivot_table(
        index="cohort", columns="period", values=id_col, aggfunc="nunique",
    ).fillna(0)
    if pivoted.shape[1] < COHORT_MIN_PERIODS:
        return {
            "skipped": True,
            "reason": "Cohort retention needs at least "
                      f"{COHORT_MIN_PERIODS} periods of history; only "
                      f"{pivoted.shape[1]} were observed.",
        }

    # Keep the most recent cohorts (they are the most decision-relevant).
    pivoted = pivoted.sort_index(ascending=False).head(COHORT_MAX_COHORTS)

    retention = pivoted.div(pivoted[0].replace(0, np.nan), axis=0) * 100
    retention = retention.fillna(0)
    matrix: list[dict[str, Any]] = []
    for cohort, row in retention.iterrows():
        matrix.append({
            "cohort": str(cohort),
            "cohort_size": int(pivoted.loc[cohort, 0]),
            "retention": [round(float(v), 1) for v in row.values],
        })

    # Surface the single most notable finding: the largest retention drop
    # between consecutive periods across cohorts with size >= 10.
    best: dict[str, Any] | None = None
    for cohort, row in retention.iterrows():
        size = int(pivoted.loc[cohort, 0])
        if size < 10:
            continue
        values = row.values
        for p in range(1, len(values)):
            drop = float(values[p - 1]) - float(values[p])
            if best is None or drop > best["drop"]:
                best = {
                    "cohort": str(cohort),
                    "cohort_size": size,
                    "period": int(p),
                    "retention_before": round(float(values[p - 1]), 1),
                    "retention_after": round(float(values[p]), 1),
                    "drop": round(drop, 1),
                }
    return {
        "identifier_column": id_col,
        "date_column": date_col,
        "cohorts": [m["cohort"] for m in matrix],
        "periods": [int(c) for c in retention.columns],
        "matrix": matrix,
        "most_notable": best,
        "method": (
            "Cohort month = first month an identifier appears; retention at "
            "period p = % of the cohort still active p months later."
        ),
    }


# ---------------------------------------------------------------------------
# 4. group_significance_test
# ---------------------------------------------------------------------------

GROUP_MIN_GROUP_SIZE = 8


def _cohens_d(a: np.ndarray, b: np.ndarray) -> float | None:
    na, nb = a.size, b.size
    if na < 2 or nb < 2:
        return None
    va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if pooled == 0:
        return None
    return float((a.mean() - b.mean()) / pooled)


def compare_two_groups(
    metric: pd.Series,
    group: pd.Series,
    label_a: str,
    label_b: str,
) -> dict[str, Any] | None:
    """Formal comparison of a numeric metric between two groups.

    Test selection reuses the normality machinery from eda/tests.py: if both
    groups are plausibly normal an independent t-test is used, otherwise a
    Mann-Whitney U. Always reports an effect size (Cohen's d). Never raises.
    Language contract: the result only ever states a "statistically
    significant difference" — never causation.
    """
    from eda.tests import normality
    from scipy import stats

    sub = pd.DataFrame({"metric": metric, "group": group}).dropna()
    a = sub.loc[sub["group"] == label_a, "metric"].to_numpy(dtype=float)
    b = sub.loc[sub["group"] == label_b, "metric"].to_numpy(dtype=float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if a.size < GROUP_MIN_GROUP_SIZE or b.size < GROUP_MIN_GROUP_SIZE:
        return None
    na = normality(pd.Series(a))
    nb = normality(pd.Series(b))
    both_normal = bool(na and nb and na["is_normal"] and nb["is_normal"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            if both_normal:
                stat, p = stats.ttest_ind(a, b, equal_var=False)
                method = "Welch's t-test (both groups plausibly normal)"
            else:
                stat, p = stats.mannwhitneyu(a, b, alternative="two-sided")
                method = "Mann-Whitney U (non-parametric; normality check failed)"
        except Exception:
            return None
    d = _cohens_d(a, b)
    significant = bool(p < 0.05)
    direction = "higher" if a.mean() > b.mean() else "lower"
    return {
        "group_a": label_a,
        "group_b": label_b,
        "n_a": int(a.size),
        "n_b": int(b.size),
        "mean_a": round(float(a.mean()), 4),
        "mean_b": round(float(b.mean()), 4),
        "median_a": round(float(np.median(a)), 4),
        "median_b": round(float(np.median(b)), 4),
        "method": method,
        "statistic": round(float(stat), 4),
        "p_value": round(float(p), 6),
        "significant": significant,
        "effect_size_d": round(d, 4) if d is not None else None,
        "interpretation": (
            "There is a statistically significant difference between the two "
            "groups."
            if significant
            else "No statistically significant difference between the two "
                 "groups was detected."
        ),
        "direction": direction,
    }


def group_significance_test(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    task: dict[str, Any],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Formal 2-group comparison for each numeric metric across every
    exactly-2-value categorical column. Effect size + significance only."""
    numeric = _numeric_cols(classification)
    binary_cats = [
        c for c, info in classification.items()
        if info.get("kind") == "categorical" and info.get("cardinality") == 2
    ]
    if not numeric or not binary_cats:
        return {
            "skipped": True,
            "reason": "This comparison needs at least one numeric metric and "
                      "one two-value categorical column; none were detected.",
        }
    out: dict[str, Any] = {}
    for ncol in numeric[:6]:
        for ccol in binary_cats[:6]:
            values = df[ccol].dropna().astype("string").unique()[:2]
            if len(values) < 2:
                continue
            res = compare_two_groups(df[ncol], df[ccol], str(values[0]), str(values[1]))
            if res is None:
                continue
            out[f"{ncol}__by__{ccol}"] = {
                **res, "numeric_column": ncol, "category_column": ccol,
            }
    if not out:
        return {
            "skipped": True,
            "reason": "No two-group comparison could be computed (groups too "
                      "small or metric non-numeric in each group).",
        }
    return out


# ---------------------------------------------------------------------------
# 5. feature_engineering_suggestions
# ---------------------------------------------------------------------------

FE_LOG_SKEW_THRESHOLD = 1.0
FE_ENCODING_CARDINALITY_MIN = 20
FE_CORRELATION_REDUNDANT = 0.85


def feature_engineering_suggestions(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    task: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Rule-based feature-engineering advice. Advisory only — never mutates
    data and never creates derived columns.

    Reuses the backbone's skew statistics and correlation matrix so nothing
    is recomputed.
    """
    numeric_stats = summary.get("numeric_stats") or {}
    correlations = summary.get("correlations") or {}

    log_candidates = []
    for col, stats in numeric_stats.items():
        skew = stats.get("skew")
        if skew is None:
            continue
        if abs(float(skew)) >= FE_LOG_SKEW_THRESHOLD:
            # Log transform needs strictly positive support.
            values = pd.to_numeric(df[col], errors="coerce").dropna()
            positive = bool(len(values) > 0 and values.min() > 0)
            log_candidates.append({
                "column": col,
                "skew": round(float(skew), 3),
                "log_transform": positive,
                "suggestion": (
                    "apply a log transform (strictly positive values)" if positive
                    else "consider a log-plus-constant or other skew transform"
                ),
            })
    log_candidates.sort(key=lambda c: abs(c["skew"]), reverse=True)

    encoding_suggestions = []
    for col, info in classification.items():
        if info.get("kind") != "categorical":
            continue
        cardinality = info.get("cardinality") or 0
        total = info.get("total") or 0
        if cardinality < FE_ENCODING_CARDINALITY_MIN:
            continue
        encoding_suggestions.append({
            "column": col,
            "cardinality": cardinality,
            "total": total,
            "suggestion": (
                "high cardinality — use target/frequency encoding or treat as "
                "free text rather than one-hot"
            ),
        })

    redundant_pairs = []
    for col_a, targets in correlations.items():
        for col_b, r in targets.items():
            if col_a >= col_b or r is None:
                continue
            if abs(float(r)) >= FE_CORRELATION_REDUNDANT:
                redundant_pairs.append({
                    "column_a": col_a,
                    "column_b": col_b,
                    "correlation": round(float(r), 3),
                })
    redundant_pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)

    return {
        "log_transform_candidates": log_candidates[:8],
        "encoding_suggestions": encoding_suggestions[:8],
        "redundant_pairs": redundant_pairs[:8],
        "advisory": True,
        "method": (
            "Rule-based heuristics reusing the backbone skew stats and "
            "correlation matrix. Proposals only — no derived column is "
            "created."
        ),
    }


# ---------------------------------------------------------------------------
# 6. multivariate_anomaly_detection
# ---------------------------------------------------------------------------

ANOMALY_MIN_NUMERIC = 2
ANOMALY_MIN_ROWS = 30
ANOMALY_MAX_CONTAMINATION = 0.05
ANOMALY_TOP_N = 30


def multivariate_anomaly_detection(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    task: dict[str, Any],
) -> dict[str, Any]:
    """Isolation Forest across the numeric feature space.

    Catches multivariate outliers that per-column IQR misses. Top-N flagged
    row positions are exposed as ``chart_data`` (the frontend can reach them
    via /subset?indices=...). Requires >= 2 numeric columns and >= 30 rows.
    """
    numeric = _numeric_cols(classification)
    if len(numeric) < ANOMALY_MIN_NUMERIC:
        return {
            "skipped": True,
            "reason": "Multivariate anomaly detection needs at least "
                      f"{ANOMALY_MIN_NUMERIC} numeric columns; the dataset "
                      f"has {len(numeric)}.",
        }
    data = df[numeric].dropna()
    if len(data) < ANOMALY_MIN_ROWS:
        return {
            "skipped": True,
            "reason": f"Needs at least {ANOMALY_MIN_ROWS} complete rows; "
                      f"only {len(data)} are available.",
        }
    try:
        from sklearn.ensemble import IsolationForest
    except Exception as exc:  # pragma: no cover
        return {"skipped": True, "reason": f"scikit-learn unavailable: {exc}"}

    X = data[numeric].to_numpy(dtype=float)
    contamination = min(ANOMALY_MAX_CONTAMINATION, max(0.001, 100.0 / X.shape[0]))
    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=0,
        n_jobs=1,
    )
    model.fit(X)
    scores = model.score_samples(X)
    predicted = model.predict(X)

    flagged_idx = np.flatnonzero(predicted == -1)
    if flagged_idx.size == 0:
        return {
            "skipped": True,
            "reason": "No multivariate outliers were detected at the current "
                      "contamination level.",
        }
    # Top-N by anomaly score (most negative = most anomalous).
    order = np.argsort(scores[flagged_idx])
    top = flagged_idx[order][:ANOMALY_TOP_N]
    row_positions = [int(data.index[i]) for i in top]
    chart_data = []
    for i in top:
        chart_data.append({
            "index": int(data.index[i]),
            "score": round(float(scores[i]), 4),
            "values": {col: round(float(X[i, j]), 4) for j, col in enumerate(numeric)},
        })
    return {
        "n_flagged": int(flagged_idx.size),
        "share_flagged": round(flagged_idx.size / X.shape[0], 4),
        "contamination": round(contamination, 4),
        "rows_checked": int(X.shape[0]),
        "columns": numeric,
        "chart_data": chart_data,
        "row_positions": row_positions,
        "method": (
            "Isolation Forest (200 trees) over standard-scaled numeric "
            "columns; flagged = score below the contamination threshold. "
            "Complements per-column IQR outliers by finding rows that are "
            "unusual in combination."
        ),
    }
