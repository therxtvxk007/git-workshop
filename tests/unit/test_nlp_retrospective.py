"""Recollection is marked, never filtered."""

from __future__ import annotations

import itertools

import pytest

from pramaanx.nlp.retrospective import (
    CUES,
    find_retrospective_spans,
    is_probably_retrospective,
    retrospective_kinds,
)


class TestDetection:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("The 10th anniversary of the attack was marked on Sunday.", "anniversary"),
            ("A memorial service was held and officials paid tribute.", "memorial"),
            ("The court sentenced three men after a long trial.", "judicial"),
            ("The chargesheet named four accused.", "judicial"),
            ("The probe into the blast was reopened last month.", "investigation"),
            ("Looking back, residents recalled the night clearly.", "recall"),
            ("A documentary on the events premiered this week.", "documentary"),
            ("It later emerged that the toll had risen.", "later_reporting"),
            ("A timeline of what happened in the district was published.", "summary"),
        ],
    )
    def test_each_cue_family_is_detected(self, text: str, kind: str) -> None:
        # Required behaviour 18.
        assert kind in retrospective_kinds(text)
        assert find_retrospective_spans(text)

    def test_ordinary_current_reporting_is_not_marked(self) -> None:
        assert find_retrospective_spans("Forces were deployed in the district today.") == ()
        assert retrospective_kinds("Forces were deployed in the district today.") == ()


class TestSpans:
    def test_spans_slice_the_original(self) -> None:
        text = "The 10th anniversary of the attack: a documentary premiered, and the trial ended."
        for span in find_retrospective_spans(text):
            assert text[span.start : span.end] == span.text

    def test_spans_do_not_overlap(self) -> None:
        # "10th anniversary of the" would otherwise yield nested spans, making
        # the output depend on cue ordering rather than on the text.
        text = "The 10th anniversary of the attack was marked."
        spans = find_retrospective_spans(text)
        for earlier, later in itertools.pairwise(spans):
            assert earlier.end <= later.start

    def test_spans_come_back_in_document_order(self) -> None:
        text = "A documentary aired. The 5th anniversary followed. The verdict came later."
        starts = [span.start for span in find_retrospective_spans(text)]
        assert starts == sorted(starts)

    def test_detection_is_deterministic(self) -> None:
        text = "A documentary aired. The 5th anniversary followed. The verdict came later."
        assert [s.model_dump() for s in find_retrospective_spans(text)] == [
            s.model_dump() for s in find_retrospective_spans(text)
        ]


class TestFeatureNotFilter:
    def test_one_cue_is_a_signal_not_a_verdict(self) -> None:
        # "the aftermath of the blast" appears in same-day coverage, so a
        # single marker cannot be allowed to condemn an article.
        text = "In the aftermath of the blast, security was tightened across the city."
        assert find_retrospective_spans(text)
        assert is_probably_retrospective(text) is False

    def test_several_independent_cues_do_make_a_verdict(self) -> None:
        text = (
            "On the 10th anniversary of the attack, a documentary was screened and "
            "the trial court delivered its verdict."
        )
        assert is_probably_retrospective(text) is True

    def test_a_retrospective_frame_around_current_facts_is_still_returned(self) -> None:
        # The article does both jobs. Rejecting it loses the current fact;
        # ignoring the frame dates the fact to the wrong decade. Marking is the
        # only option that keeps both.
        text = "On the anniversary of the 2008 attacks, security was tightened across the city."
        spans = find_retrospective_spans(text)
        assert spans
        assert "security was tightened" in text

    def test_kinds_are_sorted_and_unique(self) -> None:
        text = "The 5th anniversary and the 10th anniversary were both marked."
        kinds = retrospective_kinds(text)
        assert list(kinds) == sorted(set(kinds))

    def test_every_declared_cue_has_a_kind_and_a_pattern(self) -> None:
        assert CUES
        assert all(cue.kind and cue.pattern for cue in CUES)
