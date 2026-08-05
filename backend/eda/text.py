"""Free-text column analysis.

Long-form text (avg > FREE_TEXT_AVG_WORDS words) is *not* treated as a
categorical variable — a free-text column can have thousands of distinct
values, so "top categories" would be meaningless. Instead we report:

  * length distribution (words per value)
  * vocabulary size (distinct tokens)
  * top unigrams and bigrams (lowercased, stopwords removed)
  * a flag for whether the column is usable as an identifier / join key

All tokenization is deterministic and dependency-free (regex + a small
stopword list). Sentiment analysis is intentionally NOT included: it would
require a model and would violate the "deterministic stats" rule.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pandas as pd

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'_-]{1,}")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
    "this", "that", "with", "from", "for", "are", "was", "were", "is", "be",
    "to", "of", "in", "on", "at", "by", "as", "it", "its", "not", "no", "so",
    "you", "your", "we", "our", "they", "their", "i", "he", "she", "them",
    "have", "has", "had", "do", "does", "did", "will", "would", "can", "could",
    "should", "may", "might", "about", "into", "over", "also", "than", "very",
}

_TOKEN_CAP = 200_000


def _tokens(series: pd.Series) -> Counter:
    counter: Counter = Counter()
    sample = series.astype(str).dropna()
    sample = sample.head(_TOKEN_CAP)
    for text in sample:
        words = [w.lower() for w in _WORD_RE.findall(text)]
        counter.update(w for w in words if w not in _STOPWORDS and len(w) > 1)
    return counter


def text_summary(series: pd.Series) -> dict[str, Any]:
    """Length profile + top words/bigrams for a free-text column."""
    clean = series.astype(str).dropna()
    clean = clean[clean.str.strip() != ""]
    if clean.empty:
        return {}
    word_counts = clean.str.split(r"\s+").str.len()
    vocab = _tokens(clean)
    total_tokens = sum(vocab.values()) or 1

    bigrams: Counter = Counter()
    sample = clean.head(_TOKEN_CAP)
    for text in sample:
        words = [w.lower() for w in _WORD_RE.findall(text) if w.lower() not in _STOPWORDS and len(w) > 1]
        bigrams.update(zip(words, words[1:]))

    def _top(counter: Counter, n: int) -> list[dict[str, Any]]:
        return [
            {"value": str(k), "count": int(v)}
            for k, v in counter.most_common(n)
        ]

    return {
        "n": int(len(clean)),
        "avg_words": round(float(word_counts.mean()), 2),
        "median_words": float(word_counts.median()),
        "max_words": int(word_counts.max()),
        "vocabulary_size": len(vocab),
        "lexical_diversity": round(len(vocab) / total_tokens, 4),
        "top_words": _top(vocab, 10),
        "top_bigrams": _top(bigrams, 8),
        "note": (
            "Treated as free text, not a categorical variable: categories "
            "would be meaningless with this many distinct values."
        ),
    }


def is_join_key(series: pd.Series, unique_ratio: float) -> dict[str, bool]:
    """Heuristic: could this free-text column serve as a join key?"""
    clean = series.astype(str).dropna()
    return {
        "likely_join_key": bool(
            unique_ratio > 0.95
            and len(clean) > 0
            and clean.str.len().mean() > 4
            and clean.str.len().mean() < 60
        ),
    }
