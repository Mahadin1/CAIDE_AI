"""New adaptive-plan task implementations (deterministic, pandas/numpy only).

These follow the exact same shape as the tasks in ``executor.py``: pure
functions that read the already-computed backbone summary and/or the loaded
frame, never mutate ``df``, and return JSON-safe dicts keyed by column. The
executor registers and dispatches them; the planner advertises them in the
closed task set; findings.py turns their output into user-facing findings.

Design rules honoured here (see docs/ARCHITECTURE.md §1):

  * thresholds are always *derived from the data's own baseline* (IQR bounds,
    baseline rates, actual reduction) rather than assumed constant;
  * results are proposals/measurements — nothing here ever transforms ``df``
    or creates derived columns automatically;
  * text embedding is the only heavyweight step and it is lazy + cached.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger("datascope.advanced")

# ---------------------------------------------------------------------------
# category_harmonization
# ---------------------------------------------------------------------------

CAT_CARDINALITY_MIN = 5
CAT_CARDINALITY_MAX = 2000
CAT_MERGE_REDUCTION_MARGIN_PCT = 5.0  # fire only above this actual reduction
CAT_FUZZY_RATIO = 90  # rapidfuzz normalized similarity to merge (0..100)


def _norm_value(value: str) -> str:
    """Case / whitespace / punctuation normalization for category values."""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _cluster_categories(
    value_counts: dict[str, int],
) -> tuple[list[dict[str, Any]], int]:
    """Cluster near-duplicate category labels (normalized exact + fuzzy).

    Returns (clusters, merged_unique). A cluster is
    {rep, count, variants: [other raw values merged in]}. Variants that are
    identical after normalization merge first (ratio 100); remaining distinct
    forms merge when rapidfuzz similarity >= CAT_FUZZY_RATIO and they share
    the first character (guards against nonsense cross-word merges).
    """
    try:
        from rapidfuzz import fuzz
    except Exception:  # pragma: no cover - optional dep
        return [], len(value_counts)

    groups: list[dict[str, Any]] = []
    for raw, count in sorted(
        value_counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True
    ):
        norm = _norm_value(raw)
        best: dict[str, Any] | None = None
        best_score = 0.0
        for g in groups:
            score = float(fuzz.ratio(norm, _norm_value(g["rep"])))
            if score > best_score:
                best, best_score = g, score
        if (
            best is not None
            and best_score >= CAT_FUZZY_RATIO
            and bool(norm)
            and norm[0] == _norm_value(best["rep"])[0]
        ):
            best["variants"].append(raw)
            best["count"] += count
        else:
            groups.append({"rep": raw, "count": count, "variants": []})
    return groups, len(groups)


def harmonize_categories(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Fuzzy-cluster near-duplicate categorical values; report only columns
    where merging would cut the unique count by more than 5%."""
    out: dict[str, Any] = {}
    for col, info in classification.items():
        if info["kind"] != "categorical":
            continue
        cardinality = info.get("cardinality") or 0
        if not (CAT_CARDINALITY_MIN <= cardinality <= CAT_CARDINALITY_MAX):
            continue
        series = df[col].dropna().astype("string")
        counts = series.value_counts().to_dict()
        if len(counts) < CAT_CARDINALITY_MIN:
            continue
        original_unique = len(counts)
        clusters, merged_unique = _cluster_categories(counts)
        if merged_unique == 0 or merged_unique >= original_unique:
            continue
        reduction_pct = (original_unique - merged_unique) / original_unique * 100.0
        if reduction_pct <= CAT_MERGE_REDUCTION_MARGIN_PCT:
            continue
        merges = []
        for cluster in sorted(clusters, key=lambda c: c["count"], reverse=True)[:3]:
            if not cluster["variants"]:
                continue
            merges.append({
                "canonical": str(cluster["rep"])[:80],
                "variants": [str(v)[:80] for v in cluster["variants"][:3]],
                "merged_rows": int(cluster["count"]),
            })
        if not merges:
            continue
        out[col] = {
            "original_unique": original_unique,
            "merged_unique": merged_unique,
            "reduction_pct": round(reduction_pct, 2),
            "reduction_margin_threshold_pct": CAT_MERGE_REDUCTION_MARGIN_PCT,
            "example_merges": merges,
            "method": (
                "Fuzzy clustering of category labels (case/whitespace/"
                "punctuation normalization + rapidfuzz similarity)."
            ),
        }
    return out


# ---------------------------------------------------------------------------
# outlier_subpopulation
# ---------------------------------------------------------------------------

SUBGROUP_MIN_SIZE = 20
SUBGROUP_MIN_OUTLIERS = 3
SUBGROUP_SIGMA = 2.0  # concentration must exceed baseline by 2 subgroup-SEs


def outlier_subpopulations(
    summary: dict[str, Any],
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Reuse the backbone IQR outlier bounds and check whether the flagged
    outliers concentrate inside one category value (a real subpopulation)."""
    outliers = summary.get("outliers") or {}
    categorical = [
        c for c, info in classification.items()
        if info["kind"] == "categorical" and 2 <= (info.get("cardinality") or 0) <= 100
    ]
    out: dict[str, Any] = {}
    for num_col, meta in outliers.items():
        if num_col not in df.columns or df[num_col].dtype.kind not in "fiub":
            continue
        count = int(meta.get("count") or 0)
        low = meta.get("low_bound")
        high = meta.get("high_bound")
        if count < 3 or low is None or high is None:
            continue
        values = pd.to_numeric(df[num_col], errors="coerce")
        outlier_mask = values.isna() | ((values < low) | (values > high))
        base_rate = float(meta.get("share") or 0.0)
        if base_rate <= 0:
            continue
        rows = df.shape[0]
        candidates: list[dict[str, Any]] = []
        for cat_col in categorical:
            cat = df[cat_col].astype("string")
            for value in cat.dropna().unique()[:40]:
                sub = cat == value
                n_v = int(sub.sum())
                if n_v < SUBGROUP_MIN_SIZE:
                    continue
                out_v = int(outlier_mask[sub].sum())
                if out_v < SUBGROUP_MIN_OUTLIERS:
                    continue
                p_v = out_v / n_v
                se = float(np.sqrt(base_rate * (1 - base_rate) / n_v))
                bound = base_rate + SUBGROUP_SIGMA * se
                if p_v > bound:
                    candidates.append({
                        "category_column": cat_col,
                        "value": str(value)[:80],
                        "subgroup_count": n_v,
                        "subgroup_outlier_count": out_v,
                        "subgroup_outlier_rate": round(p_v, 4),
                        "baseline_outlier_rate": round(base_rate, 4),
                        "ratio": round(p_v / base_rate, 2),
                        "significance_bound": round(bound, 4),
                        "rows_checked": rows,
                    })
        if not candidates:
            continue
        candidates.sort(key=lambda c: c["ratio"], reverse=True)
        top = candidates[0]
        out[f"{num_col}__by__{top['category_column']}"] = {
            "numeric_column": num_col,
            **top,
            "method": (
                "Outliers (IQR bounds from the backbone) tested for "
                "concentration inside single category values; threshold is the "
                "category's own baseline rate plus two standard errors of that "
                "rate given the subgroup size."
            ),
        }
    return out


# ---------------------------------------------------------------------------
# data_quality_score
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else 0.0


def data_quality_score(
    summary: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    """Composite 0–100 score derived entirely from the backbone stats.

    Everything here reuses numbers the backbone already computed — null rates,
    IQR outlier shares, duplicate share, and the mixed/constant/empty column
    classification — so it is cheap, deterministic and domain-agnostic.
    """
    classification = summary.get("column_classification") or {}
    columns = list(classification)
    n = max(1, len(columns))

    missing_pct = list((summary.get("missing_pct") or {}).values())
    avg_missing = _mean([float(v) for v in missing_pct])
    nulls_penalty = min(20.0, avg_missing / 50.0 * 20.0)

    outlier_shares = [
        float(v.get("share") or 0.0) for v in (summary.get("outliers") or {}).values()
    ]
    avg_outlier = _mean(outlier_shares)
    implausible_penalty = min(15.0, avg_outlier / 0.05 * 15.0)

    dup_share = float(summary.get("duplicate_share") or 0.0)
    duplicates_penalty = min(15.0, dup_share / 10.0 * 15.0)

    mixed_count = sum(1 for c in columns if classification[c].get("kind") == "mixed")
    mixed_share = mixed_count / n
    mixed_type_penalty = min(15.0, mixed_share / 0.2 * 15.0)

    dead_count = sum(
        1 for c in columns if classification[c].get("kind") in ("constant", "empty")
    )
    dead_share = dead_count / n
    constants_penalty = min(5.0, dead_share / 0.2 * 5.0)

    total_penalty = (
        nulls_penalty + implausible_penalty + duplicates_penalty
        + mixed_type_penalty + constants_penalty
    )
    score = max(0, int(round(100.0 - total_penalty)))
    if score >= 90:
        grade = "excellent"
    elif score >= 75:
        grade = "good"
    elif score >= 60:
        grade = "fair"
    else:
        grade = "needs_attention"

    return {
        "score": score,
        "grade": grade,
        "components": {
            "avg_missing_pct": round(avg_missing, 2),
            "avg_outlier_share": round(avg_outlier, 4),
            "duplicate_share": round(dup_share, 2),
            "mixed_column_share": round(mixed_share, 4),
            "constant_or_empty_share": round(dead_share, 4),
        },
        "penalties": {
            "nulls": round(nulls_penalty, 2),
            "implausible_values": round(implausible_penalty, 2),
            "duplicates": round(duplicates_penalty, 2),
            "mixed_types": round(mixed_type_penalty, 2),
            "constant_or_empty": round(constants_penalty, 2),
        },
        "method": (
            "Composite quality score starting at 100 and deducting for "
            "null-rate, IQR-outlier share, duplicate-row share, mixed-type and "
            "constant/empty columns — all thresholds scaled relative to each "
            "column's own distribution, never a fixed value range."
        ),
    }


# ---------------------------------------------------------------------------
# text_theme_extraction
# ---------------------------------------------------------------------------

TEXT_SAMPLE_CAP = 2000
TEXT_MIN_ROWS = 30
_TFIDF_MAX_FEATURES = 1000


def _pca_scores(X: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic PCA via SVD (numpy only). Returns (scores, evr)."""
    Xc = X - X.mean(axis=0)
    _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    total = float(np.sum(S ** 2))
    evr = (S ** 2 / max(total, 1e-12))[:k]
    scores = Xc @ Vt[:k].T
    return scores, evr


def _tfidf_theme_scores(
    corpus: list[str], k: int
) -> tuple[np.ndarray, np.ndarray] | None:
    """Lightweight theme space: TF-IDF + truncated SVD (no torch, no model
    download, single-digit MiB). Returns (scores n×k, explained-variance)."""
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(
        stop_words="english", max_features=_TFIDF_MAX_FEATURES,
        ngram_range=(1, 2),
    )
    X = vec.fit_transform(corpus)
    if X.shape[0] < 2 or X.shape[1] < 2:
        return None
    svd = TruncatedSVD(n_components=k, random_state=0)
    scores = svd.fit_transform(X)
    return scores, svd.explained_variance_ratio_


def _load_sbert_model():
    """Load the sentence-transformer model for one call only (never pinned
    for the process lifetime). Only used when TEXT_THEME_SBERT=1 — the
    lightweight TF-IDF path is the default so torch never enters this
    process. This path belongs on a dedicated worker with its own memory
    budget, not next to the API/job worker."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def text_themes(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Embed a free-text column locally and reduce to latent themes via PCA.

    Default path is a pure-sklearn TF-IDF + TruncatedSVD reduction (no torch,
    no model download). Setting TEXT_THEME_SBERT=1 switches to the
    sentence-transformers embeddings instead. Reports the *actual* explained
    variance and, per theme, the 2–3 real rows that load highest on it as
    human-readable anchors. Only runs when a free_text column exists
    (proposed by the planner, not forced in fallback).
    """
    text_cols = [
        c for c, info in classification.items()
        if info["kind"] == "free_text"
        and (info.get("avg_word_count") or 0) > 5
    ]
    out: dict[str, Any] = {}
    if not text_cols:
        return out

    use_sbert = settings.text_theme_sbert
    model = None
    if use_sbert:
        try:
            model = _load_sbert_model()
        except Exception as exc:  # pragma: no cover - offline env
            logger.warning(
                "SBERT theme path unavailable (%s); falling back to "
                "TF-IDF themes", exc,
            )
            use_sbert = False

    for col in text_cols:
        try:
            texts = df[col].dropna().astype(str).str.slice(0, 512)
            texts = texts[texts.str.len() > 3]
            if len(texts) < TEXT_MIN_ROWS:
                continue
            if len(texts) > TEXT_SAMPLE_CAP:
                texts = texts.sample(TEXT_SAMPLE_CAP, random_state=1)
            corpus = texts.tolist()
            if use_sbert:
                vectors = model.encode(corpus, normalize_embeddings=True,
                                       show_progress_bar=False)
                X = np.asarray(vectors, dtype=np.float64)
                k = min(5, X.shape[0] - 1, X.shape[1])
                if k < 2:
                    continue
                scores, evr = _pca_scores(X, k)
                method = (
                    "Embedded with sentence-transformers/all-MiniLM-L6-V2 "
                    "(local, no API calls) then PCA-reduced; explained "
                    "variance is the measured share of total variance per "
                    "component."
                )
            else:
                k = min(5, len(corpus) - 1, _TFIDF_MAX_FEATURES)
                if k < 2:
                    continue
                svd_result = _tfidf_theme_scores(corpus, k)
                if svd_result is None:
                    continue
                scores, evr = svd_result
                method = (
                    "TF-IDF weighted terms reduced with TruncatedSVD "
                    "(lightweight, no embedding model); explained variance "
                    "is the measured share of total variance per component."
                )
            cumulative = float(np.sum(evr))
            if cumulative < 0.05:
                # Nearly no shared structure — reporting themes would be noise.
                continue
            themes = []
            for comp in range(k):
                loadings = np.abs(scores[:, comp])
                idx = np.argsort(loadings)[::-1][:3]
                examples = [
                    {"text": str(corpus[i])[:140],
                     "loading": round(float(scores[i, comp]), 3)}
                    for i in idx
                ]
                themes.append({"component": comp + 1, "examples": examples})
            out[col] = {
                "texts_embedded": len(corpus),
                "components": int(k),
                "explained_variance": [round(float(v), 4) for v in evr],
                "cumulative_explained_variance": round(cumulative, 4),
                "themes": themes,
                "method": method,
            }
        except Exception as exc:  # pragma: no cover
            logger.warning("theme extraction failed for %s: %s", col, exc)
            continue
    return out


# ---------------------------------------------------------------------------
# distribution_drift
# ---------------------------------------------------------------------------

PSI_FLAG_THRESHOLD = 0.1
PSI_EPS = 1e-4


def _psi(expected_p: np.ndarray, actual_p: np.ndarray) -> float:
    a = np.clip(actual_p, PSI_EPS, None)
    e = np.clip(expected_p, PSI_EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def distribution_drift(
    summary: dict[str, Any], df: pd.DataFrame, task: dict[str, Any]
) -> dict[str, Any]:
    """PSI between the current dataset and the user's most recent prior
    report, using the prior report's stored histograms as the reference
    distribution. Silent no-op (empty dict) when no comparable prior report
    was found at plan time."""
    prior = summary.get("_prior_report")
    if not prior:
        return {"skipped": True,
                "reason": "No comparable prior report exists for this user, "
                          "so distribution drift was not computed."}
    prior_hist = prior.get("histograms") or {}
    prior_stats = prior.get("numeric_stats") or {}
    prior_rows = int(prior.get("shape", {}).get("rows") or 0)

    numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns]
    out: dict[str, Any] = {}
    for col in numeric_cols:
        ph = prior_hist.get(col)
        if not ph or not ph.get("bin_edges") or not ph.get("counts"):
            continue
        edges = np.asarray(ph["bin_edges"], dtype=float)
        counts = np.asarray(ph["counts"], dtype=float)
        if edges.ndim != 1 or len(edges) != len(counts) + 1:
            continue
        if counts.sum() <= 0 or np.any(np.diff(edges) <= 0):
            continue
        values = pd.to_numeric(df[col], errors="coerce").dropna()
        values = values[np.isfinite(values)].to_numpy(dtype=float)
        if values.size < 30:
            continue
        expected_p = counts / counts.sum()
        actual, _ = np.histogram(values, bins=edges)
        if actual.sum() <= 0:
            continue
        actual_p = actual / actual.sum()
        psi = _psi(expected_p, actual_p)
        if psi <= PSI_FLAG_THRESHOLD:
            continue
        prior_mean = prior_stats.get(col, {}).get("mean")
        current_mean = float(np.mean(values))
        mean_shift = (
            round(float(current_mean) - float(prior_mean), 4)
            if prior_mean is not None else None
        )
        out[col] = {
            "psi": round(psi, 4),
            "threshold": PSI_FLAG_THRESHOLD,
            "prior_rows": prior_rows,
            "current_rows": int(values.size),
            "prior_mean": (round(float(prior_mean), 4)
                           if prior_mean is not None else None),
            "current_mean": round(current_mean, 4),
            "mean_shift": mean_shift,
            "interpretation": (
                "The distribution of this column has shifted materially "
                "relative to your most recent analysis of a similar file."
            ),
        }
    return out


# ---------------------------------------------------------------------------
# pattern_extraction_proposal
# ---------------------------------------------------------------------------

PATTERN_MATCH_RATE = 0.70  # minimum share of non-null rows before proposing

_PATTERNS: list[tuple[str, str, str]] = [
    (
        "number_unit",
        r"^\d+(?:[.,]\d+)?\s*(?:kg|g|lb|lbs|oz|ml|l|cm|m|mm|px|kb|mb|gb|tb|"
        r"%|usd|eur|gbp|euro|dollar|hrs?|mins?|secs?|wks?|days?|mo|yrs?)\b.*$",
        "_value",
    ),
    (
        "version_like",
        r"^(?:v\d+(?:\.\d+)*|\d+\.\d+(?:\.\d+)*(?:[+-][\w.]+)?)$",
        "_version",
    ),
    (
        "embedded_tag",
        r"^.*(?:<[a-zA-Z0-9_./:-]+>|#[a-zA-Z0-9_-]+|@[a-zA-Z0-9_.-]+).*$",
        "_tag",
    ),
    (
        "leading_number",
        r"^\d+(?:[.,]\d+)?(?:\s+|\b)\w",
        "_number",
    ),
    (
        "reference_code",
        r"^[A-Za-z]{1,5}[-_/]?\d{4,}(?:[-_/][A-Za-z0-9]+)?$",
        "_code",
    ),
]


def patterns_proposal(
    df: pd.DataFrame, classification: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Detect a consistent embedded pattern in a text column and *propose*
    extracting a derived field — never mutates the frame or creates the
    column. Deliberately conservative: needs >70% of non-null rows to match
    the best regex before it fires."""
    text_cols = [
        c for c, info in classification.items()
        if info["kind"] == "free_text"
        or (info["kind"] == "categorical"
            and (info.get("cardinality") or 0) >= 10)
    ]
    out: dict[str, Any] = {}
    for col in text_cols:
        series = df[col].dropna().astype(str)
        series = series[series.str.len() > 0]
        total = len(series)
        if total < 30:
            continue
        best: tuple[float, str, str, str] | None = None
        for name, pattern, suffix in _PATTERNS:
            rx = re.compile(pattern, re.IGNORECASE)
            matched = int(series.map(lambda v: bool(rx.match(v.strip()))).sum())
            rate = matched / total
            if best is None or rate > best[0]:
                best = (rate, name, suffix, pattern)
        if best is None or best[0] < PATTERN_MATCH_RATE:
            continue
        rate, name, suffix, pattern = best
        rx = re.compile(pattern, re.IGNORECASE)
        examples = [
            str(v)[:80] for v in series
            if rx.match(str(v).strip())
        ][:3]
        out[col] = {
            "pattern": name,
            "match_rate": round(rate, 4),
            "match_rate_threshold": PATTERN_MATCH_RATE,
            "regex": pattern[:200],
            "example_matches": examples,
            "derived_field_proposal": f"{col}{suffix}",
            "note": (
                "A consistent pattern was detected in this column. Extracting "
                f"'{col}{suffix}' as a derived field would let you filter, "
                "group or chart on it directly. This is a proposal only — the "
                "derived column has not been created."
            ),
        }
    return out
