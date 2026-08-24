"""Temporal knowledge graph.

Edges are timestamped assertions, never overwritten. That is the difference
between a temporal KG and a "knowledge graph" that is really a snapshot: the
question this system asks is "what did the graph look like on 3 March, and what
usually follows that shape", which a snapshot cannot answer at all.

`MemoryGraph` is exact and embedded. Kùzu is the local analytical backend for
when the edge list stops fitting comfortably in memory; Neo4j is the interactive
backend for analysts who need to explore provenance by hand.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from ..types import EventTuple, Target


@dataclass(slots=True)
class Edge:
    subject: str
    relation: str
    object: str
    event_type: str
    timestamp: datetime
    location: str
    doc_id: str
    source_id: str
    confidence: float = 1.0
    conflict: bool = False

    def key(self) -> tuple[str, str, str]:
        return (self.subject, self.relation, self.object)


class TemporalGraph(Protocol):
    name: str

    def add_edges(self, edges: Iterable[Edge]) -> None: ...
    def edges_in(self, start: datetime, end: datetime) -> list[Edge]: ...
    def neighbours(self, node: str, as_of: datetime, window_days: int) -> list[Edge]: ...


class MemoryGraph:
    """Edge list with a sorted time index and node adjacency.

    Every read takes an `as_of`. There is no method that returns "the current
    graph", because at forecast time there is no such thing -- only the graph as
    it stood before the origin.
    """

    name = "memory"

    def __init__(self) -> None:
        self._edges: list[Edge] = []
        self._times: list[datetime] = []
        self._by_node: dict[str, list[int]] = defaultdict(list)
        self._by_target: dict[str, list[int]] = defaultdict(list)
        self._sorted = True

    def add_edges(self, edges: Iterable[Edge]) -> None:
        for e in edges:
            self._edges.append(e)
            self._sorted = False
        self._reindex()

    def _reindex(self) -> None:
        if self._sorted:
            return
        order = sorted(range(len(self._edges)), key=lambda i: self._edges[i].timestamp)
        self._edges = [self._edges[i] for i in order]
        self._times = [e.timestamp for e in self._edges]
        self._by_node.clear()
        self._by_target.clear()
        for i, e in enumerate(self._edges):
            self._by_node[e.subject].append(i)
            if e.object != e.subject:
                self._by_node[e.object].append(i)
            self._by_target[f"{e.location}|{e.event_type}"].append(i)
        self._sorted = True

    # ------------------------------------------------------------ reads ---

    def _slice(self, start: datetime, end: datetime) -> range:
        lo = bisect.bisect_left(self._times, start)
        hi = bisect.bisect_left(self._times, end)
        return range(lo, hi)

    def edges_in(self, start: datetime, end: datetime) -> list[Edge]:
        self._reindex()
        return [self._edges[i] for i in self._slice(start, end)]

    def neighbours(self, node: str, as_of: datetime, window_days: int = 90) -> list[Edge]:
        self._reindex()
        start = as_of - timedelta(days=window_days)
        return [
            self._edges[i] for i in self._by_node.get(node, ())
            if start <= self._edges[i].timestamp < as_of
        ]

    def target_history(self, target: Target | str, as_of: datetime,
                       window_days: int | None = None) -> list[Edge]:
        self._reindex()
        key = target if isinstance(target, str) else target.key()
        idx = self._by_target.get(key, ())
        start = as_of - timedelta(days=window_days) if window_days else None
        return [
            self._edges[i] for i in idx
            if self._edges[i].timestamp < as_of
            and (start is None or self._edges[i].timestamp >= start)
        ]

    def counts_by_day(self, target: Target | str, start: datetime, end: datetime) -> list[int]:
        key = target if isinstance(target, str) else target.key()
        n_days = max((end - start).days, 0)
        out = [0] * n_days
        for e in self.target_history(key, end):
            if e.timestamp < start:
                continue
            d = (e.timestamp - start).days
            if 0 <= d < n_days:
                out[d] += 1
        return out

    def structural_continuations(
        self, as_of: datetime, *, window_days: int = 30, min_support: int = 2
    ) -> list[tuple[Target, float, list[str]]]:
        """Targets whose recent edge pattern historically preceded an event.

        This is the temporal-KG branch of candidate generation: it proposes
        continuations of structure the graph has already seen, which is exactly
        the class of hypothesis an LLM sampler is worst at because it requires
        counting, not plausibility.
        """
        self._reindex()
        recent = self.edges_in(as_of - timedelta(days=window_days), as_of)
        by_target: dict[str, list[Edge]] = defaultdict(list)
        for e in recent:
            by_target[f"{e.location}|{e.event_type}"].append(e)

        out: list[tuple[Target, float, list[str]]] = []
        for key, edges in by_target.items():
            if len(edges) < min_support:
                continue
            loc, et = key.split("|", 1)
            # Support x confidence x relation diversity. A target with four
            # edges all carrying the same relation from the same document
            # cluster is weaker evidence than four distinct relations.
            rel_div = len({e.relation for e in edges}) / len(edges)
            src_div = len({e.source_id for e in edges}) / len(edges)
            mean_conf = sum(e.confidence for e in edges) / len(edges)
            score = mean_conf * (0.4 + 0.3 * rel_div + 0.3 * src_div) * min(len(edges) / 5.0, 1.5)
            out.append((Target(location=loc, event_type=et), float(score),
                        [e.doc_id for e in edges]))
        return sorted(out, key=lambda t: -t[1])

    def path(self, source: str, target: str, as_of: datetime,
             max_hops: int = 3, window_days: int = 180) -> list[Edge] | None:
        """Shortest provenance path. Used in the analyst view to answer 'why is
        this connected to that', which a similarity score cannot."""
        self._reindex()
        start = as_of - timedelta(days=window_days)
        frontier: list[tuple[str, list[Edge]]] = [(source, [])]
        seen = {source}
        for _ in range(max_hops):
            nxt: list[tuple[str, list[Edge]]] = []
            for node, path in frontier:
                for i in self._by_node.get(node, ()):
                    e = self._edges[i]
                    if not (start <= e.timestamp < as_of):
                        continue
                    other = e.object if e.subject == node else e.subject
                    if other == target:
                        return [*path, e]
                    if other not in seen:
                        seen.add(other)
                        nxt.append((other, [*path, e]))
            frontier = nxt
            if not frontier:
                break
        return None

    @property
    def n_edges(self) -> int:
        return len(self._edges)

    @property
    def n_nodes(self) -> int:
        self._reindex()
        return len(self._by_node)


def edges_from_tuples(tuples: Sequence[EventTuple], doc_times: dict[str, datetime]) -> list[Edge]:
    """Convert extractions to edges.

    Tuples failing the publication-cutoff check are dropped here rather than
    filtered later. An invalid tuple that reaches the graph is permanent: every
    later read of that graph is contaminated, and no downstream filter can undo
    it because the edge no longer carries the reason it was invalid.
    """
    out: list[Edge] = []
    for t in tuples:
        if not t.publication_cutoff_valid:
            continue
        ts = t.event_time or doc_times.get(t.doc_id)
        if ts is None:
            continue
        out.append(Edge(
            subject=t.subject, relation=t.relation, object=t.object,
            event_type=t.event_type, timestamp=ts, location=t.location,
            doc_id=t.doc_id, source_id=t.source_id,
            confidence=t.extractor_confidence, conflict=t.conflict,
        ))
    return out


class KuzuGraph:
    """Embedded analytical backend. Same reads, Cypher underneath."""

    name = "kuzu"

    def __init__(self, path: str = "artifacts/graph.kuzu") -> None:
        self.path = path
        self._conn = None

    def _connect(self):
        if self._conn is None:
            import kuzu

            db = kuzu.Database(self.path)
            self._conn = kuzu.Connection(db)
            self._conn.execute(
                "CREATE NODE TABLE IF NOT EXISTS Entity(name STRING, PRIMARY KEY(name))"
            )
            self._conn.execute(
                "CREATE REL TABLE IF NOT EXISTS Asserted(FROM Entity TO Entity, "
                "relation STRING, event_type STRING, ts TIMESTAMP, location STRING, "
                "doc_id STRING, source_id STRING, confidence DOUBLE)"
            )
        return self._conn

    def add_edges(self, edges: Iterable[Edge]) -> None:
        conn = self._connect()
        for e in edges:
            for n in (e.subject, e.object):
                conn.execute("MERGE (:Entity {name: $n})", {"n": n})
            conn.execute(
                "MATCH (a:Entity {name:$s}), (b:Entity {name:$o}) "
                "CREATE (a)-[:Asserted {relation:$r, event_type:$et, ts:$ts, "
                "location:$loc, doc_id:$d, source_id:$src, confidence:$c}]->(b)",
                {"s": e.subject, "o": e.object, "r": e.relation, "et": e.event_type,
                 "ts": e.timestamp, "loc": e.location, "d": e.doc_id,
                 "src": e.source_id, "c": e.confidence},
            )

    def edges_in(self, start: datetime, end: datetime) -> list[Edge]:
        conn = self._connect()
        res = conn.execute(
            "MATCH (a:Entity)-[r:Asserted]->(b:Entity) WHERE r.ts >= $s AND r.ts < $e "
            "RETURN a.name, r.relation, b.name, r.event_type, r.ts, r.location, "
            "r.doc_id, r.source_id, r.confidence",
            {"s": start, "e": end},
        )
        return [Edge(*row) for row in res]

    def neighbours(self, node: str, as_of: datetime, window_days: int = 90) -> list[Edge]:
        conn = self._connect()
        start = as_of - timedelta(days=window_days)
        res = conn.execute(
            "MATCH (a:Entity)-[r:Asserted]-(b:Entity) WHERE a.name = $n "
            "AND r.ts >= $s AND r.ts < $e "
            "RETURN a.name, r.relation, b.name, r.event_type, r.ts, r.location, "
            "r.doc_id, r.source_id, r.confidence",
            {"n": node, "s": start, "e": as_of},
        )
        return [Edge(*row) for row in res]


def build_graph(backend: str, **kwargs) -> TemporalGraph:
    if backend == "memory":
        return MemoryGraph()
    if backend == "kuzu":
        return KuzuGraph(**kwargs)
    if backend == "neo4j":
        raise NotImplementedError(
            "the Neo4j backend is a deployment concern: point NEO4J_URI at the "
            "instance and use the same Cypher as KuzuGraph"
        )
    raise ValueError(f"unknown graph backend {backend!r}")
