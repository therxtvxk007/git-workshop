"""Script is observed; language is inferred. The tests keep them apart.

The failure being guarded against is specific and quiet: a pipeline that reads
Devanagari as Hindi produces per-language coverage numbers that look excellent
and are wrong for every Marathi article in the corpus.
"""

from __future__ import annotations

import pytest

from _nlp_builders import edge_case, language_codes, language_fixture
from pramaanx.nlp.language import (
    SCRIPT_TO_LANGUAGES,
    SUPPORTED_LANGUAGES,
    LanguageDetector,
    ScriptHeuristicDetector,
    assess_language,
)
from pramaanx.nlp.schemas import LanguageAssessment
from pramaanx.nlp.script import (
    SCRIPT_UNKNOWN,
    detect_scripts,
    dominant_script,
    is_mixed_script,
    script_counts,
    script_of_char,
)


class TestScriptDetection:
    @pytest.mark.parametrize("code", language_codes())
    def test_every_supported_language_detects_its_script(self, code: str) -> None:
        entry = language_fixture(code)
        assert dominant_script(entry["text"]) == entry["script"]

    def test_all_thirteen_languages_have_a_fixture(self) -> None:
        # The claim "thirteen languages are represented" is only worth what the
        # fixtures cover, so the fixture set is asserted against the declared
        # list rather than trusted to keep up with it.
        assert set(language_codes()) == set(SUPPORTED_LANGUAGES)

    def test_digits_and_punctuation_have_no_script(self) -> None:
        # Letting them vote would make a Hindi article containing a phone
        # number look partly Latin.
        for char in "0123456789 .,!?-()":
            assert script_of_char(char) is None

    def test_text_with_no_letters_is_unknown_not_latin(self) -> None:
        assert dominant_script("12345 !!! ...") == SCRIPT_UNKNOWN
        assert detect_scripts("12345 !!!") == ()

    def test_mixed_script_reports_both(self) -> None:
        text = edge_case("mixed_script")
        scripts = detect_scripts(text)
        assert set(scripts) == {"Deva", "Latn"}
        assert is_mixed_script(text)

    def test_a_stray_abbreviation_does_not_make_a_document_bilingual(self) -> None:
        # One Latin token in a Malayalam article is not code-mixing, and
        # reporting it as such would make every Indian-language article look
        # partly English.
        text = language_fixture("ml")["text"] + " SP"
        assert detect_scripts(text) == ("Mlym",)

    def test_counts_are_ordered_and_deterministic(self) -> None:
        counts = script_counts(edge_case("mixed_script"))
        assert list(counts.values()) == sorted(counts.values(), reverse=True)
        assert script_counts(edge_case("mixed_script")) == counts

    def test_zero_width_joiners_do_not_vote(self) -> None:
        # They are orthographically meaningful but say nothing about which
        # script, so they must not tip a count.
        assert script_of_char("‍") is None
        assert script_of_char("‌") is None


class TestLanguageIsNotScript:
    def test_devanagari_does_not_imply_hindi(self) -> None:
        # Required behaviour 8, and the single most consequential test here.
        assessment = assess_language(language_fixture("hi")["text"])
        assert assessment.script_codes == ("Deva",)
        assert assessment.ambiguous is True
        assert assessment.language_code is None
        assert set(assessment.candidate_language_codes) == {"hi", "mr"}

    def test_marathi_gets_the_same_ambiguous_answer_as_hindi(self) -> None:
        # If these differed, the detector would be guessing from something
        # other than the script -- and doing it silently.
        hindi = assess_language(language_fixture("hi")["text"])
        marathi = assess_language(language_fixture("mr")["text"])
        assert hindi.candidate_language_codes == marathi.candidate_language_codes

    def test_bengali_script_stays_open_between_bengali_and_assamese(self) -> None:
        assessment = assess_language(language_fixture("bn")["text"])
        assert assessment.ambiguous is True
        assert set(assessment.candidate_language_codes) == {"bn", "as"}

    @pytest.mark.parametrize("code", ["ml", "ta", "te", "kn", "gu", "pa", "or", "ur"])
    def test_a_script_carrying_one_language_resolves(self, code: str) -> None:
        assessment = assess_language(language_fixture(code)["text"])
        assert assessment.language_code == code
        assert assessment.ambiguous is False

    def test_a_resolved_language_is_never_fully_confident(self) -> None:
        # The scope is an assumption: Devanagari Nepali and Malayalam-script
        # Sanskrit both exist outside it.
        assessment = assess_language(language_fixture("ta")["text"])
        assert assessment.confidence is not None
        assert assessment.confidence < 1.0

    def test_every_script_mapping_names_only_supported_languages(self) -> None:
        for languages in SCRIPT_TO_LANGUAGES.values():
            assert set(languages) <= set(SUPPORTED_LANGUAGES)


class TestEnglishVersusRomanised:
    def test_english_is_recognised_from_function_words(self) -> None:
        assessment = assess_language(language_fixture("en")["text"])
        assert assessment.language_code == "en"
        assert assessment.ambiguous is False

    def test_romanised_indian_text_is_not_called_english(self) -> None:
        # Latin script is not English. Calling it English routes it to an
        # English-only extractor that finds nothing and reports no problem.
        assessment = assess_language("police ne bataya ki sadak band thi")
        assert assessment.language_code is None
        assert assessment.ambiguous is True

    def test_text_with_no_words_at_all_is_unknown(self) -> None:
        assessment = assess_language("123 456 789")
        assert assessment.language_code is None
        assert assessment.ambiguous is False


class TestDeclaredLanguage:
    def test_a_declared_language_can_disambiguate(self) -> None:
        assessment = assess_language(language_fixture("mr")["text"], declared_language="mr")
        assert assessment.language_code == "mr"
        assert assessment.ambiguous is False

    def test_a_declared_language_cannot_override_the_script(self) -> None:
        # A feed mislabelling its Marathi section as Hindi is a real and common
        # error; it must not be able to relabel Tamil as Hindi.
        assessment = assess_language(language_fixture("ta")["text"], declared_language="hi")
        assert assessment.language_code == "ta"

    def test_a_declaration_outside_the_candidates_is_ignored(self) -> None:
        assessment = assess_language(language_fixture("hi")["text"], declared_language="fr")
        assert assessment.ambiguous is True
        assert assessment.language_code is None

    def test_disambiguation_lowers_confidence_below_direct_detection(self) -> None:
        # The answer now rests on the feed's own metadata, which is weaker
        # evidence than the characters.
        assessment = assess_language(language_fixture("hi")["text"], declared_language="hi")
        assert assessment.confidence is not None
        assert assessment.confidence <= 0.7


class TestDetectorProtocol:
    def test_the_default_detector_satisfies_the_protocol(self) -> None:
        assert isinstance(ScriptHeuristicDetector(), LanguageDetector)

    def test_an_injected_backend_is_used(self) -> None:
        class Stub:
            name = "stub"
            version = "1"

            def detect(self, text: str) -> LanguageAssessment:
                return LanguageAssessment(
                    language_code="xx", backend=self.name, backend_version=self.version
                )

        assert assess_language("anything", detector=Stub()).language_code == "xx"

    def test_an_ambiguous_assessment_must_name_its_candidates(self) -> None:
        # "ambiguous" with no alternatives is indistinguishable from "unknown"
        # and throws away what a reviewer would act on.
        with pytest.raises(ValueError, match="must name its candidates"):
            LanguageAssessment(ambiguous=True, backend="x", backend_version="1")

    def test_an_unambiguous_assessment_cannot_list_rivals(self) -> None:
        with pytest.raises(ValueError, match="claims to be"):
            LanguageAssessment(
                language_code="hi",
                ambiguous=False,
                candidate_language_codes=("hi", "mr"),
                backend="x",
                backend_version="1",
            )
