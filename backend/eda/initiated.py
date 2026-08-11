"""User-initiated analysis skills (#9-#14).

These modes are NOT part of the automatic report — the user explicitly asks
for them after a report exists, and they cost extra credits (Pro+ only, gated
server-side in main.py via eda/gating.py):

  9.  predictive_baseline   — honest baseline model for a chosen target
  10. psm                    — propensity-score matched association estimate
  11. key_driver             — relative importance ranking for an outcome
  12. what_if                — scenario predictions against an existing baseline
  13. segment_comparison     — two user-defined segments, formal test + effect
  14. decompose              — metric change split into mix shift vs within

Invariants (see docs/ARCHITECTURE.md §1):

  * every number is computed by pandas/scipy/sklearn — never by the LLM;
  * every function is exception-safe: a guard failure returns a ``skipped``
    dict with a plain-language reason so the endpoint always answers;
  * deterministic: fixed random_state everywhere, no fits written to disk;
  * #12 what_if re-fits the same deterministic baseline configuration, so its
    prediction is identical to the stored baseline run;
  * language discipline: #10 and #11 report associations only — the PSM
    result carries a mandatory, non-suppressible caveat payload the frontend
    must render.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

from eda.classification import NON_CHARTABLE_KINDS

# Compute bounds: skills run on the already-loaded (possibly sampled) frame,
# but models are capped so a giant file cannot hang a request.
SKILL_MAX_ROWS = 50_000
SKILL_MAX_FEATURES = 40
HOLDOUT_FRAC = 0.2
RANDOM_STATE = 0
MIN_TRAIN_ROWS = 40
MIN_TREATMENT_ROWS = 20


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _numeric_cols(classification: dict[str, dict[str, Any]]) -> list[str]:
    return [c for c, info in classification.items() if info.get("kind") == "numeric"]


def _feature_cols(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    exclude: set[str],
) -> list[str]:
    """Candidate predictor columns: numeric + low-cardinality categoricals.
    Never includes identifiers, free text, dates, constants or the target."""
    out: list[str] = []
    for col, info in classification.items():
        if col in exclude or info.get("kind") in NON_CHARTABLE_KINDS:
            continue
        if info.get("kind") == "constant":
            continue
        cardinality = info.get("cardinality") or 0
        if info.get("kind") == "categorical" and cardinality > 24:
            continue
        if df[col].nunique(dropna=True) <= 1:
            continue
        out.append(col)
    return out[:SKILL_MAX_FEATURES]


def _cap_rows(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) > SKILL_MAX_ROWS:
        rng = np.random.default_rng(RANDOM_STATE)
        df = df.iloc[rng.choice(len(df), size=SKILL_MAX_ROWS, replace=False)]
    return df


def _design_matrix(
    df: pd.DataFrame, feature_cols: list[str], target_col: str
) -> pd.DataFrame:
    """Numeric design matrix (one-hot encodes low-cardinality categoricals).
    Returns empty frame when no usable features remain."""
    X = df[feature_cols].copy()
    for col in feature_cols:
        info_kind = _kind_of(df, col)
        if info_kind == "categorical":
            X[col] = X[col].astype("string").fillna("__missing__")
    X = pd.get_dummies(X, prefix_sep="=", drop_first=False)
    X = X.apply(pd.to_numeric, errors="coerce")
    X = X.fillna(0.0)
    # Drop any resulting constant columns (including the target if it leaked).
    X = X.loc[:, X.nunique(dropna=True) > 1]
    return X


def _kind_of(df: pd.DataFrame, col: str) -> str:
    if pd.api.types.is_numeric_dtype(df[col]) and df[col].nunique(dropna=True) > 8:
        return "numeric"
    return "categorical"


def _target_kind(df: pd.DataFrame, target: str) -> str:
    nunique = df[target].nunique(dropna=True)
    if nunique <= 2:
        return "binary"
    if pd.api.types.is_numeric_dtype(df[target]):
        return "numeric"
    return "categorical"


def _train_model(
    X: pd.DataFrame, y: pd.Series, kind: str
) -> tuple[Any, dict[str, Any]]:
    """Deterministic train/holdout split + model fit. Returns (model, meta).

    Regression: RandomForestRegressor. Binary: RandomForestClassifier. A naive
    baseline (mean / majority class) is always reported so the model metrics
    are honest. Holdout is stratified for classification.
    """
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.model_selection import train_test_split

    y = y.astype(float) if kind == "numeric" else y.astype("string")
    stratify = y if kind != "numeric" else None
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=HOLDOUT_FRAC, random_state=RANDOM_STATE,
        stratify=stratify,
    )
    if kind == "numeric":
        model = RandomForestRegressor(
            n_estimators=120, max_depth=8, min_samples_leaf=4,
            random_state=RANDOM_STATE, n_jobs=1,
        )
    else:
        model = RandomForestClassifier(
            n_estimators=120, max_depth=8, min_samples_leaf=4,
            random_state=RANDOM_STATE, n_jobs=1,
        )
    model.fit(X_tr, y_tr)
    return model, {"X_tr": X_tr, "X_te": X_te, "y_tr": y_tr, "y_te": y_te}


def _holdout_metrics(model: Any, meta: dict[str, Any], kind: str) -> dict[str, Any]:
    """Holdout metrics plus the naive baseline the model must beat."""
    from sklearn.metrics import (
        balanced_accuracy_score, mean_absolute_error, mean_squared_error,
        r2_score, roc_auc_score,
    )

    X_te, y_te = meta["X_te"], meta["y_te"]
    if kind == "numeric":
        pred = model.predict(X_te).astype(float)
        naive = float(np.mean(meta["y_tr"].astype(float)))
        return {
            "rmse": round(float(np.sqrt(mean_squared_error(y_te, pred))), 4),
            "mae": round(float(mean_absolute_error(y_te, pred)), 4),
            "r2": round(float(r2_score(y_te, pred)), 4),
            "naive_mean_mae": round(float(mean_absolute_error(y_te, np.full_like(pred, naive))), 4),
            "holdout_rows": int(len(y_te)),
        }
    classes = np.unique(y_te.to_numpy())
    if len(classes) == 2:
        pred = model.predict_proba(X_te)[:, 1]
        auc = roc_auc_score(y_te == classes[1], pred)
    else:
        pred = model.predict(X_te)
        auc = None
    acc = balanced_accuracy_score(y_te, model.predict(X_te))
    naive = float(meta["y_tr"].value_counts().idxmax())  # majority class
    naive_acc = balanced_accuracy_score(
        y_te, np.full(len(y_te), naive, dtype=object)
    )
    return {
        "auc": round(float(auc), 4) if auc is not None else None,
        "balanced_accuracy": round(float(acc), 4),
        "naive_majority_balanced_accuracy": round(float(naive_acc), 4),
        "holdout_rows": int(len(y_te)),
        "positive_class": str(classes[1]) if len(classes) == 2 else None,
    }


def _permutation_importance(
    model: Any, meta: dict[str, Any], feature_names: list[str], kind: str
) -> list[dict[str, Any]]:
    """Permutation importance on the holdout (top features with their columns).
    Permuting destroys the association between a feature and the outcome, so
    the drop in score is a *relative* importance measure, not causation."""
    from sklearn.inspection import permutation_importance

    X_te, y_te = meta["X_te"], meta["y_te"]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = permutation_importance(
                model, X_te, y_te, n_repeats=5, random_state=RANDOM_STATE,
                scoring="r2" if kind == "numeric" else "roc_auc", n_jobs=1,
            )
    except Exception:
        return []
    scores = sorted(
        zip(feature_names, result.importances_mean),
        key=lambda t: abs(t[1]), reverse=True,
    )
    return [
        {"feature": name, "importance": round(float(imp), 4)}
        for name, imp in scores[:10]
        if abs(float(imp)) > 1e-9
    ]


def _resolve_feature_names(X: pd.DataFrame) -> list[str]:
    return list(X.columns)


def _skip(reason: str) -> dict[str, Any]:
    return {"skipped": True, "reason": reason}


def _guard_target(df: pd.DataFrame, target: str) -> dict[str, Any] | None:
    if target not in df.columns:
        return _skip(f"Target column '{target}' does not exist in the file.")
    if df[target].isna().all():
        return _skip(f"Target column '{target}' is entirely empty.")
    if df[target].nunique(dropna=True) < 2:
        return _skip(f"Target column '{target}' has fewer than two distinct values.")
    return None


# ---------------------------------------------------------------------------
# 9. predictive_baseline
# ---------------------------------------------------------------------------

def predictive_baseline(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Fit an honest baseline model for a target the user chooses.

    Returns holdout metrics (with the naive baseline comparison so the model
    can't look good by accident) and permutation importance.
    """
    target = str(params.get("target_column") or "").strip()
    if not target:
        return _skip("A target column is required.")
    if _guard_target(df, target):
        return _guard_target(df, target)

    work = _cap_rows(df).dropna(subset=[target])
    if len(work) < MIN_TRAIN_ROWS:
        return _skip(f"Needs at least {MIN_TRAIN_ROWS} rows with a target "
                     f"value; only {len(work)} available.")

    kind = _target_kind(work, target)
    if kind not in ("numeric", "binary"):
        return _skip("The target must be numeric (regression) or a two-value "
                     "column (classification).")
    if kind == "binary":
        work = work[work[target].notna()]
        top2 = work[target].astype("string").value_counts().head(2).index
        work = work[work[target].astype("string").isin(top2)]

    feature_cols = _feature_cols(work, classification, exclude={target})
    if not feature_cols:
        return _skip("No usable predictor columns remain after excluding "
                     "identifiers, free text and dates.")
    X = _design_matrix(work, feature_cols, target)
    if len(X.columns) < 2:
        return _skip("Not enough non-constant features to fit a model.")
    y = work[target]

    try:
        model, meta = _train_model(X, y, kind)
        metrics = _holdout_metrics(model, meta, kind)
        importance = _permutation_importance(model, meta, _resolve_feature_names(X), kind)
    except Exception as exc:  # noqa: BLE001
        return _skip(f"The model could not be fitted for this data: {exc}")

    return {
        "target_column": target,
        "task_type": "regression" if kind == "numeric" else "classification",
        "rows_used": int(len(X)),
        "feature_count": int(X.shape[1]),
        "model": (
            "Random Forest (120 trees, max_depth 8) with a deterministic "
            "80/20 holdout split."
        ),
        "metrics": metrics,
        "permutation_importance": importance,
        "features": feature_cols,
        "method": (
            "Baseline supervised model with honest holdout metrics compared "
            "to a naive predictor. Permutation importance measures the drop "
            "in holdout score when a feature's values are shuffled — a "
            "relative association, not a causal effect."
        ),
    }


# ---------------------------------------------------------------------------
# 10. psm — opt-in treatment effect estimator (association only)
# ---------------------------------------------------------------------------

def psm_analysis(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Propensity-score matched comparison between two groups.

    Association only. The returned payload ALWAYS carries a mandatory,
    non-suppressible ``caveat`` block that the frontend must render as a fixed
    non-collapsible notice.
    """
    treatment = str(params.get("treatment_column") or "").strip()
    outcome = str(params.get("outcome_column") or "").strip()
    if not treatment or not outcome:
        return _skip("Both a treatment column and an outcome column are required.")
    if treatment not in df.columns:
        return _skip(f"Treatment column '{treatment}' does not exist.")
    if outcome not in df.columns:
        return _skip(f"Outcome column '{outcome}' does not exist.")

    t_nunique = df[treatment].nunique(dropna=True)
    if t_nunique != 2:
        return _skip(f"The treatment column '{treatment}' must have exactly "
                     f"two values; it has {t_nunique}.")

    work = _cap_rows(df).dropna(subset=[treatment, outcome])
    labels = work[treatment].astype("string").dropna().unique()[:2]
    if len(labels) < 2:
        return _skip("The treatment column needs both groups present.")
    treated, control = str(labels[0]), str(labels[1])
    treat_mask = work[treatment].astype("string") == treated
    if int(treat_mask.sum()) < MIN_TREATMENT_ROWS or int((~treat_mask).sum()) < MIN_TREATMENT_ROWS:
        return _skip(f"Each group needs at least {MIN_TREATMENT_ROWS} rows.")

    feature_cols = _feature_cols(work, classification, exclude={treatment, outcome})
    if not feature_cols:
        return _skip("No usable covariates remain to compute propensity scores.")
    X = _design_matrix(work, feature_cols, treatment)
    if len(X.columns) < 2:
        return _skip("Not enough non-constant covariates for propensity scoring.")
    y_treat = (work[treatment].astype("string") == treated).astype(int)

    from scipy import stats
    from sklearn.linear_model import LogisticRegression

    try:
        logit = LogisticRegression(max_iter=2000, random_state=RANDOM_STATE, C=1e3)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            logit.fit(X, y_treat)
            propensity = logit.predict_proba(X)[:, 1]

        # Before-matching balance: standardized mean difference per covariate.
        def _smd(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
            num = X.loc[mask_a, :].mean() - X.loc[mask_b, :].mean()
            var = X.loc[mask_a, :].var(ddof=1) + X.loc[mask_b, :].var(ddof=1)
            denom = np.sqrt(np.clip(var, 1e-12, None))
            with np.errstate(divide="ignore", invalid="ignore"):
                return float(np.nanmax(np.abs(num / denom)) if len(num) else 0.0)

        before_smd = _smd(y_treat == 1, y_treat == 0)

        # Nearest-neighbour matching without replacement, with caliper.
        p_treated = propensity[y_treat == 1]
        p_control = propensity[y_treat == 0]
        caliper = 0.2 * float(np.std(propensity))
        idx_t = np.flatnonzero(y_treat == 1)
        idx_c = np.flatnonzero(y_treat == 0)
        used: set[int] = set()
        pairs: list[tuple[int, int]] = []
        order = np.argsort(p_treated)[::-1]
        for pos in order:
            t_idx = idx_t[pos]
            dists = np.abs(p_control - p_treated[pos])
            candidates = [j for j in range(len(idx_c)) if idx_c[j] not in used]
            if not candidates:
                continue
            j = min(candidates, key=lambda j: dists[j])
            if dists[j] > caliper:
                continue
            used.add(idx_c[j])
            pairs.append((int(t_idx), int(idx_c[j])))

        if len(pairs) < MIN_TREATMENT_ROWS:
            return _skip("Too few matched pairs were found within the caliper "
                         "to report a stable estimate.")

        # Matched balance + ATT estimate.
        y = work[outcome].astype(float)
        matched_treat = np.array([y.iloc[a] for a, _ in pairs])
        matched_ctrl = np.array([y.iloc[b] for _, b in pairs])
        att = float(matched_treat.mean() - matched_ctrl.mean())

        m_treat = y[y_treat == 1]
        m_ctrl = y[y_treat == 0]
        raw_diff = float(m_treat.mean() - m_ctrl.mean())

        treated_matches = np.zeros(len(X), dtype=bool)
        treated_matches[[a for a, _ in pairs]] = True
        matched_p = propensity[treated_matches | (np.isin(np.arange(len(X)), [b for _, b in pairs]))]
        after_smd = _smd(
            treated_matches & (y_treat == 1),
            (np.isin(np.arange(len(X)), [b for _, b in pairs])) & (y_treat == 0),
        )
    except Exception as exc:  # noqa: BLE001
        return _skip(f"PSM could not be computed for this data: {exc}")

    return {
        "treatment_column": treatment,
        "outcome_column": outcome,
        "treated_group": treated,
        "control_group": control,
        "raw_rows_treated": int(treat_mask.sum()),
        "raw_rows_control": int((~treat_mask).sum()),
        "matched_pairs": len(pairs),
        "att_estimate": round(att, 4),
        "raw_group_difference": round(raw_diff, 4),
        "balance_before_smd": round(before_smd, 4),
        "balance_after_smd": round(after_smd, 4),
        "caliper": round(float(caliper), 4),
        "covariates": feature_cols,
        "method": (
            "Logistic-regression propensity scores, nearest-neighbour "
            "matching without replacement within a 0.2-SD caliper, then the "
            "difference in mean outcome between matched pairs (ATT)."
        ),
        "caveat": {
            "mandatory": True,
            "non_suppressible": True,
            "text": (
                "This is an ASSOCIATION estimate, not proof of causation. "
                "Matching only balances the observed covariates included in "
                "the propensity model; unmeasured confounders, selection into "
                "the treatment group, and outcome measurement differences can "
                "still bias the estimate. Treat the ATT as a descriptive "
                "difference between otherwise-similar groups, not as the "
                "effect of the treatment."
            ),
        },
    }


# ---------------------------------------------------------------------------
# 11. key_driver
# ---------------------------------------------------------------------------

def key_driver_analysis(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Rank the columns most strongly associated with an outcome, validated
    on a holdout set. Reports relative importance — association, not cause."""
    target = str(params.get("target_column") or "").strip()
    if not target:
        return _skip("An outcome (target) column is required.")
    if _guard_target(df, target):
        return _guard_target(df, target)

    work = _cap_rows(df).dropna(subset=[target])
    kind = _target_kind(work, target)
    if kind not in ("numeric", "binary"):
        return _skip("The outcome must be numeric or a two-value column.")
    if kind == "binary":
        top2 = work[target].astype("string").value_counts().head(2).index
        work = work[work[target].astype("string").isin(top2)]

    feature_cols = _feature_cols(work, classification, exclude={target})
    if not feature_cols:
        return _skip("No usable predictor columns remain after excluding "
                     "identifiers, free text and dates.")
    X = _design_matrix(work, feature_cols, target)
    if len(X.columns) < 2:
        return _skip("Not enough non-constant features to rank.")
    y = work[target]

    try:
        model, meta = _train_model(X, y, kind)
        metrics = _holdout_metrics(model, meta, kind)
        importance = _permutation_importance(model, meta, _resolve_feature_names(X), kind)
    except Exception as exc:  # noqa: BLE001
        return _skip(f"The driver model could not be fitted: {exc}")

    return {
        "target_column": target,
        "task_type": "regression" if kind == "numeric" else "classification",
        "rows_used": int(len(X)),
        "drivers": importance,
        "holdout_metrics": metrics,
        "method": (
            "Random Forest with a holdout split; drivers ranked by "
            "permutation importance (drop in holdout score when the column is "
            "shuffled). A rank here is a relative association, not a causal "
            "effect."
        ),
    }


# ---------------------------------------------------------------------------
# 12. what_if — inference against an existing baseline
# ---------------------------------------------------------------------------

def what_if_scenario(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    params: dict[str, Any],
    baseline_run: dict[str, Any] | None,
) -> dict[str, Any]:
    """Predict an outcome for hypothetical feature values.

    Re-fits the same deterministic baseline configuration so the result is
    identical to the stored baseline run. Requires a completed
    predictive_baseline for the same target (checked at the API layer).
    """
    if baseline_run is None:
        return _skip("No completed predictive baseline exists for this "
                     "report. Run 'Predictive Baseline' first.")
    target = str(params.get("target_column") or "").strip()
    stored_target = str((baseline_run.get("params_json") or {}).get("target_column") or "")
    if target and target != stored_target:
        return _skip(f"This report's baseline was built for '{stored_target}', "
                     f"not '{target}'.")
    target = stored_target or target
    scenario = params.get("scenario") or {}
    if not isinstance(scenario, dict) or not scenario:
        return _skip("A scenario dictionary of {column: value} is required.")

    work = _cap_rows(df).dropna(subset=[target])
    kind = _target_kind(work, target)
    if kind not in ("numeric", "binary"):
        return _skip("The baseline target must be numeric or two-value.")
    if kind == "binary":
        top2 = work[target].astype("string").value_counts().head(2).index
        work = work[work[target].astype("string").isin(top2)]

    feature_cols = _feature_cols(work, classification, exclude={target})
    X = _design_matrix(work, feature_cols, target)
    if len(X.columns) < 2:
        return _skip("Not enough non-constant features to run the scenario.")
    y = work[target]

    try:
        model, meta = _train_model(X, y, kind)
        metrics = _holdout_metrics(model, meta, kind)
        # Residual spread on holdout -> approximate prediction interval.
        if kind == "numeric":
            resid = meta["y_te"].astype(float) - model.predict(meta["X_te"]).astype(float)
            resid_std = float(np.std(resid))
        else:
            resid_std = None
    except Exception as exc:  # noqa: BLE001
        return _skip(f"The scenario could not be evaluated: {exc}")

    # Build the scenario row aligned to the design matrix.
    row: dict[str, float] = {}
    for feat in X.columns:
        base = feat.split("=")[0]
        if base not in scenario:
            row[feat] = 0.0
            continue
        value = str(scenario[base])
        if "=" in feat:  # one-hot encoded categorical level
            row[feat] = 1.0 if feat.endswith("=" + value) else 0.0
        else:
            try:
                row[feat] = float(value)
            except (TypeError, ValueError):
                return _skip(f"Scenario value for numeric column '{base}' "
                             f"must be a number, got '{value}'.")
    try:
        scenario_frame = pd.DataFrame([row], columns=X.columns).astype(float)
        if kind == "numeric":
            pred = float(model.predict(scenario_frame)[0])
            width = 1.96 * resid_std
            out_pred = {
                "prediction": round(pred, 4),
                "lower": round(pred - width, 4),
                "upper": round(pred + width, 4),
                "interval_note": (
                    "Approximate 95% interval from holdout residual spread; "
                    "it reflects model noise, not full scenario uncertainty."
                ),
            }
        else:
            classes = np.unique(y.astype("string").to_numpy())
            prob = model.predict_proba(scenario_frame)[0, 1]
            out_pred = {
                "probability_positive_class": round(float(prob), 4),
                "predicted_class": str(classes[int(prob >= 0.5)]),
            }
    except Exception as exc:  # noqa: BLE001
        return _skip(f"The scenario could not be evaluated: {exc}")

    return {
        "target_column": target,
        "scenario": scenario,
        "result": out_pred,
        "based_on_baseline": True,
        "rows_used": int(len(X)),
        "holdout_metrics": metrics,
        "method": (
            "Re-fit of the report's deterministic baseline model; the "
            "scenario row is scored against it. Inference only — no model "
            "training beyond the baseline configuration."
        ),
    }


# ---------------------------------------------------------------------------
# 13. segment_comparison
# ---------------------------------------------------------------------------

def segment_comparison(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Compare two explicitly defined segments on a numeric metric with a
    formal test and effect size. Reuses the 2-group engine from adaptive.py.
    Language: 'statistically significant difference' only — never causation.
    """
    from eda.adaptive import compare_two_groups

    metric = str(params.get("numeric_column") or "").strip()
    seg_a = params.get("segment_a") or {}
    seg_b = params.get("segment_b") or {}
    if not metric or metric not in df.columns:
        return _skip("A numeric metric column is required.")
    if not isinstance(seg_a, dict) or not isinstance(seg_b, dict):
        return _skip("segment_a and segment_b must be {column: value} dicts.")
    if not seg_a or not seg_b:
        return _skip("Both segments must be defined with at least one "
                     "{column: value} filter.")

    def _mask(seg: dict[str, Any]) -> pd.Series:
        mask = pd.Series(True, index=df.index)
        for col, val in seg.items():
            if col not in df.columns:
                return pd.Series(False, index=df.index)
            mask &= df[col].astype("string").astype(object) == str(val)
        return mask

    mask_a, mask_b = _mask(seg_a), _mask(seg_b)
    overlap = int((mask_a & mask_b).sum())
    if overlap:
        return _skip("The two segment definitions overlap — they must be "
                     "mutually exclusive for a clean comparison.")
    if int(mask_a.sum()) < 8 or int(mask_b.sum()) < 8:
        return _skip("Each segment needs at least 8 rows with the metric.")

    res = compare_two_groups(df[metric], pd.Series(
        np.where(mask_a, "A", np.where(mask_b, "B", None)), index=df.index,
    ), "A", "B")
    if res is None:
        return _skip("The comparison could not be computed for these segments.")

    res["segment_a"] = seg_a
    res["segment_b"] = seg_b
    res["rows_a"] = int(mask_a.sum())
    res["rows_b"] = int(mask_b.sum())
    res["numeric_column"] = metric
    res["method"] = (
        res.get("method", "") + " User-defined segments compared "
        "with a formal significance test and Cohen's d."
    )
    return res


# ---------------------------------------------------------------------------
# 14. decompose — metric change mix shift vs within-segment
# ---------------------------------------------------------------------------

def decompose_change(
    df: pd.DataFrame,
    classification: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Split a metric's change between two periods into mix (compositional)
    shift vs within-segment contribution, for a segment column.

    Standard decomposition with an interaction term:
        total Δ  =  within + mix + interaction
        within   = Σ share_t1 × (rate_t2 − rate_t1)
        mix      = Σ (share_t2 − share_t1) × rate_t1
    """
    metric = str(params.get("metric_column") or "").strip()
    date_col = str(params.get("date_column") or "").strip()
    segment = str(params.get("segment_column") or "").strip()
    if not metric or not date_col or not segment:
        return _skip("metric_column, date_column and segment_column are all "
                     "required.")
    for col in (metric, date_col, segment):
        if col not in df.columns:
            return _skip(f"Column '{col}' does not exist in the file.")

    work = df[[metric, date_col, segment]].dropna()
    if work.empty:
        return _skip("No complete rows for the three selected columns.")
    try:
        dates = pd.to_datetime(work[date_col], errors="coerce")
        work = work.assign(_date=dates).dropna(subset=["_date"])
        work["_period"] = work["_date"].dt.to_period("M")
    except Exception:
        return _skip("The date column could not be parsed.")
    periods = sorted(work["_period"].unique().astype(str))
    if len(periods) < 2:
        return _skip("At least two distinct periods are required to "
                     "decompose a change.")

    p1 = str(params.get("period_start") or periods[0])
    p2 = str(params.get("period_end") or periods[-1])
    if p1 not in [str(p) for p in periods] or p2 not in [str(p) for p in periods]:
        return _skip(f"Periods must be chosen from the observed set: "
                     f"{', '.join(str(p) for p in periods[:8])}{'…' if len(periods) > 8 else ''}.")
    if p1 == p2:
        return _skip("period_start and period_end must differ.")

    metric_values = pd.to_numeric(work[metric], errors="coerce")
    work = work.assign(_metric=metric_values).dropna(subset=["_metric"])
    if work.empty:
        return _skip("The metric column has no numeric values.")

    d1 = work[work["_period"].astype(str) == p1]
    d2 = work[work["_period"].astype(str) == p2]
    total1, total2 = float(d1["_metric"].sum()), float(d2["_metric"].sum())
    if total1 <= 0 or total2 <= 0:
        return _skip("Both periods need a positive metric total to "
                     "decompose a change.")

    seg1 = d1.groupby(segment)["_metric"].agg(["sum", "mean", "count"])
    seg2 = d2.groupby(segment)["_metric"].agg(["sum", "mean", "count"])
    all_segs = sorted(set(seg1.index) | set(seg2.index))

    # Standard total-change decomposition. For a SUM metric the identity is:
    #   Δ total = within + mix + interaction
    #     within_s      = n1_s × (rate2_s − rate1_s)          [rates change,
    #                                                          composition fixed]
    #     mix_s         = (n2_s − n1_s) × rate1_s             [composition
    #                                                          shift, rates fixed]
    #     interaction_s = (n2_s − n1_s) × (rate2_s − rate1_s)
    within = mix = interaction = 0.0
    rows: list[dict[str, Any]] = []
    for s in all_segs:
        s1 = seg1.loc[s] if s in seg1.index else None
        s2 = seg2.loc[s] if s in seg2.index else None
        if s1 is None or s2 is None:
            continue
        n1, n2 = float(s1["count"]), float(s2["count"])
        rate1, rate2 = float(s1["mean"]), float(s2["mean"])
        w = n1 * (rate2 - rate1)
        m = (n2 - n1) * rate1
        i = (n2 - n1) * (rate2 - rate1)
        within += w
        mix += m
        interaction += i
        rows.append({
            "segment": str(s),
            "count_p1": int(n1),
            "count_p2": int(n2),
            "rate_p1": round(rate1, 4),
            "rate_p2": round(rate2, 4),
            "within_contribution": round(float(w), 4),
            "mix_contribution": round(float(m), 4),
            "interaction_contribution": round(float(i), 4),
        })

    total_change = total2 - total1
    return {
        "metric_column": metric,
        "segment_column": segment,
        "period_start": p1,
        "period_end": p2,
        "total_p1": round(total1, 4),
        "total_p2": round(total2, 4),
        "total_change": round(total_change, 4),
        "within_effect": round(within, 4),
        "mix_effect": round(mix, 4),
        "interaction": round(interaction, 4),
        "per_segment": rows,
        "method": (
            "Standard total-change decomposition: within (segment rates "
            "changing with composition fixed), mix (compositional shift with "
            "rates fixed) and interaction."
        ),
    }
