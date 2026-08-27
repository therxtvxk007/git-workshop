"""Entity resolution and event deduplication."""

from __future__ import annotations

import pytest

from pramaanx.entities import (
    EntityKind,
    EntityRole,
    assign_independence_groups,
    deduplicate_mentions,
    normalise_name,
    resolve_entities,
    similarity,
)
from _phase2_builders import at, mention, series_of


class TestNormalisation:
    def test_strips_titles_and_accents(self) -> None:
        assert normalise_name("President Séléka") == "seleka"

    def test_strips_trailing_org_suffix_only_at_the_end(self) -> None:
        assert normalise_name("Acme Corp") == "acme"
        # "Corp" leading is part of the name, not a suffix.
        assert normalise_name("Corp Security Ltd") == "corp security"

    def test_empty_input_is_not_an_entity(self) -> None:
        assert normalise_name("  ...  ") == ""
        assert normalise_name(None) == ""

    def test_word_order_is_not_identity(self) -> None:
        assert similarity("Ministry of Home Affairs", "Home Affairs Ministry") == 1.0

    def test_abbreviation_matches_expansion(self) -> None:
        # Initials are sorted, so CIP is the initial set of Communist Party of India.
        assert similarity("CIP", "Communist Party of India") >= 0.9

    def test_two_unparseable_names_do_not_match(self) -> None:
        assert similarity("...", "!!!") == 0.0


class TestResolution:
    def test_inflection_variants_merge(self) -> None:
        mentions = [
            mention(observed_days=1, event_days=1, subject="Maoists", span="one"),
            mention(observed_days=2, event_days=2, subject="Maoist", span="two"),
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        actors = [e for e in index.entities if e.kind is EntityKind.ACTOR]
        assert len(actors) == 1
        assert set(actors[0].surfaces) == {"Maoist", "Maoists"}

    def test_unrelated_names_do_not_merge(self) -> None:
        mentions = [
            mention(observed_days=1, event_days=1, subject="Maoists", span="one"),
            mention(observed_days=2, event_days=2, subject="Border Guards", span="two"),
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        actors = [e for e in index.entities if e.kind is EntityKind.ACTOR]
        assert len(actors) == 2

    def test_subject_and_object_share_one_namespace(self) -> None:
        """A group that attacks and is attacked is one group, not two."""
        mentions = [
            mention(observed_days=1, event_days=1, subject="Maoists", obj="Police", span="one"),
            mention(observed_days=2, event_days=2, subject="Police", obj="Maoists", span="two"),
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        actors = {e.canonical_name for e in index.entities if e.kind is EntityKind.ACTOR}
        assert actors == {"Maoists", "Police"}

    def test_mentions_after_the_cutoff_are_excluded(self) -> None:
        mentions = [
            mention(observed_days=1, event_days=1, subject="Maoists", span="early"),
            mention(observed_days=40, event_days=2, subject="Naxalites", span="late"),
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        names = {e.canonical_name for e in index.entities}
        assert "Naxalites" not in names

    def test_resolution_is_order_independent(self) -> None:
        mentions = series_of(count=6, spacing_days=5)
        forward = resolve_entities(mentions, cutoff_at=at(200))
        backward = resolve_entities(list(reversed(mentions)), cutoff_at=at(200))
        assert [e.entity_id for e in forward.entities] == [e.entity_id for e in backward.entities]

    def test_canonical_name_is_the_most_frequent_surface(self) -> None:
        mentions = [
            mention(observed_days=1, event_days=1, subject="Maoists", span="a"),
            mention(observed_days=2, event_days=2, subject="Maoists", span="b"),
            mention(observed_days=3, event_days=3, subject="Maoist", span="c"),
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        actor = next(e for e in index.entities if e.kind is EntityKind.ACTOR)
        assert actor.canonical_name == "Maoists"

    def test_role_lookup(self) -> None:
        target = mention(
            observed_days=1, event_days=1, subject="Maoists", obj="Police", span="one"
        )
        index = resolve_entities([target], cutoff_at=at(30))
        assert index.actors_for(target.mention_id)
        assert index.targets_for(target.mention_id)
        assert index.location_for(target.mention_id) is not None
        assert index.entity_ids_for(target.mention_id, role=EntityRole.SUBJECT) == (
            index.actors_for(target.mention_id)
        )

    def test_threshold_is_validated(self) -> None:
        with pytest.raises(ValueError, match="merge_threshold"):
            resolve_entities([], cutoff_at=at(1), merge_threshold=1.5)


class TestIndependenceGroups:
    def test_identical_spans_form_one_group(self) -> None:
        wire = "Heavy fighting was reported near the district headquarters overnight"
        mentions = [
            mention(observed_days=index, event_days=1, span=wire, observation_id=f"obs{index}")
            for index in range(4)
        ]
        groups = assign_independence_groups(mentions)
        assert len(groups) == 1
        assert len(groups[0].mention_ids) == 4

    def test_different_spans_stay_separate(self) -> None:
        mentions = [
            mention(observed_days=1, event_days=1, span="a clash near the border post"),
            mention(observed_days=2, event_days=1, span="flooding displaced many families"),
        ]
        assert len(assign_independence_groups(mentions)) == 2

    def test_empty_spans_do_not_collapse_together(self) -> None:
        """Two unparseable spans are two failures, not one shared story."""
        mentions = [
            mention(observed_days=1, event_days=1, span="...", observation_id="a"),
            mention(observed_days=2, event_days=1, span="!!!", observation_id="b"),
        ]
        assert len(assign_independence_groups(mentions)) == 2

    def test_threshold_is_validated(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            assign_independence_groups([], threshold=2.0)


class TestDeduplication:
    def test_one_event_reported_many_times_is_one_cluster(self) -> None:
        wire = "Security forces clashed with insurgents near the district headquarters"
        mentions = [
            mention(observed_days=11, event_days=10, span=wire, observation_id=f"obs{index}")
            for index in range(5)
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        clusters = deduplicate_mentions(mentions, index, cutoff_at=at(30))
        assert len(clusters) == 1
        assert clusters[0].support == 5

    def test_effective_support_counts_stories_not_reprints(self) -> None:
        wire = "Security forces clashed with insurgents near the district headquarters"
        mentions = [
            mention(observed_days=11, event_days=10, span=wire, observation_id=f"obs{i}")
            for i in range(5)
        ]
        mentions.append(
            mention(
                observed_days=11,
                event_days=10,
                span="An entirely separate correspondent filed this independent account",
                observation_id="obs-indep",
            )
        )
        index = resolve_entities(mentions, cutoff_at=at(30))
        cluster = deduplicate_mentions(mentions, index, cutoff_at=at(30))[0]
        assert cluster.support == 6
        assert cluster.effective_support == 2

    def test_distant_events_are_separate_clusters(self) -> None:
        mentions = [
            mention(observed_days=11, event_days=10, span="first clash"),
            mention(observed_days=61, event_days=60, span="second clash"),
        ]
        index = resolve_entities(mentions, cutoff_at=at(90))
        assert len(deduplicate_mentions(mentions, index, cutoff_at=at(90))) == 2

    def test_denial_marks_the_cluster_contested_without_removing_it(self) -> None:
        mentions = [
            mention(observed_days=11, event_days=10, span="a clash took place at dawn"),
            mention(
                observed_days=12,
                event_days=10,
                span="officials denied any clash occurred",
                modality="denied",
                observation_id="denial",
            ),
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        cluster = deduplicate_mentions(mentions, index, cutoff_at=at(30))[0]
        assert cluster.contested
        assert cluster.denial_count == 1
        assert cluster.corroboration_count == 1

    def test_undated_mentions_are_kept(self) -> None:
        mentions = [
            mention(observed_days=11, event_days=10, span="a dated clash"),
            mention(observed_days=12, event_days=None, span="an undated report of a clash"),
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        clusters = deduplicate_mentions(mentions, index, cutoff_at=at(30))
        kept = {mid for cluster in clusters for mid in cluster.mention_ids}
        assert len(kept) == 2
        assert any(cluster.undated_mention_ids for cluster in clusters)

    def test_mentions_after_the_cutoff_never_enter_a_cluster(self) -> None:
        mentions = [
            mention(observed_days=11, event_days=10, span="visible clash"),
            mention(observed_days=99, event_days=10, span="clash reported much later"),
        ]
        index = resolve_entities(mentions, cutoff_at=at(30))
        clusters = deduplicate_mentions(mentions, index, cutoff_at=at(30))
        assert sum(cluster.support for cluster in clusters) == 1
