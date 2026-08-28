"""Aliases that know what year it is, and never guess who they mean."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from _nlp_builders import alias, registry_of
from pramaanx.nlp.actors import (
    EMPTY_REGISTRY,
    ActorAliasRegistry,
    ActorRegistryError,
    AliasKind,
    extract_actor_mentions,
)
from pramaanx.nlp.schemas import ActorMention, ResolutionStatus, TextSpan

Y2019 = datetime(2019, 1, 1, tzinfo=UTC)
Y2021 = datetime(2021, 1, 1, tzinfo=UTC)
Y2023 = datetime(2023, 1, 1, tzinfo=UTC)
Y2026 = datetime(2026, 3, 5, tzinfo=UTC)


class TestEffectiveDating:
    def test_an_alias_only_matches_inside_its_interval(self) -> None:
        # Required behaviour 16. An undated alias table answers with today's
        # answer, retroactively rewriting what an old article was about.
        registry = registry_of(
            alias("Old Front", "actor_1", effective_from=Y2019, effective_to=Y2021)
        )
        assert registry.actors_for("Old Front", datetime(2020, 6, 1, tzinfo=UTC)) == ("actor_1",)
        assert registry.actors_for("Old Front", Y2023) == ()

    def test_the_interval_is_half_open(self) -> None:
        registry = registry_of(alias("Front", "actor_1", effective_from=Y2019, effective_to=Y2021))
        assert registry.actors_for("Front", Y2019) == ("actor_1",)
        assert registry.actors_for("Front", Y2021) == ()

    def test_a_rename_maps_both_names_to_one_actor(self) -> None:
        # The whole reason canonical ids exist: the organisation is continuous
        # even when the string in the article is not.
        registry = registry_of(
            alias(
                "Old Front",
                "actor_1",
                kind=AliasKind.FORMER_NAME,
                effective_from=Y2019,
                effective_to=Y2021,
            ),
            alias("New Front", "actor_1", effective_from=Y2021),
        )
        assert registry.actors_for("Old Front", Y2019) == ("actor_1",)
        assert registry.actors_for("New Front", Y2026) == ("actor_1",)

    def test_a_zero_width_interval_is_refused(self) -> None:
        # Raised inside a Pydantic validator, so it arrives wrapped.
        with pytest.raises(ValidationError, match="strictly after"):
            alias("X", "actor_1", effective_from=Y2021, effective_to=Y2021)

    def test_a_blank_alias_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="cannot be blank"):
            alias("   ", "actor_1")

    def test_a_naive_moment_is_refused(self) -> None:
        with pytest.raises(ActorRegistryError, match="timezone-aware"):
            registry_of(alias("X", "a")).actors_for("X", datetime(2026, 1, 1))  # noqa: DTZ001


class TestAmbiguityIsNotResolved:
    def test_a_shared_alias_returns_every_candidate(self) -> None:
        # Choosing the more famous one is how a small local outfit's activity
        # gets attributed to a national organisation.
        registry = registry_of(
            alias("The Front", "actor_1"),
            alias("The Front", "actor_2"),
        )
        resolution = registry.resolve("The Front", Y2026)
        assert resolution.status is ResolutionStatus.AMBIGUOUS
        assert resolution.canonical_actor_id is None
        assert resolution.candidate_actor_ids == ("actor_1", "actor_2")

    def test_an_unmatched_name_stays_unmatched(self) -> None:
        assert registry_of(alias("X", "a")).resolve("Y", Y2026).status is (
            ResolutionStatus.UNRESOLVED
        )

    def test_the_model_refuses_an_ambiguous_mention_naming_one_actor(self) -> None:
        with pytest.raises(ValueError, match="ambiguous but names one actor"):
            ActorMention(
                span=TextSpan(start=0, end=3, text="abc"),
                canonical_actor_id="actor_1",
                matched_alias="abc",
                alias_version="v",
                status=ResolutionStatus.AMBIGUOUS,
                candidate_actor_ids=("actor_1", "actor_2"),
            )

    def test_the_model_refuses_a_resolved_mention_with_no_actor(self) -> None:
        with pytest.raises(ValueError, match="resolved with no actor id"):
            ActorMention(
                span=TextSpan(start=0, end=3, text="abc"),
                matched_alias="abc",
                alias_version="v",
                status=ResolutionStatus.RESOLVED,
            )


class TestExtraction:
    def test_a_matching_alias_produces_a_mention(self) -> None:
        registry = registry_of(alias("Red Star Brigade", "actor_1"))
        mentions = extract_actor_mentions(
            "Police said the Red Star Brigade claimed the attack.",
            registry=registry,
            as_of=Y2026,
        )
        assert len(mentions) == 1
        assert mentions[0].canonical_actor_id == "actor_1"
        assert mentions[0].span.text == "Red Star Brigade"

    def test_the_longest_alias_wins(self) -> None:
        # "Red Star Brigade" is one mention, not an overlapping pair.
        registry = registry_of(
            alias("Red Star", "actor_1"),
            alias("Red Star Brigade", "actor_2"),
        )
        mentions = extract_actor_mentions(
            "The Red Star Brigade issued a statement.", registry=registry, as_of=Y2026
        )
        assert len(mentions) == 1
        assert mentions[0].span.text == "Red Star Brigade"

    def test_an_abbreviation_does_not_fire_inside_a_word(self) -> None:
        registry = registry_of(alias("RSB", "actor_1", kind=AliasKind.ABBREVIATION))
        assert extract_actor_mentions("The RSBX group", registry=registry, as_of=Y2026) == ()
        assert extract_actor_mentions("The RSB group", registry=registry, as_of=Y2026)

    def test_matching_is_case_insensitive(self) -> None:
        registry = registry_of(alias("Red Star Brigade", "actor_1"))
        assert extract_actor_mentions("the red star brigade said", registry=registry, as_of=Y2026)

    def test_spans_slice_the_original(self) -> None:
        text = "Police said the Red Star Brigade claimed the attack."
        registry = registry_of(alias("Red Star Brigade", "actor_1"))
        for mention in extract_actor_mentions(text, registry=registry, as_of=Y2026):
            assert text[mention.span.start : mention.span.end] == mention.span.text

    def test_an_expired_alias_produces_no_mention(self) -> None:
        registry = registry_of(
            alias("Old Front", "actor_1", effective_from=Y2019, effective_to=Y2021)
        )
        assert extract_actor_mentions("The Old Front said", registry=registry, as_of=Y2026) == ()

    def test_the_empty_registry_finds_nothing(self) -> None:
        # The correct behaviour for a pipeline whose actor table is absent: no
        # actors, rather than actors guessed from context.
        assert (
            extract_actor_mentions(
                "Maoist cadres were active in the district.",
                registry=EMPTY_REGISTRY,
                as_of=Y2026,
            )
            == ()
        )

    def test_ideology_and_location_do_not_imply_an_actor(self) -> None:
        # An article about an attack in a district does not thereby name a
        # group. Inferring one would make actor features a restatement of
        # location features.
        registry = registry_of(alias("Red Star Brigade", "actor_1"))
        assert (
            extract_actor_mentions(
                "Maoist cadres attacked a post in Bastar district.",
                registry=registry,
                as_of=Y2026,
            )
            == ()
        )


class TestDeterminism:
    def test_alias_order_does_not_change_the_result(self) -> None:
        # Required behaviour 23. The order a YAML file lists aliases in is not
        # a fact about the world.
        entries = [
            alias("Red Star Brigade", "actor_1"),
            alias("RSB", "actor_1", kind=AliasKind.ABBREVIATION),
            alias("Blue Front", "actor_2"),
        ]
        text = "The RSB and the Blue Front were named; the Red Star Brigade denied it."
        forward = extract_actor_mentions(
            text, registry=ActorAliasRegistry.from_entries(entries), as_of=Y2026
        )
        backward = extract_actor_mentions(
            text, registry=ActorAliasRegistry.from_entries(reversed(entries)), as_of=Y2026
        )
        assert [m.model_dump() for m in forward] == [m.model_dump() for m in backward]

    def test_the_alias_version_is_order_independent(self) -> None:
        entries = [alias("A Front", "actor_1"), alias("B Front", "actor_2")]
        forward = ActorAliasRegistry.from_entries(entries).alias_version
        backward = ActorAliasRegistry.from_entries(reversed(entries)).alias_version
        assert forward == backward

    def test_the_alias_version_changes_when_the_table_does(self) -> None:
        # A mention carrying the version can be rechecked later against the
        # exact table that produced it.
        one = ActorAliasRegistry.from_entries([alias("A Front", "actor_1")])
        two = ActorAliasRegistry.from_entries(
            [alias("A Front", "actor_1"), alias("B Front", "actor_2")]
        )
        assert one.alias_version != two.alias_version

    def test_mentions_come_back_in_document_order(self) -> None:
        registry = registry_of(alias("Blue Front", "actor_2"), alias("RSB", "actor_1"))
        text = "The RSB spoke, then the Blue Front replied."
        starts = [
            m.span.start for m in extract_actor_mentions(text, registry=registry, as_of=Y2026)
        ]
        assert starts == sorted(starts)


class TestDisplayNames:
    def test_the_display_name_is_separate_from_the_identifier(self) -> None:
        # A pipeline keyed on the display name silently rewrites history when
        # the display name changes.
        registry = ActorAliasRegistry.from_entries(
            [alias("Red Star Brigade", "actor_1")], actor_1="Red Star Brigade"
        )
        assert registry.display_name("actor_1") == "Red Star Brigade"
        assert registry.display_name("actor_missing") is None
