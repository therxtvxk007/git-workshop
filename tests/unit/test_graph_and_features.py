"""The evidence graph, retrieval, and feature construction."""

from __future__ import annotations

import pytest
from _phase2_builders import at, mention, series_of

from pramaanx.entities import deduplicate_mentions, resolve_entities
from pramaanx.features import SeriesKey, build_features, series_from_clusters
from pramaanx.graph import EdgeRelation, RetrievalQuery, build_graph, retrieve_evidence


def _world(mentions: list, cutoff_day: float) -> tuple:
    cutoff = at(cutoff_day)
    index = resolve_entities(mentions, cutoff_at=cutoff)
    clusters = deduplicate_mentions(mentions, index, cutoff_at=cutoff)
    graph = build_graph(clusters, index, cutoff_at=cutoff)
    return index, clusters, graph


class TestGraphConstruction:
    def test_participants_and_events_become_nodes(self) -> None:
        mentions = [mention(observed_days=11, event_days=10, subject="Maoists", obj="Police")]
        _, clusters, graph = _world(mentions, 30)
        kinds = {node.kind.value for node in graph.nodes}
        assert kinds == {"entity", "event"}
        assert len(clusters) == 1

    def test_co_occurrence_links_participants(self) -> None:
        mentions = [mention(observed_days=11, event_days=10, subject="Maoists", obj="Police")]
        index, _, graph = _world(mentions, 30)
        actor = next(e for e in index.entities if e.canonical_name == "Maoists")
        neighbours = graph.neighbours(actor.entity_id, relations={EdgeRelation.CO_OCCURRED})
        assert neighbours

    def test_succession_edges_link_consecutive_events(self) -> None:
        _, _, graph = _world(series_of(count=4, spacing_days=20), 200)
        successions = [e for e in graph.edges if e.relation is EdgeRelation.PRECEDED_BY]
        assert len(successions) == 3

    def test_as_of_refuses_to_look_past_the_build_cutoff(self) -> None:
        _, _, graph = _world(series_of(count=3, spacing_days=10), 100)
        with pytest.raises(ValueError, match="exceeds the graph cutoff"):
            graph.as_of(at(200))

    def test_as_of_hides_later_edges(self) -> None:
        _, _, graph = _world(series_of(count=4, spacing_days=20), 200)
        early = graph.as_of(at(40))
        assert len(early.edges) < len(graph.edges)
        assert all(edge.observed_at <= at(40) for edge in early.edges)

    def test_edge_weight_saturates_and_is_discounted_when_contested(self) -> None:
        _, _, graph = _world(series_of(count=2, spacing_days=15), 100)
        weights = [edge.weight for edge in graph.edges]
        assert all(0.0 <= weight < 1.0 for weight in weights)


class TestRetrieval:
    def test_pack_is_capped_per_independence_group(self) -> None:
        wire = "Heavy fighting was reported near the district headquarters overnight"
        mentions = [
            mention(observed_days=11, event_days=10, span=wire, observation_id=f"obs{i}")
            for i in range(12)
        ]
        index, clusters, graph = _world(mentions, 30)
        actor = next(e for e in index.entities if e.canonical_name == "Maoists")
        query = RetrievalQuery(
            seed_entity_ids=[actor.entity_id],
            event_types=["armed_clash"],
            as_of=at(30),
            limit=10,
        )
        pack = retrieve_evidence(graph, clusters, mentions, query)
        # One wire story, so the cap keeps it from filling the pack.
        assert len(pack.items) <= 2
        assert pack.independence_count == 1

    def test_contradictions_are_never_crowded_out(self) -> None:
        mentions = [
            mention(
                observed_days=11,
                event_days=10,
                span=f"an independent account number {i} of the clash",
                observation_id=f"obs{i}",
            )
            for i in range(8)
        ]
        mentions.append(
            mention(
                observed_days=12,
                event_days=10,
                span="officials denied that any clash occurred at all",
                modality="denied",
                observation_id="denial",
            )
        )
        index, clusters, graph = _world(mentions, 30)
        actor = next(e for e in index.entities if e.canonical_name == "Maoists")
        pack = retrieve_evidence(
            graph,
            clusters,
            mentions,
            RetrievalQuery(
                seed_entity_ids=[actor.entity_id],
                event_types=["armed_clash"],
                as_of=at(30),
                limit=3,
            ),
        )
        assert pack.contradiction_count >= 1
        assert not pack.unanimous()

    def test_refs_carry_independence_clusters(self) -> None:
        mentions = series_of(count=3, spacing_days=10)
        index, clusters, graph = _world(mentions, 100)
        actor = next(e for e in index.entities if e.canonical_name == "Maoists")
        pack = retrieve_evidence(
            graph,
            clusters,
            mentions,
            RetrievalQuery(
                seed_entity_ids=[actor.entity_id], event_types=["armed_clash"], as_of=at(100)
            ),
        )
        assert pack.items
        assert all(ref.independence_cluster for ref in pack.refs())

    def test_query_needs_a_seed(self) -> None:
        with pytest.raises(ValueError, match="seed entity or event type"):
            RetrievalQuery(as_of=at(10))

    def test_retrieval_past_the_cutoff_raises(self) -> None:
        mentions = series_of(count=3, spacing_days=10)
        _, clusters, graph = _world(mentions, 100)
        with pytest.raises(ValueError, match="exceeds the graph cutoff"):
            retrieve_evidence(
                graph,
                clusters,
                mentions,
                RetrievalQuery(event_types=["armed_clash"], as_of=at(300)),
            )


class TestFeatures:
    def test_counts_use_event_time_within_available_clusters(self) -> None:
        mentions = series_of(count=5, spacing_days=10, start_day=10)
        _, clusters, graph = _world(mentions, 100)
        series = series_from_clusters(clusters)[0]
        vector = build_features(series, clusters, graph, as_of=at(100))
        assert vector.get("events_last_365d") == 5.0

    def test_an_event_reported_late_does_not_appear_early(self) -> None:
        """The core leak guard: availability filters before event time counts.

        The two events are 50 days apart so that deduplication keeps them
        separate; at 2 days apart they are one event by design, and the test
        would be measuring the merge tolerance rather than the cutoff.
        """
        mentions = [
            mention(observed_days=11, event_days=10, span="promptly reported clash"),
            mention(observed_days=90, event_days=60, span="an archive released much later"),
        ]
        # One cutoff, one cluster set. Reusing the day-120 clusters for a day-30
        # view would carry day-90 evidence into January's counts.
        _, early_clusters, early_graph = _world(mentions, 30)
        _, late_clusters, late_graph = _world(mentions, 120)
        series = SeriesKey(
            event_type="armed_clash",
            actor_id=early_clusters[0].actor_ids[0],
            location_id=early_clusters[0].location_entity_id,
        )
        early = build_features(series, early_clusters, early_graph, as_of=at(30))
        late = build_features(series, late_clusters, late_graph, as_of=at(120))
        assert early.support == 1
        assert late.support == 2

    def test_features_refuse_a_cluster_set_from_another_cutoff(self) -> None:
        """A cluster set is an artefact of one cutoff; reading it at another leaks."""
        _, clusters, graph = _world(series_of(count=4, spacing_days=20), 200)
        series = series_from_clusters(clusters)[0]
        with pytest.raises(ValueError, match="predates the graph cutoff"):
            build_features(series, clusters, graph, as_of=at(100))

    def test_building_past_the_graph_cutoff_raises(self) -> None:
        mentions = series_of(count=3, spacing_days=10)
        _, clusters, graph = _world(mentions, 100)
        series = series_from_clusters(clusters)[0]
        with pytest.raises(ValueError, match="cannot build features"):
            build_features(series, clusters, graph, as_of=at(300))

    def test_regular_series_has_low_dispersion(self) -> None:
        _, clusters, graph = _world(series_of(count=6, spacing_days=20), 200)
        series = series_from_clusters(clusters)[0]
        vector = build_features(series, clusters, graph, as_of=at(200))
        assert vector.get("interval_dispersion") < 0.2
        assert vector.get("interval_mean_days") == pytest.approx(20.0, abs=1.0)

    def test_empty_series_falls_back_to_declared_defaults(self) -> None:
        _, clusters, graph = _world(series_of(count=2, spacing_days=10), 100)
        empty = SeriesKey(event_type="cyclone", actor_id=None, location_id=None)
        vector = build_features(empty, clusters, graph, as_of=at(100))
        assert vector.support == 0
        assert vector.get("novelty") == 1.0
        assert vector.get("events_last_30d") == 0.0

    def test_reporting_lag_is_measured(self) -> None:
        _, clusters, graph = _world(
            series_of(count=4, spacing_days=15, reporting_lag_days=5.0), 200
        )
        series = series_from_clusters(clusters)[0]
        vector = build_features(series, clusters, graph, as_of=at(200))
        assert vector.get("reporting_lag_mean_days") == pytest.approx(5.0, abs=0.5)

    def test_missing_feature_in_dense_vector_raises(self) -> None:
        _, clusters, graph = _world(series_of(count=3, spacing_days=10), 100)
        series = series_from_clusters(clusters)[0]
        vector = build_features(series, clusters, graph, as_of=at(100))
        with pytest.raises(KeyError):
            vector.as_ordered(["events_last_30d", "not_a_feature"])
