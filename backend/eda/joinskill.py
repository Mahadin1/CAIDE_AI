"""Two-dataset join quality assessment (#15).

This is a separate, attach-to-report skill: the user has a finished report
and wants to bring in a *second* file. We never materialize the merged frame —
we only measure how a join on chosen keys would behave:

  * left/right match rate (how much of each side would have a partner)
  * duplicate keys per side (how many rows would fan out / inflate a merge)
  * orphaned rows per side (records that would be dropped in an inner join)

Everything is deterministic pandas. A malformed request returns a ``skipped``
result rather than raising, so the endpoint always answers.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _skip(reason: str) -> dict[str, Any]:
    return {"skipped": True, "reason": reason}


def join_quality(
    left: pd.DataFrame,
    right: pd.DataFrame,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Assess joining `left` to `right` on the given key columns.

    params::
      left_key   — column name on the report's file
      right_key  — column name on the attached second file
      how        — 'inner' | 'left' (default 'left'), the intended join
    """
    left_key = str(params.get("left_key") or "").strip()
    right_key = str(params.get("right_key") or "").strip()
    if not left_key or not right_key:
        return _skip("Both left_key and right_key are required.")
    how = str(params.get("how") or "left").lower()
    if how not in ("inner", "left"):
        return _skip("how must be 'inner' or 'left'.")
    if left_key not in left.columns:
        return _skip(f"left_key '{left_key}' is not a column in the analyzed "
                     "file.")
    if right_key not in right.columns:
        return _skip(f"right_key '{right_key}' is not a column in the "
                     "attached file.")

    l_rows = int(len(left))
    r_rows = int(len(right))
    if l_rows == 0 or r_rows == 0:
        return _skip("Neither file may be empty.")

    def _key_summary(df: pd.DataFrame, key: str) -> dict[str, Any]:
        k = df[key].astype("string").str.strip()
        present = k.notna()
        non_null = k[present]
        dups = non_null[non_null.duplicated(keep=False)]
        dup_keys = (
            dups.value_counts().head(8).to_dict()
            if len(dups) else {}
        )
        return {
            "rows": int(len(df)),
            "null_keys": int((~present).sum()),
            "unique_keys": int(non_null.nunique()),
            "duplicate_key_rows": int(len(dups)),
            "duplicate_key_rows_pct": round(len(dups) / len(df), 4),
            "max_fanout_for_key": (
                int(dups.value_counts().max()) if len(dups) else 1
            ),
            "example_duplicate_keys": {str(k): int(v) for k, v in dup_keys.items()},
        }

    l_keys = left[left_key].astype("string").str.strip()
    r_keys = right[right_key].astype("string").str.strip()
    l_uniq = set(l_keys.dropna().unique())
    r_uniq = set(r_keys.dropna().unique())

    matched_l = sum(1 for v in l_keys.dropna() if v in r_uniq)
    matched_r = sum(1 for v in r_keys.dropna() if v in l_uniq)

    # Correct for duplicated keys: a left row whose key exists on the right
    # has a partner, even though it may fan out. Orphans are rows whose key
    # never appears on the other side.
    l_orphans = int((~l_keys.isin(r_uniq)).sum())
    r_orphans = int((~r_keys.isin(l_uniq)).sum())

    # Inner-join row count projection (each matching pair = 1, ignoring fanout
    # blow-up from duplicate keys, which the max_fanout fields flag).
    inner_rows_estimate = sum(
        min(v, r_keys.value_counts().get(k, 0)) for k, v in l_keys.value_counts().items()
        if k in r_uniq
    )

    severity = "high"
    if matched_l == 0:
        verdict = ("No keys match between the two files. Check that the key "
                   "columns have compatible formats and values (e.g. leading "
                   "zeros, casing, or unit differences).")
    else:
        l_match_pct = matched_l / max(1, l_rows)
        r_match_pct = matched_r / max(1, r_rows)
        if l_match_pct < 0.5:
            verdict = (
                f"Only {l_match_pct * 100:.0f}% of rows in the analyzed file "
                "have a matching key. An inner join would drop most of your "
                "data; a left join would leave large gaps on the right side."
            )
        elif l_match_pct < 0.9:
            verdict = (
                f"{l_match_pct * 100:.0f}% of rows match. Review the "
                f"{(1 - l_match_pct) * 100:.0f}% that do not before merging."
            )
        else:
            severity = "low" if (l_match_pct > 0.98 and r_match_pct > 0.9) else "medium"
            verdict = (
                f"{l_match_pct * 100:.0f}% of rows have a matching key — the "
                "join looks clean, assuming the duplicate keys are handled."
            )

    left_summary = _key_summary(left, left_key)
    right_summary = _key_summary(right, right_key)
    if left_summary["duplicate_key_rows_pct"] > 0.01 or \
       right_summary["duplicate_key_rows_pct"] > 0.01:
        verdict += (" Duplicate keys are present on one or both sides — a "
                    "naive merge would multiply rows. Aggregate or de-dupe "
                    "before joining.")

    return {
        "left_file": {
            "key_column": left_key,
            "summary": left_summary,
            "matched_rows": matched_l,
            "matched_pct": round(matched_l / l_rows, 4) if l_rows else 0.0,
            "orphaned_rows": l_orphans,
            "orphaned_pct": round(l_orphans / l_rows, 4) if l_rows else 0.0,
        },
        "right_file": {
            "key_column": right_key,
            "summary": right_summary,
            "matched_rows": matched_r,
            "matched_pct": round(matched_r / r_rows, 4) if r_rows else 0.0,
            "orphaned_rows": r_orphans,
            "orphaned_pct": round(r_orphans / r_rows, 4) if r_rows else 0.0,
        },
        "projected_inner_join_rows": int(inner_rows_estimate),
        "verdict": verdict,
        "severity": severity,
        "method": (
            "Key-match enumeration between the two files plus per-side "
            "duplicate-key and null-key counts. No merged frame is built."
        ),
    }
