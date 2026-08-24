"""ITHI: three types of historical information.

The observation ITHI formalises is that "history" is not one thing. Retrieving
the most recent events, the same calendar phase in previous cycles, and the most
semantically similar past episodes are three different queries, and a retriever
that collapses them into "most similar recent documents" answers none of them
well.

Each type is retrieved separately and kept separately. Merging them into a
single relevance score here would discard exactly the distinction the hazard
model needs in order to learn that, say, flood risk is driven by periodic
history while cyber risk is driven by sequential history.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from ..types import Target
from .graph import Edge, MemoryGraph


@dataclass
class HistorySet:
    sequential: list[Edge] = field(default_factory=list)
    periodic: list[Edge] = field(default_factory=list)
    relevant: list[Edge] = field(default_factory=list)

    def all_edges(self) -> list[Edge]:
        seen: set[tuple] = set()
        out: list[Edge] = []
        for e in self.sequential + self.periodic + self.relevant:
            k = (e.doc_id, e.subject, e.relation, e.object)
            if k not in seen:
                seen.add(k)
                out.append(e)
        return out

    def features(self) -> dict[str, float]:
        return {
            "ithi_n_sequential": float(len(self.sequential)),
            "ithi_n_periodic": float(len(self.periodic)),
            "ithi_n_relevant": float(len(self.relevant)),
            "ithi_seq_confidence": _mean_conf(self.sequential),
            "ithi_per_confidence": _mean_conf(self.periodic),
            "ithi_rel_confidence": _mean_conf(self.relevant),
            "ithi_overlap": _overlap(self.sequential, self.relevant),
        }


def _mean_conf(edges: Sequence[Edge]) -> float:
    return float(np.mean([e.confidence for e in edges])) if edges else 0.0


def _overlap(a: Sequence[Edge], b: Sequence[Edge]) -> float:
    """How much sequential and relevant history agree. High overlap means the
    two retrievers found the same thing and the evidence is narrower than the
    document count suggests."""
    if not a or not b:
        return 0.0
    sa = {e.doc_id for e in a}
    sb = {e.doc_id for e in b}
    return len(sa & sb) / len(sa | sb)


@dataclass
class IthiRetriever:
    graph: MemoryGraph
    max_per_type: int = 8
    sequential_days: int = 30
    periodic_cycles: tuple[int, ...] = (7, 365)     # weekly and annual phase
    periodic_tolerance_days: int = 3

    def retrieve(
        self,
        target: Target,
        as_of: datetime,
        *,
        similar_targets: Sequence[tuple[str, float]] = (),
    ) -> HistorySet:
        seq = self._sequential(target, as_of)
        per = self._periodic(target, as_of)
        rel = self._relevant(similar_targets, as_of)
        return HistorySet(sequential=seq, periodic=per, relevant=rel)

    def _sequential(self, target: Target, as_of: datetime) -> list[Edge]:
        edges = self.graph.target_history(target, as_of, window_days=self.sequential_days)
        return sorted(edges, key=lambda e: -e.timestamp.timestamp())[: self.max_per_type]

    def _periodic(self, target: Target, as_of: datetime) -> list[Edge]:
        """Same phase of each cycle, in previous periods.

        Not 'the same date last year' -- a tolerance window, because a monsoon
        does not arrive on an anniversary. The tolerance is what turns this from
        a trivia lookup into a seasonal prior.
        """
        out: list[Edge] = []
        history = self.graph.target_history(target, as_of)
        for cycle in self.periodic_cycles:
            for k in range(1, 6):
                centre = as_of - timedelta(days=cycle * k)
                if centre < as_of - timedelta(days=365 * 5):
                    break
                lo = centre - timedelta(days=self.periodic_tolerance_days)
                hi = centre + timedelta(days=self.periodic_tolerance_days)
                out.extend(e for e in history if lo <= e.timestamp <= hi)
        seen: set[str] = set()
        uniq = []
        for e in out:
            if e.doc_id not in seen:
                seen.add(e.doc_id)
                uniq.append(e)
        return uniq[: self.max_per_type]

    def _relevant(self, similar_targets: Sequence[tuple[str, float]],
                  as_of: datetime) -> list[Edge]:
        """History of *other* targets judged similar. This is how a system
        forecasts an event type at a location that has never seen one."""
        out: list[Edge] = []
        for key, weight in similar_targets[: self.max_per_type]:
            edges = self.graph.target_history(key, as_of, window_days=180)
            for e in edges[-2:]:
                e.confidence = min(1.0, e.confidence * float(weight))
                out.append(e)
        return out[: self.max_per_type]
