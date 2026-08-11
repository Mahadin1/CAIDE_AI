"""Narration — the single LLM call that turns computed findings into prose
plus a data dictionary.

Scope contract (see docs/ARCHITECTURE.md §1 and the platform spec):

  * the narrator receives ONLY the analysis plan, the computed findings, and a
    compact overview (shape, format, mode, sample info, and a per-column
    summary of kind/cardinality/missingness/example values);
  * it never sees raw row-level data and never computes statistics;
  * a SINGLE LLM call returns BOTH the narrative prose AND a
    ``column_glossary`` ({col: description}). This is the only data-dictionary
    touchpoint — no separate LLM call is made for the glossary (spec #7);
  * if the LLM call fails for any reason, a deterministic long-form narrative
    AND a deterministic glossary are assembled locally, so a completed
    analysis always produces a readable report and a complete dictionary.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("datascope.narrator")

# Kind -> plain-language phrase used by the deterministic glossary.
_KIND_PHRASE: dict[str, str] = {
    "numeric": "a numeric measurement",
    "categorical": "a categorical label",
    "date_like": "a date or timestamp",
    "mixed": "a column mixing numbers and text",
    "constant": "a single constant value",
    "identifier": "an identifier or unique key",
    "free_text": "free-form text",
    "boolean": "a true/false flag",
    "empty": "an empty column",
}

NARRATE_SYSTEM_PROMPT = (
    "You are a senior data analyst explaining an exploratory analysis to a "
    "non-technical stakeholder. You will receive a JSON bundle containing:\n"
    "  * 'plan'    — the analysis tasks that were chosen and why\n"
    "  * 'findings'— fully computed, deterministic findings (method, "
    "evidence, interpretation, action)\n"
    "  * 'overview'— dataset shape, format, sampling mode, and a per-column "
    "summary (kind, cardinality, missingness, example values)\n\n"
    "Hard rules:\n"
    "- Never invent, guess, or extrapolate a number, column name, or "
    "relationship that is not in the findings. Exact figures are shown in "
    "the charts, so a rounded natural-language reference is fine.\n"
    "- Explain WHY each analysis was chosen or skipped (use the plan's "
    "rationale), what the result means, and what the reader should do about "
    "it (use each finding's interpretation and action).\n"
    "- If the data was sampled, say so in the opening and note that "
    "proportions carry the stated margin of error.\n"
    "- Walk through the data like a story: start with the overall shape and "
    "quality, then relationships, then the details that matter most.\n"
    "- Plain prose only: no headers, no bullets, no markdown, no code "
    "blocks. Several well-structured paragraphs.\n"
    f"- Keep the narrative under {settings.narrative_max_words} words.\n"
    "- Build a 'column_glossary': one concise plain-English description "
    "per column (a data dictionary), using ONLY the column summary in the "
    "overview — its kind, cardinality, missingness and example values. Never "
    "refer to values that are not among the shown examples.\n\n"
    "Respond with a single JSON object, no markdown, no commentary:\n"
    '{"narrative": "<the full narrative as one string>", '
    '"column_glossary": {"<column name>": "<short description>", ...}}'
)


def _fallback_glossary(
    overview: dict[str, Any],
) -> dict[str, str]:
    """Deterministic data dictionary built from the overview's column info.

    Uses kind + cardinality + missingness + samples. Never references any
    value that isn't in the overview, so it is always accurate.
    """
    glossary: dict[str, str] = {}
    for col in overview.get("columns", []):
        name = col.get("name", "")
        kind = col.get("kind", "categorical")
        cardinality = col.get("cardinality")
        missing = col.get("missing_pct")
        parts = [_KIND_PHRASE.get(kind, "a column")]
        if cardinality is not None:
            parts.append(f"{cardinality:,} distinct values")
        if missing is not None and missing > 0:
            parts.append(f"{missing:.0f}% missing")
        samples = col.get("samples") or []
        if samples:
            shown = ", ".join(str(s) for s in samples[:2])
            parts.append(f"examples: {shown}")
        glossary[name] = ", ".join(parts) + "."
    return glossary


def _fallback_narrative(
    plan: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    overview: dict[str, Any],
) -> str:
    """Deterministic narrative built from findings — used when the LLM is
    unavailable, so a report is always produced and always accurate."""
    paras: list[str] = []

    shape = overview.get("shape", {})
    mode = overview.get("mode", "full")
    intro = (
        f"This report covers {shape.get('rows', 0):,} rows across "
        f"{shape.get('columns', 0)} columns."
    )
    if mode != "full":
        sample = overview.get("sample_info", {})
        intro += (
            f" Because the file is large, the detailed analyses used a "
            f"deterministic random sample of {sample.get('sample_rows', 0):,} "
            f"rows (of {sample.get('total_rows', 0):,} total). Exact global "
            "aggregates were computed over every row via streaming "
            "statistics; proportions below carry a worst-case margin of error "
            f"of ±{sample.get('margin_of_error', 0) * 100:.1f} percentage "
            "points at 95% confidence."
        )
    paras.append(intro)

    high = [f for f in findings if f.get("severity") == "high"]
    medium = [f for f in findings if f.get("severity") == "medium"]
    low = [f for f in findings if f.get("severity") == "low"]

    if high:
        paras.append(
            "The most important things to know first: "
            + " ".join(f["message"] for f in high[:4])
        )

    for f in findings:
        sentence = f.get("interpretation", f.get("message", ""))
        action = f.get("action")
        paras.append(sentence + (f" Suggested next step: {action}." if action else ""))

    if medium:
        paras.append(
            "Other things worth keeping in mind: "
            + " ".join(f["message"] for f in medium[:5])
        )

    if plan:
        planned = "; ".join(t["description"] for t in plan[:6])
        paras.append(
            "The analysis focused on: " + planned + ". The accompanying "
            "charts show the exact figures behind each statement."
        )

    paras.append(
        "Recommendation: treat the highest-severity items first — they are "
        "the findings most likely to change a decision. The dataset looks "
        "fit for further analysis once the flagged data-quality issues are "
        "reviewed."
    )
    return "\n\n".join(paras)


def _parse_bundle(content: str) -> dict[str, Any] | None:
    """Parse the {narrative, column_glossary} JSON bundle. Never raises."""
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            obj = json.loads(text[start:end + 1])
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    if not isinstance(obj, dict):
        return None
    narrative = obj.get("narrative")
    glossary = obj.get("column_glossary")
    if not isinstance(narrative, str) or not narrative.strip():
        return None
    if not isinstance(glossary, dict):
        glossary = {}
    return {
        "narrative": narrative.strip(),
        "column_glossary": {
            str(k): str(v)[:400]
            for k, v in glossary.items()
            if str(v).strip()
        },
    }


async def narrate(
    plan: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    overview: dict[str, Any],
) -> dict[str, Any]:
    """Produce the narration bundle {narrative, column_glossary}.

    One LLM call only (spec #7: the glossary folds into the existing narrate
    call). On any failure the deterministic equivalents are used, so the
    result is always complete.
    """
    glossary = _fallback_glossary(overview)
    fallback = {
        "narrative": _fallback_narrative(plan, findings, overview),
        "column_glossary": glossary,
    }

    if not findings or all(f.get("type") == "clean" for f in findings):
        return fallback
    if not settings.openrouter_api_key:
        return fallback

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": NARRATE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"plan": plan, "findings": findings, "overview": overview},
                    default=str,
                ),
            },
        ],
        "temperature": 0.3,
        "max_tokens": 3200,
    }

    try:
        async with httpx.AsyncClient(timeout=90) as client:
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
                bundle = _parse_bundle(content)
                if bundle:
                    bundle["column_glossary"] = {
                        **glossary,
                        **bundle.get("column_glossary", {}),
                    }
                    return bundle
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        logger.warning("narrator LLM call failed; using deterministic prose")

    return fallback
