"""Rule-based findings — the deterministic "decide" layer.

Every finding is a structured object:

    {
      "type":          stable machine type,
      "severity":      "high" | "medium" | "low",
      "method":        what was computed and how (deterministic),
      "evidence":      the concrete statistic + threshold that triggered it,
      "interpretation": plain-language meaning for a non-technical reader,
      "action":        a concrete thing the user could do next,
      "message":       one short sentence (used by fallback prose + lists),
      "column"?:       affected column(s),
    }

Findings come from two places: the backbone statistics (missingness,
correlations, outliers, skew, duplicates, constants, mixed types, ...) and
the adaptive plan results stored in `summary["adaptive"]` (normality tests,
ANOVA, VIF, Mann-Kendall, Little's MCAR, text analysis, ...). Both are fully
deterministic — no LLM input here.
"""
from __future__ import annotations

import math
from typing import Any

from eda.classification import NON_CHARTABLE_KINDS

SKEW_THRESHOLD = 1.0
MISSING_HIGH_PCT = 20.0
MISSING_CRITICAL_PCT = 50.0
CORRELATION_STRONG = 0.7
OUTLIER_SHARE_NOTABLE = 0.01
OUTLIER_SHARE_HIGH = 0.05
CATEGORICAL_DOMINANCE_SHARE = 0.9
ALPHA = 0.05


def _f(x: float | None, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    try:
        if math.isnan(float(x)):
            return "n/a"
    except TypeError:
        pass
    return f"{float(x):.{nd}f}"


def _pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    try:
        if math.isnan(float(x)):
            return "n/a"
    except TypeError:
        pass
    return f"{float(x) * 100:.1f}%"


def _sev(condition: bool, high: str, medium: str) -> str:
    return high if condition else medium


def _base(ttype: str, severity: str, method: str) -> dict[str, Any]:
    return {"type": ttype, "severity": severity, "method": method}


def _column_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    classification = summary.get("column_classification", {})

    for col, info in classification.items():
        kind = info["kind"]
        if kind == "constant":
            out.append({
                **_base("constant", "medium",
                        "Classified as constant because one value covers ≥99% of rows."),
                "column": col,
                "evidence": {"top_value_share": info["top_value_share"],
                             "threshold": 0.99},
                "interpretation": (
                    f"'{col}' is the same value in "
                    f"{info['top_value_share'] * 100:.0f}% of rows, so it "
                    "carries no information for distinguishing records."),
                "action": "Drop it from analyses, or confirm it was not "
                          "intended to vary.",
                "message": f"'{col}' is constant ({info['top_value_share'] * 100:.0f}% one value).",
            })
        elif kind == "date_like":
            out.append({
                **_base("date_text", "medium",
                        "Classified as date-like because ≥80% of non-null values parse as dates."),
                "column": col,
                "evidence": {"date_parse_rate": info.get("date_parse_rate", 1.0),
                             "threshold": 0.8},
                "interpretation": (
                    f"'{col}' holds dates but is stored as "
                    f"{'text' if info.get('date_parse_rate', 1.0) < 1.0 else 'a datetime'}. "
                    "Text dates block time-based analysis."),
                "action": "Convert it to a datetime type before doing any "
                          "time-series work.",
                "message": f"'{col}' looks like a date stored as text.",
            })
        elif kind == "mixed":
            out.append({
                **_base("mixed_type", "medium",
                        "Classified as mixed because some-but-not-all values parse as numbers."),
                "column": col,
                "evidence": {"numeric_share": info.get("numeric_share"),
                             "range": "(0, 1)"},
                "interpretation": (
                    f"'{col}' mixes numbers and text "
                    f"({_pct(info.get('numeric_share'))} numeric) — a classic "
                    "sign of data-entry inconsistencies like '300$' or "
                    "'four hundred'."),
                "action": "Clean the non-numeric values (or convert them) so "
                          "the column can be analyzed numerically.",
                "message": f"'{col}' mixes numbers and text.",
            })
        elif kind == "identifier":
            out.append({
                **_base("identifier", "low",
                        "Classified as identifier because >90% of values are unique."),
                "column": col,
                "evidence": {"unique_ratio": info.get("unique_ratio"),
                             "threshold": 0.9},
                "interpretation": (
                    f"'{col}' is almost certainly an identifier "
                    f"({_pct(info.get('unique_ratio'))} unique values) — a key, "
                    "not a category."),
                "action": "Use it as a join key or record id; exclude it from "
                          "category charts.",
                "message": f"'{col}' looks like an identifier, not a category.",
            })
        elif kind == "free_text":
            out.append({
                **_base("free_text", "low",
                        "Classified as free text because average length exceeds 5 words."),
                "column": col,
                "evidence": {"avg_word_count": info.get("avg_word_count"),
                             "threshold": 5.0},
                "interpretation": (
                    f"'{col}' is long-form text (avg "
                    f"{_f(info.get('avg_word_count'), 1)} words) and is analyzed "
                    "with word frequencies, not as a category."),
                "action": "If it is really a category, standardize its values; "
                          "otherwise keep it as text.",
                "message": f"'{col}' is free text and was analyzed accordingly.",
            })
        elif kind == "empty":
            out.append({
                **_base("empty_column", "high",
                        "Classified as empty because it has no non-null values."),
                "column": col,
                "evidence": {"total": info["total"]},
                "interpretation": f"'{col}' is completely empty.",
                "action": "Drop it, or check why the source produced no values.",
                "message": f"'{col}' is empty.",
            })
    return out


def _missing_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for col, pct in summary.get("missing_pct", {}).items():
        if pct > MISSING_HIGH_PCT:
            sev = _sev(pct > MISSING_CRITICAL_PCT, "high", "medium")
            out.append({
                **_base("missing", sev, "Missing-value percentage per column."),
                "column": col,
                "evidence": {"percent_missing": pct, "threshold": MISSING_HIGH_PCT},
                "interpretation": (
                    f"'{col}' is missing {pct:.1f}% of its values"
                    + (" — over half, so most analyses on it will be thin."
                       if pct > MISSING_CRITICAL_PCT else ".")),
                "action": ("Investigate the source before imputing; if "
                           "missingness is random, decide whether to impute, "
                           "flag, or drop the column."),
                "message": f"'{col}' is missing {pct:.1f}% of its values.",
            })
    # Little's MCAR test, if the plan ran it.
    mcar = summary.get("adaptive", {}).get("missing_pattern", {}).get("littles_mcar")
    if mcar:
        out.append({
            **_base("mcar", "low" if mcar["mcar"] else "medium",
                    "Little's MCAR test on numeric columns (chi-square)."),
            "evidence": {"p_value": mcar["p_value"], "alpha": ALPHA},
            "interpretation": mcar["conclusion"],
            "action": ("If not MCAR, check whether missingness depends on "
                       "other columns (MAR) before imputing."),
            "message": f"Missingness is {'consistent with' if mcar['mcar'] else 'NOT consistent with'} MCAR (p={_f(mcar['p_value'], 6)}).",
        })
    patterns = summary.get("adaptive", {}).get("missing_pattern", {}).get("co_missing") or []
    if isinstance(patterns, dict):
        patterns = list(patterns.values())
    for cm in patterns:
        if cm.get("share_both_missing", 0) > 0.1:
            out.append({
                **_base("co_missing", "medium",
                        "Pairwise co-missingness of the most-missing columns."),
                "column": cm["column_a"],
                "evidence": {
                    "column_a": cm["column_a"], "column_b": cm["column_b"],
                    "share_both_missing": cm["share_both_missing"],
                },
                "interpretation": (
                    f"'{cm['column_a']}' and '{cm['column_b']}' are missing "
                    "together in "
                    f"{_pct(cm['share_both_missing'])} of rows — they may be "
                    "populated by the same source step."),
                "action": "Fill or drop them as a pair; their missingness is "
                          "not independent.",
                "message": f"'{cm['column_a']}' and '{cm['column_b']}' tend to be missing together.",
            })
    return out


def _correlation_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for col_a, targets in summary.get("correlations", {}).items():
        for col_b, r in targets.items():
            if col_a >= col_b or r is None:
                continue
            if abs(r) > CORRELATION_STRONG:
                out.append({
                    **_base("correlation", "high", "Pearson correlation on numeric columns."),
                    "column": f"{col_a} · {col_b}",
                    "evidence": {"r": r, "threshold": CORRELATION_STRONG},
                    "interpretation": (
                        f"'{col_a}' and '{col_b}' are strongly correlated "
                        f"(r = {_f(r, 3)}); they move together."),
                    "action": ("Don't use both as independent predictors in a "
                               "model — pick one or combine them."),
                    "message": f"'{col_a}' and '{col_b}' are strongly correlated (r = {_f(r, 3)}).",
                })
    for key, entry in summary.get("adaptive", {}).get("spearman_sig", {}).items():
        if entry.get("linear_only"):
            out.append({
                **_base("nonlinear_relation", "medium",
                        "Pearson vs Spearman comparison on numeric pairs."),
                "column": f"{entry['column_a']} · {entry['column_b']}",
                "evidence": {
                    "pearson_r": entry["pearson_r"],
                    "spearman_r": entry["spearman_r"],
                },
                "interpretation": (
                    f"'{entry['column_a']}' vs '{entry['column_b']}': Pearson "
                    f"r={_f(entry['pearson_r'], 2)} but Spearman "
                    f"r={_f(entry['spearman_r'], 2)} — the relationship is "
                    "monotonic but not linear."),
                "action": "Use rank-based methods (Spearman) or transform the "
                          "data before linear modelling.",
                "message": f"'{entry['column_a']}' vs '{entry['column_b']}' is monotonic but not linear.",
            })
    return out


def _outlier_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for col, info in summary.get("outliers", {}).items():
        if info["count"] and info["share"] > OUTLIER_SHARE_NOTABLE:
            out.append({
                **_base("outliers", _sev(info["share"] > OUTLIER_SHARE_HIGH, "high", "medium"),
                        "IQR method (bounds = Q1−1.5·IQR / Q3+1.5·IQR)."),
                "column": col,
                "evidence": {"count": info["count"], "share": info["share"],
                             "low_bound": info["low_bound"],
                             "high_bound": info["high_bound"]},
                "interpretation": (
                    f"'{col}' has {info['count']} outliers "
                    f"({info['share'] * 100:.1f}% of rows) beyond the IQR "
                    f"bounds [{_f(info['low_bound'])} , {_f(info['high_bound'])}]."),
                "action": "Review the sample values — decide whether they are "
                          "errors to fix or genuine extremes to keep.",
                "message": f"'{col}' has {info['count']} outliers ({info['share'] * 100:.1f}%).",
            })
    for col, entry in summary.get("adaptive", {}).get("outlier_multimethod", {}).items():
        z = entry.get("zscore")
        if not z:
            continue
        overlap = (entry.get("iqr_count") or 0) and (z.get("count") or 0)
        disagreement = bool(
            (entry.get("iqr_count") or 0) > 0 and (z.get("count") or 0) == 0
        ) or bool((entry.get("iqr_count") or 0) == 0 and (z.get("count") or 0) > 0)
        if overlap and disagreement:
            out.append({
                **_base("outlier_method_disagreement", "low",
                        "IQR vs robust Z-score cross-check."),
                "column": col,
                "evidence": {"iqr_count": entry.get("iqr_count"),
                             "zscore_count": z.get("count")},
                "interpretation": (
                    f"'{col}': IQR flags {entry.get('iqr_count')} outliers but "
                    f"the robust Z-score flags {z.get('count')} — the flagged "
                    "rows differ between methods, so these are marginal cases."),
                "action": "Look at the flagged rows directly rather than "
                          "trusting either rule blindly.",
                "message": f"'{col}' outlier flags differ between IQR and Z-score methods.",
            })
    return out


def _skew_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for col, stats in summary.get("numeric_stats", {}).items():
        skew = stats.get("skew")
        if skew is None:
            continue
        if abs(skew) <= SKEW_THRESHOLD:
            continue
        out.append({
            **_base("skew", _sev(abs(skew) > 2, "high", "medium"),
                    "Fisher-Pearson skewness of the numeric column."),
            "column": col,
            "evidence": {"skew": skew, "threshold": SKEW_THRESHOLD},
            "interpretation": (
                f"'{col}' is heavily skewed (skew = {_f(skew, 3)}) — the mean "
                "is pulled by the tail, so the median is a safer summary."),
            "action": "Report the median; consider a log transform before "
                      "any modelling that assumes symmetry.",
            "message": f"'{col}' is heavily skewed (skew = {_f(skew, 3)}).",
        })
    return out


def _categorical_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    classification = summary.get("column_classification", {})
    for col, info in summary.get("categorical_summary", {}).items():
        if classification.get(col, {}).get("kind") in NON_CHARTABLE_KINDS:
            continue
        if info["cardinality"] <= 1:
            continue
        if info["top"] and info["top"][0]["share"] > CATEGORICAL_DOMINANCE_SHARE:
            top = info["top"][0]
            out.append({
                **_base("categorical_dominance", "medium",
                        "Top-value share of categorical columns."),
                "column": col,
                "evidence": {"dominant_value": top["value"],
                             "share": top["share"], "threshold": CATEGORICAL_DOMINANCE_SHARE},
                "interpretation": (
                    f"'{col}' is dominated by '{top['value']}' "
                    f"({top['share'] * 100:.1f}% of rows)."),
                "action": "Either the dominated value is the norm (fine), or "
                          "the column's scope is narrower than expected.",
                "message": f"'{col}' is dominated by '{top['value']}'.",
            })
    return out


def _group_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    comparisons = list(summary.get("numeric_by_categorical", {}).values())
    comparisons.sort(key=lambda c: abs(c.get("effect_size_std") or 0), reverse=True)
    for cmp in comparisons[:5]:
        effect = cmp.get("effect_size_std") or 0
        if abs(effect) < 0.5:
            continue
        groups = cmp["groups"]
        top, bottom = groups[0], groups[-1]
        out.append({
            **_base("group_difference", _sev(abs(effect) > 1, "high", "medium"),
                    "Group means compared; effect size = gap in overall std devs."),
            "column": f"{cmp['numeric_column']} · {cmp['category_column']}",
            "evidence": {
                "numeric_column": cmp["numeric_column"],
                "category_column": cmp["category_column"],
                "top_group": top["group"], "top_mean": top["mean"],
                "bottom_group": bottom["group"], "bottom_mean": bottom["mean"],
                "effect_size_std": effect, "threshold": 0.5,
            },
            "interpretation": (
                f"Average '{cmp['numeric_column']}' differs across "
                f"'{cmp['category_column']}': '{top['group']}' averages "
                f"{_f(top['mean'])} vs {_f(bottom['mean'])} for "
                f"'{bottom['group']}' ({effect:.2f} std devs)."),
            "action": "Dig into the top/bottom groups — this split may be "
                      "your best segmentation variable.",
            "message": f"'{cmp['numeric_column']}' differs notably across '{cmp['category_column']}'.",
        })

    for entry in summary.get("adaptive", {}).get("anova_kruskal", {}).values():
        ph = entry.get("post_hoc")
        if entry.get("significant") and ph and ph.get("significant"):
            out.append({
                **_base("post_hoc_difference", "medium",
                        "Kruskal-Wallis + Mann-Whitney post-hoc on the extreme groups."),
                "column": f"{entry.get('numeric_column', '')} · {entry.get('category_column', '')}",
                "evidence": {
                    "group_a": ph["group_a"], "group_b": ph["group_b"],
                    "mean_a": ph["mean_a"], "mean_b": ph["mean_b"],
                    "p_value": ph["p_value"],
                },
                "interpretation": (
                    f"'{ph['group_a']}' and '{ph['group_b']}' differ "
                    f"significantly (p={_f(ph['p_value'], 6)}) on the numeric "
                    "column."),
                "action": "Quantify the difference and decide if it is "
                          "business-relevant, not just statistically significant.",
                "message": f"Groups '{ph['group_a']}' and '{ph['group_b']}' differ significantly.",
            })
    return out


def _trend_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for col, trend in summary.get("time_trends", {}).items():
        corr = trend.get("trend_correlation") or 0
        if abs(corr) < 0.5:
            continue
        out.append({
            **_base("trend", "medium",
                    "Monthly row-count trend correlation on the date column."),
            "column": col,
            "evidence": {"trend_correlation": corr, "threshold": 0.5,
                         "periods": trend.get("periods")},
            "interpretation": (
                f"Row counts by '{col}' trend {trend['direction']} from "
                f"{trend.get('start')} to {trend.get('end')}."),
            "action": "If the trend matters, model it explicitly; a trend is "
                      "not the same as causation.",
            "message": f"Row counts by '{col}' show a {trend['direction']} trend.",
        })
    mk = summary.get("adaptive", {}).get("trend_mannkendall", {})
    for col, res in mk.items():
        if res and res.get("significant"):
            out.append({
                **_base("mann_kendall_trend", "medium",
                        "Mann-Kendall trend test on the date series."),
                "column": col,
                "evidence": {"tau": res.get("tau"), "p_value": res.get("p_value")},
                "interpretation": (
                    f"'{col}' shows a significant {res.get('direction')} trend "
                    f"(τ={_f(res.get('tau'))}, p={_f(res.get('p_value'), 6)})."),
                "action": "Treat the trend as real signal for forecasting or "
                          "monitoring.",
                "message": f"'{col}' has a significant {res.get('direction')} trend.",
            })
    return out


def _adaptive_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    adaptive = summary.get("adaptive", {})

    for col, res in adaptive.get("normality", {}).items():
        if res and not res.get("is_normal"):
            out.append({
                **_base("non_normal", "low", res.get("method", "normality test")),
                "column": col,
                "evidence": {"p_value": res.get("p_value"), "alpha": ALPHA},
                "interpretation": (
                    f"'{col}' is significantly non-normal "
                    f"(p={_f(res.get('p_value'), 6)}), so mean-based summaries "
                    "and parametric tests are less trustworthy."),
                "action": "Prefer medians, quantiles and non-parametric tests "
                          "for this column.",
                "message": f"'{col}' is significantly non-normal.",
            })

    for col, res in adaptive.get("vif", {}).items():
        if res and res.get("collinear"):
            out.append({
                **_base("multicollinearity", "medium",
                        "Variance Inflation Factor (regression R²)."),
                "column": col,
                "evidence": {"vif": res.get("vif"), "threshold": 10},
                "interpretation": (
                    f"'{col}' has VIF {res.get('vif') or '∞'} — "
                    f"{res['interpretation']}."),
                "action": "Drop or combine one of the collinear columns before "
                          "using them in a regression.",
                "message": f"'{col}' shows multicollinearity (VIF ≥ 10).",
            })

    for col, res in adaptive.get("distribution_fit", {}).items():
        if res and res.get("best") not in ("normal",):
            out.append({
                **_base("distribution_shape", "low",
                        "AIC-ranked candidate distribution fitting."),
                "column": col,
                "evidence": {"best_fit": res.get("best"),
                             "candidates": res.get("candidates")},
                "interpretation": (
                    f"'{col}' is best described by a {res.get('best')} "
                    f"distribution rather than a normal one."),
                "action": "Choose tests/summaries that match this shape "
                          "(e.g. log transform for lognormal-like data).",
                "message": f"'{col}' resembles a {res.get('best')} distribution.",
            })

    for col, res in adaptive.get("text_top_words", {}).items():
        if res and res.get("top_words"):
            words = ", ".join(w["value"] for w in res["top_words"][:5])
            out.append({
                **_base("text_profile", "low",
                        "Word/ngram frequency analysis of the free-text column."),
                "column": col,
                "evidence": {"vocabulary_size": res.get("vocabulary_size"),
                             "top_words": words},
                "interpretation": (
                    f"'{col}' has a vocabulary of {res.get('vocabulary_size')} "
                    f"tokens; top terms: {words}."),
                "action": "Consider clustering or topic labelling if this "
                          "column drives decisions.",
                "message": f"'{col}' text vocabulary size: {res.get('vocabulary_size')}.",
            })

    for col, res in adaptive.get("duplicate_ids", {}).items():
        if res and res.get("duplicate_count"):
            out.append({
                **_base("duplicate_ids", "high" if res["duplicate_share"] > 0.05 else "medium",
                        "Uniqueness check on identifier-like columns."),
                "column": col,
                "evidence": {"duplicate_count": res["duplicate_count"],
                             "duplicate_share": res["duplicate_share"]},
                "interpretation": (
                    f"'{col}' was expected to be unique but has "
                    f"{res['duplicate_count']} duplicate values "
                    f"({_pct(res['duplicate_share'])})."),
                "action": "Fix or deduplicate before joining on this key.",
                "message": f"'{col}' has {res['duplicate_count']} duplicate ids.",
            })
    return out


def _data_quality_score_finding(summary: dict[str, Any]) -> dict[str, Any] | None:
    res = summary.get("adaptive", {}).get("data_quality_score")
    if not res or not isinstance(res, dict) or res.get("skipped"):
        return None
    grade = res.get("grade", "needs_attention")
    score = res.get("score", 0)
    sev = {"excellent": "low", "good": "low", "fair": "medium"}.get(
        grade, "high")
    parts = []
    p = res.get("penalties") or {}
    if p.get("nulls", 0) > 0:
        parts.append(f"nulls −{p['nulls']:.0f}")
    if p.get("implausible_values", 0) > 0:
        parts.append(f"implausible values −{p['implausible_values']:.0f}")
    if p.get("duplicates", 0) > 0:
        parts.append(f"duplicates −{p['duplicates']:.0f}")
    if p.get("mixed_types", 0) > 0:
        parts.append(f"mixed types −{p['mixed_types']:.0f}")
    if p.get("constant_or_empty", 0) > 0:
        parts.append(f"constant/empty −{p['constant_or_empty']:.0f}")
    detail = "; ".join(parts) if parts else "no penalties applied"
    return {
        **_base("data_quality_score", sev, res.get("method", "")),
        "evidence": {
            "score": score, "grade": grade,
            "components": res.get("components"),
            "penalties": p,
        },
        "interpretation": (
            f"Overall data quality is {grade.replace('_', ' ')} "
            f"(score {score}/100). Penalty breakdown: {detail}."
        ),
        "action": (
            "Start with the biggest penalty: address that issue first, then "
            "re-run the analysis."
        ),
        "message": f"Data quality score: {score}/100 ({grade.replace('_', ' ')}).",
    }


def _new_adaptive_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Findings from the six newer adaptive tasks (advanced.py)."""
    out: list[dict[str, Any]] = []
    adaptive = summary.get("adaptive", {})

    for col, res in (adaptive.get("category_harmonization") or {}).items():
        if not isinstance(res, dict):
            continue
        merges = res.get("example_merges") or []
        if not merges:
            continue
        m = merges[0]
        variants = ", ".join(f"'{v}'" for v in m.get("variants", [])[:2])
        out.append({
            **_base("category_harmonization", "medium",
                    res.get("method", "Fuzzy label clustering.")),
            "column": col,
            "evidence": {
                "original_unique": res.get("original_unique"),
                "merged_unique": res.get("merged_unique"),
                "reduction_pct": res.get("reduction_pct"),
                "threshold_pct": res.get("reduction_margin_threshold_pct"),
                "example_merges": merges,
            },
            "interpretation": (
                f"'{col}' has {res.get('original_unique')} distinct values, "
                f"but {res.get('merged_unique')} of them look like "
                f"near-duplicates of each other. Merging would cut the unique "
                f"count by {_f(res.get('reduction_pct'), 1)}% — e.g. "
                f"'{m.get('canonical')}' also appears as {variants}."
            ),
            "action": (
                "Confirm the merge groups, then standardize the labels in your "
                "source so categories count consistently."
            ),
            "message": f"'{col}' has near-duplicate category labels ({_f(res.get('reduction_pct'), 1)}% reducible).",
        })

    for key, res in (adaptive.get("outlier_subpopulation") or {}).items():
        if not isinstance(res, dict):
            continue
        out.append({
            **_base("outlier_subpopulation",
                    "high" if (res.get("ratio") or 0) > 5 else "medium",
                    res.get("method", "Outlier concentration vs baseline rate.")),
            "column": f"{res.get('numeric_column')} · {res.get('category_column')}",
            "evidence": {
                "numeric_column": res.get("numeric_column"),
                "category_column": res.get("category_column"),
                "value": res.get("value"),
                "subgroup_count": res.get("subgroup_count"),
                "subgroup_outlier_count": res.get("subgroup_outlier_count"),
                "subgroup_outlier_rate": res.get("subgroup_outlier_rate"),
                "baseline_outlier_rate": res.get("baseline_outlier_rate"),
                "ratio": res.get("ratio"),
                "significance_bound": res.get("significance_bound"),
            },
            "interpretation": (
                f"Outliers in '{res.get('numeric_column')}' are heavily "
                f"concentrated in '{res.get('category_column')}' = "
                f"'{res.get('value')}': {res.get('subgroup_outlier_count')} of "
                f"{res.get('subgroup_count')} rows in that group are outliers "
                f"({_pct(res.get('subgroup_outlier_rate'))}), vs a baseline of "
                f"{_pct(res.get('baseline_outlier_rate'))} — a "
                f"{res.get('ratio')}× concentration."
            ),
            "action": (
                "Investigate what is different about that subgroup — the "
                "outliers may be a real subpopulation rather than data errors."
            ),
            "message": f"'{res.get('numeric_column')}' outliers concentrate in '{res.get('value')}' ({res.get('ratio')}× baseline).",
        })

    drift = adaptive.get("distribution_drift") or {}
    if isinstance(drift, dict) and not drift.get("skipped"):
        for col, res in drift.items():
            if not isinstance(res, dict):
                continue
            out.append({
                **_base("distribution_drift", "medium",
                        "PSI (population stability index) vs prior report."),
                "column": col,
                "evidence": {
                    "psi": res.get("psi"),
                    "threshold": res.get("threshold"),
                    "prior_rows": res.get("prior_rows"),
                    "current_rows": res.get("current_rows"),
                    "mean_shift": res.get("mean_shift"),
                    "prior_mean": res.get("prior_mean"),
                    "current_mean": res.get("current_mean"),
                },
                "interpretation": (
                    f"'{col}' has drifted materially (PSI = {_f(res.get('psi'))} "
                    f"> {res.get('threshold')}) compared to your most recent "
                    f"analysis ({res.get('prior_rows')} rows then vs "
                    f"{res.get('current_rows')} now). "
                    + (f"Mean moved from {_f(res.get('prior_mean'))} to "
                       f"{_f(res.get('current_mean'))}."
                       if res.get("mean_shift") is not None else "")
                ),
                "action": (
                    "Treat this file as a distributional change, not a "
                    "re-run — re-validate any model or threshold built on the "
                    "previous dataset."
                ),
                "message": f"'{col}' shows distributional drift vs your prior analysis (PSI {_f(res.get('psi'))}).",
            })

    for col, res in (adaptive.get("pattern_extraction_proposal") or {}).items():
        if not isinstance(res, dict):
            continue
        out.append({
            **_base("pattern_extraction_proposal", "low",
                    "Regex pattern-match rate across non-null text values."),
            "column": col,
            "evidence": {
                "pattern": res.get("pattern"),
                "match_rate": res.get("match_rate"),
                "threshold": res.get("match_rate_threshold"),
                "derived_field_proposal": res.get("derived_field_proposal"),
                "example_matches": res.get("example_matches"),
            },
            "interpretation": (
                f"{_pct(res.get('match_rate'))} of '{col}' values follow one "
                f"consistent pattern ('{res.get('pattern')}'). Extracting "
                f"'{res.get('derived_field_proposal')}' would let you filter, "
                "group or chart on that field directly."
            ),
            "action": (
                "Extract the derived field if you need to analyze that "
                "component separately — this is a proposal, nothing was changed."
            ),
            "message": f"'{col}' contains a consistent '{res.get('pattern')}' pattern ({_pct(res.get('match_rate'))} match).",
        })

    for col, res in (adaptive.get("text_theme_extraction") or {}).items():
        if not isinstance(res, dict) or res.get("skipped"):
            continue
        top_theme = (res.get("themes") or [{}])[0]
        examples = top_theme.get("examples") or []
        anchor = examples[0]["text"] if examples else ""
        out.append({
            **_base("text_theme_extraction", "medium",
                    res.get("method", "Local embeddings + PCA.")),
            "column": col,
            "evidence": {
                "texts_embedded": res.get("texts_embedded"),
                "components": res.get("components"),
                "explained_variance": res.get("explained_variance"),
                "cumulative_explained_variance": res.get("cumulative_explained_variance"),
            },
            "interpretation": (
                f"'{col}' clusters into {res.get('components')} latent themes "
                f"explaining "
                f"{_pct(res.get('cumulative_explained_variance'))} of the "
                "text's variance (measured, not assumed). A representative "
                f"text is: \"{anchor[:120]}\""
            ),
            "action": (
                "If the themes map to real business categories, add them as a "
                "derived label — or just use them to skim what this column is "
                "about."
            ),
            "message": f"'{col}' has {res.get('components')} latent themes ({_pct(res.get('cumulative_explained_variance'))} variance explained).",
        })
    return out


def select_findings(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble all deterministic findings for a summary."""
    findings: list[dict[str, Any]] = []

    # Duplicate rows.
    dup_count = int(summary.get("duplicate_count", 0))
    if dup_count:
        dup_share = float(summary.get("duplicate_share") or 0)
        findings.append({
            **_base("duplicates", "high" if dup_share > 5 else "medium",
                    "Exact-duplicate-row detection (all columns)."),
            "evidence": {"count": dup_count, "share": dup_share},
            "interpretation": (
                f"{dup_count} exact duplicate rows ({dup_share:.1f}% of rows) "
                "inflate counts and double-count records."),
            "action": "Decide whether duplicates are re-submissions to remove, "
                      "or legitimate repeats to keep.",
            "message": f"{dup_count} duplicate rows detected ({dup_share:.1f}%).",
        })

    dq = _data_quality_score_finding(summary)
    if dq:
        findings.append(dq)

    findings += _column_findings(summary)
    findings += _missing_findings(summary)
    findings += _correlation_findings(summary)
    findings += _outlier_findings(summary)
    findings += _skew_findings(summary)
    findings += _categorical_findings(summary)
    findings += _group_findings(summary)
    findings += _trend_findings(summary)
    findings += _adaptive_findings(summary)
    findings += _new_adaptive_findings(summary)

    if not summary.get("correlations") and not summary.get("numeric_stats"):
        findings.append({
            **_base("no_numeric", "medium",
                    "Scan for numeric columns across the whole file."),
            "evidence": {},
            "interpretation": "No numeric columns were detected, so correlation "
                              "and outlier analysis are not available.",
            "action": "Convert numeric-looking text columns, then re-run.",
            "message": "No numeric columns were detected.",
        })
    if not findings:
        findings.append({
            **_base("clean", "low", "Full rule set passed with nothing notable."),
            "evidence": {},
            "interpretation": "No major data-quality or relationship issues "
                              "were flagged.",
            "action": "Read the charts for the full picture.",
            "message": "No significant issues were flagged.",
        })
    return findings
