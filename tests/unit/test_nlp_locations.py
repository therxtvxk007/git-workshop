"""Place candidates are found here; districts are resolved by WP0, or not at all."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

from _nlp_builders import CUTOFF, StubResolver
from pramaanx.nlp.locations import (
    STATES,
    DistrictResolver,
    LocationQuery,
    NullDistrictResolver,
    extract_location_mentions,
    find_place_candidates,
    find_state_context,
)
from pramaanx.nlp.schemas import LocationMention, ResolutionStatus, TextSpan


class TestCandidateDetection:
    def test_an_administrative_cue_produces_a_candidate(self) -> None:
        spans = find_place_candidates("The incident was in Kishtwar district on Sunday.")
        assert "Kishtwar" in [span.text for span in spans]

    def test_a_locative_preposition_produces_a_candidate(self) -> None:
        spans = find_place_candidates("The incident happened in Bijapur last week.")
        assert "Bijapur" in [span.text for span in spans]

    def test_candidates_slice_the_original(self) -> None:
        text = "Forces moved in Kishtwar district and later in Bijapur."
        for span in find_place_candidates(text):
            assert text[span.start : span.end] == span.text

    def test_ranks_and_pronouns_are_not_places(self) -> None:
        # Without this, every named officer and every quoted sentence opener
        # became a place candidate.
        spans = [span.text for span in find_place_candidates('"We are investigating," he said.')]
        assert "We" not in spans

    def test_candidates_do_not_overlap(self) -> None:
        spans = find_place_candidates("Forces moved in Kishtwar district today.")
        for earlier, later in itertools.pairwise(spans):
            assert earlier.end <= later.start

    def test_detection_is_deterministic(self) -> None:
        text = "Forces moved in Kishtwar district and later in Bijapur."
        assert [s.model_dump() for s in find_place_candidates(text)] == [
            s.model_dump() for s in find_place_candidates(text)
        ]


class TestStateContext:
    def test_a_single_state_is_found(self) -> None:
        assert find_state_context("The incident was in Karnataka last week.") == "Karnataka"

    def test_two_states_give_no_context(self) -> None:
        # Picking the first would resolve "Bijapur" to whichever state the
        # sub-editor happened to mention earlier.
        assert find_state_context("Both Karnataka and Chhattisgarh reported incidents.") is None

    def test_no_state_gives_no_context(self) -> None:
        assert find_state_context("The road was closed.") is None

    def test_the_state_list_is_a_closed_set(self) -> None:
        assert len(STATES) == len(set(STATES))
        assert "Karnataka" in STATES and "Chhattisgarh" in STATES


class TestResolutionIsDelegated:
    def test_the_default_resolver_resolves_nothing(self) -> None:
        # A deliberately useless default: a pipeline without geography wired in
        # must produce visibly unresolved locations, not plausible wrong ones.
        assert isinstance(NullDistrictResolver(), DistrictResolver)
        mentions = extract_location_mentions("Forces moved in Kishtwar district.", as_of=CUTOFF)
        assert mentions
        assert all(mention.status is ResolutionStatus.UNRESOLVED for mention in mentions)
        assert all(mention.candidate_district_ids == () for mention in mentions)

    def test_an_injected_resolver_is_used(self) -> None:
        resolver = StubResolver({"Kishtwar": ("dist_kishtwar",)})
        mentions = extract_location_mentions(
            "Forces moved in Kishtwar district.", as_of=CUTOFF, resolver=resolver
        )
        resolved = [m for m in mentions if m.status is ResolutionStatus.RESOLVED]
        assert [m.candidate_district_ids for m in resolved] == [("dist_kishtwar",)]

    def test_an_ambiguous_place_stays_ambiguous(self) -> None:
        # Required behaviour 14. Bijapur names districts in two states, and
        # choosing one silently is how incidents get attributed to the wrong
        # half of the country.
        resolver = StubResolver({"Bijapur": ("dist_bijapur_ka", "dist_bijapur_cg")})
        mentions = extract_location_mentions(
            "The incident happened in Bijapur.", as_of=CUTOFF, resolver=resolver
        )
        ambiguous = [m for m in mentions if m.status is ResolutionStatus.AMBIGUOUS]
        assert len(ambiguous) == 1
        assert len(ambiguous[0].candidate_district_ids) == 2

    def test_the_resolver_is_told_the_as_of_date(self) -> None:
        # A district that split in 2022 has two correct answers depending on
        # the date, so the date is not optional.
        resolver = StubResolver()
        extract_location_mentions("Forces moved in Kishtwar.", as_of=CUTOFF, resolver=resolver)
        assert resolver.queries
        assert all(query.as_of == CUTOFF for query in resolver.queries)

    def test_the_resolver_is_told_the_language(self) -> None:
        resolver = StubResolver()
        extract_location_mentions(
            "Forces moved in Kishtwar.", as_of=CUTOFF, resolver=resolver, language="en"
        )
        assert all(query.language == "en" for query in resolver.queries)


class TestSearchWidening:
    def test_an_unknown_state_marks_the_search_as_widened(self) -> None:
        # Required behaviour 15. Searching all of India is permitted; doing it
        # silently is not.
        resolver = StubResolver()
        mentions = extract_location_mentions(
            "The incident happened in Bijapur.", as_of=CUTOFF, resolver=resolver
        )
        assert all(mention.search_widened for mention in mentions)
        assert all(query.widened for query in resolver.queries)

    def test_a_known_state_does_not_widen(self) -> None:
        resolver = StubResolver()
        mentions = extract_location_mentions(
            "The incident happened in Bijapur, Karnataka.", as_of=CUTOFF, resolver=resolver
        )
        assert not any(mention.search_widened for mention in mentions)
        assert all(mention.state_context == "Karnataka" for mention in mentions)

    def test_the_state_context_travels_to_the_resolver(self) -> None:
        resolver = StubResolver()
        extract_location_mentions(
            "The incident happened in Bijapur, Karnataka.", as_of=CUTOFF, resolver=resolver
        )
        assert all(query.state_context == "Karnataka" for query in resolver.queries)


class TestMentionInvariants:
    def test_a_resolved_mention_needs_exactly_one_candidate(self) -> None:
        with pytest.raises(ValueError, match="resolution means exactly one"):
            LocationMention(
                span=TextSpan(start=0, end=3, text="abc"),
                normalized_name="abc",
                candidate_district_ids=("a", "b"),
                status=ResolutionStatus.RESOLVED,
            )

    def test_an_ambiguous_mention_needs_more_than_one(self) -> None:
        with pytest.raises(ValueError, match="ambiguity means more than one"):
            LocationMention(
                span=TextSpan(start=0, end=3, text="abc"),
                normalized_name="abc",
                candidate_district_ids=("a",),
                status=ResolutionStatus.AMBIGUOUS,
            )

    def test_an_unresolved_mention_carries_no_candidates(self) -> None:
        # Otherwise it is ambiguity wearing the wrong label.
        with pytest.raises(ValueError, match="ambiguity wearing the wrong label"):
            LocationMention(
                span=TextSpan(start=0, end=3, text="abc"),
                normalized_name="abc",
                candidate_district_ids=("a",),
                status=ResolutionStatus.UNRESOLVED,
            )

    def test_a_naive_as_of_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            extract_location_mentions("in Kishtwar", as_of=datetime(2026, 3, 5))  # noqa: DTZ001

    def test_a_query_carries_everything_the_resolver_needs(self) -> None:
        query = LocationQuery(
            place_text="Bijapur",
            state_context=None,
            as_of=datetime(2026, 3, 5, tzinfo=UTC),
            language="en",
            widened=True,
        )
        assert query.widened is True
        assert query.state_context is None
