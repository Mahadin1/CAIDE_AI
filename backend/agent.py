"""The DataScope EDA agent — public orchestration facade.

This module is the single entry point the HTTP layer and the worker use. It
ties together the deterministic `eda` package modules and the two LLM steps:

    1. load + profile the file (loader, sampling, fingerprint)
    2. plan  (planner: LLM fingerprint -> tasks, or deterministic fallback)
    3. compute (executor: backbone + plan tasks, all deterministic)
    4. findings (findings: rule-based, evidence + interpretation + action)
    5. narrate (narrator: LLM, or deterministic fallback)

Division of labour (see docs/ARCHITECTURE.md): pandas/scipy/statsmodels
compute, rules decide, the LLM only plans and narrates. No number in any
report is ever produced by the LLM.

Backwards compatibility: `run_eda(df)`, `classify_columns(df)` and
`select_findings(summary)` remain available with their original signatures.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from config import settings

from eda.classification import classify_columns
from eda.fingerprint import build_fingerprint
from eda.loader import LoadedData, cleanup_loaded, load_dataframe
from eda.sampling import analysis_mode, sample_info, seed_for_path
from eda.planner import build_plan
from eda.executor import run_pipeline_on_frame
from eda.findings import select_findings
from eda.narrator import narrate
from eda.stats_core import build_chart_specs, run_backbone

logger = logging.getLogger("datascope.agent")


@dataclass
class PreparedFile:
    loaded: LoadedData
    classification: dict[str, dict[str, Any]]
    fingerprint: dict[str, Any]
    mode: str
    sample_info: dict[str, Any]
    plan_tasks: list[dict[str, Any]] = field(default_factory=list)
    plan_source: str = "fallback"
    plan_cache_key: str = ""


# ---------------------------------------------------------------------------
# Legacy-compatible pieces (kept for existing callers)
# ---------------------------------------------------------------------------

def run_eda(df: Any) -> dict[str, Any]:
    """Original signature: full deterministic summary for a DataFrame."""
    classification = classify_columns(df)
    summary = run_backbone(df, classification)
    summary["chart_specs"] = build_chart_specs(summary)
    return summary


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def prepare(
    data: bytes,
    filename: str,
    storage_path: str,
) -> PreparedFile:
    """Load + profile the file. Synchronous (CPU-bound)."""
    loaded = load_dataframe(
        data,
        filename,
        max_rows_full=settings.max_rows_full,
        sample_target=settings.sample_target_rows,
        seed=seed_for_path(storage_path),
        max_cols=settings.max_columns,
    )
    classification = classify_columns(loaded.df)
    fingerprint = build_fingerprint(loaded.df, loaded, classification)
    mode = analysis_mode(int(len(loaded.df)), loaded.total_rows,
                         settings.max_rows_full)
    s_info = sample_info(
        mode,
        loaded.total_rows,
        int(len(loaded.df)),
        storage_path,
        truncated_cols=loaded.truncated_cols,
    )
    return PreparedFile(
        loaded=loaded,
        classification=classification,
        fingerprint=fingerprint,
        mode=mode,
        sample_info=s_info,
    )


async def plan_file(
    prepared: PreparedFile,
    overrides: dict[str, Any] | None = None,
) -> PreparedFile:
    """Generate (or fetch cached) the analysis plan for a prepared file."""
    plan = await build_plan(prepared.fingerprint, overrides)
    prepared.plan_tasks = plan["tasks"]
    prepared.plan_source = plan["source"]
    prepared.plan_cache_key = plan["cache_key"]
    return prepared


def column_type_map(prepared: PreparedFile) -> dict[str, str]:
    """Editable column-kind map for the plan-preview UI."""
    return {
        col: info["kind"]
        for col, info in prepared.classification.items()
    }


def build_prior_context(
    fingerprint: dict[str, Any], prior_report: dict[str, Any] | None
) -> dict[str, Any]:
    """Prior-report context embedded in the fingerprint for the planner.

    Only the *existence* of a comparable prior report is exposed (plus the
    shared numeric column names) so the LLM can decide to propose a
    distribution-drift check. The full reference histograms are never sent to
    the LLM — the executor reads them from the passed prior payload instead.
    """
    if not prior_report:
        return {"exists": False, "comparable": False}
    hist = prior_report.get("histograms") or {}
    prior_numeric = [
        c for c, h in hist.items()
        if isinstance(h, dict) and h.get("bin_edges") and h.get("counts")
    ]
    if not prior_numeric:
        return {"exists": True, "comparable": False, "prior_rows": None,
                "prior_numeric": []}
    current_numeric = {
        c["name"] for c in fingerprint.get("columns", [])
        if c.get("kind") == "numeric"
    }
    shared = [c for c in prior_numeric if c in current_numeric]
    comparable = len(shared) / max(1, len(prior_numeric)) >= 0.5
    return {
        "exists": True,
        "comparable": comparable,
        "prior_rows": (prior_report.get("shape") or {}).get("rows"),
        "shared_numeric": shared[:12],
    }


def attach_prior_context(
    prepared: PreparedFile, prior_report: dict[str, Any] | None
) -> PreparedFile:
    """Mutate the prepared fingerprint with prior-report context (for plan
    consistency between the plan preview and the worker, both must inject the
    exact same context before planning)."""
    prepared.fingerprint["prior_report"] = build_prior_context(
        prepared.fingerprint, prior_report
    )
    return prepared


def build_overview(prepared: PreparedFile, summary: dict[str, Any]) -> dict[str, Any]:
    """The overview block sent to the narrator alongside plan + findings."""
    return {
        "shape": summary["shape"],
        "format": prepared.loaded.fmt,
        "encoding": prepared.loaded.encoding,
        "mode": prepared.mode,
        "sample_info": prepared.sample_info,
    }


def execute(
    prepared: PreparedFile,
    storage_path: str,
    overrides: dict[str, Any] | None = None,
    prior_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic half of the pipeline (blocking — call via to_thread).

    Returns summary + findings + provenance. The narrative is produced
    separately by :func:`narrate_result` so the worker can keep the event
    loop free during heavy pandas work and await the LLM separately.
    """
    summary = run_pipeline_on_frame(
        prepared.loaded.df,
        loaded=prepared.loaded,
        plan_tasks=prepared.plan_tasks,
        overrides=overrides,
        storage_path=storage_path,
        prior_report=prior_report,
    )
    findings = select_findings(summary)
    summary["findings"] = findings
    return {
        "summary": summary,
        "findings": findings,
        "plan_tasks": prepared.plan_tasks,
        "plan_source": prepared.plan_source,
        "plan_cache_key": prepared.plan_cache_key,
        "mode": prepared.mode,
        "sample_info": prepared.sample_info,
        "format": prepared.loaded.fmt,
        "encoding": prepared.loaded.encoding,
    }


async def narrate_result(prepared: PreparedFile, result: dict[str, Any]) -> str:
    """Async LLM narration over an :func:`execute` result (with fallback)."""
    overview = build_overview(prepared, result["summary"])
    return await narrate(result["plan_tasks"], result["findings"], overview)


async def execute_and_narrate(
    prepared: PreparedFile,
    storage_path: str,
    overrides: dict[str, Any] | None = None,
    prior_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for small pipelines: execute + narrate."""
    result = execute(prepared, storage_path, overrides, prior_report)
    result["narrative"] = await narrate_result(prepared, result)
    return result


async def prepare_plan_and_execute(
    data: bytes,
    filename: str,
    storage_path: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience: prepare -> plan -> execute -> narrate in one call."""
    prepared = prepare(data, filename, storage_path)
    await plan_file(prepared, overrides)
    return await execute_and_narrate(prepared, storage_path, overrides)


def load_and_classify(
    data: bytes, filename: str, storage_path: str
) -> dict[str, Any]:
    """Load a file and classify its columns. Returns a dict with the frame,
    classification and the LoadedData (for cleanup)."""
    loaded = load_dataframe(
        data,
        filename,
        max_rows_full=settings.max_rows_full,
        sample_target=settings.sample_target_rows,
        seed=seed_for_path(storage_path),
        max_cols=settings.max_columns,
    )
    return {
        "df": loaded.df,
        "classification": classify_columns(loaded.df),
        "loaded": loaded,
    }


def dispose(prepared: PreparedFile | LoadedData) -> None:
    """Release temp-file resources for a PreparedFile or a LoadedData."""
    loaded = prepared if isinstance(prepared, LoadedData) else prepared.loaded
    cleanup_loaded(loaded)
