"""Properties that must hold however the input arrives.

Syndication is where a forecasting system most easily invents evidence. Five
mastheads carrying one PTI file look, to any count-based feature, exactly like
five newsrooms independently confirming a story. The metamorphic property is
therefore stated as a relation rather than a value: multiplying copies of one
report must not increase measured independence, no matter how many copies
there are or what order they arrive in.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from _news_builders import WIRE_BODY, record, wire_copies
from pramaanx.ingest.article_content import (
    GroupingReason,
    LicenceClass,
    group_syndication,
)

RETRIEVED = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)


def distinct(count: int) -> list:  # type: ignore[type-arg]
    """``count`` genuinely different stories from ``count`` different outlets."""
    return [
        record(
            source_id=f"outlet_{index}",
            url=f"https://outlet{index}.test/story/{index}",
            headline=f"Distinct headline number {index}",
            body=f"An entirely separate account of a different event, number {index}, "
            f"written in different words about a different district entirely.",
        )
        for index in range(count)
    ]


class TestWireCopyDoesNotCreateIndependence:
    def test_five_wire_copies_are_one_information_lineage(self) -> None:
        # Required behaviour 3, and the reason this module exists.
        report = group_syndication(wire_copies(5))
        assert report.independent_lineage_count == 1
        assert len(report.groups) == 1
        assert report.groups[0].size == 5
        assert report.groups[0].wire_service == "PTI"

    @pytest.mark.parametrize("count", [2, 3, 5, 12, 40])
    def test_multiplying_copies_never_increases_independence(self, count: int) -> None:
        # The metamorphic relation itself: independence is invariant under
        # duplication. A distribution contract is not corroboration.
        one = group_syndication(wire_copies(1)).independent_lineage_count
        many = group_syndication(wire_copies(count)).independent_lineage_count
        assert many == one == 1

    def test_undeclared_syndication_is_still_caught(self) -> None:
        # An outlet that strips the agency credit is the common case, and the
        # one a wire-service field alone would miss. Identical text is identical
        # text whether or not anybody admits where it came from.
        report = group_syndication(wire_copies(4, wire=None))
        assert report.independent_lineage_count == 1
        assert GroupingReason.IDENTICAL_CONTENT in report.groups[0].reasons

    def test_lightly_edited_copy_is_still_one_lineage(self) -> None:
        # Outlets trim. A copy with a sentence cut is not a second witness.
        trimmed = record(
            source_id="outlet_trim",
            url="https://outlet-trim.test/story/1",
            headline="Explosives recovered in district search operation",
            body=WIRE_BODY + " Further details were awaited.",
            wire_service="PTI",
        )
        report = group_syndication([*wire_copies(3), trimmed])
        assert report.independent_lineage_count == 1

    def test_genuinely_different_reports_stay_independent(self) -> None:
        # The property has to cut both ways, or grouping could pass every test
        # above by collapsing everything into one group.
        report = group_syndication(distinct(4))
        assert report.independent_lineage_count == 4
        assert all(group.size == 1 for group in report.groups)

    def test_mixed_input_separates_wire_copy_from_original_reporting(self) -> None:
        report = group_syndication([*wire_copies(5), *distinct(3)])
        assert report.independent_lineage_count == 4

    def test_one_outlet_running_two_stories_is_not_syndicating_to_itself(self) -> None:
        # Similarity must never merge records from the same source: merging
        # them would understate that outlet's own output.
        first = record(source_id="outlet_a", url="https://a.test/1", body=WIRE_BODY)
        second = record(source_id="outlet_a", url="https://a.test/2", body=WIRE_BODY + " More.")
        report = group_syndication([first, second])
        assert len(report.groups) == 2


class TestSimilarityMerging:
    """The hardest case: syndication nobody declared, in text somebody edited.

    Identical bytes are easy. What actually arrives is a wire file with two
    sentences cut, a house headline, and no agency credit -- and it is still one
    story. These tests drive the similarity path directly, with an explicit
    threshold, because that is the path a lightly-edited copy takes.
    """

    def _edited_pair(self, wire: str | None) -> list:  # type: ignore[type-arg]
        original = record(
            source_id="outlet_a",
            url="https://outlet-a.test/story/1",
            headline="Explosives recovered in district search operation",
            body=WIRE_BODY,
            wire_service=wire,
        )
        edited = record(
            source_id="outlet_b",
            url="https://outlet-b.test/story/1",
            headline="Explosives recovered in district search operation",
            body=WIRE_BODY + " Further details were awaited at the time of going to press.",
            wire_service=wire,
        )
        return [original, edited]

    def test_edited_copy_merges_on_similarity_when_no_wire_is_declared(self) -> None:
        pair = self._edited_pair(wire=None)
        # Distinct text, so the exact-match pass cannot be what merges them.
        assert pair[0].content_group_hash != pair[1].content_group_hash
        report = group_syndication(pair, similarity_threshold=0.5)
        assert len(report.groups) == 1
        assert GroupingReason.HIGH_SIMILARITY in report.groups[0].reasons
        assert report.independent_lineage_count == 1

    def test_a_declared_wire_is_recorded_as_the_reason(self) -> None:
        report = group_syndication(self._edited_pair(wire="PTI"), similarity_threshold=0.5)
        assert GroupingReason.DECLARED_WIRE in report.groups[0].reasons
        assert report.groups[0].wire_service == "PTI"

    def test_below_the_threshold_they_stay_apart_as_documents(self) -> None:
        # Grouping is a claim about text. Above the threshold it is made,
        # below it is not -- and the default is deliberately strict.
        report = group_syndication(self._edited_pair(wire=None), similarity_threshold=0.99)
        assert len(report.groups) == 2

    def test_a_declared_wire_still_carries_lineage_across_separate_groups(self) -> None:
        # Even when the text has diverged too far to group, an agency credit on
        # both copies means one newsroom filed once. Lineage is the honest
        # count; grouping is only how the text clustered.
        report = group_syndication(self._edited_pair(wire="PTI"), similarity_threshold=0.99)
        assert len(report.groups) == 2
        assert report.independent_lineage_count == 1

    def test_a_group_with_two_different_declared_wires_claims_neither(self) -> None:
        # Two agencies credited on one clustered story is a contradiction, and
        # picking one would be a guess about provenance.
        pair = self._edited_pair(wire=None)
        conflicting = [
            pair[0].model_copy(update={"wire_service": "PTI"}),
            pair[1].model_copy(update={"wire_service": "ANI"}),
        ]
        report = group_syndication(conflicting, similarity_threshold=0.5)
        assert report.groups[0].wire_service is None

    def test_merging_a_chain_of_three_produces_one_group(self) -> None:
        # Transitivity through the union-find: A~B and B~C means one story,
        # even where A and C were never compared directly.
        chain = [
            record(
                source_id=f"outlet_{index}",
                url=f"https://outlet{index}.test/story/1",
                headline="Explosives recovered in district search operation",
                body=WIRE_BODY + (" Extra." * index),
            )
            for index in range(3)
        ]
        report = group_syndication(chain, similarity_threshold=0.5)
        assert len(report.groups) == 1
        assert report.groups[0].size == 3

    def test_a_record_with_no_text_at_all_does_not_merge_by_similarity(self) -> None:
        # An empty shingle set has nothing in common with anything, and must
        # not be treated as similar to everything.
        blank = record(
            source_id="outlet_blank",
            url="https://outlet-blank.test/1",
            headline=None,
            body=None,
            licence=LicenceClass.UNKNOWN,
        )
        report = group_syndication([blank, *self._edited_pair(wire=None)], similarity_threshold=0.5)
        assert any(group.size == 1 for group in report.groups)
        assert len(report.groups) == 2


class TestDeterminism:
    def test_grouping_is_deterministic_across_repeated_runs(self) -> None:
        # Required behaviour 4.
        records = [*wire_copies(5), *distinct(4)]
        first = group_syndication(records)
        for _ in range(5):
            assert group_syndication(records).model_dump() == first.model_dump()

    def test_grouping_is_invariant_under_input_order(self) -> None:
        # Required behaviour 11, on the grouping path. Shuffling the input must
        # not change a single byte of the result.
        records = [*wire_copies(5), *distinct(4)]
        baseline = group_syndication(records).model_dump()
        shuffler = random.Random(20260828)
        for _ in range(10):
            shuffled = list(records)
            shuffler.shuffle(shuffled)
            assert group_syndication(shuffled).model_dump() == baseline

    def test_group_and_lineage_ids_are_stable_across_runs(self) -> None:
        # Identifiers must come from content, never from a counter or a clock:
        # two runs over the same evidence have to name things identically or a
        # reproducibility test cannot tell a real change from a fresh draw.
        first = group_syndication(wire_copies(5)).groups[0]
        second = group_syndication(list(reversed(wire_copies(5)))).groups[0]
        assert first.group_id == second.group_id
        assert first.lineage_id == second.lineage_id

    def test_groups_are_returned_in_a_stable_order(self) -> None:
        records = [*wire_copies(3), *distinct(5)]
        identifiers = [group.group_id for group in group_syndication(records).groups]
        assert identifiers == sorted(identifiers)

    def test_members_within_a_group_are_sorted(self) -> None:
        group = group_syndication(wire_copies(5)).groups[0]
        assert list(group.member_observation_ids) == sorted(group.member_observation_ids)


class TestAssignmentPreservesOriginals:
    def test_assignment_annotates_without_rewriting(self) -> None:
        # Preserving the ungrouped record is what lets a later run re-group
        # under a different threshold and show what changed.
        records = wire_copies(3)
        before = [item.model_dump_json() for item in records]
        report = group_syndication(records)
        assigned = report.assigned(records)
        assert [item.model_dump_json() for item in records] == before
        assert all(item.syndication_group_id is not None for item in assigned)
        assert len({item.source_lineage_id for item in assigned}) == 1

    def test_assignment_does_not_change_record_identity(self) -> None:
        records = wire_copies(3)
        assigned = group_syndication(records).assigned(records)
        assert [item.article_content_hash for item in assigned] == [
            item.article_content_hash for item in records
        ]

    def test_a_record_outside_the_report_is_refused(self) -> None:
        report = group_syndication(wire_copies(2))
        with pytest.raises(KeyError, match="not in this syndication report"):
            report.group_for("art_nonexistent")


class TestGroupingEdgeCases:
    def test_an_empty_input_produces_an_empty_report(self) -> None:
        report = group_syndication([])
        assert report.groups == ()
        assert report.independent_lineage_count == 0

    def test_a_single_record_is_a_singleton_group(self) -> None:
        report = group_syndication([record()])
        assert report.groups[0].reasons == (GroupingReason.SINGLETON,)
        assert report.independent_lineage_count == 1

    def test_duplicate_observation_ids_are_refused(self) -> None:
        # Two records claiming the same identity is a bug upstream, and
        # silently deduplicating would hide it.
        duplicated = record()
        with pytest.raises(ValueError, match="duplicate observation ids"):
            group_syndication([duplicated, duplicated.model_copy()])

    @pytest.mark.parametrize("threshold", [0.0, -0.5, 1.5])
    def test_an_out_of_range_threshold_is_refused(self, threshold: float) -> None:
        with pytest.raises(ValueError, match="similarity_threshold"):
            group_syndication(wire_copies(2), similarity_threshold=threshold)

    def test_a_stricter_threshold_never_merges_more(self) -> None:
        # Monotonicity: raising the bar can only split groups, never join them.
        records = [*wire_copies(4), *distinct(3)]
        loose = group_syndication(records, similarity_threshold=0.5)
        strict = group_syndication(records, similarity_threshold=1.0)
        assert len(strict.groups) >= len(loose.groups)

    def test_records_with_no_body_do_not_all_collapse_together(self) -> None:
        # Every body-less record normalising to the same hash would make a
        # metadata-only source look like one enormous syndicated story.
        headline_only = [
            record(
                source_id=f"outlet_{index}",
                url=f"https://outlet{index}.test/{index}",
                headline=f"Distinct headline {index} about a separate district event",
                body=None,
            )
            for index in range(4)
        ]
        assert group_syndication(headline_only).independent_lineage_count == 4
