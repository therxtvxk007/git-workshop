"""Sentence spans that slice the original exactly, in every script."""

from __future__ import annotations

import itertools

import pytest

from _nlp_builders import edge_case, language_codes, language_fixture
from pramaanx.nlp.sentence import TERMINATORS, segment_sentences, sentence_containing


class TestSpansAreExact:
    @pytest.mark.parametrize("code", language_codes())
    def test_every_sentence_slices_the_original(self, code: str) -> None:
        # Required behaviour 1, for all thirteen languages. Segmentation runs on
        # the original rather than the normalised view precisely so this cannot
        # depend on an alignment being right.
        text = language_fixture(code)["text"]
        for span in segment_sentences(text):
            assert text[span.start : span.end] == span.text

    @pytest.mark.parametrize("name", ["mixed_script", "zero_width", "abbreviations", "danda"])
    def test_edge_cases_slice_exactly(self, name: str) -> None:
        text = edge_case(name)
        for span in segment_sentences(text):
            assert text[span.start : span.end] == span.text

    def test_spans_do_not_overlap_and_advance(self) -> None:
        text = language_fixture("en")["text"]
        spans = segment_sentences(text)
        for earlier, later in itertools.pairwise(spans):
            assert earlier.end <= later.start


class TestTerminators:
    @pytest.mark.parametrize("code", language_codes())
    def test_each_language_splits_into_its_expected_sentences(self, code: str) -> None:
        entry = language_fixture(code)
        assert len(segment_sentences(entry["text"])) == entry["sentences"]

    def test_the_danda_terminates(self) -> None:
        # Its absence from a Latin-only terminator set is the standard way an
        # Indic segmenter returns one enormous sentence per paragraph.
        assert len(segment_sentences(edge_case("danda"))) == 3

    def test_the_urdu_full_stop_terminates(self) -> None:
        assert len(segment_sentences(language_fixture("ur")["text"])) == 2

    def test_the_terminator_set_covers_indic_and_urdu(self) -> None:
        assert {"\u0964", "\u0965", "\u06d4", "\u061f"} <= TERMINATORS


class TestThingsThatAreNotBoundaries:
    def test_honorifics_initials_and_decimals_do_not_split(self) -> None:
        # "Dr. R. K. Sharma met Shri Verma at 3.30 p.m." is one sentence, and
        # every one of those full stops is a chance to get it wrong.
        text = edge_case("abbreviations")
        assert len(segment_sentences(text)) == 2

    def test_a_dotted_abbreviation_does_not_strand_a_fragment(self) -> None:
        spans = segment_sentences("The meeting ran to 4.30 p.m. Everyone left.")
        assert len(spans) == 2
        assert spans[1].text == "Everyone left."

    def test_a_mid_sentence_ellipsis_does_not_split(self) -> None:
        assert len(segment_sentences(edge_case("ellipsis"))) == 2

    def test_a_terminal_ellipsis_does_split(self) -> None:
        spans = segment_sentences("He stopped speaking... The room stayed quiet.")
        assert len(spans) == 2

    def test_a_decimal_number_does_not_split(self) -> None:
        assert len(segment_sentences("The figure was 3.5 per cent.")) == 1

    def test_a_dotted_date_does_not_split(self) -> None:
        assert len(segment_sentences("It happened on 01.03.2026 in the district.")) == 1


class TestQuotesAndBreaks:
    def test_a_closing_quote_stays_with_its_sentence(self) -> None:
        text = edge_case("quote_with_terminator")
        spans = segment_sentences(text)
        assert len(spans) == 2
        assert spans[0].text.endswith("said.")

    def test_a_newline_is_a_boundary(self) -> None:
        # Feed-supplied text uses line breaks where a human would use a stop.
        spans = segment_sentences("First line with no stop\nSecond line")
        assert len(spans) == 2

    def test_blank_lines_do_not_produce_empty_sentences(self) -> None:
        spans = segment_sentences("First.\n\n\nSecond.")
        assert len(spans) == 2
        assert all(span.text.strip() for span in spans)

    def test_mixed_script_is_segmented_without_damage(self) -> None:
        # Required behaviour 9.
        text = edge_case("mixed_script")
        spans = segment_sentences(text)
        assert len(spans) == 2
        assert "the road was closed" in spans[0].text
        assert all(text[span.start : span.end] == span.text for span in spans)


class TestEdges:
    def test_empty_and_blank_text_yield_nothing(self) -> None:
        assert segment_sentences("") == ()
        assert segment_sentences("   \n  ") == ()

    def test_text_with_no_terminator_is_one_sentence(self) -> None:
        assert len(segment_sentences("no terminator here")) == 1

    def test_output_is_deterministic(self) -> None:
        text = language_fixture("hi")["text"]
        assert [span.model_dump() for span in segment_sentences(text)] == [
            span.model_dump() for span in segment_sentences(text)
        ]

    def test_sentence_containing_finds_the_covering_span(self) -> None:
        text = language_fixture("en")["text"]
        spans = segment_sentences(text)
        assert sentence_containing(spans, 0) == spans[0]
        assert sentence_containing(spans, len(text) + 50) is None
