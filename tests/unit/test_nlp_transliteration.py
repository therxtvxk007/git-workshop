"""Transliteration is a matching aid. It is never the text, and never evidence."""

from __future__ import annotations

import pytest

from _nlp_builders import language_fixture
from pramaanx.nlp.transliterate import (
    SCHEME,
    TRANSLITERATION_VERSION,
    UNSUPPORTED_SCRIPTS,
    can_transliterate,
    script_base,
    transliterate,
    transliteration_key,
)

INDIC = ["Deva", "Beng", "Guru", "Gujr", "Orya", "Taml", "Telu", "Knda", "Mlym"]


class TestScope:
    @pytest.mark.parametrize("script", INDIC)
    def test_every_indic_script_is_transliterable(self, script: str) -> None:
        assert can_transliterate(script)
        assert script_base(script) is not None

    def test_latin_is_not_transliterated(self) -> None:
        assert transliterate("already latin", script_code="Latn") is None
        assert "Latn" in UNSUPPORTED_SCRIPTS

    def test_urdu_is_not_transliterated(self) -> None:
        # Urdu omits short vowels, so romanisation needs a lexicon rather than
        # a character map. A mechanical attempt would produce consonant
        # skeletons that collide with unrelated words -- worse than nothing,
        # because it would match aliases it should not.
        assert transliterate(language_fixture("ur")["text"], script_code="Arab") is None
        assert "Arab" in UNSUPPORTED_SCRIPTS

    def test_every_unsupported_script_says_why(self) -> None:
        assert all(reason.strip() for reason in UNSUPPORTED_SCRIPTS.values())


class TestOriginalIsUntouched:
    @pytest.mark.parametrize("code", ["hi", "bn", "ta", "ml", "te", "kn", "gu", "pa", "or"])
    def test_the_original_is_carried_unchanged(self, code: str) -> None:
        # Required behaviour 20.
        entry = language_fixture(code)
        view = transliterate(entry["text"], script_code=entry["script"])
        assert view is not None
        assert view.original_text == entry["text"]

    def test_the_scheme_and_version_are_recorded(self) -> None:
        view = transliterate("नई", script_code="Deva")
        assert view is not None
        assert view.transformation == SCHEME
        assert view.transformation_version == TRANSLITERATION_VERSION

    def test_the_result_is_latin(self) -> None:
        view = transliterate("पुलिस", script_code="Deva")
        assert view is not None
        assert view.transformed_text.isascii()


class TestAlignment:
    @pytest.mark.parametrize("code", ["hi", "bn", "ta", "ml", "te", "kn", "gu", "pa", "or"])
    def test_every_transliterated_range_maps_back_exactly(self, code: str) -> None:
        entry = language_fixture(code)
        text = entry["text"]
        view = transliterate(text, script_code=entry["script"])
        assert view is not None
        for index in range(len(view.transformed_text)):
            span = view.to_original_span(index, index + 1)
            if span is not None:
                assert text[span.start : span.end] == span.text

    def test_a_consonant_and_its_vowel_sign_map_as_one_cluster(self) -> None:
        # Mapping back must yield a complete cluster, not a consonant with its
        # vowel severed.
        view = transliterate("कि", script_code="Deva")
        assert view is not None
        span = view.to_original_span(0, len(view.transformed_text))
        assert span is not None
        assert span.text == "कि"

    def test_a_virama_suppresses_the_inherent_vowel(self) -> None:
        with_vowel = transliterate("क", script_code="Deva")
        without = transliterate("क्", script_code="Deva")
        assert with_vowel is not None and without is not None
        assert with_vowel.transformed_text == "ka"
        assert without.transformed_text == "k"

    def test_latin_inside_indic_text_passes_through_aligned(self) -> None:
        # Code-mixed reporting must transliterate without losing its English.
        text = "पुलिस SP"
        view = transliterate(text, script_code="Deva")
        assert view is not None
        assert "SP" in view.transformed_text
        index = view.transformed_text.index("SP")
        span = view.to_original_span(index, index + 2)
        assert span is not None
        assert span.text == "SP"


class TestMatchingUse:
    def test_the_same_word_in_two_scripts_shares_a_prefix(self) -> None:
        # The job transliteration exists for: one alias matching several
        # scripts, instead of a registry enumerating each.
        devanagari = transliteration_key("पुलिस", script_code="Deva")
        assert devanagari.startswith("pulis")

    def test_the_key_is_case_folded(self) -> None:
        assert transliteration_key("SP", script_code="Deva") == "sp"

    def test_an_unsupported_script_falls_back_to_the_original(self) -> None:
        # One code path for the caller, rather than a conditional that silently
        # skips Urdu.
        assert transliteration_key("ABC", script_code="Arab") == "abc"


class TestDeterminism:
    def test_transliteration_is_repeatable(self) -> None:
        text = language_fixture("hi")["text"]
        first = transliterate(text, script_code="Deva")
        second = transliterate(text, script_code="Deva")
        assert first is not None and second is not None
        assert first.model_dump() == second.model_dump()

    def test_the_indic_offset_table_is_shared_across_scripts(self) -> None:
        # ka is at offset 0x15 in every Indic block, which is why one table
        # serves nine scripts. If this stopped holding, nine tables would have
        # drifted apart instead.
        for script, first_consonant in (
            ("Deva", "क"),
            ("Beng", "ক"),
            ("Guru", "ਕ"),
            ("Gujr", "ક"),
            ("Orya", "କ"),
            ("Taml", "க"),
            ("Telu", "క"),
            ("Knda", "ಕ"),
            ("Mlym", "ക"),
        ):
            view = transliterate(first_consonant, script_code=script)
            assert view is not None, script
            assert view.transformed_text == "ka", script
