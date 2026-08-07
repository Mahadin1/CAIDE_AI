"""Deterministic executor for the adaptive plan.

The executor is where "pandas/scipy compute". It takes the loaded frame, the
column classification, the analysis plan and the user overrides, and produces
the full summary JSON: the always-on backbone statistics plus the
plan-driven enhanced analyses stored under `summary["adaptive"]`.

Every plan task type maps to a pure function below. Tasks whose data
conditions are absent are recorded as *skipped* with a reason — never
silently dropped — so the narrative can explain what was chosen and why.
"""
from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd

from eda import tests as stat_tests
from eda import text as text_analysis
from eda import dates as dates_analysis
from eda.stats_core import (
    apply_overrides,
    build_chart_specs,
    run_backbone,
)
from eda.classification import classify_columns
from eda import advanced as advanced_tasks

ROBUST_Z_THRESHOLD = 3.5


# ---------------------------------------------------------------------------
# Task implementations
# ---------------------------------------------------------------------------

def _task_missing_pattern(summary: dict[str, Any], df: pd.DataFrame, task: dict) -> dict:
    littles = stat_tests.littles_mcar(df)
    co = list((summary.get("missing_patterns", {}).get("co_missing") or {}).values())
    return {
        "littles_mcar": littles,
        "co_missing": co[:5],
        "note": ("Missing-value relationships and a formal MCAR test. "
                 "Exactly which rows are missing and why is often more "
                 "important than how many."),
    }


def _task_outlier_multimethod(df: pd.DataFrame, task: dict) -> dict:
    targets = [c for c in (task.get("target_columns") or [])
               if c in df.select_dtypes(include=[np.number]).columns]
    if not targets:
        targets = list(df.select_dtypes(include=[np.number]).columns[:6])
    out: dict[str, Any] = {}
    for col in targets:
        values = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if values.size < 8:
            continue
        q1, q3 = np.percentile(values, [25, 75])
        iqr = q3 - q1
        iqr_count = int(((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0
        med = float(np.median(values))
        mad = float(np.median(np.abs(values - med)))
        if mad == 0:
            z_count = 0
        else:
            z = 0.6745 * (values - med) / mad
            z_count = int((np.abs(z) > ROBUST_Z_THRESHOLD).sum())
        out[col] = {
            "iqr_count": iqr_count,
            "zscore": {
                "count": z_count,
                "threshold": ROBUST_Z_THRESHOLD,
                "method": "Robust Z-score (median + MAD, threshold ±3.5)",
            },
            "method": ("Two outlier methods: IQR fences and a robust Z-score. "
                       "Where they disagree, the flagged rows are marginal."),
        }
    return out


def _task_normality(df: pd.DataFrame, task: dict) -> dict:
    numeric = [c for c in df.select_dtypes(include=[np.number]).columns]
    targets = [c for c in (task.get("target_columns") or []) if c in numeric] or numeric[:6]
    out: dict[str, Any] = {}
    for col in targets:
        res = stat_tests.normality(df[col])
        if res:
            out[col] = res
    return out


def _task_distribution_fit(df: pd.DataFrame, task: dict) -> dict:
    numeric = [c for c in df.select_dtypes(include=[np.number]).columns]
    # Prefer skewed columns — a normal-shaped column rarely needs fitting.
    skews = {
        c: (df[c].skew() if df[c].skew() == df[c].skew() else 0)
        for c in numeric
    }
    ranked = sorted(skews, key=lambda c: abs(skews[c]), reverse=True)
    targets = [c for c in (task.get("target_columns") or []) if c in numeric]
    targets = targets or ranked[:4]
    out: dict[str, Any] = {}
    for col in targets:
        res = stat_tests.fit_distributions(df[col])
        if res:
            out[col] = res
    return out


def _task_anova_kruskal(df: pd.DataFrame, task: dict) -> dict:
    numeric = [c for c in df.select_dtypes(include=[np.number]).columns]
    categorical = list(df.select_dtypes(include=["object", "category"]).columns)
    num_targets = [c for c in (task.get("target_columns") or []) if c in numeric] or numeric[:4]
    cat_targets = [c for c in (task.get("target_columns") or []) if c in categorical] or categorical[:4]
    out: dict[str, Any] = {}
    for ncol in num_targets[:4]:
        for ccol in cat_targets[:4]:
            res = stat_tests.group_tests(df[ncol], df[ccol])
            if res:
                out[f"{ncol}__by__{ccol}"] = {
                    **res, "numeric_column": ncol, "category_column": ccol,
                }
    return out


def _task_vif(df: pd.DataFrame, task: dict) -> dict:
    return stat_tests.vif(df)


def _task_trend_mannkendall(df: pd.DataFrame, task: dict, classification: dict) -> dict:
    date_cols = [c for c, info in classification.items() if info["kind"] == "date_like"]
    targets = [c for c in (task.get("target_columns") or []) if c in date_cols] or date_cols[:4]
    out: dict[str, Any] = {}
    for col in targets:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            s = df[col].dropna()
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                s = pd.to_datetime(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        counts = s.dt.to_period("M").value_counts().sort_index()
        res = stat_tests.mann_kendall(counts.to_numpy(dtype=float))
        if res:
            out[col] = {**res, "periods": int(len(counts)),
                        "start": str(counts.index[0]), "end": str(counts.index[-1])}
    return out


def _task_temporal(df: pd.DataFrame, classification: dict, task: dict) -> dict:
    return dates_analysis.compute_temporal_summary(df, classification)


def _task_duplicate_ids(df: pd.DataFrame, classification: dict, task: dict) -> dict:
    id_cols = [c for c, info in classification.items() if info["kind"] == "identifier"]
    targets = [c for c in (task.get("target_columns") or []) if c in id_cols] or id_cols[:4]
    out: dict[str, Any] = {}
    for col in targets:
        dup = df[col].value_counts()
        dup = dup[dup > 1]
        total = int(df[col].notna().sum())
        out[col] = {
            "duplicate_count": int(len(dup)),
            "duplicate_share": round(len(dup) / total, 4) if total else 0.0,
            "duplicate_values": [{"value": str(k), "count": int(v)}
                                 for k, v in dup.head(5).items()],
            "unique_ratio": round(df[col].nunique() / total, 4) if total else 0.0,
        }
    return out


def _task_date_as_text(df: pd.DataFrame, classification: dict, task: dict) -> dict:
    out: dict[str, Any] = {}
    for col, info in classification.items():
        if info["kind"] == "date_like" and info.get("date_parse_rate", 1.0) < 1.0:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                parsed = pd.to_datetime(df[col].astype("string").str.strip(),
                                        errors="coerce")
            unparsed = df[col][parsed.isnull()].dropna().head(5).tolist()
            out[col] = {
                "date_parse_rate": info.get("date_parse_rate"),
                "unparseable_examples": [str(v)[:60] for v in unparsed],
                "note": ("Convert this column to a datetime type before "
                         "time-series analysis."),
            }
    return out


def _task_mixed_cleanup(df: pd.DataFrame, classification: dict, task: dict) -> dict:
    out: dict[str, Any] = {}
    for col, info in classification.items():
        if info["kind"] != "mixed":
            continue
        cleaned = df[col].astype("string").str.strip().replace({"": None})
        numeric_mask = pd.to_numeric(cleaned, errors="coerce").notna()
        non_numeric = df.loc[~numeric_mask, col].dropna().head(5).tolist()
        out[col] = {
            "numeric_share": info.get("numeric_share"),
            "non_numeric_examples": [str(v)[:60] for v in non_numeric],
            "note": ("The non-numeric values listed above are what prevents "
                     "this column from being numeric."),
        }
    return out


def _task_text_top_words(df: pd.DataFrame, classification: dict, task: dict) -> dict:
    text_cols = [c for c, info in classification.items() if info["kind"] == "free_text"]
    targets = [c for c in (task.get("target_columns") or []) if c in text_cols] or text_cols[:4]
    out: dict[str, Any] = {}
    for col in targets:
        summary = text_analysis.text_summary(df[col])
        if summary:
            out[col] = summary
    return out


def _task_group_comparison(summary: dict[str, Any], task: dict) -> dict:
    # Backbone already computes per-group means; add the formal tests on the
    # most notable comparison for a post-hoc statement.
    comparisons = list(summary.get("numeric_by_categorical", {}).values())
    comparisons.sort(key=lambda c: abs(c.get("effect_size_std") or 0), reverse=True)
    out: dict[str, Any] = {}
    for cmp in comparisons[:3]:
        if abs(cmp.get("effect_size_std") or 0) < 0.5:
            continue
        out[f"{cmp['numeric_column']}__by__{cmp['category_column']}"] = {
            "effect_size_std": cmp.get("effect_size_std"),
            "groups": cmp["groups"],
            "note": ("The gap between the top and bottom group is "
                     f"{abs(cmp.get('effect_size_std') or 0):.2f} overall "
                     "standard deviations."),
        }
    return out


def _task_cardinality_sanity(df: pd.DataFrame, classification: dict, task: dict) -> dict:
    out: dict[str, Any] = {}
    for col, info in classification.items():
        if info["kind"] != "categorical":
            continue
        total = info.get("total", 0)
        cardinality = info.get("cardinality", 0)
        if total and cardinality / total > 0.9 and cardinality >= 5:
            out[col] = {
                "cardinality": cardinality,
                "total": total,
                "note": "High cardinality for a 'categorical' column — check "
                        "whether it is really a free field (e.g. names).",
            }
    return out


# ---------------------------------------------------------------------------
# Task dispatch
# ---------------------------------------------------------------------------

_TASK_HANDLERS: dict[str, Any] = {}


def _register(name: str):
    def deco(fn):
        _TASK_HANDLERS[name] = fn
        return fn
    return deco


_register("missing_pattern")(_task_missing_pattern)
_register("outlier_multimethod")(_task_outlier_multimethod)
_register("normality")(_task_normality)
_register("distribution_fit")(_task_distribution_fit)
_register("anova_kruskal")(_task_anova_kruskal)
_register("vif")(_task_vif)
_register("trend_mannkendall")(_task_trend_mannkendall)
_register("time_features")(_task_temporal)
_register("seasonality")(_task_temporal)
_register("duplicate_ids")(_task_duplicate_ids)
_register("date_as_text")(_task_date_as_text)
_register("mixed_type_cleanup")(_task_mixed_cleanup)
_register("text_top_words")(_task_text_top_words)
_register("group_comparison")(_task_group_comparison)
_register("cardinality_sanity")(_task_cardinality_sanity)
_register("category_harmonization")(
    advanced_tasks.harmonize_categories)
_register("outlier_subpopulation")(
    advanced_tasks.outlier_subpopulations)
_register("data_quality_score")(advanced_tasks.data_quality_score)
_register("text_theme_extraction")(advanced_tasks.text_themes)
_register("distribution_drift")(advanced_tasks.distribution_drift)
_register("pattern_extraction_proposal")(
    advanced_tasks.patterns_proposal)


def _execute_task(
    task: dict[str, Any],
    summary: dict[str, Any],
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    ttype = task["type"]
    try:
        if ttype == "spearman_sig":
            return stat_tests.spearman_significant(df)
        if ttype == "cramer_v":
            return summary.get("categorical_associations")
        if ttype == "vif":
            return stat_tests.vif(df)
        if ttype == "custom_question":
            return {
                "question": task.get("description", ""),
                "note": "Addressed qualitatively in the narrative using the "
                        "evidence in the findings.",
            }
        handler = _TASK_HANDLERS.get(ttype)
        if handler is None:
            return {"skipped": True, "reason": f"Unknown task type: {ttype}"}
        if ttype in ("missing_pattern",):
            return handler(summary, df, task)
        if ttype in ("trend_mannkendall", "duplicate_ids", "date_as_text",
                     "mixed_type_cleanup", "text_top_words",
                     "cardinality_sanity"):
            return handler(df, classification, task)
        if ttype in ("time_features", "seasonality"):
            return handler(df, classification, task)
        if ttype == "group_comparison":
            return handler(summary, task)
        if ttype == "outlier_multimethod":
            return handler(df, task)
        if ttype in ("normality", "distribution_fit", "anova_kruskal"):
            return handler(df, task)
        if ttype in ("category_harmonization", "text_theme_extraction",
                     "pattern_extraction_proposal"):
            return handler(df, classification, task)
        if ttype == "outlier_subpopulation":
            return handler(summary, df, classification, task)
        if ttype == "data_quality_score":
            return handler(summary, task)
        if ttype == "distribution_drift":
            return handler(summary, df, task)
        return {"skipped": True, "reason": f"Unhandled task type: {ttype}"}
    except Exception:
        return {"skipped": True,
                "reason": f"Analysis '{ttype}' could not be completed for "
                          "this data (numerical limitation), so it was skipped."}


def execute_plan(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    plan_tasks: list[dict[str, Any]],
    prior_report: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the backbone + plan. Returns (summary, executed, skipped)."""
    summary = run_backbone(df, classification)
    if prior_report:
        # Private scratch key consumed by the distribution_drift task; it is
        # stripped again below so it is never persisted into summary_json.
        summary["_prior_report"] = prior_report
    adaptive: dict[str, Any] = {}
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for task in plan_tasks:
        ttype = task["type"]
        result = _execute_task(task, summary, df, classification)
        if result and result.get("skipped"):
            skipped.append({"id": task["id"], "type": ttype,
                            "reason": result["reason"]})
            continue
        if ttype in ("time_features", "seasonality"):
            adaptive.setdefault("temporal", {}).update(result or {})
            continue
        if ttype == "spearman_sig" and result is not None:
            adaptive[ttype] = result
            executed.append(task)
            continue
        if ttype == "cramer_v" and result:
            adaptive["cramer_v"] = result
            executed.append(task)
            continue
        if result:
            adaptive.setdefault(ttype, {}).update(result)
            executed.append(task)

    summary.pop("_prior_report", None)
    summary["adaptive"] = adaptive
    summary["executed_tasks"] = [
        {"id": t["id"], "type": t["type"], "description": t["description"],
         "rationale": t["rationale"]}
        for t in executed
    ]
    summary["skipped_tasks"] = skipped
    summary["chart_specs"] = build_chart_specs(summary)
    return summary, executed, skipped


def run_pipeline_on_frame(
    df: pd.DataFrame,
    *,
    loaded,
    plan_tasks: list[dict[str, Any]],
    overrides: dict[str, Any] | None = None,
    storage_path: str = "",
    prior_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full summary for a loaded frame.

    Handles user overrides (column kinds, exclusions), the streaming globals
    for sampled files, and the adaptive plan execution.
    """
    overrides = overrides or {}

    # Apply exclusions + validated column-type overrides.
    df, override_kinds = apply_overrides(df, overrides)

    classification = classify_columns(df)
    for col, kind in override_kinds.items():
        if col in classification:
            base = classification[col]
            # Preserve cardinality/total; swap kind.
            classification[col] = {**base, "kind": kind}

    summary, executed, skipped = execute_plan(
        df, classification, plan_tasks, prior_report=prior_report
    )

    # Sampling provenance + exact streaming globals for sampled files.
    if loaded and not loaded.fully_loaded and loaded.streaming:
        globals_out = loaded.streaming.finalize()
        summary["streaming_globals"] = {
            "total_rows": globals_out["total_rows"],
            "numeric": globals_out["numeric"],
            "missing_counts": globals_out["missing_counts"],
            "top_values": globals_out["top_values"],
        }
        summary["overrides_applied"] = {
            "excluded_columns": sorted(set(overrides.get("exclude_columns") or [])
                                       & set(df.columns)),
            "column_type_overrides": override_kinds,
        }
    return summary
