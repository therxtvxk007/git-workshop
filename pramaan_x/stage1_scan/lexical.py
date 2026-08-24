"""Learned lexical indicators.

The tempting version of this module is a hand-written list of "attack clue"
phrases. That is the approach the design brief rules out, and for a good
reason: a hand-picked lexicon encodes the analyst's existing hypotheses, so the
system can only ever rediscover what someone already suspected, and its recall
on a novel precursor is zero by construction.

Instead the lexicon is *estimated* from labelled training windows using the
log-odds ratio with an informative Dirichlet prior (Monroe, Colaresi & Quinn,
2008), which is the standard estimator for "which words distinguish these two
corpora" and is far better behaved than raw frequency ratios on rare terms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .bm25 import tokenize


@dataclass
class LexicalIndicators:
    """Signed z-scores per term. Positive = distinguishes the precursor class."""

    scores: dict[str, float] = field(default_factory=dict)
    per_event_type: dict[str, dict[str, float]] = field(default_factory=dict)
    min_count: int = 3
    prior_strength: float = 1.0

    def fit(
        self,
        texts: Sequence[str],
        labels: Sequence[int],
        *,
        event_types: Sequence[str] | None = None,
        top_k: int = 400,
    ) -> LexicalIndicators:
        self.scores = self._log_odds(texts, labels, top_k)
        if event_types is not None:
            for et in sorted(set(event_types)):
                mask = [i for i, e in enumerate(event_types) if e == et]
                if len(mask) < 20 or sum(labels[i] for i in mask) < 5:
                    continue
                self.per_event_type[et] = self._log_odds(
                    [texts[i] for i in mask], [labels[i] for i in mask], top_k
                )
        return self

    def _log_odds(self, texts, labels, top_k: int) -> dict[str, float]:
        pos: dict[str, int] = {}
        neg: dict[str, int] = {}
        for text, y in zip(texts, labels, strict=True):
            bucket = pos if y else neg
            for t in set(tokenize(text)):
                bucket[t] = bucket.get(t, 0) + 1

        vocab = {t for t, c in pos.items() if c >= self.min_count}
        vocab |= {t for t, c in neg.items() if c >= self.min_count}
        if not vocab:
            return {}

        # Background counts form the Dirichlet prior, so a term seen three times
        # in the positive class and never elsewhere is shrunk toward zero rather
        # than dominating the lexicon.
        total_pos = sum(pos.get(t, 0) for t in vocab)
        total_neg = sum(neg.get(t, 0) for t in vocab)
        total_all = total_pos + total_neg
        out: dict[str, float] = {}
        for t in vocab:
            yi_p, yi_n = pos.get(t, 0), neg.get(t, 0)
            alpha = self.prior_strength * (yi_p + yi_n) / max(total_all, 1) * 1000.0
            alpha = max(alpha, 0.01)
            lp = np.log((yi_p + alpha) / (total_pos + 1000.0 - yi_p - alpha))
            ln = np.log((yi_n + alpha) / (total_neg + 1000.0 - yi_n - alpha))
            delta = lp - ln
            var = 1.0 / (yi_p + alpha) + 1.0 / (yi_n + alpha)
            out[t] = float(delta / np.sqrt(var))

        ranked = sorted(out.items(), key=lambda kv: -abs(kv[1]))[:top_k]
        return dict(ranked)

    # ------------------------------------------------------------ score ---

    def score(self, text: str, event_type: str | None = None) -> float:
        table = self.per_event_type.get(event_type, self.scores) if event_type else self.scores
        if not table:
            return 0.0
        toks = tokenize(text)
        if not toks:
            return 0.0
        hits = [table[t] for t in set(toks) if t in table]
        if not hits:
            return 0.0
        # Sum of positive evidence, damped by length: a long document should not
        # accumulate an unbounded score just by containing more words.
        pos = sum(h for h in hits if h > 0)
        return float(pos / np.sqrt(len(toks)))

    def score_all(self, texts: Sequence[str], event_type: str | None = None) -> np.ndarray:
        return np.array([self.score(t, event_type) for t in texts], dtype=np.float64)

    def top_terms(self, n: int = 20, event_type: str | None = None) -> list[tuple[str, float]]:
        table = self.per_event_type.get(event_type, self.scores) if event_type else self.scores
        return sorted(table.items(), key=lambda kv: -kv[1])[:n]

    def query_for(self, event_type: str, n: int = 25) -> str:
        """A BM25 query built from the learned lexicon, not from an analyst's
        guess about what a precursor looks like."""
        return " ".join(t for t, _ in self.top_terms(n, event_type))
