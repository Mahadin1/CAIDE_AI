"""Verification suite for the multi-skill platform features.

Covers the plan-to-skips invariant and the six new adaptive tasks plus the
user-initiated skills, each on an APPLICABLE dataset (expects a real result)
and a NON-APPLICABLE dataset (expects a clean skip, never a forced/wrong
result).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eda.classification import classify_columns
from eda import adaptive
from eda import initiated
from eda import joinskill
from eda.gating import (
    adaptive_task_tier, meets_tier, required_tier, credit_cost,
    qa_credits_for_plan, USER_SKILLS,
)


def _classify(df: pd.DataFrame):
    return classify_columns(df)


def _task(ttype: str, **kw) -> dict:
    return {"type": ttype, "id": ttype, "description": ttype, "rationale": "", **kw}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def numeric_df() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 400
    a = rng.normal(50, 10, n)
    b = rng.normal(30, 5, n)
    c = a * 0.8 + rng.normal(0, 2, n)
    return pd.DataFrame({
        "x": a, "y": b, "z": c,
        "grp": np.where(a > 50, "high", "low"),
    })


@pytest.fixture(scope="module")
def time_df() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    dates = pd.date_range("2020-01-01", periods=36, freq="MS")
    ids = [f"u{i}" for i in range(50)]
    rows = []
    for i, d in enumerate(dates):
        for uid in ids:
            rows.append({"id": uid, "month": d, "value": 10 + i * 0.4 + rng.normal(0, 1)})
    df = pd.DataFrame(rows)
    df["segment"] = np.where(df["id"].str.endswith(("0", "1", "2", "3")), "alpha", "beta")
    df.loc[df["segment"] == "alpha", "value"] += 5
    return df


@pytest.fixture(scope="module")
def binary_df() -> pd.DataFrame:
    rng = np.random.default_rng(2)
    n = 300
    x = rng.normal(0, 1, n)
    treatment = rng.integers(0, 2, n)
    outcome = 10 + 3 * treatment + 2 * x + rng.normal(0, 1, n)
    return pd.DataFrame({
        "metric": outcome,
        "treat": treatment,
        "covar": x,
        "cat": np.where(x > 0, "A", "B"),
    })


@pytest.fixture(scope="module")
def plain_df() -> pd.DataFrame:
    return pd.DataFrame({
        "name": ["alice", "bob", "carol"] * 30,
        "note": ["hello world", "nothing much", "all good"] * 30,
    })


# ---------------------------------------------------------------------------
# Gating config sanity
# ---------------------------------------------------------------------------

def test_gating_tiers():
    assert adaptive_task_tier("auto_segmentation") == "starter"
    assert adaptive_task_tier("forecast_metric") == "starter"
    assert adaptive_task_tier("group_significance_test") == "starter"
    assert adaptive_task_tier("cohort_retention") is None
    assert adaptive_task_tier("multivariate_anomaly_detection") is None
    assert meets_tier("free", "starter") is False
    assert meets_tier("starter", "starter") is True
    assert meets_tier("pro", "starter") is True


def test_user_skills_all_pro():
    for name, definition in USER_SKILLS.items():
        assert definition["tier"] == "pro", name
        assert definition["credit_cost"] > 0, name
        assert required_tier(name) == "pro"
        assert credit_cost(name) == definition["credit_cost"]
    assert credit_cost("what_if") < credit_cost("predictive_baseline")


def test_qa_credits():
    assert qa_credits_for_plan("free") == 0
    assert qa_credits_for_plan("starter") == 0
    assert qa_credits_for_plan("pro") == 300
    assert qa_credits_for_plan("scale") == 1000


# ---------------------------------------------------------------------------
# Adaptive tasks: applicable data -> real results
# ---------------------------------------------------------------------------

def test_auto_segmentation_applicable(numeric_df):
    res = adaptive.auto_segmentation(numeric_df, _classify(numeric_df), _task("auto_segmentation"))
    assert not res.get("skipped")
    assert res["k"] >= 2 and res["k"] <= 8
    assert res["clusters"] and res["row_positions"]
    assert sum(c["size"] for c in res["clusters"]) == res["rows_used"]


def test_auto_segmentation_non_applicable(plain_df):
    res = adaptive.auto_segmentation(plain_df, _classify(plain_df), _task("auto_segmentation"))
    assert res.get("skipped")
    assert "numeric" in res["reason"]


def test_forecast_applicable(time_df):
    res = adaptive.forecast_metric(time_df, _classify(time_df), _task("forecast_metric"))
    assert not res.get("skipped")
    keys = [k for k in res if k != "_capped"]
    assert keys
    entry = res[keys[0]]
    assert len(entry["mean"]) == adaptive.FORECAST_HORIZON
    assert entry["metric_column"] == "value"
    assert res.get("_capped", False) is not None


def test_forecast_non_applicable(plain_df):
    res = adaptive.forecast_metric(plain_df, _classify(plain_df), _task("forecast_metric"))
    assert res.get("skipped")
    assert "history" in res["reason"]


def test_cohort_retention_applicable(time_df):
    res = adaptive.cohort_retention(time_df, _classify(time_df), _task("cohort_retention"))
    assert not res.get("skipped")
    assert res["matrix"] and res["identifier_column"] == "id"
    assert res["most_notable"] is not None


def test_cohort_retention_non_applicable(numeric_df):
    res = adaptive.cohort_retention(numeric_df, _classify(numeric_df), _task("cohort_retention"))
    assert res.get("skipped")


def test_group_significance_applicable(binary_df):
    res = adaptive.group_significance_test(binary_df, _classify(binary_df), _task("group_significance_test"))
    assert not res.get("skipped")
    entry = list(res.values())[0]
    assert "significant" in entry
    assert "statistically significant" in entry["interpretation"].lower()


def test_group_significance_non_applicable(plain_df):
    res = adaptive.group_significance_test(plain_df, _classify(plain_df), _task("group_significance_test"))
    assert res.get("skipped")


def test_feature_engineering_applicable(numeric_df):
    res = adaptive.feature_engineering_suggestions(
        numeric_df, _classify(numeric_df), _task("feature_engineering_suggestions"), {}
    )
    assert not res.get("skipped")
    assert res.get("advisory") is True
    assert isinstance(res["log_transform_candidates"], list)


def test_multivariate_anomaly_applicable(numeric_df):
    res = adaptive.multivariate_anomaly_detection(numeric_df, _classify(numeric_df), _task("multivariate_anomaly_detection"))
    assert not res.get("skipped")
    assert res["n_flagged"] > 0
    assert res["chart_data"] and res["row_positions"]


def test_multivariate_anomaly_non_applicable(plain_df):
    res = adaptive.multivariate_anomaly_detection(plain_df, _classify(plain_df), _task("multivariate_anomaly_detection"))
    assert res.get("skipped")


# ---------------------------------------------------------------------------
# User-initiated skills
# ---------------------------------------------------------------------------

def test_predictive_baseline_applicable(numeric_df):
    res = initiated.predictive_baseline(
        numeric_df, _classify(numeric_df), {"target_column": "x"}
    )
    assert not res.get("skipped")
    assert res["task_type"] == "regression"
    assert "rmse" in res["metrics"]
    assert res["permutation_importance"]


def test_predictive_baseline_non_applicable(plain_df):
    res = initiated.predictive_baseline(
        plain_df, _classify(plain_df), {"target_column": "name"}
    )
    assert res.get("skipped")


def test_psm_applicable(binary_df):
    res = initiated.psm_analysis(
        binary_df, _classify(binary_df),
        {"treatment_column": "treat", "outcome_column": "metric"},
    )
    assert not res.get("skipped")
    assert "att_estimate" in res
    caveat = res["caveat"]
    assert caveat["mandatory"] is True and caveat["non_suppressible"] is True
    assert "association" in caveat["text"].lower()
    assert "caused" not in caveat["text"].lower()


def test_psm_non_applicable(plain_df):
    res = initiated.psm_analysis(
        plain_df, _classify(plain_df),
        {"treatment_column": "note", "outcome_column": "name"},
    )
    assert res.get("skipped")


def test_key_driver_applicable(numeric_df):
    res = initiated.key_driver_analysis(
        numeric_df, _classify(numeric_df), {"target_column": "x"}
    )
    assert not res.get("skipped")
    assert res["drivers"] and res["holdout_metrics"]


def test_key_driver_non_applicable(plain_df):
    res = initiated.key_driver_analysis(
        plain_df, _classify(plain_df), {"target_column": "name"}
    )
    assert res.get("skipped")


def test_what_if_requires_baseline(numeric_df):
    res = initiated.what_if_scenario(
        numeric_df, _classify(numeric_df),
        {"target_column": "x", "scenario": {"y": 10}}, None,
    )
    assert res.get("skipped")
    assert "baseline" in res["reason"].lower()


def test_what_if_applicable(numeric_df):
    baseline = {"params_json": {"target_column": "x"}, "result_json": {}}
    res = initiated.what_if_scenario(
        numeric_df, _classify(numeric_df),
        {"target_column": "x", "scenario": {"y": 10, "z": 5}}, baseline,
    )
    assert not res.get("skipped")
    assert res["result"]["prediction"] is not None


def test_segment_comparison_applicable(numeric_df):
    res = initiated.segment_comparison(
        numeric_df, _classify(numeric_df),
        {"numeric_column": "x", "segment_a": {"grp": "high"}, "segment_b": {"grp": "low"}},
    )
    assert not res.get("skipped")
    assert "p_value" in res and "effect_size_d" in res
    assert res["rows_a"] + res["rows_b"] <= len(numeric_df)


def test_segment_comparison_overlap_skips(numeric_df):
    res = initiated.segment_comparison(
        numeric_df, _classify(numeric_df),
        {"numeric_column": "x", "segment_a": {"grp": "high"}, "segment_b": {"grp": "high"}},
    )
    assert res.get("skipped")


def test_decompose_applicable(time_df):
    res = initiated.decompose_change(
        time_df, _classify(time_df),
        {"metric_column": "value", "date_column": "month",
         "segment_column": "segment"},
    )
    assert not res.get("skipped")
    total = res["within_effect"] + res["mix_effect"] + res["interaction"]
    assert abs(total - res["total_change"]) < 1e-6
    assert res["per_segment"]


def test_decompose_non_applicable(numeric_df):
    res = initiated.decompose_change(
        numeric_df, _classify(numeric_df),
        {"metric_column": "x", "date_column": "grp", "segment_column": "grp"},
    )
    assert res.get("skipped")


def test_join_quality_applicable():
    left = pd.DataFrame({"key": [1, 2, 3, 3, 4], "v": list("abcde")})
    right = pd.DataFrame({"key": [3, 3, 4, 5], "w": list("wxyz")})
    res = joinskill.join_quality(left, right, {"left_key": "key", "right_key": "key"})
    assert not res.get("skipped")
    assert res["left_file"]["matched_pct"] > 0
    assert res["right_file"]["summary"]["duplicate_key_rows"] == 2
    assert res["left_file"]["orphaned_rows"] == 2
    assert res["verdict"] and res["severity"]


def test_join_quality_missing_keys_skip(numeric_df):
    res = joinskill.join_quality(numeric_df, numeric_df, {"left_key": "nope", "right_key": "x"})
    assert res.get("skipped")


# ---------------------------------------------------------------------------
# Findings language discipline (#4/#11): no causal claims
# ---------------------------------------------------------------------------

def test_findings_no_causal_language(numeric_df, binary_df, time_df):
    from eda.findings import _multi_skill_findings
    from eda import executor

    # Build a summary with adaptive results in place, as the executor would.
    classification = _classify(numeric_df)
    summary = {"adaptive": {}, "numeric_stats": {}, "correlations": {},
               "column_classification": classification}
    summary["adaptive"]["auto_segmentation"] = adaptive.auto_segmentation(
        numeric_df, classification, _task("auto_segmentation"))
    gst = adaptive.group_significance_test(
        binary_df, _classify(binary_df), _task("group_significance_test"))
    summary["adaptive"]["group_significance_test"] = gst
    findings = _multi_skill_findings(summary)
    text = " ".join(
        f["message"] + " " + f["interpretation"] for f in findings
    ).lower()
    for forbidden in ("caused by", "drives", "because of treatment"):
        assert forbidden not in text
    assert "statistically significant" in text


def test_subset_rows_by_indices():
    from clean import subset_rows
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": list("vwxyz")})
    rows = subset_rows(df, "a", "1", limit=500, indices=[1, 3])
    assert rows == [{"a": 2, "b": "w"}, {"a": 4, "b": "y"}]
    out_of_range = subset_rows(df, "a", "1", limit=500, indices=[0, 99])
    assert len(out_of_range) == 1
