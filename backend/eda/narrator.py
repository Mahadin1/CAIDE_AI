"""Narration — the single LLM call that turns computed findings into prose.

The narrator receives ONLY:
  * the analysis plan (task descriptions/rationales),
  * the computed findings (method, evidence, interpretation, action),
  * a short dataset overview (shape, mode, sample info).

It never sees raw data or any number outside the findings. All numbers,
columns and relationships it mentions must already exist in the findings
JSON. If the LLM call fails for any reason, a deterministic long-form
narrative is assembled from the findings' interpretation/action fields, so a
completed analysis always produces a readable report.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("datascope.narrator")

NARRATE_SYSTEM_PROMPT = (
    "You are a senior data analyst explaining an exploratory analysis to a "
    "non-technical stakeholder. You will receive a JSON bundle containing:\n"
    "  * 'plan'    — the analysis tasks that were chosen and why\n"
    "  * 'findings'— fully computed, deterministic findings (method, "
    "evidence, interpretation, action)\n"
    "  * 'overview'— dataset shape, format, and sampling mode\n\n"
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
    f"- Keep the response under {settings.narrative_max_words} words."
)


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


async def narrate(
    plan: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    overview: dict[str, Any],
) -> str:
    """Produce the final narrative (LLM with deterministic fallback)."""
    if not findings or all(f.get("type") == "clean" for f in findings):
        return _fallback_narrative(plan, findings, overview)

    if not settings.openrouter_api_key:
        return _fallback_narrative(plan, findings, overview)

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
        "max_tokens": 2600,
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
                return content
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        logger.warning("narrator LLM call failed; using deterministic prose")

    return _fallback_narrative(plan, findings, overview)
