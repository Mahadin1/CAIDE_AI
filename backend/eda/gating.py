"""Tier and credit gating for every skill on the platform.

This module is the single source of truth for two kinds of gates:

  * Adaptive tasks (fire automatically inside a report plan). Some of them
    are heavy real compute and are gated to paid tiers — they are never
    silently added to a free user's report. Gating is enforced server-side in
    the executor (eda/executor.py); the plan preview only *labels* them.
  * User-initiated modes (#8-#15). All require Pro+ and a distinct, higher
    credit cost per use, charged server-side at queue time. `what_if` is
    cheaper than `predictive_baseline` because it is inference against an
    existing fit, not a fresh model.

Language note: nothing here touches the LLM. Tiers/costs are pure
configuration so the API layer can enforce them without trusting the UI.
"""
from __future__ import annotations

from typing import Any

# Plan ordering used for tier comparisons. Higher = more privileged.
PLAN_RANK: dict[str, int] = {
    "free": 0,
    "starter": 1,
    "pro": 2,
    "scale": 3,
}

# Adaptive tasks that are too expensive to fire on every free report.
# "starter" means the task only executes when the user's plan is at least
# Starter. Everything else in KNOWN_TASK_TYPES is "any".
ADAPTIVE_TASK_TIER: dict[str, str] = {
    "auto_segmentation": "starter",
    "forecast_metric": "starter",
    "group_significance_test": "starter",
}

# Every user-initiated mode requires at least Pro.
USER_SKILLS: dict[str, dict[str, Any]] = {
    "predictive_baseline": {
        "label": "Explicit-Target Predictive Baseline",
        "tier": "pro",
        "credit_cost": 10,
        "description": (
            "Fit a baseline model for a target you choose and report honest "
            "holdout metrics plus permutation importance."
        ),
    },
    "psm": {
        "label": "Opt-In Treatment Effect Estimator",
        "tier": "pro",
        "credit_cost": 15,
        "description": (
            "Propensity-score matched comparison between a treatment group "
            "and a control group. Association only, with a mandatory caveat."
        ),
    },
    "key_driver": {
        "label": "Key Driver / Relative Importance",
        "tier": "pro",
        "credit_cost": 8,
        "description": (
            "Rank the columns most strongly associated with an outcome you "
            "pick, validated on a holdout set."
        ),
    },
    "what_if": {
        "label": "What-If Scenario Simulator",
        "tier": "pro",
        "credit_cost": 3,
        "description": (
            "Predict an outcome for hypothetical feature values against an "
            "existing baseline model. Requires a completed predictive "
            "baseline for this report."
        ),
    },
    "segment_comparison": {
        "label": "Custom Segment Comparison",
        "tier": "pro",
        "credit_cost": 5,
        "description": (
            "Compare two segments you define explicitly with a formal "
            "significance test and effect size."
        ),
    },
    "decompose": {
        "label": "Metric Change Root-Cause Decomposition",
        "tier": "pro",
        "credit_cost": 8,
        "description": (
            "Split a metric's change between two periods into mix shift "
            "(compositional) vs within-segment contribution."
        ),
    },
    "join_quality": {
        "label": "Two-Dataset Join Quality Assessment",
        "tier": "pro",
        "credit_cost": 5,
        "description": (
            "Attach a second file and check match rate, duplicate keys and "
            "orphaned rows before you merge."
        ),
    },
}

# Interactive Q&A metering — separate, much cheaper than report credits.
QA_CREDITS_BY_PLAN: dict[str, int] = {
    "free": 0,
    "starter": 0,
    "pro": 300,
    "scale": 1000,
}


def rank(plan: str | None) -> int:
    return PLAN_RANK.get(plan or "free", 0)


def meets_tier(plan: str | None, required: str) -> bool:
    """True when the user's plan is at least `required` (free/starter/pro)."""
    return rank(plan) >= rank(required)


def adaptive_task_tier(task_type: str) -> str | None:
    """The minimum tier for an adaptive task, or None when broadly available."""
    return ADAPTIVE_TASK_TIER.get(task_type)


def skill_definition(skill: str) -> dict[str, Any] | None:
    return USER_SKILLS.get(skill)


def required_tier(skill: str) -> str | None:
    """Minimum plan for a user-initiated skill (None if unknown)."""
    definition = USER_SKILLS.get(skill)
    return definition["tier"] if definition else None


def credit_cost(skill: str) -> int:
    definition = USER_SKILLS.get(skill)
    return definition["credit_cost"] if definition else 0


def qa_credits_for_plan(plan: str | None) -> int:
    return QA_CREDITS_BY_PLAN.get(plan or "free", 0)
