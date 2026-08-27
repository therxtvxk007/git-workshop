"""A temporal evidence graph.

The graph exists to answer one question exactly: *what did we know about this
entity, and when did we know it?* Every edge therefore carries the instant it
became knowable, and every query is evaluated as of a timestamp. There is no
"current state" view, because a current-state view is precisely the structure
that leaks -- it lets a forecast for January read an edge that only existed in
March, and nothing in the data type stops it.

Nodes are entities and event clusters; edges are participation, co-occurrence
and succession. Mentions are not nodes. They are the *justification* attached
to edges, which keeps the graph small enough to traverse and keeps provenance
attached to the thing being traversed rather than to a parallel structure that
can drift out of sync.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.entities.dedupe import EventCluster
from pramaanx.entities.resolve import EntityIndex
from pramaanx.hashing import stable_id
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel, UtcDatetime

log = get_logger(__name__)


class NodeKind(StrEnum):
    ENTITY = "entity"
    EVENT = "event"


class EdgeRelation(StrEnum):
    """The edge vocabulary, kept deliberately small.

    Every relation here is derivable from the cluster set by a rule that can be
    stated in one sentence. Anything requiring inference -- causation,
    intent, alliance -- is a modelling claim and belongs to a generator, where
    it can be ablated and scored, not to the substrate every generator reads.
    """

    #: entity -> event. The entity appears in the subject position.
    ACTED_IN = "acted_in"
    #: entity -> event. The entity appears in the object position.
    TARGETED_IN = "targeted_in"
    #: event -> entity. The event is placed at this location.
    LOCATED_AT = "located_at"
    #: entity <-> entity. Both appeared in the same event cluster.
    CO_OCCURRED = "co_occurred"
    #: event -> event. Same actors and place, strictly later window.
    PRECEDED_BY = "preceded_by"


class GraphNode(PramaanModel):
    node_id: str
    kind: NodeKind
    label: str
    #: When this node first became knowable. Never the event time: a node the
    #: corpus only learns about in March does not exist in a January view even
    #: if it describes a January event.
    first_observed_at: UtcDatetime
    attributes: dict[str, str] = Field(default_factory=dict)


class GraphEdge(PramaanModel):
    edge_id: str
    source_id: str
    target_id: str
    relation: EdgeRelation
    #: Availability of the earliest mention that justifies this edge.
    observed_at: UtcDatetime
    #: Independent-story count behind the edge, carried from the cluster so
    #: that traversal can weight by evidence rather than by edge count.
    effective_support: int = Field(default=1, ge=0)
    contested: bool = False
    cluster_ids: list[str] = Field(default_factory=list)

    @property
    def weight(self) -> float:
        """Evidence weight, saturating rather than growing without bound.

        The tenth independent source changes far less than the second does, and
        a linear weight lets one heavily-covered event dominate a traversal
        that should have been about structure.
        """
        base = 1.0 - (1.0 / (1.0 + float(self.effective_support)))
        return base * (0.5 if self.contested else 1.0)

    @staticmethod
    def build_id(source_id: str, target_id: str, relation: EdgeRelation) -> str:
        return stable_id("edg", source_id, target_id, relation.value)


class EvidenceGraph(PramaanModel):
    """Nodes and edges, plus the cutoff they were built under.

    ``cutoff_at`` is stored so that a graph can never be silently reused for a
    later fold. :meth:`as_of` refuses to look past it.
    """

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    cutoff_at: UtcDatetime

    @model_validator(mode="after")
    def _check_closure(self) -> EvidenceGraph:
        known = {node.node_id for node in self.nodes}
        dangling = {
            endpoint
            for edge in self.edges
            for endpoint in (edge.source_id, edge.target_id)
            if endpoint not in known
        }
        if dangling:
            raise ValueError(f"edges reference unknown nodes: {sorted(dangling)[:5]}")
        late = [edge.edge_id for edge in self.edges if edge.observed_at > self.cutoff_at]
        if late:
            raise ValueError(f"edges observed after the cutoff: {late[:5]}")
        return self

    def node_map(self) -> dict[str, GraphNode]:
        return {node.node_id: node for node in self.nodes}

    def as_of(self, moment: datetime) -> EvidenceGraph:
        """The graph as it stood at ``moment``.

        Refuses a moment after the build cutoff instead of returning the whole
        graph, because "give me everything" and "give me everything up to a
        time I got wrong" must not produce the same answer.
        """
        if moment > self.cutoff_at:
            raise ValueError(
                f"as_of({moment.isoformat()}) exceeds the graph cutoff "
                f"{self.cutoff_at.isoformat()}; build a later graph instead"
            )
        nodes = [node for node in self.nodes if node.first_observed_at <= moment]
        known = {node.node_id for node in nodes}
        edges = [
            edge
            for edge in self.edges
            if edge.observed_at <= moment and edge.source_id in known and edge.target_id in known
        ]
        return EvidenceGraph(nodes=nodes, edges=edges, cutoff_at=moment)

    def incident(self, node_id: str) -> list[GraphEdge]:
        return [
            edge for edge in self.edges if node_id in (edge.source_id, edge.target_id)
        ]

    def neighbours(
        self, node_id: str, *, relations: Iterable[EdgeRelation] | None = None
    ) -> list[str]:
        allowed = set(relations) if relations is not None else None
        found = set()
        for edge in self.incident(node_id):
            if allowed is not None and edge.relation not in allowed:
                continue
            found.add(edge.target_id if edge.source_id == node_id else edge.source_id)
        found.discard(node_id)
        return sorted(found)

    def degree(self, node_id: str) -> int:
        return len(self.incident(node_id))

    def events_for(self, entity_id: str) -> list[str]:
        """Event nodes this entity participated in, in any role."""
        participation = {EdgeRelation.ACTED_IN, EdgeRelation.TARGETED_IN}
        located = EdgeRelation.LOCATED_AT
        found = set()
        for edge in self.incident(entity_id):
            if edge.relation in participation and edge.source_id == entity_id:
                found.add(edge.target_id)
            elif edge.relation is located and edge.target_id == entity_id:
                found.add(edge.source_id)
        return sorted(found)


def build_graph(
    clusters: Sequence[EventCluster],
    index: EntityIndex,
    *,
    cutoff_at: datetime,
    succession_window_days: float = 365.0,
) -> EvidenceGraph:
    """Assemble the evidence graph from resolved clusters.

    Clusters observed after ``cutoff_at`` are dropped rather than rejected, for
    the same reason the resolver drops late mentions: callers legitimately hand
    over a full corpus and expect the cutoff to be the filter.
    """
    available = sorted(
        (cluster for cluster in clusters if cluster.first_observed_at <= cutoff_at),
        key=lambda item: item.cluster_id,
    )
    entities = index.by_id()

    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    def add_node(node: GraphNode) -> None:
        existing = nodes.get(node.node_id)
        if existing is None or node.first_observed_at < existing.first_observed_at:
            nodes[node.node_id] = node

    def add_edge(
        source_id: str,
        target_id: str,
        relation: EdgeRelation,
        cluster: EventCluster,
    ) -> None:
        edge_id = GraphEdge.build_id(source_id, target_id, relation)
        existing = edges.get(edge_id)
        if existing is None:
            edges[edge_id] = GraphEdge(
                edge_id=edge_id,
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                observed_at=cluster.first_observed_at,
                effective_support=cluster.effective_support,
                contested=cluster.contested,
                cluster_ids=[cluster.cluster_id],
            )
            return
        merged_ids = sorted({*existing.cluster_ids, cluster.cluster_id})
        edges[edge_id] = existing.model_copy(
            update={
                # The edge became knowable at its *earliest* justification.
                "observed_at": min(existing.observed_at, cluster.first_observed_at),
                "effective_support": existing.effective_support + cluster.effective_support,
                "contested": existing.contested or cluster.contested,
                "cluster_ids": merged_ids,
            }
        )

    for cluster in available:
        add_node(
            GraphNode(
                node_id=cluster.cluster_id,
                kind=NodeKind.EVENT,
                label=cluster.event_type,
                first_observed_at=cluster.first_observed_at,
                attributes={
                    "event_type": cluster.event_type,
                    "window_start": cluster.window_start.isoformat(),
                    "window_end": cluster.window_end.isoformat(),
                },
            )
        )
        participants = [*cluster.actor_ids, *cluster.target_ids]
        if cluster.location_entity_id:
            participants.append(cluster.location_entity_id)
        for entity_id in participants:
            entity = entities.get(entity_id)
            if entity is None:
                continue
            add_node(
                GraphNode(
                    node_id=entity_id,
                    kind=NodeKind.ENTITY,
                    label=entity.canonical_name,
                    first_observed_at=entity.first_observed_at,
                    attributes={"kind": entity.kind.value},
                )
            )

        for actor_id in cluster.actor_ids:
            if actor_id in nodes:
                add_edge(actor_id, cluster.cluster_id, EdgeRelation.ACTED_IN, cluster)
        for target_id in cluster.target_ids:
            if target_id in nodes:
                add_edge(target_id, cluster.cluster_id, EdgeRelation.TARGETED_IN, cluster)
        if cluster.location_entity_id and cluster.location_entity_id in nodes:
            add_edge(
                cluster.cluster_id,
                cluster.location_entity_id,
                EdgeRelation.LOCATED_AT,
                cluster,
            )

        present = sorted({*cluster.actor_ids, *cluster.target_ids} & set(nodes))
        for position, left in enumerate(present):
            for right in present[position + 1 :]:
                add_edge(left, right, EdgeRelation.CO_OCCURRED, cluster)

    _add_succession_edges(available, nodes, edges, window_days=succession_window_days)

    graph = EvidenceGraph(
        nodes=sorted(nodes.values(), key=lambda item: item.node_id),
        edges=sorted(edges.values(), key=lambda item: item.edge_id),
        cutoff_at=cutoff_at,
    )
    log.info(
        "graph.built",
        nodes=len(graph.nodes),
        edges=len(graph.edges),
        cutoff=cutoff_at.isoformat(),
    )
    return graph


def _add_succession_edges(
    clusters: Sequence[EventCluster],
    nodes: dict[str, GraphNode],
    edges: dict[str, GraphEdge],
    *,
    window_days: float,
) -> None:
    """Link consecutive events sharing actors and place.

    Succession is what makes the graph temporal rather than merely dated: it is
    the structure a hazard-style generator walks to ask "how long since the last
    one, and how regular is the spacing?".

    The edge points from the later event to the earlier one, and is only added
    when the later event was *observable* after the earlier one. Two events can
    be ordered by event time yet reach the corpus in the opposite order, and an
    edge asserting succession on the strength of event time alone would be a
    fact the corpus did not have at the time.
    """
    by_series: dict[tuple[str, tuple[str, ...], str], list[EventCluster]] = defaultdict(list)
    for cluster in clusters:
        key = (
            cluster.event_type,
            tuple(sorted(cluster.actor_ids)),
            cluster.location_entity_id or "",
        )
        by_series[key].append(cluster)

    horizon = window_days * 86400.0
    for series in by_series.values():
        if len(series) < 2:
            continue
        ordered = sorted(series, key=lambda item: (item.window_start, item.cluster_id))
        for position, later in enumerate(ordered[1:], start=1):
            earlier = ordered[position - 1]
            gap = (later.window_start - earlier.window_start).total_seconds()
            if gap <= 0 or gap > horizon:
                continue
            if later.first_observed_at < earlier.first_observed_at:
                continue
            if later.cluster_id not in nodes or earlier.cluster_id not in nodes:
                continue
            edge_id = GraphEdge.build_id(
                later.cluster_id, earlier.cluster_id, EdgeRelation.PRECEDED_BY
            )
            edges[edge_id] = GraphEdge(
                edge_id=edge_id,
                source_id=later.cluster_id,
                target_id=earlier.cluster_id,
                relation=EdgeRelation.PRECEDED_BY,
                # Knowable only once both ends are.
                observed_at=max(later.first_observed_at, earlier.first_observed_at),
                effective_support=min(later.effective_support, earlier.effective_support),
                contested=later.contested or earlier.contested,
                cluster_ids=sorted({later.cluster_id, earlier.cluster_id}),
            )
