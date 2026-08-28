"""Time expressions anchored to publication, ambiguous where the text is."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from _nlp_builders import ANCHOR
from pramaanx.nlp.schemas import ResolutionStatus, TemporalKind, TemporalMention, TextSpan
from pramaanx.nlp.temporal import anchor_for, extract_temporal_mentions


def only(text: str, *, anchor: datetime = ANCHOR) -> TemporalMention:
    mentions = extract_temporal_mentions(text, anchor=anchor)
    assert len(mentions) == 1, [mention.span.text for mention in mentions]
    return mentions[0]


class TestAbsoluteDates:
    def test_an_iso_date_resolves(self) -> None:
        mention = only("The meeting is on 2026-03-04 in the district.")
        assert mention.kind is TemporalKind.ISO_DATE
        assert mention.resolution_status is ResolutionStatus.RESOLVED
        assert mention.normalized_start == datetime(2026, 3, 4, tzinfo=UTC)

    def test_a_month_name_date_resolves(self) -> None:
        mention = only("It happened on 4 March 2026 near the market.")
        assert mention.normalized_start == datetime(2026, 3, 4, tzinfo=UTC)

    def test_an_american_order_month_name_date_resolves(self) -> None:
        mention = only("It happened on March 4, 2026 near the market.")
        assert mention.normalized_start == datetime(2026, 3, 4, tzinfo=UTC)

    def test_a_missing_year_uses_the_anchor_year(self) -> None:
        mention = only("It happened on 4 March near the market.")
        assert mention.normalized_start == datetime(2026, 3, 4, tzinfo=UTC)

    def test_a_date_range_covers_both_ends(self) -> None:
        mention = only("Polls run 4-6 March in the district.")
        assert mention.kind is TemporalKind.DATE_RANGE
        assert mention.normalized_start == datetime(2026, 3, 4, tzinfo=UTC)
        assert mention.normalized_end == datetime(2026, 3, 7, tzinfo=UTC)

    def test_an_impossible_date_is_not_invented(self) -> None:
        assert extract_temporal_mentions("filed 2026-02-30 today", anchor=ANCHOR) == () or all(
            mention.kind is not TemporalKind.ISO_DATE
            for mention in extract_temporal_mentions("filed 2026-02-30", anchor=ANCHOR)
        )


class TestAmbiguityIsPreserved:
    def test_an_ambiguous_numeric_date_stays_ambiguous(self) -> None:
        # Required behaviour 13. 01/03/2026 is 1 March under Indian convention
        # and 3 January under American. Choosing the local one would be right
        # most of the time, which is what makes it dangerous.
        mention = only("The order is dated 01/03/2026 and was circulated.")
        assert mention.resolution_status is ResolutionStatus.AMBIGUOUS
        assert mention.normalized_start is None
        assert len(mention.candidate_interpretations) == 2
        assert "2026-01-03/2026-01-04" in mention.candidate_interpretations
        assert "2026-03-01/2026-03-02" in mention.candidate_interpretations

    def test_an_unambiguous_numeric_date_resolves(self) -> None:
        # 25 cannot be a month, so there is only one reading and nothing to
        # withhold.
        mention = only("The order is dated 25/03/2026 and was circulated.")
        assert mention.resolution_status is ResolutionStatus.RESOLVED
        assert mention.normalized_start == datetime(2026, 3, 25, tzinfo=UTC)

    def test_a_two_digit_year_is_expanded(self) -> None:
        mention = only("The order is dated 25/03/26 and was circulated.")
        assert mention.normalized_start == datetime(2026, 3, 25, tzinfo=UTC)

    def test_an_unqualified_weekday_stays_ambiguous(self) -> None:
        # "On Sunday" usually means the Sunday just gone, but "usually" is not
        # a basis for asserting a date.
        mention = only("Forces were deployed on Thursday in the district.")
        assert mention.kind is TemporalKind.WEEKDAY
        assert mention.resolution_status is ResolutionStatus.AMBIGUOUS
        assert len(mention.candidate_interpretations) == 2

    def test_a_qualified_weekday_resolves(self) -> None:
        mention = only("Forces were deployed last Thursday in the district.")
        assert mention.resolution_status is ResolutionStatus.RESOLVED
        assert mention.normalized_start is not None
        assert mention.normalized_start < ANCHOR

    def test_the_model_refuses_a_resolved_ambiguous_mention(self) -> None:
        # Enforced on the schema, so no extractor can quietly narrow one later.
        with pytest.raises(ValueError, match="carries a single normalised"):
            TemporalMention(
                span=TextSpan(start=0, end=3, text="abc"),
                kind=TemporalKind.NUMERIC_DATE,
                normalized_start=ANCHOR,
                resolution_status=ResolutionStatus.AMBIGUOUS,
                anchor_time=ANCHOR,
                candidate_interpretations=("a", "b"),
            )


class TestRelativeExpressions:
    def test_relative_days_use_the_publication_anchor(self) -> None:
        # Required behaviour 11.
        assert only("It happened yesterday.").normalized_start == datetime(2026, 2, 28, tzinfo=UTC)
        assert only("It happens tomorrow.").normalized_start == datetime(2026, 3, 2, tzinfo=UTC)

    def test_a_different_anchor_moves_the_answer(self) -> None:
        # The anchor is genuinely used, not decorative.
        later = ANCHOR + timedelta(days=10)
        assert only("It happened yesterday.", anchor=later).normalized_start == datetime(
            2026, 3, 10, tzinfo=UTC
        )

    def test_offsets_backwards_resolve(self) -> None:
        mention = only("The recovery was made three days ago.")
        assert mention.kind is TemporalKind.OFFSET_AGO
        assert mention.normalized_start == datetime(2026, 2, 26, tzinfo=UTC)

    def test_offsets_forwards_resolve(self) -> None:
        mention = only("The verdict is expected in two weeks.")
        assert mention.kind is TemporalKind.OFFSET_AHEAD
        assert mention.normalized_start == datetime(2026, 3, 15, tzinfo=UTC)

    def test_last_week_is_before_the_anchor(self) -> None:
        mention = only("The seizure was made last week.")
        assert mention.normalized_end is not None
        assert mention.normalized_end <= ANCHOR + timedelta(days=1)

    def test_next_week_is_after_the_anchor(self) -> None:
        mention = only("The meeting is scheduled next week.")
        assert mention.is_future_claim is True


class TestRetrospectiveAndFuture:
    def test_a_future_statement_is_marked_not_rejected(self) -> None:
        # An article describing the future is normal and useful; discarding it
        # would remove the most forecast-relevant sentences in the corpus.
        mention = only("Forces will be deployed in three days.")
        assert mention.is_future_claim is True
        assert mention.resolution_status is ResolutionStatus.RESOLVED

    def test_an_old_year_is_marked_retrospective(self) -> None:
        mention = only("The attacks in 2008 changed the city.")
        assert mention.kind is TemporalKind.YEAR
        assert mention.is_retrospective is True

    def test_a_current_year_reference_is_not_retrospective(self) -> None:
        mention = only("The policy was adopted in 2026.")
        assert mention.is_retrospective is False

    def test_vague_past_language_is_unresolved_and_retrospective(self) -> None:
        mention = only("The area was quiet previously.")
        assert mention.kind is TemporalKind.VAGUE_PAST
        assert mention.resolution_status is ResolutionStatus.UNRESOLVED
        assert mention.is_retrospective is True


class TestExtractionBehaviour:
    def test_spans_slice_the_original(self) -> None:
        text = "It happened on 4 March 2026, three days ago, in 2008."
        for mention in extract_temporal_mentions(text, anchor=ANCHOR):
            assert text[mention.span.start : mention.span.end] == mention.span.text

    def test_overlapping_matches_keep_the_longest(self) -> None:
        # "4 March 2026" must be one dated mention, not a date plus a bare year.
        mentions = extract_temporal_mentions("dated 4 March 2026 here", anchor=ANCHOR)
        assert len(mentions) == 1
        assert mentions[0].span.text == "4 March 2026"

    def test_mentions_are_returned_in_document_order(self) -> None:
        text = "Filed 2026-03-04, then yesterday, then in 2008."
        starts = [m.span.start for m in extract_temporal_mentions(text, anchor=ANCHOR)]
        assert starts == sorted(starts)

    def test_extraction_is_deterministic(self) -> None:
        text = "Filed 2026-03-04, then yesterday, then in 2008, on Thursday."
        first = [m.model_dump() for m in extract_temporal_mentions(text, anchor=ANCHOR)]
        second = [m.model_dump() for m in extract_temporal_mentions(text, anchor=ANCHOR)]
        assert first == second

    def test_a_naive_anchor_is_refused(self) -> None:
        # Required behaviour 25.
        with pytest.raises(ValueError, match="timezone-aware"):
            extract_temporal_mentions("yesterday", anchor=datetime(2026, 3, 1))  # noqa: DTZ001

    def test_text_with_no_dates_yields_nothing(self) -> None:
        assert extract_temporal_mentions("The road was closed.", anchor=ANCHOR) == ()


class TestAnchorSelection:
    def test_publication_time_is_preferred(self) -> None:
        published = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        resolvable = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
        assert anchor_for(published, resolvable) == published

    def test_first_resolvable_is_the_conservative_fallback(self) -> None:
        # Later than publication, so it can only pull a relative date forward,
        # never invent an earlier one.
        resolvable = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
        assert anchor_for(None, resolvable) == resolvable
