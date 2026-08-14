"""Report Q&A (#8) — ask questions about an existing report.

Scope contract (see docs/ARCHITECTURE.md §1):

  * this is an EXPLICITLY FLAGGED LLM touchpoint — the platform's third and
    final LLM use (planner, narrator, and now Q&A);
  * the model answers ONLY from the stored report blob: ``summary_json``
    (computed statistics, findings, executed/skipped tasks), the narrative,
    and the column_glossary produced at narration time. It never sees raw
    row-level data and never computes statistics — a follow-up turn that
    needs a real number is answered with the closest stored figure plus a
    note that the number comes from the report;
  * every turn is persisted to ``qa_turns``; metering is a separate, much
    cheaper credit meter (qa_credits) gated server-side;
  * the system prompt hard-blocks questions that would require raw data
    access, and never lets the model invent statistics.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("datascope.qa")

QA_SYSTEM_PROMPT = (
    "You are a data analyst answering a stakeholder's question about ONE "
    "existing analysis report. You receive the report's stored narrative, its "
    "column glossary (data dictionary), and a compact digest of its computed "
    "statistics and findings.\n\n"
    "Hard rules:\n"
    "- Answer only from what is in this report. Never invent numbers, "
    "columns, or relationships.\n"
    "- You do NOT have access to the underlying data rows. If a question "
    "requires a number the report did not store, say you do not have that "
    "figure in this report rather than guessing.\n"
    "- Be concise and plain-spoken. Quote exact figures only when they appear "
    "verbatim in the provided digest or narrative.\n"
    "- If the report notes the data was sampled, reflect that in answers "
    "that involve proportions.\n"
    "- Never claim a result is causal. Use 'associates with' or 'statistically "
    "significant difference' at most.\n\n"
    "Respond with a plain answer, no markdown headers."
)


def _digest(report: dict[str, Any]) -> str:
    """Compact, JSON-serializable digest of a report for the LLM.

    Pulls only the stored, already-computed fields — never raw data. Long
    arrays (histograms, per-value breakdowns) are truncated hard.
    """
    summary = report.get("summary_json") or {}
    digest: dict[str, Any] = {
        "shape": summary.get("shape"),
        "analysis_mode": summary.get("analysis_mode"),
        "sample_info": report.get("sample_info_json"),
        "findings": [
            {
                "severity": f.get("severity"),
                "message": f.get("message"),
                "interpretation": f.get("interpretation"),
            }
            for f in (summary.get("findings") or [])
        ],
        "executed_tasks": summary.get("executed_tasks"),
        "skipped_tasks": [
            {
                "type": t.get("type"),
                "reason": t.get("reason"),
            }
            for t in (summary.get("skipped_tasks") or [])
        ],
        "numeric_stats": {
            col: {
                k: v for k, v in stats.items()
                if k in ("mean", "median", "std", "skew", "min", "max", "count")
            }
            for col, stats in (summary.get("numeric_stats") or {}).items()
        },
        "correlations": {
            col: {k: round(v, 4) if isinstance(v, (int, float)) else v
                  for k, v in targets.items() if k in summary.get("numeric_stats", {})}
            for col, targets in (summary.get("correlations") or {}).items()
        },
        "missing_patterns": {
            "missing": summary.get("missing_patterns", {}).get("missing"),
            "co_missing": [
                {"pair": k, **v}
                for k, v in list((summary.get("missing_patterns", {})
                                  .get("co_missing") or {}).items())[:4]
            ],
        },
        "column_glossary": report.get("column_glossary"),
        "narrative": (report.get("narrative") or "")[:4000],
    }
    return json.dumps(digest, default=str, ensure_ascii=False)[:12000]


async def answer_question(
    report: dict[str, Any],
    question: str,
    previous_turns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Answer `question` about `report`. Never raises — returns an answer dict
    (with ``"answered": True/False``) so the endpoint can persist it."""
    q = (question or "").strip()
    if not q:
        return {"answered": False, "answer": "Ask a question about your report."}

    if not settings.openrouter_api_key:
        return {
            "answered": False,
            "answer": (
                "Live Q&A is not available right now (the LLM service is not "
                "configured). The report's narrative and findings above still "
                "answer most questions."
            ),
        }

    messages = [
        {"role": "system", "content": QA_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Report digest:\n" + _digest(report)
            ),
        },
    ]
    for turn in (previous_turns or [])[-4:]:
        messages.append({"role": "user", "content": turn.get("question", "")})
        messages.append({"role": "assistant", "content": turn.get("answer", "")})
    messages.append({"role": "user", "content": "Question: " + q})

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://datascope.app",
                    "X-Title": "DataScope",
                },
                json={
                    "model": settings.openrouter_model,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 600,
                },
            )
            resp.raise_for_status()
            answer = (
                resp.json()["choices"][0]["message"]["content"] or ""
            ).strip()
            if not answer:
                raise ValueError("empty answer")
            return {"answered": True, "answer": answer}
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        logger.warning("qa LLM call failed; returning scoped fallback")
        return {
            "answered": False,
            "answer": (
                "I could not reach the answering service. In the meantime, "
                "the report narrative and the findings list in the report "
                "likely cover your question."
            ),
        }
