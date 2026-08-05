"""Automatic full-vs-sample analysis mode selection.

The loader already decides whether to load every row or a deterministic
sample (see eda/loader.py). This module turns that decision into the
*analysis mode* stored on the report and produces the `sample_info_json`
that makes the report transparent about how the data was handled:

  * mode        — "full" | "sample" | "truncated"
  * total_rows  — exact count of rows in the source file
  * sample_rows — rows actually used for the detailed analyses
  * fraction    — sample_rows / total_rows
  * method      — how the sample was drawn (deterministic + seeded)
  * margin_of_error — worst-case 95% CI bound for proportions
  * confidence  — stated confidence level
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

CONFIDENCE_LEVEL = 0.95
_Z = 1.96  # z-value for a two-sided 95% confidence interval


def seed_for_path(storage_path: str) -> int:
    """Deterministic per-file seed: same path -> same sample -> same numbers."""
    digest = hashlib.sha1(storage_path.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % (2 ** 32)


def margin_of_error(sample_rows: int, confidence: float = CONFIDENCE_LEVEL) -> float:
    """Worst-case margin of error for a proportion from a simple random
    sample (p=0.5 maximises the variance of a binomial proportion)."""
    if sample_rows <= 0:
        return 1.0
    return round(_Z * math.sqrt(0.25 / sample_rows), 4)


def analysis_mode(loaded_rows: int, total_rows: int, max_rows_full: int) -> str:
    """Decide the mode given how many rows the loader kept in memory."""
    if not loaded_rows:
        return "truncated"
    if loaded_rows >= total_rows:
        return "full"
    if total_rows > max_rows_full:
        return "sample"
    return "full"


def sample_info(
    mode: str,
    total_rows: int,
    sample_rows: int,
    storage_path: str = "",
    truncated_cols: list[str] | None = None,
) -> dict[str, Any]:
    """Build the `sample_info_json` block stored on the report."""
    fraction = (sample_rows / total_rows) if total_rows else 0.0
    info: dict[str, Any] = {
        "mode": mode,
        "total_rows": total_rows,
        "sample_rows": sample_rows,
        "sampled_fraction": round(fraction, 4),
        "confidence_level": CONFIDENCE_LEVEL,
        "sampling_method": (
            "Deterministic, position-stratified random sample "
            f"(seed = sha1(storage_path), target <= {sample_rows} rows)."
            if mode != "full"
            else "All rows were loaded and analyzed exactly."
        ),
        "seed": seed_for_path(storage_path) if mode != "full" else None,
    }
    if mode != "full":
        info["margin_of_error"] = margin_of_error(sample_rows)
        info["interpretation"] = (
            "Proportions reported below carry a worst-case margin of error of "
            f"±{info['margin_of_error'] * 100:.1f} percentage points at "
            f"{CONFIDENCE_LEVEL * 100:.0f}% confidence. Exact global "
            "aggregates (means, standard deviations, missing counts, "
            "top-value frequencies) were computed over every row in the "
            "file via streaming statistics; only the deep analyses "
            "(correlations, outliers, statistical tests, chart-level "
            "breakdowns) use the sample."
        )
    if truncated_cols:
        info["truncated_columns"] = truncated_cols
    return info
