"""Offsets that survive transformation, or fail loudly.

An offset that is wrong by one is worse than one that is missing: it still
validates, still looks like a citation, and quotes the wrong characters. These
tests exist to make that state unreachable.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pramaanx.nlp.alignment import (
    AlignmentBuilder,
    AlignmentError,
    combining_clusters,
    identity_view,
    require_span,
)
from pramaanx.nlp.schemas import AlignedTextView, TextSpan


def builder(text: str) -> AlignmentBuilder:
    return AlignmentBuilder(text, transformation="test", version="1")


class TestTextSpan:
    def test_a_span_carries_exactly_what_it_covers(self) -> None:
        span = TextSpan.over("hello world", 6, 11)
        assert span.text == "world"
        assert span.verify_against("hello world")

    def test_offsets_and_text_may_not_disagree(self) -> None:
        with pytest.raises(ValidationError, match="offsets and the text disagree"):
            TextSpan(start=0, end=5, text="abc")

    def test_a_zero_width_span_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="empty or inverted"):
            TextSpan(start=3, end=3, text="")

    def test_an_inverted_span_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="empty or inverted"):
            TextSpan(start=5, end=2, text="")

    def test_a_span_out_of_range_is_refused(self) -> None:
        with pytest.raises(ValueError, match="does not fit"):
            TextSpan.over("short", 0, 99)

    def test_whitespace_at_a_span_edge_survives(self) -> None:
        # The base model strips strings. If that applied here, this span would
        # silently lose its trailing space and become wrong by one character
        # while still looking well-formed.
        span = TextSpan.over("a b c", 1, 3)
        assert span.text == " b"
        assert span.verify_against("a b c")

    def test_a_span_of_pure_whitespace_survives(self) -> None:
        span = TextSpan.over("a   b", 1, 4)
        assert span.text == "   "
        assert len(span.text) == 3


class TestBuilder:
    def test_identity_alignment_round_trips(self) -> None:
        view = identity_view("hello", transformation="id", version="1")
        assert view.transformed_text == "hello"
        span = view.to_original_span(1, 3)
        assert span is not None
        assert span.text == "el"

    def test_one_character_expanding_to_many_maps_to_the_whole_source(self) -> None:
        # Decomposition: one original character becomes several transformed
        # ones, and each must point back at the character it came from.
        build = builder("X")
        build.emit("abc", 0, 1)
        view = build.build()
        span = view.to_original_span(0, 3)
        assert span is not None
        assert (span.start, span.end) == (0, 1)

    def test_many_characters_composing_to_one_map_to_the_whole_range(self) -> None:
        # Composition is the case a single-index alignment gets wrong: mapping
        # back would truncate to the first character and quote half a grapheme.
        build = builder("ab")
        build.emit("c", 0, 2)
        view = build.build()
        span = view.to_original_span(0, 1)
        assert span is not None
        assert (span.start, span.end) == (0, 2)
        assert span.text == "ab"

    def test_a_dropped_range_is_recorded(self) -> None:
        build = builder("a-b")
        build.emit("a", 0, 1)
        build.drop(1, 2)
        build.emit("b", 2, 3)
        view = build.build()
        assert view.transformed_text == "ab"
        assert [(span.start, span.end) for span in view.removed_spans] == [(1, 2)]

    def test_dropping_does_not_shift_later_offsets(self) -> None:
        build = builder("a-b")
        build.emit("a", 0, 1)
        build.drop(1, 2)
        build.emit("b", 2, 3)
        view = build.build()
        span = view.to_original_span(1, 2)
        assert span is not None
        assert (span.start, span.end) == (2, 3)

    def test_inserted_characters_have_no_origin(self) -> None:
        build = builder("ab")
        build.emit("a", 0, 1)
        build.emit_unmapped("!")
        build.emit("b", 1, 2)
        view = build.build()
        assert view.to_original_span(1, 2) is None

    def test_a_range_of_only_inserted_characters_is_not_citable(self) -> None:
        build = builder("a")
        build.emit_unmapped("xyz")
        build.emit("a", 0, 1)
        view = build.build()
        assert view.to_original_span(0, 3) is None
        with pytest.raises(AlignmentError, match="maps to no original"):
            require_span(view, 0, 3)

    def test_a_mixed_range_maps_to_the_grounded_part(self) -> None:
        build = builder("ab")
        build.emit("a", 0, 1)
        build.emit_unmapped("!")
        build.emit("b", 1, 2)
        view = build.build()
        span = view.to_original_span(0, 3)
        assert span is not None
        assert (span.start, span.end) == (0, 2)

    def test_emitting_outside_the_original_is_refused(self) -> None:
        with pytest.raises(AlignmentError, match="does not fit"):
            builder("ab").emit("x", 0, 99)

    def test_dropping_outside_the_original_is_refused(self) -> None:
        with pytest.raises(AlignmentError, match="does not fit"):
            builder("ab").drop(0, 99)

    def test_empty_emissions_are_no_ops(self) -> None:
        build = builder("ab")
        build.emit("", 0, 1)
        build.emit_unmapped("")
        build.drop(1, 1)
        assert build.build().transformed_text == ""


class TestViewValidation:
    def test_an_alignment_shorter_than_its_text_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="does not cover the text"):
            AlignedTextView(
                original_text="abc",
                transformed_text="abc",
                transformed_to_original=(0, 1),
                transformed_to_original_end=(1, 2),
                transformation="t",
                transformation_version="1",
            )

    def test_a_half_known_origin_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="half-known origin"):
            AlignedTextView(
                original_text="abc",
                transformed_text="a",
                transformed_to_original=(0,),
                transformed_to_original_end=(None,),
                transformation="t",
                transformation_version="1",
            )

    def test_an_origin_outside_the_original_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="outside the original"):
            AlignedTextView(
                original_text="abc",
                transformed_text="a",
                transformed_to_original=(0,),
                transformed_to_original_end=(99,),
                transformation="t",
                transformation_version="1",
            )

    def test_a_range_outside_the_transformed_text_raises(self) -> None:
        view = identity_view("abc", transformation="id", version="1")
        with pytest.raises(ValueError, match="does not fit transformed text"):
            view.to_original_span(0, 99)


class TestCombiningClusters:
    def test_a_starter_and_its_marks_form_one_cluster(self) -> None:
        # "e" + combining acute is one cluster, so NFC over it is closed and
        # alignment can attribute the composed result to both characters.
        clusters = list(combining_clusters("éx"))
        assert [text for _, _, text in clusters] == ["é", "x"]

    def test_clusters_tile_the_input_exactly(self) -> None:
        text = "नई दिल्ली"
        clusters = list(combining_clusters(text))
        assert "".join(chunk for _, _, chunk in clusters) == text
        assert clusters[0][0] == 0
        assert clusters[-1][1] == len(text)

    def test_empty_text_yields_no_clusters(self) -> None:
        assert list(combining_clusters("")) == []
