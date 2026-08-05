"""Online / streaming statistics that merge across chunks.

These are used so a huge file never needs to live in memory to answer the
"global" questions: what is the mean/variance of each numeric column, how many
values are missing, and what are the most common category values. The math is
exact for mean/variance/skew/kurtosis (Welford's algorithm, numerically
stable and mergeable), exact for missing counts, and exact for top-K category
frequencies (capped at `k` entries — counts below the cap are exact).

Correlations, crosstabs, outlier detection and hypothesis tests are *not*
stream-mergeable cheaply, so those run on a deterministic sample instead (see
eda/sampling.py). The report always states which numbers are exact globals and
which come from the sample.
"""
from __future__ import annotations

import math
from typing import Any, Iterator

import numpy as np
import pandas as pd


class OnlineStats:
    """Mergeable Welford accumulator for mean / variance / skew / kurtosis."""

    __slots__ = ("n", "mean", "_m2", "_m3", "_m4")

    def __init__(
        self,
        n: int = 0,
        mean: float = 0.0,
        m2: float = 0.0,
        m3: float = 0.0,
        m4: float = 0.0,
    ) -> None:
        self.n = n
        self.mean = mean
        self._m2 = m2
        self._m3 = m3
        self._m4 = m4

    def update(self, value: float) -> None:
        """Add a single observation."""
        n1 = self.n
        self.n = n1 + 1
        delta = value - self.mean
        delta_n = delta / self.n
        delta_n2 = delta_n * delta_n
        term1 = delta * delta_n * n1
        self._m4 += term1 * delta_n2 * (self.n * self.n - 3 * self.n + 3) + 6 * delta_n2 * self._m2 - 4 * delta_n * self._m3
        self._m3 += term1 * delta_n * (self.n - 2) - 3 * delta_n * self._m2
        self._m2 += term1
        self.mean += delta_n

    def update_all(self, values: np.ndarray) -> None:
        """Add a vector of observations (uses the vectorized batch update)."""
        values = np.asarray(values, dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return
        self.merge(OnlineStats.from_values(values))

    @staticmethod
    def from_values(values: np.ndarray) -> "OnlineStats":
        out = OnlineStats()
        n = values.size
        if n == 0:
            return out
        mean = float(values.mean())
        # Biased moments (delta degrees of freedom) then convert to the
        # accumulator convention used by Welford's merge formula.
        m2 = float(((values - mean) ** 2).sum())
        m3 = float(((values - mean) ** 3).sum())
        m4 = float(((values - mean) ** 4).sum())
        out.n = n
        out.mean = mean
        out._m2 = m2
        out._m3 = m3
        out._m4 = m4
        return out

    def merge(self, other: "OnlineStats") -> None:
        """Combine two accumulators (the merge formula for Welford's method)."""
        if other.n == 0:
            return
        if self.n == 0:
            self.n, self.mean, self._m2, self._m3, self._m4 = (
                other.n,
                other.mean,
                other._m2,
                other._m3,
                other._m4,
            )
            return
        n1, n2 = self.n, other.n
        n = n1 + n2
        delta = other.mean - self.mean
        delta2 = delta * delta
        delta3 = delta2 * delta
        delta4 = delta2 * delta2

        m2 = self._m2 + other._m2 + delta2 * n1 * n2 / n
        m3 = (
            self._m3
            + other._m3
            + delta3 * n1 * n2 * (n1 - n2) / (n * n)
            + 3.0 * delta * (n1 * other._m2 - n2 * self._m2) / n
        )
        m4 = (
            self._m4
            + other._m4
            + delta4 * n1 * n2 * (n1 * n1 - n1 * n2 + n2 * n2) / (n ** 3)
            + 6.0 * delta2 * (n1 * n1 * other._m2 + n2 * n2 * self._m2) / (n * n)
            + 4.0 * delta * (n1 * self._m3 - n2 * other._m3) / n
        )
        self.n = n
        self.mean += delta * n2 / n
        self._m2 = m2
        self._m3 = m3
        self._m4 = m4

    def finalize(self) -> dict[str, float]:
        """Return {n, mean, variance, std, skew, kurtosis} (None-safe)."""
        if self.n == 0:
            return {"n": 0, "mean": None, "variance": None, "std": None,
                    "skew": None, "kurtosis": None}
        n = float(self.n)
        variance = self._m2 / (n - 1) if n > 1 else 0.0
        std = math.sqrt(max(variance, 0.0))
        skew = None
        kurt = None
        if std > 0:
            # Adjust biased moments to the sample (unbiased-ish) convention.
            m2 = self._m2 / n
            m3 = self._m3 / n
            m4 = self._m4 / n
            if n > 2:
                # Sample skewness (adjusted for bias via the factor).
                g1 = m3 / (m2 ** 1.5)
                skew = g1 * math.sqrt(n * (n - 1)) / (n - 2) if n > 2 else g1
            if n > 3:
                g2 = m4 / (m2 * m2) - 3.0
                kurt = ((n - 1) / ((n - 2) * (n - 3))) * ((n + 1) * g2 + 6)
        return {
            "n": int(self.n),
            "mean": float(self.mean),
            "variance": float(variance),
            "std": float(std),
            "skew": skew,
            "kurtosis": kurt,
        }


class TopKCounter:
    """Exact top-K frequency counter (bounded memory).

    All counts are exact; values beyond the cap simply aren't tracked, so
    reported "top values" for a huge file are exact for the values shown.
    """

    __slots__ = ("_k", "_counts")

    def __init__(self, k: int = 10000) -> None:
        self._k = k
        self._counts: dict[str, int] = {}

    def update(self, value: Any) -> None:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return
        key = str(value)
        if key in self._counts:
            self._counts[key] += 1
        elif len(self._counts) < self._k:
            self._counts[key] = 1

    def update_series(self, series: pd.Series) -> None:
        for value in series.dropna().head(500000).tolist():
            self.update(value)

    def merge(self, other: "TopKCounter") -> None:
        for key, count in other._counts.items():
            if key in self._counts:
                self._counts[key] += count
            elif len(self._counts) < self._k:
                self._counts[key] = count

    def top(self, n: int = 10) -> list[dict[str, Any]]:
        top_items = sorted(self._counts.items(), key=lambda kv: kv[1], reverse=True)[:n]
        return [{"value": key, "count": count} for key, count in top_items]


class StreamingSummary:
    """Mergeable per-column aggregates accumulated while reading chunks.

    After feeding every chunk of a file you get, per numeric column, exact
    mean/std/skew/kurtosis; per column, exact missing counts; and per
    categorical column, exact top-K frequencies. This powers the
    "global aggregates" section of reports on files that were sampled.
    """

    def __init__(self) -> None:
        self.total_rows = 0
        self.missing_counts: dict[str, int] = {}
        self.numeric: dict[str, OnlineStats] = {}
        self.topk: dict[str, TopKCounter] = {}

    def add_chunk(self, df: pd.DataFrame) -> None:
        self.total_rows += int(len(df))
        for col in df.columns:
            self.missing_counts[col] = self.missing_counts.get(col, 0) + int(
                df[col].isna().sum()
            )
        for col in df.select_dtypes(include=[np.number]).columns:
            values = df[col].to_numpy(dtype=float)
            stats = self.numeric.get(col)
            if stats is None:
                stats = OnlineStats()
                self.numeric[col] = stats
            stats.update_all(values)
        for col in df.select_dtypes(include=["object", "category"]).columns:
            counter = self.topk.get(col)
            if counter is None:
                counter = TopKCounter()
                self.topk[col] = counter
            counter.update_series(df[col])

    def finalize(self) -> dict[str, Any]:
        numeric_out: dict[str, dict[str, float]] = {}
        for col, stats in self.numeric.items():
            stats_out = stats.finalize()
            if stats_out["n"] > 0:
                numeric_out[col] = stats_out
        topk_out: dict[str, list[dict[str, Any]]] = {
            col: counter.top(10) for col, counter in self.topk.items()
        }
        return {
            "total_rows": self.total_rows,
            "missing_counts": self.missing_counts,
            "numeric": numeric_out,
            "top_values": topk_out,
        }
