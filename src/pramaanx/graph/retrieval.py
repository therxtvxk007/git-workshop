"""Cutoff-safe retrieval over the evidence graph.

Retrieval turns a question -- "what is known about these actors, in this place,
before this instant?" -- into an evidence pack that a generator or an
adjudicator can read.

Two rules shape the design.

*The pack is capped per independent story, not per document.* A syndicated wire
report reprinted forty times must not be able to fill forty of the fifty slots.
Diversity is enforced structurally by round-robin over independence groups
rather than by hoping a similarity penalty catches it.

*Contradicting evidence is never crowded out.* Denials are selected before the
pack is filled by score, because the failure mode of an evidence pack is not
that it is too small, it is that it is unanimous when reality is not.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import Field, model_validator

from pramaanx.entities.dedupe import CORROBORATING_MODALITIES, EventCluster
from pramaanx.graph.evidence_graph import EdgeRelation, EvidenceGraph
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel, UtcDatetime
from pramaanx.schemas.event import EventMention
from pramaanx.schemas.evidence import EvidenceRef, Stance

log = get_logger(__name__)

#: Half-life of evidence recency, in days. A year-old event still counts; it
#: counts about a quarter as much as last week's.
DEFAULT_HALF_LIFE_DAYS = 120.0

#: Score multiplier per graph hop away from the seed entities.
HOP_DECAY = 0.55

#: Most items one independence group may contribute to a pack.
MAX_PER_INDEPENDENCE_GROUP = 2


class RetrievalQuery(PramaanModel):
    """What to retrieve, and the instant to retrieve it as of."""

    seed_entity_ids: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    as_of: UtcDatetime
    lookback_days: float = Field(default=730.0, gt=0.0)
    max_hops: int = Field(default=2, ge=0, le=4)
    limit: int = Field(default=50, gt=0)
    half_life_days: float = Field(default=DEFAULT_HALF_LIFE_DAYS, gt=0.0)

    @model_validator(mode="after")
    def _check_seeds(self) -> RetrievalQuery:
        if not self.seed_entity_ids and not self.event_types:
            raise ValueError("a retrieval query needs at least one seed entity or event type")
        return self

    @property
    def window_start(self) -> datetime:
        return self.as_of - timedelta(days=self.lookback_days)


class ScoredEvidence(PramaanModel):
    """One retrieved item, with the score and the path that justify it."""

    cluster_id: str
    mention_id: str
    hops: int = Field(ge=0)
    recency: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0)
    ref: EvidenceRef


class EvidencePack(PramaanModel):
    """The result of one retrieval, ready to attach to a hypothesis."""

    query: RetrievalQuery
    items: list[ScoredEvidence] = Field(default_factory=list)
    #: Groups that were found but dropped by the per-group cap or the limit.
    suppressed_group_ids: list[str] = Field(default_factory=list)
    truncated: bool = False

    @property
    def independence_count(self) -> int:
        """Independent stories represented in the pack."""
        return len({item.ref.cluster_key for item in self.items})

    @property
    def contradiction_count(self) -> int:
        return sum(1 for item in self.items if item.ref.stance == "contradicts")

    def refs(self) -> list[EvidenceRef]:
        """The plain references, for :class:`~pramaanx.schemas.event.EventHypothesis`."""
        return [item.ref for item in self.items]

    def unanimous(self) -> bool:
        """True when nothing in the pack disagrees with anything else.

        Worth checking before a confident forecast: a unanimous pack over a
        single independence group is one source, however many items it holds.
        """
        return self.contradiction_count == 0


def _stance_for(mention: EventMention, requested_types: Sequence[str]) -> Stance:
    """Classify a mention's relationship to the question being asked.

    A denial contradicts. An assertion of a requested event type supports.
    Everything else is context -- including assertions of *other* event types,
    which are informative background but are not evidence for this question and
    must not be counted as if they were.
    """
    if mention.modality == "denied":
        return "contradicts"
    if mention.modality in CORROBORATING_MODALITIES:
        if not requested_types or mention.event_type in set(requested_types):
            return "supports"
    return "context"


def _recency(observed_at: datetime, *, as_of: datetime, half_life_days: float) -> float:
    """Exponential decay on availability, clamped to [0, 1]."""
    age_days = max((as_of - observed_at).total_seconds() / 86400.0, 0.0)
    return float(0.5 ** (age_days / half_life_days))


def _reliability(
    *, effective_support: int, contested: bool, mention: EventMention
) -> float:
    """A coarse reliability for one reference.

    Built from independent support and the extractor's own confidence, and
    halved when the cluster is contested. It is not a calibrated probability
    and is not used as one -- it orders a pack, nothing more.

    Support and contestedness are passed in rather than read off the cluster,
    because both are aggregates over every mention available when the cluster
    was *built*. Reading them directly would let a corroborating report filed
    next month raise the reliability of a reference retrieved as of today, and
    let a denial that has not arrived yet mark a claim contested.
    """
    independence = 1.0 - (1.0 / (1.0 + float(effective_support)))
    combined = 0.5 * independence + 0.5 * mention.extraction_probability
    if contested:
        combined *= 0.5
    return float(min(max(combined, 0.0), 1.0))


def _support_as_of(
    cluster: EventCluster,
    mention_by_id: dict[str, EventMention],
    *,
    as_of: datetime,
) -> tuple[int, bool]:
    """Recompute independent support and contestedness from available mentions.

    Returns ``(effective_support, contested)`` counting only what a reader at
    ``as_of`` could actually have seen.
    """
    groups = 0
    denials = 0
    corroborations = 0
    for group in cluster.independence_groups:
        available = [
            mention_by_id[mention_id]
            for mention_id in group.mention_ids
            if mention_id in mention_by_id
            and mention_by_id[mention_id].observed_at <= as_of
        ]
        if not available:
            continue
        groups += 1
        for mention in available:
            if mention.modality == "denied":
                denials += 1
            elif mention.modality in CORROBORATING_MODALITIES:
                corroborations += 1
    return groups, bool(denials and corroborations)


def retrieve_evidence(
    graph: EvidenceGraph,
    clusters: Sequence[EventCluster],
    mentions: Sequence[EventMention],
    query: RetrievalQuery,
) -> EvidencePack:
    """Retrieve an evidence pack for ``query``.

    The graph is first narrowed with :meth:`EvidenceGraph.as_of`, so an
    accidental query past the build cutoff raises rather than quietly returning
    evidence from the future.
    """
    view = graph.as_of(query.as_of)
    mention_by_id = {mention.mention_id: mention for mention in mentions}
    cluster_by_id = {cluster.cluster_id: cluster for cluster in clusters}

    reachable = _walk(view, query)
    requested_types = list(query.event_types)

    scored: list[ScoredEvidence] = []
    for cluster_id, hops in sorted(reachable.items()):
        cluster = cluster_by_id.get(cluster_id)
        if cluster is None:
            continue
        if requested_types and cluster.event_type not in set(requested_types):
            continue
        if cluster.first_observed_at > query.as_of:
            continue
        if cluster.window_end < query.window_start:
            continue
        support, contested = _support_as_of(cluster, mention_by_id, as_of=query.as_of)
        for group in cluster.independence_groups:
            for mention_id in group.mention_ids:
                mention = mention_by_id.get(mention_id)
                if mention is None or mention.observed_at > query.as_of:
                    continue
                recency = _recency(
                    mention.observed_at,
                    as_of=query.as_of,
                    half_life_days=query.half_life_days,
                )
                reliability = _reliability(
                    effective_support=support, contested=contested, mention=mention
                )
                score = recency * reliability * (HOP_DECAY**hops)
                scored.append(
                    ScoredEvidence(
                        cluster_id=cluster_id,
                        mention_id=mention_id,
                        hops=hops,
                        recency=recency,
                        score=score,
                        ref=EvidenceRef(
                            observation_id=mention.observation_id,
                            claim=mention.supporting_span[:512],
                            stance=_stance_for(mention, requested_types),
                            independence_cluster=group.group_id,
                            reliability=reliability,
                        ),
                    )
                )

    selected, suppressed, truncated = _select(scored, limit=query.limit)
    pack = EvidencePack(
        query=query,
        items=selected,
        suppressed_group_ids=suppressed,
        truncated=truncated,
    )
    log.info(
        "graph.retrieved",
        candidates=len(scored),
        selected=len(selected),
        independence=pack.independence_count,
        contradictions=pack.contradiction_count,
    )
    return pack


def _walk(view: EvidenceGraph, query: RetrievalQuery) -> dict[str, int]:
    """Breadth-first walk from the seeds, returning event nodes and hop counts.

    Entity-to-entity co-occurrence edges are traversed to widen the frontier;
    event nodes encountered on the way are collected with the hop count at
    which they were first reached. First-reached rather than shortest-overall
    is exact here because BFS visits in non-decreasing depth.
    """
    seeds = sorted(set(query.seed_entity_ids))
    known = {node.node_id for node in view.nodes}
    frontier = [entity_id for entity_id in seeds if entity_id in known]

    if not frontier:
        # No seed survived the as-of view. Fall back to every event of the
        # requested types, which is the honest answer to "nothing is known
        # about these actors yet" -- base rates, not silence.
        return {
            node.node_id: query.max_hops
            for node in view.nodes
            if node.attributes.get("event_type") in set(query.event_types)
        }

    reached: dict[str, int] = {}
    visited: set[str] = set(frontier)
    for hop in range(query.max_hops + 1):
        next_frontier: list[str] = []
        for entity_id in frontier:
            for event_id in view.events_for(entity_id):
                reached.setdefault(event_id, hop)
            if hop < query.max_hops:
                for neighbour in view.neighbours(
                    entity_id, relations={EdgeRelation.CO_OCCURRED}
                ):
                    if neighbour not in visited:
                        visited.add(neighbour)
                        next_frontier.append(neighbour)
        if not next_frontier:
            break
        frontier = sorted(next_frontier)
    return reached


def _select(
    scored: Sequence[ScoredEvidence], *, limit: int
) -> tuple[list[ScoredEvidence], list[str], bool]:
    """Choose the pack: contradictions first, then round-robin by group.

    Round-robin rather than a global sort is what actually enforces diversity.
    A global sort with a per-group cap still lets the highest-scoring group take
    its full allowance before any other group is considered, which on a
    saturated news day means the pack is one story and its two best rewrites.
    """
    by_group: dict[str, list[ScoredEvidence]] = defaultdict(list)
    for item in sorted(scored, key=lambda entry: (-entry.score, entry.mention_id)):
        by_group[item.ref.cluster_key].append(item)

    selected: list[ScoredEvidence] = []
    chosen_ids: set[str] = set()

    # Contradictions are seeded first, one per group, before the general fill.
    for group_id in sorted(by_group):
        for item in by_group[group_id]:
            if item.ref.stance == "contradicts" and len(selected) < limit:
                selected.append(item)
                chosen_ids.add(item.mention_id)
                break

    taken_per_group: dict[str, int] = defaultdict(int)
    for item in selected:
        taken_per_group[item.ref.cluster_key] += 1

    exhausted = False
    while len(selected) < limit and not exhausted:
        exhausted = True
        for group_id in sorted(by_group):
            if len(selected) >= limit:
                break
            if taken_per_group[group_id] >= MAX_PER_INDEPENDENCE_GROUP:
                continue
            for item in by_group[group_id]:
                if item.mention_id in chosen_ids:
                    continue
                selected.append(item)
                chosen_ids.add(item.mention_id)
                taken_per_group[group_id] += 1
                exhausted = False
                break

    suppressed = sorted(
        group_id
        for group_id, items in by_group.items()
        if any(item.mention_id not in chosen_ids for item in items)
    )
    selected.sort(key=lambda entry: (-entry.score, entry.mention_id))
    truncated = bool(suppressed)
    return selected, suppressed, truncated
