"""Phase 0 planning — a small LLM call turns the data fingerprint into an
adaptive analysis plan.

The planner is deliberately the ONLY place the LLM influences *what* gets
computed. It receives the compact fingerprint (eda/fingerprint.py), returns a
JSON list of tasks from a closed set the executor understands, and the
executor then runs everything deterministically.

Robustness contract:

  * if the LLM is unavailable, misconfigured, or returns unparseable output,
    `build_plan` returns the deterministic `fallback_plan` (source="fallback");
  * the returned plan is always a list of validated tasks — unknown task
    types are dropped, never crashed on;
  * the same fingerprint + overrides produce the same plan (cached in
    memory and persisted on the upload/report rows).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("datascope.planner")

# The closed set of tasks the executor can run. Keeping this small guarantees
# that even a very creative LLM cannot ask for something we can't do.
KNOWN_TASK_TYPES = {
    "missing_pattern", "outlier_multimethod", "normality", "distribution_fit",
    "anova_kruskal", "spearman_sig", "cramer_v", "vif", "trend_mannkendall",
    "time_features", "seasonality", "duplicate_ids", "date_as_text",
    "mixed_type_cleanup", "text_top_words", "group_comparison",
    "cardinality_sanity", "custom_question",
}

PLANNER_SYSTEM_PROMPT = (
    "You are a senior data analyst designing an exploratory data analysis "
    "plan for a dataset. You receive a compact 'fingerprint' describing "
    "columns: their detected kinds, cardinality, missingness and example "
    "values.\n\n"
    "Your job is to return a JSON object with a 'tasks' array. Each task is:\n"
    '{"type": <one of the allowed types>, "description": <what to check>, '
    '"rationale": <why it matters>, "target_columns": [column names], '
    '"enabled": true}\n\n'
    "Allowed task types (use ONLY these):\n"
    "missing_pattern, outlier_multimethod, normality, distribution_fit, "
    "anova_kruskal, spearman_sig, cramer_v, vif, trend_mannkendall, "
    "time_features, seasonality, duplicate_ids, date_as_text, "
    "mixed_type_cleanup, text_top_words, group_comparison, "
    "cardinality_sanity, custom_question\n\n"
    "Rules:\n"
    "- Choose 5 to 12 tasks that best fit THIS dataset's story. Do not pick "
    "tasks the data cannot support (e.g. time_features with no date-like "
    "column).\n"
    "- Prefer deep, non-boring checks: correlations with caveats, "
    "group differences, missingness patterns, trend/seasonality, "
    "distribution problems, duplicate/identifier analysis.\n"
    "- A 'custom_question' task may encode a hypothesis worth testing "
    "about specific columns; keep description concrete.\n"
    "- Keep every description and rationale under 30 words. Concise plans "
    "fit the output limit.\n"
    "- Return ONLY valid JSON. No markdown, no commentary."
)


def _fallback_plan(fingerprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic plan built from cheap data conditions.

    This is what runs when the LLM is unavailable, and it is also the
    guaranteed-coverage baseline the executor always applies on top of the
    backbone statistics.
    """
    cols = fingerprint.get("columns", [])
    by_kind: dict[str, list[str]] = {}
    for c in cols:
        by_kind.setdefault(c["kind"], []).append(c["name"])
    tasks: list[dict[str, Any]] = []

    def add(ttype: str, description: str, rationale: str, targets: list[str]) -> None:
        tasks.append({
            "id": f"fb-{len(tasks)}",
            "type": ttype,
            "description": description,
            "rationale": rationale,
            "target_columns": targets[:8],
            "enabled": True,
        })

    numeric = by_kind.get("numeric", [])
    categorical = by_kind.get("categorical", [])
    date_like = by_kind.get("date_like", [])
    free_text = by_kind.get("free_text", [])
    identifiers = by_kind.get("identifier", [])
    mixed = by_kind.get("mixed", [])

    if numeric:
        add("normality", "Check which numeric columns are (not) normally distributed",
            "Normality decides which summaries and tests are trustworthy.",
            numeric[:6])
        add("outlier_multimethod", "Detect outliers with IQR and robust Z-score",
            "Outliers can be real signal or data-entry errors; two methods disambiguate.",
            numeric[:6])
        if len(numeric) >= 2:
            add("spearman_sig", "Correlate numeric columns with Pearson AND Spearman, with significance",
                "Linear r can miss monotonic relationships; comparing both is more honest.",
                numeric[:8])
            add("vif", "Check multicollinearity between numeric columns",
                "High VIF means regression coefficients would be unreliable.",
                numeric[:10])
        if numeric and categorical:
            add("anova_kruskal", "Compare group means of numeric columns across categories",
                "Reveals which category splits drive the differences.",
                numeric[:4] + categorical[:4])
    if len(categorical) >= 2:
        add("cramer_v", "Measure categorical association strength between category columns",
            "Finds relationships between categories that bar charts hide.",
            categorical[:8])
    if numeric and categorical:
        add("group_comparison", "Break numeric columns down by category groups",
            "Surface 'which group differs from which' with post-hoc checks.",
            numeric[:4] + categorical[:4])
    if date_like:
        add("time_features", "Extract year/month/weekday/hour patterns from date columns",
            "Temporal features reveal daily, weekly or yearly cycles.",
            date_like[:4])
        add("trend_mannkendall", "Test date series for monotonic trends (Mann-Kendall)",
            "A formal trend test is more robust than eyeballing a line chart.",
            date_like[:4])
        add("seasonality", "Check for month-of-year seasonality in row counts",
            "Seasonality tells you when activity concentrates.",
            date_like[:4])
    if free_text:
        add("text_top_words", "Summarize free-text columns with word/ngram frequencies",
            "Free text is analyzed as text, not as thousands of categories.",
            free_text[:4])
    if identifiers:
        add("duplicate_ids", "Check identifiers for uniqueness and duplicate keys",
            "Identifiers that repeat break joins and uniqueness assumptions.",
            identifiers[:4])
    if mixed:
        add("mixed_type_cleanup", "Identify columns mixing numbers and text",
            "Mixed types usually signal data-entry errors worth fixing.",
            mixed[:6])
    missing_cols = [c["name"] for c in cols if (c.get("missing_pct") or 0) > 0]
    if len(missing_cols) >= 2:
        add("missing_pattern", "Analyze missing-value patterns and test MCAR",
            "Knowing WHY values are missing changes what you may safely assume.",
            missing_cols[:8])
    if not tasks:
        add("cardinality_sanity", "Review column cardinality for over-/under-splitting",
            "Baseline sanity check for datasets with little signal.",
            [c["name"] for c in cols][:6])
    return tasks


def _parse_tasks(raw: str) -> list[dict[str, Any]]:
    """Extract and validate a tasks list from LLM output. Never raises."""
    text = raw.strip()
    # Strip markdown code fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("[")
    end = text.rfind("]")
    try:
        if start == -1 or end == -1 or end <= start:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end <= start:
                return []
            payload = text[start:end + 1]
            obj = json.loads(payload)
            tasks = obj.get("tasks", []) if isinstance(obj, dict) else []
        else:
            tasks = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("planner output was not valid JSON; using fallback")
        return []

    validated: list[dict[str, Any]] = []
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        ttype = task.get("type")
        if ttype not in KNOWN_TASK_TYPES:
            continue
        if not task.get("enabled", True):
            continue
        validated.append({
            "id": f"plan-{i}",
            "type": ttype,
            "description": str(task.get("description") or "").strip()[:400],
            "rationale": str(task.get("rationale") or "").strip()[:400],
            "target_columns": [str(c) for c in (task.get("target_columns") or [])][:8],
            "enabled": True,
        })
    return validated


def cache_key(fingerprint: dict[str, Any]) -> str:
    """Cache key from the fingerprint only. Column-type overrides affect
    *execution*, not *planning*, so a previewed plan is always the same plan
    that gets executed (custom questions are appended separately)."""
    payload = json.dumps({"f": fingerprint}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


# In-memory plan cache keyed by (fingerprint, overrides) hash. Persisting the
# plan on the upload/report rows makes this a soft cache only.
_PLAN_CACHE: dict[str, list[dict[str, Any]]] = {}


async def _call_planner(fingerprint: dict[str, Any]) -> str | None:
    if not settings.openrouter_api_key:
        return None
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user",
             "content": "Dataset fingerprint (JSON):\n" + json.dumps(fingerprint, default=str)},
        ],
        "temperature": 0.2,
        "max_tokens": 2400,
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
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
            return (data["choices"][0]["message"]["content"] or "").strip() or None
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        logger.warning("planner LLM call failed; using fallback plan")
        return None


async def build_plan(
    fingerprint: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    *,
    force_llm: bool = True,
) -> dict[str, Any]:
    """Return {'tasks': [...], 'source': 'llm'|'fallback', 'cache_key': str}.

    The returned plan is always valid for the executor.
    """
    overrides = overrides or {}
    ckey = cache_key(fingerprint)

    # Custom questions from the user are always appended to any plan.
    custom_questions = overrides.get("custom_questions") or []
    custom_tasks = [
        {
            "id": f"custom-{i}",
            "type": "custom_question",
            "description": str(q).strip()[:400],
            "rationale": "Requested by the user during plan review.",
            "target_columns": [],
            "enabled": True,
        }
        for i, q in enumerate(custom_questions)
        if str(q).strip()
    ]

    cached = _PLAN_CACHE.get(ckey)
    if cached is not None:
        return {"tasks": cached + custom_tasks, "source": "cache",
                "cache_key": ckey}

    if force_llm:
        raw = await _call_planner(fingerprint)
        if raw:
            tasks = _parse_tasks(raw)
            if tasks:
                _PLAN_CACHE[ckey] = tasks
                return {"tasks": tasks + custom_tasks, "source": "llm",
                        "cache_key": ckey}

    tasks = _fallback_plan(fingerprint)
    _PLAN_CACHE[ckey] = tasks
    return {"tasks": tasks + custom_tasks, "source": "fallback",
            "cache_key": ckey}
