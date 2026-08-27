"""Cutoff safety across the downstream stages.

The unit tests check each stage in isolation. These check the property that
actually matters and that no single stage can guarantee alone: an observation
that becomes available *after* a cutoff must be invisible to everything
computed *at* that cutoff -- resolution, deduplication, the graph, features and
proposals -- and must become visible once the cutoff moves past it.

The negative control is the important half. A test that only asserts "the late
event is absent" passes just as well against a pipeline that drops everything,
so each case also asserts that the same event appears at the later cutoff.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.entities import deduplicate_mentions, resolve_entities
from pramaanx.features import SeriesKey, build_features
from pramaanx.generators import ForecastContext, TemporalRuleGenerator
from pramaanx.graph import RetrievalQuery, build_graph, retrieve_evidence
from pramaanx.hashing import stable_id
from pramaanx.schemas.event import EventMention

BASE = datetime(2025, 1, 1, tzinfo=UTC)
EARLY_CUTOFF = BASE + timedelta(days=100)
LATE_CUTOFF = BASE + timedelta(days=300)


def _at(days: float) -> datetime:
    return BASE + timedelta(days=days)


def _mention(*, observed_days: float, event_days: float, span: str) -> EventMention:
    obs_id = stable_id("obs", span, str(observed_days))
    return EventMention(
        mention_id=EventMention.build_id(obs_id, "participates_in", span),
        observation_id=obs_id,
        observed_at=_at(observed_days),
        subject="Maoists",
        relation="participates_in",
        object=None,
        event_type="armed_clash",
        location_text="Bastar",
        event_time_start=_at(event_days),
        event_time_end=_at(event_days),
        modality="asserted",
        extraction_probability=0.8,
        supporting_span=span,
        explicit_fields=set(),
        unresolved_fields=set(),
    )


@pytest.fixture
def corpus() -> list[EventMention]:
    """Four early events, plus one that only becomes available at day 250.

    The late arrival describes an event at day 50 -- inside the early cutoff by
    event time, outside it by availability. That is exactly the row that leaks
    if a stage filters on the wrong timestamp.
    """
    early = [
        _mention(observed_days=10 + index * 20 + 1, event_days=10 + index * 20, span=f"clash {index}")
        for index in range(4)
    ]
    late = _mention(observed_days=250, event_days=50, span="an archive released much later")
    return [*early, late]


def _pipeline(mentions: list[EventMention], cutoff: datetime) -> tuple:
    index = resolve_entities(mentions, cutoff_at=cutoff)
    clusters = deduplicate_mentions(mentions, index, cutoff_at=cutoff)
    graph = build_graph(clusters, index, cutoff_at=cutoff)
    return index, clusters, graph


class TestLateArrivalIsInvisible:
    def test_deduplication_excludes_then_includes(self, corpus: list[EventMention]) -> None:
        _, early_clusters, _ = _pipeline(corpus, EARLY_CUTOFF)
        _, late_clusters, _ = _pipeline(corpus, LATE_CUTOFF)
        early_mentions = {mid for c in early_clusters for mid in c.mention_ids}
        late_mentions = {mid for c in late_clusters for mid in c.mention_ids}
        leaked = corpus[-1].mention_id
        assert leaked not in early_mentions
        assert leaked in late_mentions

    def test_graph_excludes_then_includes(self, corpus: list[EventMention]) -> None:
        _, _, early_graph = _pipeline(corpus, EARLY_CUTOFF)
        _, _, late_graph = _pipeline(corpus, LATE_CUTOFF)
        assert len(late_graph.nodes) > len(early_graph.nodes)
        assert all(edge.observed_at <= EARLY_CUTOFF for edge in early_graph.edges)

    def test_features_exclude_then_include(self, corpus: list[EventMention]) -> None:
        index, clusters, graph = _pipeline(corpus, LATE_CUTOFF)
        series = SeriesKey(
            event_type="armed_clash",
            actor_id=clusters[0].actor_ids[0],
            location_id=clusters[0].location_entity_id,
        )
        early = build_features(series, clusters, graph, as_of=EARLY_CUTOFF)
        late = build_features(series, clusters, graph, as_of=LATE_CUTOFF)
        assert early.support == 4
        assert late.support == 5
        assert index.entities

    def test_retrieval_excludes_then_includes(self, corpus: list[EventMention]) -> None:
        index, clusters, graph = _pipeline(corpus, LATE_CUTOFF)
        actor = next(e for e in index.entities if e.canonical_name == "Maoists")

        def _pack(as_of: datetime) -> set[str]:
            result = retrieve_evidence(
                graph,
                clusters,
                corpus,
                RetrievalQuery(
                    seed_entity_ids=[actor.entity_id],
                    event_types=["armed_clash"],
                    as_of=as_of,
                    lookback_days=400.0,
                    limit=50,
                ),
            )
            return {item.mention_id for item in result.items}

        leaked = corpus[-1].mention_id
        assert leaked not in _pack(EARLY_CUTOFF)
        assert leaked in _pack(LATE_CUTOFF)


class TestGeneratorRefusesToLookAhead:
    def test_proposing_past_the_graph_cutoff_raises(self, corpus: list[EventMention]) -> None:
        index, clusters, graph = _pipeline(corpus, EARLY_CUTOFF)
        generator = TemporalRuleGenerator(
            corpus, clusters, index, graph, time_buckets=("0-7d", "7-30d", "30-90d")
        )
        with pytest.raises(ValueError, match="after the graph cutoff"):
            generator.propose(
                ForecastContext(
                    cutoff_at=LATE_CUTOFF,
                    evidence_snapshot_id="snap",
                    proposal_budget=10,
                    horizon_days=90,
                )
            )

    def test_evidence_attached_to_proposals_predates_the_cutoff(
        self, corpus: list[EventMention]
    ) -> None:
        index, clusters, graph = _pipeline(corpus, EARLY_CUTOFF)
        generator = TemporalRuleGenerator(
            corpus, clusters, index, graph, time_buckets=("0-7d", "7-30d", "30-90d")
        )
        proposals = generator.propose(
            ForecastContext(
                cutoff_at=EARLY_CUTOFF,
                evidence_snapshot_id="snap",
                proposal_budget=50,
                horizon_days=90,
            )
        )
        by_id = {mention.observation_id: mention for mention in corpus}
        for proposal in proposals:
            for ref in proposal.hypothesis.evidence:
                assert by_id[ref.observation_id].observed_at <= EARLY_CUTOFF
