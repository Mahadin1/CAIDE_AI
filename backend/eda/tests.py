"""Enhanced statistical tests — scipy/statsmodels, deterministic.

Every function here is defensive: it returns a structured result or `None`
(never raises), so a numerical failure on one analysis can never fail the
whole report. Results are labelled with the method used and a `n` (sample
size) so the narrative can be honest about power/sensitivity.

Available analyses (each also referenced by the adaptive planner):

  * normality           — Shapiro-Wilk (n <= 5000) else D'Agostino's K²
  * fit_distributions   — AIC-ranked candidate distributions
  * group_tests         — ANOVA + Kruskal-Wallis (+ pairwise top-vs-bottom)
  * spearman_significant— Pearson + Spearman with p-values
  * mann_kendall        — monotonic trend on a time-ordered series
  * vif                 — variance inflation factor (manual, via lstsq)
  * littles_mcar        — Little's MCAR test for missing data
"""
from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_ALPHA = 0.05


def _clean_numeric(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    return values[np.isfinite(values)]


def normality(series: pd.Series) -> dict[str, Any] | None:
    """Test whether a numeric column looks normally distributed."""
    from scipy import stats

    values = _clean_numeric(series)
    if values.size < 8:
        return None
    if values.size <= 5000:
        stat, p = stats.shapiro(values)
        method = "Shapiro-Wilk"
    else:
        stat, p = stats.normaltest(values)
        method = "D'Agostino-Pearson K²"
    if math.isnan(float(p)):
        return None
    return {
        "method": method,
        "n": int(values.size),
        "statistic": round(float(stat), 4),
        "p_value": round(float(p), 6),
        "is_normal": bool(p >= DEFAULT_ALPHA),
        "interpretation": (
            "consistent with a normal distribution" if p >= DEFAULT_ALPHA
            else "significantly non-normal"
        ),
    }


def fit_distributions(series: pd.Series, top_n: int = 3) -> dict[str, Any] | None:
    """Fit common distributions to a numeric column, ranked by AIC."""
    from scipy import stats as scipy_stats

    values = _clean_numeric(series)
    if values.size < 30:
        return None
    # Only fit to strictly positive data for the positive-support candidates.
    candidates = [
        ("normal", scipy_stats.norm),
        ("exponential", scipy_stats.expon),
        ("uniform", scipy_stats.uniform),
    ]
    positive = values[values > 0]
    if positive.size >= 30:
        candidates += [("lognormal", scipy_stats.lognorm), ("gamma", scipy_stats.gamma)]
    if values.size >= 2 and len(np.unique(values)) >= 5:
        candidates += [("beta", scipy_stats.beta)]

    fits: list[dict[str, Any]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, dist in candidates:
            try:
                if name == "beta":
                    # Scale beta to [0,1] first for numerical stability.
                    lo, hi = float(values.min()), float(values.max())
                    if hi - lo < 1e-9:
                        continue
                    scaled = (values - lo) / (hi - lo)
                    params = dist.fit(scaled)
                    log_lik = dist.logpdf(scaled, *params).sum()
                else:
                    params = dist.fit(values)
                    log_lik = dist.logpdf(values, *params).sum()
            except Exception:
                continue
            k = len(params)
            aic = 2 * k - 2 * float(log_lik)
            fits.append({"name": name, "aic": round(float(aic), 2),
                         "log_lik": round(float(log_lik), 2), "n_params": k})
    if not fits:
        return None
    fits.sort(key=lambda f: f["aic"])
    return {
        "n": int(values.size),
        "best": fits[0]["name"],
        "candidates": fits[:top_n],
        "interpretation": (
            f"The lowest-AIC candidate is {fits[0]['name']}. Lower AIC means a "
            "better fit given the number of parameters."
        ),
    }


def group_tests(
    numeric: pd.Series, categorical: pd.Series, max_groups: int = 8
) -> dict[str, Any] | None:
    """ANOVA (parametric) + Kruskal-Wallis (non-parametric) across groups.

    Also computes the top-vs-bottom group pair and a Mann-Whitney U post-hoc
    so the report can point at *which* groups differ.
    """
    from scipy import stats

    df = pd.DataFrame({"n": numeric, "c": categorical}).dropna()
    if df.empty:
        return None
    groups: dict[str, np.ndarray] = {}
    for name, sub in df.groupby("c")["n"]:
        values = sub.to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if values.size >= 3:
            groups[str(name)] = values
    if len(groups) < 2 or len(groups) > max_groups:
        return None
    names = sorted(groups)
    arrays = [groups[n] for n in names]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            anova_f, anova_p = stats.f_oneway(*arrays)
        except Exception:
            anova_f, anova_p = float("nan"), float("nan")
        try:
            kw_h, kw_p = stats.kruskal(*arrays)
        except Exception:
            kw_h, kw_p = float("nan"), float("nan")

    means = {n: float(np.mean(v)) for n, v in groups.items()}
    top = max(names, key=lambda n: means[n])
    bottom = min(names, key=lambda n: means[n])
    post_hoc = None
    if top != bottom:
        try:
            u, p = stats.mannwhitneyu(groups[top], groups[bottom], alternative="two-sided")
            post_hoc = {
                "group_a": top,
                "group_b": bottom,
                "mean_a": round(means[top], 4),
                "mean_b": round(means[bottom], 4),
                "p_value": round(float(p), 6),
                "significant": bool(p < DEFAULT_ALPHA),
            }
        except Exception:
            post_hoc = None

    significant = (
        (not math.isnan(anova_p) and anova_p < DEFAULT_ALPHA)
        or (not math.isnan(kw_p) and kw_p < DEFAULT_ALPHA)
    )
    return {
        "groups": [{"name": n, "mean": round(means[n], 4),
                    "count": int(len(v))} for n, v in groups.items()],
        "anova": {"f": _round(anova_f), "p_value": _round(anova_p)},
        "kruskal": {"h": _round(kw_h), "p_value": _round(kw_p)},
        "significant": bool(significant),
        "post_hoc": post_hoc,
        "interpretation": (
            "group means differ significantly" if significant
            else "no significant difference between group means was detected"
        ),
    }


def _round(x: float) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x), 6)


def spearman_significant(
    df: pd.DataFrame, max_cols: int = 12
) -> dict[str, Any]:
    """Pearson + Spearman correlations with p-values for numeric pairs.

    Bounded to `max_cols` so a wide frame can't explode the pairwise cost.
    """
    from scipy import stats

    numeric = df.select_dtypes(include=[np.number])
    cols = list(numeric.columns)[:max_cols]
    out: dict[str, Any] = {}
    if len(cols) < 2:
        return out
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            pair = numeric[[a, b]].dropna()
            if len(pair) < 5:
                continue
            x = pair[a].to_numpy(dtype=float)
            y = pair[b].to_numpy(dtype=float)
            if np.std(x) == 0 or np.std(y) == 0:
                continue
            try:
                pear_r, pear_p = stats.pearsonr(x, y)
            except Exception:
                continue
            try:
                spear_r, spear_p = stats.spearmanr(x, y)
            except Exception:
                spear_r, spear_p = pear_r, pear_p
            out[f"{a}__vs__{b}"] = {
                "column_a": a,
                "column_b": b,
                "pearson_r": round(float(pear_r), 4),
                "pearson_p": round(float(pear_p), 6),
                "spearman_r": round(float(spear_r), 4),
                "spearman_p": round(float(spear_p), 6),
                "pearson_significant": bool(pear_p < DEFAULT_ALPHA),
                "spearman_significant": bool(spear_p < DEFAULT_ALPHA),
                "n": int(len(pair)),
                "linear_only": abs(pear_r) >= 0.1 and abs(spear_r - pear_r) > 0.15,
            }
    return out


def mann_kendall(series: pd.Series) -> dict[str, Any] | None:
    """Mann-Kendall monotonic trend test on a time-ordered numeric series."""
    x = _clean_numeric(series)
    if x.size < 8:
        return None
    n = x.size
    s = 0
    for i in range(n - 1):
        s += int((x[i + 1:] > x[i]).sum()) - int((x[i + 1:] < x[i]).sum())
    # Variance with tie correction.
    ties = 0
    for _, count in pd.Series(x).value_counts().items():
        if count > 1:
            ties += count * (count - 1) * (2 * count + 5)
    var_s = (n * (n - 1) * (2 * n + 5) - ties) / 18.0
    if var_s <= 0:
        return None
    z = (s - 1) / math.sqrt(var_s) if s > 0 else ((s + 1) / math.sqrt(var_s) if s < 0 else 0.0)
    from scipy import stats
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    tau = (2 * s) / (n * (n - 1))
    return {
        "s": int(s),
        "z": round(float(z), 4),
        "tau": round(float(tau), 4),
        "p_value": round(float(p), 6),
        "direction": "increasing" if s > 0 else ("decreasing" if s < 0 else "flat"),
        "significant": bool(p < DEFAULT_ALPHA),
    }


def vif(df: pd.DataFrame, max_cols: int = 15) -> dict[str, Any]:
    """Variance Inflation Factor for numeric columns (manual OLS)."""
    numeric = df.select_dtypes(include=[np.number]).dropna()
    cols = [c for c in numeric.columns if numeric[c].std() > 0][:max_cols]
    out: dict[str, Any] = {}
    if len(cols) < 2:
        return out
    X = numeric[cols].to_numpy(dtype=float)
    X_mean = X - X.mean(axis=0)
    for idx, col in enumerate(cols):
        y = X_mean[:, idx]
        other = np.delete(X_mean, idx, axis=1)
        if other.shape[1] == 0:
            continue
        if other.shape[0] <= other.shape[1]:
            vif_val = float("inf")
        else:
            try:
                beta, *_ = np.linalg.lstsq(other, y, rcond=None)
                resid = y - other @ beta
                ss_res = float(resid @ resid)
                ss_tot = float(y @ y)
                r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
                vif_val = 1.0 / (1.0 - r2) if r2 < 1.0 else float("inf")
            except Exception:
                vif_val = float("inf")
        out[col] = {
            "vif": None if vif_val == float("inf") else round(vif_val, 2),
            "collinear": vif_val == float("inf") or (isinstance(vif_val, float) and vif_val >= 10),
            "interpretation": (
                "high multicollinearity (VIF >= 10)" if vif_val != float("inf") and vif_val >= 10
                else "perfectly collinear with other columns" if vif_val == float("inf")
                else "acceptable"
            ),
        }
    return out


def littles_mcar(
    df: pd.DataFrame, max_patterns: int = 60
) -> dict[str, Any] | None:
    """Little's Missing Completely At Random test.

    Under MCAR the mean of the observed values for a variable is the same
    across every missingness pattern. We compute, per pattern, the
    standardized mean deviation vector (using the overall covariance of the
    variables observed in that pattern) and sum to a chi-square statistic.

    Returns None when the test is not computable (e.g. too few complete
    numeric columns) — never raises.
    """
    from scipy import stats

    numeric = df.select_dtypes(include=[np.number])
    numeric = numeric.loc[:, numeric.std() > 0]
    if numeric.shape[1] < 3 or len(numeric) < 30:
        return None
    try:
        pattern_key = numeric.isnull().sum(axis=1) * 0
        pattern = numeric.notnull().astype(int).astype(str).agg("".join, axis=1)
        overall_means = numeric.mean().to_dict()
        overall_cov = numeric.cov()
        chi2 = 0.0
        df_total = 0
        patterns_used = 0
        for _, rows in numeric.groupby(pattern):
            if len(rows) < 5:
                continue
            observed = [c for c in numeric.columns if rows[c].notna().all()]
            if len(observed) < 2:
                continue
            mean_diff = rows[observed].mean() - pd.Series(
                {c: overall_means[c] for c in observed}
            )
            cov = overall_cov.loc[observed, observed]
            try:
                inv = np.linalg.pinv(cov.to_numpy(dtype=float))
            except Exception:
                continue
            d = mean_diff.to_numpy(dtype=float)
            chi2 += len(rows) * float(d @ inv @ d)
            df_total += len(observed)
            patterns_used += 1
            if patterns_used >= max_patterns:
                break
        if patterns_used < 2 or df_total <= 0:
            return None
        p = 1 - stats.chi2.cdf(chi2, df_total - 1)
        return {
            "chi2": round(float(chi2), 3),
            "df": int(df_total - 1),
            "p_value": round(float(p), 6),
            "patterns_used": int(patterns_used),
            "conclusion": (
                "compatible with MCAR (missingness independent of values)"
                if p >= DEFAULT_ALPHA
                else "not compatible with MCAR (missingness likely depends on values — MAR or MNAR)"
            ),
            "mcar": bool(p >= DEFAULT_ALPHA),
        }
    except Exception:
        return None
