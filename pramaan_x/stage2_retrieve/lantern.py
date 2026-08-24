"""LANTERN-style evidence selection: long-window strength against short-window
novelty, compacted by Pareto-greedy selection, plus a structure-aware analogy.

The idea being implemented is that a stable long-run pattern and a sudden recent
break are *different* kinds of evidence and must be scored separately. Averaging
them into one recency weight -- which is what a plain decay does -- makes a
target with twenty years of quiet history and a violent last fortnight
indistinguishable from one with a steady low hum.

The selection step matters as much as the scoring. Given a budget of evidence
slots, taking the top-k by score fills them with near-duplicates of the single
strongest signal. Pareto-greedy selection instead keeps items that are not
dominated on (relevance, novelty, source independence) jointly, so the budget
buys coverage instead of repetition.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from ..types import Target
from .graph import Edge, MemoryGraph


@dataclass
class LanternScores:
    long_strength: float = 0.0
    short_novelty: float = 0.0
    analogy: float = 0.0
    selected: list[Edge] = field(default_factory=list)
    dominated_dropped: int = 0

    def features(self) -> dict[str, float]:
        return {
            "lantern_long_strength": self.long_strength,
            "lantern_short_novelty": self.short_novelty,
            "lantern_analogy": self.analogy,
            "lantern_evidence_kept": float(len(self.selected)),
            "lantern_evidence_dropped": float(self.dominated_dropped),
        }


@dataclass
class Lantern:
    graph: MemoryGraph
    long_days: int = 180
    short_days: int = 14
    budget: int = 12

    # ------------------------------------------------------- scoring ---

    def long_window_strength(self, target: Target, as_of: datetime) -> float:
        """Stability of the long-run interaction pattern.

        Measured as mean daily rate scaled by *regularity* (inverse coefficient
        of variation). A target that produces one edge every week for six months
        scores higher than one that produced the same total in a single burst --
        the first is a pattern, the second is an incident.
        """
        start = as_of - timedelta(days=self.long_days)
        counts = np.asarray(self.graph.counts_by_day(target, start, as_of), dtype=float)
        if counts.size == 0 or counts.sum() == 0:
            return 0.0
        rate = counts.mean()
        cv = counts.std() / max(rate, 1e-9)
        regularity = 1.0 / (1.0 + cv)
        return float(np.log1p(counts.sum()) * regularity)

    def short_window_novelty(self, target: Target, as_of: datetime) -> float:
        """How far the recent window departs from the long-run baseline.

        A rate ratio in log space, so a quiet target going from 0.1 to 1.0
        edges/day and a busy one going from 5 to 50 register the same novelty --
        which is correct, because both are a tenfold shift.
        """
        long_start = as_of - timedelta(days=self.long_days)
        short_start = as_of - timedelta(days=self.short_days)
        long_counts = np.asarray(self.graph.counts_by_day(target, long_start, short_start), float)
        short_counts = np.asarray(self.graph.counts_by_day(target, short_start, as_of), float)
        if short_counts.size == 0:
            return 0.0
        base = long_counts.mean() if long_counts.size else 0.0
        recent = short_counts.mean()
        # Additive smoothing keeps a first-ever edge from producing an infinite
        # ratio, which would let one document dominate the whole score.
        return float(np.log((recent + 0.05) / (base + 0.05)))

    def analogy(self, target: Target, as_of: datetime,
                candidates: Sequence[Target], *, top_k: int = 5) -> tuple[float, list[str]]:
        """Structure-aware analogy: which other targets have recently looked
        like this one, and how strongly.

        Similarity is over the *shape* of recent activity -- relation mix,
        source mix, burstiness -- not over text. Two locations reported in
        different languages by different outlets can still be structurally
        analogous, and text similarity would miss it entirely.
        """
        raw = {target.key(): self._signature(target, as_of, normalise=False)}
        for other in candidates:
            if other.key() == target.key():
                continue
            sig = self._signature(other, as_of, normalise=False)
            if sig is not None:
                raw[other.key()] = sig
        if raw.get(target.key()) is None or len(raw) < 2:
            return 0.0, []

        # Standardise each component across the candidate pool before comparing.
        # Without this the raw signature is dominated by log-volume, every pair
        # points in nearly the same direction, and cosine similarity returns
        # ~1.0 for every target -- a number that looks like a strong analogy and
        # carries no information at all.
        keys = [k for k, v in raw.items() if v is not None]
        M = np.vstack([raw[k] for k in keys])
        M = (M - M.mean(axis=0)) / np.maximum(M.std(axis=0), 1e-9)
        norms = np.maximum(np.linalg.norm(M, axis=1, keepdims=True), 1e-9)
        M = M / norms
        me_idx = keys.index(target.key())
        sims = M @ M[me_idx]
        scored = sorted(
            ((float(sims[i]), keys[i]) for i in range(len(keys)) if i != me_idx),
            reverse=True,
        )
        if not scored:
            return 0.0, []
        top = scored[:top_k]
        return float(np.mean([s for s, _ in top])), [k for _, k in top]

    def _signature(self, target: Target, as_of: datetime,
                   *, normalise: bool = True) -> np.ndarray | None:
        edges = self.graph.target_history(target, as_of, window_days=self.long_days)
        if len(edges) < 2:
            return None
        rels: dict[str, int] = {}
        srcs: dict[str, int] = {}
        for e in edges:
            rels[e.relation] = rels.get(e.relation, 0) + 1
            srcs[e.source_id] = srcs.get(e.source_id, 0) + 1
        counts = np.asarray(
            self.graph.counts_by_day(target, as_of - timedelta(days=self.long_days), as_of),
            dtype=float,
        )
        burstiness = counts.std() / max(counts.mean(), 1e-9) if counts.size else 0.0
        vec = np.array([
            len(rels) / max(len(edges), 1),
            len(srcs) / max(len(edges), 1),
            float(np.log1p(len(edges))),
            burstiness,
            float(np.mean([e.confidence for e in edges])),
        ], dtype=np.float64)
        if not normalise:
            return vec
        n = np.linalg.norm(vec)
        return vec / n if n > 0 else None

    # ---------------------------------------------- evidence selection ---

    def select_evidence(
        self,
        edges: Sequence[Edge],
        as_of: datetime,
        *,
        budget: int | None = None,
    ) -> tuple[list[Edge], int]:
        """Pareto-greedy selection over (relevance, novelty, source spread).

        Greedy because the exact problem is submodular maximisation under a
        cardinality constraint and therefore NP-hard; greedy gives the standard
        (1 - 1/e) guarantee and runs in milliseconds. Pareto because the three
        criteria are not commensurable -- collapsing them into a weighted sum
        would need weights we have no principled way to set here, and the
        learned fusion in stage 2 is the right place for that.
        """
        budget = budget or self.budget
        if not edges:
            return [], 0
        items = list(edges)

        rel = np.array([e.confidence for e in items])
        age = np.array([max((as_of - e.timestamp).days, 0) for e in items], dtype=float)
        nov = 1.0 / (1.0 + age / max(self.short_days, 1))

        # Source spread is the third axis. With only (relevance, novelty) and a
        # corpus where confidences tie, every older edge is dominated by the
        # newest one and the frontier collapses to a single item -- which is a
        # correct Pareto answer to the wrong question, since the point of the
        # budget is coverage.
        src_rank: dict[str, int] = {}
        for e in items:
            src_rank[e.source_id] = src_rank.get(e.source_id, 0) + 1
        spread = np.array([1.0 / src_rank[e.source_id] for e in items])

        keep: list[int] = []
        for i in range(len(items)):
            dominated = any(
                (rel[j] >= rel[i] and nov[j] >= nov[i] and spread[j] >= spread[i]
                 and (rel[j] > rel[i] or nov[j] > nov[i] or spread[j] > spread[i]))
                for j in range(len(items)) if j != i
            )
            if not dominated:
                keep.append(i)
        dropped = len(items) - len(keep)

        # Top up from the dominated set when the frontier is smaller than the
        # budget. A dominated item is worse than something on the frontier; it
        # is not worthless, and an unfilled evidence slot helps nobody.
        if len(keep) < budget:
            rest = sorted((i for i in range(len(items)) if i not in set(keep)),
                          key=lambda i: -(rel[i] + nov[i] + spread[i]))
            keep = keep + rest[: budget - len(keep)]
            dropped = len(items) - len(keep)
        if not keep:
            keep = list(range(len(items)))

        # Greedy fill, penalising sources and relations already represented.
        chosen: list[int] = []
        used_src: set[str] = set()
        used_rel: set[str] = set()
        remaining = set(keep)
        while remaining and len(chosen) < budget:
            best, best_gain = None, -np.inf
            for i in remaining:
                e = items[i]
                novelty_bonus = (0.0 if e.source_id in used_src else 0.5) + \
                                (0.0 if e.relation in used_rel else 0.3)
                gain = rel[i] + nov[i] + novelty_bonus
                if gain > best_gain:
                    best, best_gain = i, gain
            chosen.append(best)
            remaining.discard(best)
            used_src.add(items[best].source_id)
            used_rel.add(items[best].relation)
        return [items[i] for i in chosen], dropped

    # ------------------------------------------------------------ run ---

    def score(self, target: Target, as_of: datetime,
              candidates: Sequence[Target] = ()) -> LanternScores:
        long_s = self.long_window_strength(target, as_of)
        short_n = self.short_window_novelty(target, as_of)
        ana, _ = self.analogy(target, as_of, candidates) if candidates else (0.0, [])
        edges = self.graph.target_history(target, as_of, window_days=self.long_days)
        sel, dropped = self.select_evidence(edges, as_of)
        return LanternScores(long_strength=long_s, short_novelty=short_n,
                             analogy=ana, selected=sel, dominated_dropped=dropped)
