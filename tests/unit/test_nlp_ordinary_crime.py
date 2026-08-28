"""The screen keeps anything it cannot rule out, and never reads who is involved."""

from __future__ import annotations

import itertools

import pytest

from pramaanx.nlp.ordinary_crime import (
    FORBIDDEN_FEATURE_TERMS,
    ORDINARY_CRIME_TERMS,
    TARGET_FAMILY_TERMS,
    assess_ordinary_crime,
    lexicon_terms,
)
from pramaanx.nlp.schemas import CrimeVerdict, OrdinaryCrimeAssessment, TextSpan


class TestRecallProtection:
    def test_an_article_with_any_target_indicator_is_retained(self) -> None:
        # Required behaviour 19, stated at its most important: an IED recovery
        # inside an otherwise ordinary-crime story is kept.
        text = (
            "Police investigating a robbery case recovered an IED from the "
            "premises during the search."
        )
        assessment = assess_ordinary_crime(text)
        assert assessment.verdict is CrimeVerdict.POTENTIALLY_RELEVANT
        assert assessment.ordinary_crime_spans
        assert assessment.target_family_spans

    @pytest.mark.parametrize(
        "indicator",
        [
            "IED",
            "landmine",
            "grenade",
            "Maoist",
            "Naxal",
            "militant",
            "insurgent",
            "UAPA",
            "arms cache",
            "left-wing extremism",
        ],
    )
    def test_each_target_indicator_alone_retains_the_article(self, indicator: str) -> None:
        text = f"A theft was reported. Officials mentioned {indicator} in the area."
        assert assess_ordinary_crime(text).verdict is CrimeVerdict.POTENTIALLY_RELEVANT

    def test_pure_ordinary_crime_is_screened_out(self) -> None:
        text = "Two men were arrested for chain snatching near the market on Sunday."
        assessment = assess_ordinary_crime(text)
        assert assessment.verdict is CrimeVerdict.LIKELY_ORDINARY_CRIME
        assert assessment.target_family_spans == ()

    def test_unreadable_text_is_retained_not_discarded(self) -> None:
        # The lexicons are English-only, so silence usually means "this screen
        # could not read the article", which is not a finding about the article.
        assessment = assess_ordinary_crime("റോഡ് അടച്ചിരുന്നു എന്ന് ഉദ്യോഗസ്ഥൻ പറഞ്ഞു.")
        assert assessment.verdict is CrimeVerdict.INSUFFICIENT_EVIDENCE

    def test_neutral_text_is_retained(self) -> None:
        assessment = assess_ordinary_crime("The district administration reviewed arrangements.")
        assert assessment.verdict is CrimeVerdict.INSUFFICIENT_EVIDENCE
        assert assessment.ordinary_crime_spans == ()


class TestRejectionNeedsPositiveEvidence:
    def test_absence_of_terrorism_vocabulary_is_not_a_rejection(self) -> None:
        # The asymmetry the whole screen rests on: nothing is rejected for what
        # it fails to mention.
        assert assess_ordinary_crime("The road was resurfaced.").verdict is not (
            CrimeVerdict.LIKELY_ORDINARY_CRIME
        )

    def test_the_model_refuses_a_rejection_with_no_evidence(self) -> None:
        with pytest.raises(ValueError, match="absence of other vocabulary"):
            OrdinaryCrimeAssessment(
                verdict=CrimeVerdict.LIKELY_ORDINARY_CRIME, reason="nothing found"
            )

    def test_the_model_refuses_a_rejection_despite_a_target_indicator(self) -> None:
        with pytest.raises(ValueError, match="Any credible target-family indicator"):
            OrdinaryCrimeAssessment(
                verdict=CrimeVerdict.LIKELY_ORDINARY_CRIME,
                ordinary_crime_spans=(TextSpan(start=0, end=5, text="theft"),),
                target_family_spans=(TextSpan(start=6, end=9, text="ied"),),
                reason="mixed",
            )

    def test_a_verdict_always_carries_a_reason(self) -> None:
        assert assess_ordinary_crime("A burglary was reported.").reason


class TestProtectedTraits:
    def test_no_lexicon_contains_a_protected_trait_term(self) -> None:
        # There is no version of this system in which a community term belongs
        # in a threat lexicon -- including the version where it improves a
        # metric. Asserted rather than trusted, because a lexicon is exactly
        # the kind of list that grows by accretion.
        offenders = sorted(FORBIDDEN_FEATURE_TERMS & lexicon_terms())
        assert offenders == []

    def test_no_lexicon_term_contains_a_protected_trait_as_a_substring(self) -> None:
        offenders = sorted(
            f"{term} <- {forbidden}"
            for term in lexicon_terms()
            for forbidden in FORBIDDEN_FEATURE_TERMS
            if forbidden in term
        )
        assert offenders == []

    def test_community_terms_do_not_change_the_verdict(self) -> None:
        # The same facts with different people in them must screen identically.
        base = "Two men were arrested for chain snatching near the market."
        for trait in ["Hindu", "Muslim", "Dalit", "Bangladeshi", "tribal"]:
            variant = base.replace("Two men", f"Two {trait} men")
            assert assess_ordinary_crime(variant).verdict is assess_ordinary_crime(base).verdict

    def test_a_place_of_worship_does_not_raise_relevance(self) -> None:
        neutral = assess_ordinary_crime("A theft was reported near the building.")
        religious = assess_ordinary_crime("A theft was reported near the mosque.")
        assert neutral.verdict is religious.verdict


class TestSpansAndDeterminism:
    def test_spans_slice_the_original(self) -> None:
        text = "Police investigating a robbery recovered an IED and a landmine."
        assessment = assess_ordinary_crime(text)
        for span in assessment.ordinary_crime_spans + assessment.target_family_spans:
            assert text[span.start : span.end] == span.text

    def test_matching_is_case_insensitive(self) -> None:
        assert assess_ordinary_crime("An ied was recovered.").verdict is (
            CrimeVerdict.POTENTIALLY_RELEVANT
        )

    def test_an_indicator_does_not_fire_inside_a_word(self) -> None:
        # "ied" appears inside "occupied", "studied", "denied" and hundreds of
        # other words; without word boundaries this screen would retain the
        # entire corpus and prove nothing.
        assessment = assess_ordinary_crime("The building was occupied and the claim denied.")
        assert assessment.target_family_spans == ()

    def test_spans_do_not_overlap(self) -> None:
        text = "A landmine and an improvised explosive device were found."
        spans = assess_ordinary_crime(text).target_family_spans
        for earlier, later in itertools.pairwise(spans):
            assert earlier.end <= later.start

    def test_assessment_is_deterministic(self) -> None:
        text = "Police investigating a robbery recovered an IED near the post."
        assert assess_ordinary_crime(text).model_dump() == assess_ordinary_crime(text).model_dump()

    def test_the_lexicons_are_non_empty_and_disjoint(self) -> None:
        assert ORDINARY_CRIME_TERMS and TARGET_FAMILY_TERMS
        assert not set(ORDINARY_CRIME_TERMS) & set(TARGET_FAMILY_TERMS)
