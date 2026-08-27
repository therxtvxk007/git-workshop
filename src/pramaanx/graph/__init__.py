"""The temporal evidence graph and retrieval over it.

:mod:`pramaanx.graph.evidence_graph`
    Entities and event clusters as nodes, with every edge stamped by the
    instant it became knowable. Queries are evaluated as of a timestamp; there
    is no current-state view to leak through.

:mod:`pramaanx.graph.retrieval`
    Evidence packs, capped per independent story and never unanimous by
    construction when the corpus disagrees.

The graph is a substrate, not a model. Every relation it carries is derivable
from the cluster set by a one-sentence rule. Anything that needs inference --
causation, intent, alliance -- belongs to a generator, where it can be ablated
and scored on its own.
"""

from __future__ import annotations

from pramaanx.graph.evidence_graph import (
    EdgeRelation,
    EvidenceGraph,
    GraphEdge,
    GraphNode,
    NodeKind,
    build_graph,
)
from pramaanx.graph.retrieval import (
    DEFAULT_HALF_LIFE_DAYS,
    HOP_DECAY,
    MAX_PER_INDEPENDENCE_GROUP,
    EvidencePack,
    RetrievalQuery,
    ScoredEvidence,
    retrieve_evidence,
)

__all__ = [
    "DEFAULT_HALF_LIFE_DAYS",
    "HOP_DECAY",
    "MAX_PER_INDEPENDENCE_GROUP",
    "EdgeRelation",
    "EvidenceGraph",
    "EvidencePack",
    "GraphEdge",
    "GraphNode",
    "NodeKind",
    "RetrievalQuery",
    "ScoredEvidence",
    "build_graph",
    "retrieve_evidence",
]
