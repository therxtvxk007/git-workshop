"""Canonical text that never loses its way back, and never edits meaning."""

from __future__ import annotations

import pytest

from _nlp_builders import edge_case, language_codes, language_fixture
from pramaanx.hashing import hash_text
from pramaanx.nlp.normalize import (
    NORMALIZATION_VERSION,
    normalise,
    normalised_key,
    original_text_hash,
)


class TestOriginalIsImmutable:
    @pytest.mark.parametrize("code", language_codes())
    def test_the_original_is_carried_unchanged(self, code: str) -> None:
        text = language_fixture(code)["text"]
        assert normalise(text).original_text == text

    def test_the_hash_is_of_the_original_not_the_normalised_form(self) -> None:
        # A normalised hash would match for two documents differing only in the
        # invisible characters this module strips -- which is exactly the
        # difference worth detecting.
        raw = edge_case("zero_width")
        assert original_text_hash(raw) == hash_text(raw)
        assert original_text_hash(raw) != hash_text(normalise(raw).transformed_text)

    def test_the_version_is_recorded(self) -> None:
        assert normalise("x").transformation_version == NORMALIZATION_VERSION


class TestAlignmentSurvivesNormalisation:
    @pytest.mark.parametrize("code", language_codes())
    def test_every_normalised_range_maps_back_exactly(self, code: str) -> None:
        # Required behaviour 2, across all thirteen scripts.
        text = language_fixture(code)["text"]
        view = normalise(text)
        for index in range(len(view.transformed_text)):
            span = view.to_original_span(index, index + 1)
            if span is not None:
                assert text[span.start : span.end] == span.text

    def test_zero_width_characters_cannot_shift_evidence(self) -> None:
        # Required behaviour 4. The word is intact in the normalised view, and
        # maps back to the original characters that spell it -- not to a range
        # shifted by the invisible ones that were removed.
        raw = edge_case("zero_width")
        view = normalise(raw)
        assert "district" in view.transformed_text
        start = view.transformed_text.index("district")
        span = view.to_original_span(start, start + len("district"))
        assert span is not None
        assert span.verify_against(raw)
        assert span.text.replace("­", "") == "district"

    def test_every_removal_is_recorded(self) -> None:
        raw = edge_case("zero_width")
        view = normalise(raw)
        removed = "".join(span.text for span in view.removed_spans)
        assert "​" in removed
        assert "­" in removed

    def test_repeated_substrings_do_not_confuse_the_mapping(self) -> None:
        # Required behaviour 3. Four identical tokens: a substring search would
        # find the first every time, which is why offsets are carried rather
        # than recovered.
        raw = edge_case("repeated_substring")
        view = normalise(raw)
        occurrences = []
        start = 0
        while (found := view.transformed_text.find("Kishtwar", start)) != -1:
            occurrences.append(found)
            start = found + 1
        assert len(occurrences) == 4
        spans = [view.to_original_span(found, found + len("Kishtwar")) for found in occurrences]
        starts = [span.start for span in spans if span is not None]
        assert len(set(starts)) == 4, "each occurrence must map to a distinct original offset"
        for span in spans:
            assert span is not None
            assert span.verify_against(raw)


class TestWhatNormalisationChanges:
    def test_unicode_composition_is_canonicalised(self) -> None:
        composed = normalise("é").transformed_text
        decomposed = normalise("é").transformed_text
        assert composed == decomposed

    def test_whitespace_runs_collapse_to_one_space(self) -> None:
        assert normalise("a    b").transformed_text == "a b"

    def test_line_breaks_are_preserved(self) -> None:
        # They are the most reliable sentence boundary in feed-supplied text;
        # collapsing them into spaces makes segmentation worse.
        assert normalise("a\nb").transformed_text == "a\nb"

    def test_a_whitespace_run_containing_a_break_becomes_one_break(self) -> None:
        # CRLF is one boundary, not two, and a run of blank lines is one
        # boundary rather than a boundary per line. Emitting per character
        # would multiply paragraph breaks the writer did not intend.
        assert normalise("a\r\nb").transformed_text == "a\nb"
        assert normalise("a\n\n\nb").transformed_text == "a\nb"
        assert normalise("a \n b").transformed_text == "a\nb"

    def test_leading_and_trailing_whitespace_is_dropped_not_emitted(self) -> None:
        view = normalise("  a  ")
        assert view.transformed_text == "a"
        assert len(view.removed_spans) == 2

    def test_curly_quotes_fold_to_straight(self) -> None:
        assert normalise("“hello”").transformed_text == '"hello"'

    def test_dashes_fold_to_hyphen(self) -> None:
        assert normalise("a—b").transformed_text == "a-b"

    def test_control_characters_are_removed(self) -> None:
        view = normalise("a\x00b")
        assert view.transformed_text == "ab"
        assert len(view.removed_spans) == 1


class TestWhatNormalisationMustNotChange:
    def test_indic_joiners_are_preserved(self) -> None:
        # ZWJ and ZWNJ decide whether a consonant cluster renders as a conjunct.
        # Removing them changes the word, not its appearance, so "punctuation
        # normalisation" must stop short of them.
        raw = edge_case("joiner_preserved")
        assert "‍" in raw
        assert "‍" in normalise(raw).transformed_text

    def test_digits_are_not_transliterated(self) -> None:
        # Converting Devanagari digits to ASCII would be a semantic edit, and
        # normalisation is a spelling operation.
        assert "१" in normalise("१२").transformed_text

    def test_nothing_is_translated(self) -> None:
        text = language_fixture("hi")["text"]
        view = normalise(text)
        assert any(0x0900 <= ord(char) <= 0x097F for char in view.transformed_text)

    def test_the_danda_survives(self) -> None:
        # The segmenter needs it; folding it to a full stop would work by
        # accident and break on the double danda.
        assert "।" in normalise("वाक्य।").transformed_text


class TestDeterminism:
    @pytest.mark.parametrize("code", language_codes())
    def test_normalisation_is_repeatable(self, code: str) -> None:
        text = language_fixture(code)["text"]
        assert normalise(text).model_dump() == normalise(text).model_dump()

    def test_normalisation_is_idempotent_on_its_own_output(self) -> None:
        once = normalise("  a—b  “c” ").transformed_text
        assert normalise(once).transformed_text == once

    def test_the_lookup_key_is_case_folded(self) -> None:
        assert normalised_key("  Kishtwar  ") == "kishtwar"
