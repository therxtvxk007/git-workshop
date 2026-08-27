"""Hypothetical scenarios and the counterfactual track."""

from __future__ import annotations

import pytest
from _phase2_builders import at, series_of

from pramaanx.entities import deduplicate_mentions, resolve_entities
from pramaanx.scenarios import (
    AddEvent,
    RemoveEvent,
    ReplaceActor,
    Scenario,
    ShiftTime,
    apply_scenario,
)


def _world(cutoff_day: float = 200.0) -> tuple:
    mentions = series_of(count=5, spacing_days=20)
    cutoff = at(cutoff_day)
    index = resolve_entities(mentions, cutoff_at=cutoff)
    clusters = deduplicate_mentions(mentions, index, cutoff_at=cutoff)
    return index, clusters, cutoff


def _scenario(*interventions) -> Scenario:  # type: ignore[no-untyped-def]
    return Scenario(
        scenario_id=Scenario.build_id("test", at(200)),
        name="test",
        description="a test scenario",
        cutoff_at=at(200),
        author="tests",
        interventions=list(interventions),
    )


class TestScenarioValidation:
    def test_a_scenario_needs_an_author(self) -> None:
        with pytest.raises(ValueError, match="who posed it"):
            Scenario(
                scenario_id="scn_x",
                name="n",
                description="d",
                cutoff_at=at(10),
                author="  ",
                interventions=[RemoveEvent(cluster_ids=["clu_x"])],
            )

    def test_a_scenario_needs_interventions(self) -> None:
        with pytest.raises(ValueError, match="just the baseline"):
            Scenario(
                scenario_id="scn_x",
                name="n",
                description="d",
                cutoff_at=at(10),
                author="tests",
                interventions=[],
            )

    def test_replacing_an_actor_with_itself_is_refused(self) -> None:
        with pytest.raises(ValueError, match="identical to the original"):
            ReplaceActor(original_entity_id="ent_a", replacement_entity_id="ent_a")

    def test_intervention_union_is_discriminated_on_kind(self) -> None:
        """ShiftTime and RemoveEvent share a field shape; kind must decide."""
        scenario = _scenario(ShiftTime(cluster_ids=["clu_x"], delta_days=-5.0))
        assert isinstance(scenario.interventions[0], ShiftTime)


class TestInterventions:
    def test_added_events_are_marked_hypothetical(self) -> None:
        index, clusters, _cutoff = _world()
        actor = clusters[0].actor_ids[0]
        scenario = _scenario(
            AddEvent(
                event_type="armed_clash",
                actor_ids=[actor],
                occurred_at=at(150),
                rationale="assumed escalation",
            )
        )
        updated, _ = apply_scenario(clusters, index, scenario)
        assumed = [cluster for cluster in updated if cluster.hypothetical]
        assert len(assumed) == 1
        assert assumed[0].cluster_id.startswith("hyp_")

    def test_assumed_events_carry_no_fabricated_mentions(self) -> None:
        index, clusters, _ = _world()
        actor = clusters[0].actor_ids[0]
        scenario = _scenario(
            AddEvent(event_type="armed_clash", actor_ids=[actor], occurred_at=at(150))
        )
        updated, _ = apply_scenario(clusters, index, scenario)
        assumed = next(cluster for cluster in updated if cluster.hypothetical)
        assert assumed.mention_ids == []
        assert all(group.mention_ids == [] for group in assumed.independence_groups)

    def test_assumed_event_after_the_cutoff_is_refused(self) -> None:
        index, clusters, _ = _world()
        actor = clusters[0].actor_ids[0]
        scenario = _scenario(
            AddEvent(event_type="armed_clash", actor_ids=[actor], occurred_at=at(199))
        )
        # Inside the cutoff is fine.
        apply_scenario(clusters, index, scenario)
        late = _scenario(AddEvent(event_type="armed_clash", actor_ids=[actor], occurred_at=at(250)))
        with pytest.raises(ValueError, match="after the scenario"):
            apply_scenario(clusters, index, late)

    def test_add_event_needs_an_actor_or_a_location(self) -> None:
        with pytest.raises(ValueError, match="actor or a location"):
            AddEvent(event_type="armed_clash", occurred_at=at(10))

    def test_removing_a_missing_cluster_raises(self) -> None:
        index, clusters, _ = _world()
        with pytest.raises(KeyError, match="not present"):
            apply_scenario(clusters, index, _scenario(RemoveEvent(cluster_ids=["clu_nope"])))

    def test_removal_shrinks_the_world(self) -> None:
        index, clusters, _ = _world()
        scenario = _scenario(RemoveEvent(cluster_ids=[clusters[0].cluster_id]))
        updated, _ = apply_scenario(clusters, index, scenario)
        assert len(updated) == len(clusters) - 1

    def test_actor_replacement_rewrites_participation(self) -> None:
        index, clusters, _ = _world()
        original = clusters[0].actor_ids[0]
        scenario = _scenario(
            ReplaceActor(original_entity_id=original, replacement_entity_id="ent_other")
        )
        updated, _ = apply_scenario(clusters, index, scenario)
        assert all("ent_other" in cluster.actor_ids for cluster in updated)
        assert all(cluster.hypothetical for cluster in updated)

    def test_time_shift_moves_the_window(self) -> None:
        index, clusters, _ = _world()
        target = clusters[0]
        scenario = _scenario(ShiftTime(cluster_ids=[target.cluster_id], delta_days=-5.0))
        updated, _ = apply_scenario(clusters, index, scenario)
        shifted = next(cluster for cluster in updated if cluster.hypothetical)
        assert shifted.window_start < target.window_start


class TestIsolation:
    def test_the_baseline_cluster_list_is_never_mutated(self) -> None:
        index, clusters, _ = _world()
        before = [cluster.model_copy(deep=True) for cluster in clusters]
        actor = clusters[0].actor_ids[0]
        apply_scenario(
            clusters,
            index,
            _scenario(
                AddEvent(event_type="armed_clash", actor_ids=[actor], occurred_at=at(150)),
                ReplaceActor(original_entity_id=actor, replacement_entity_id="ent_other"),
            ),
        )
        assert clusters == before

    def test_no_baseline_cluster_is_hypothetical(self) -> None:
        _, clusters, _ = _world()
        assert not any(cluster.hypothetical for cluster in clusters)

    def test_scenario_graph_is_cut_at_the_scenario_cutoff(self) -> None:
        index, clusters, _ = _world()
        actor = clusters[0].actor_ids[0]
        _, graph = apply_scenario(
            clusters,
            index,
            _scenario(AddEvent(event_type="armed_clash", actor_ids=[actor], occurred_at=at(150))),
        )
        assert graph.cutoff_at == at(200)
