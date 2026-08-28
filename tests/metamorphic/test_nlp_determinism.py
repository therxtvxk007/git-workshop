"""Properties that must hold under transformations that should change nothing.

Metamorphic tests catch the class of bug that unit tests structurally cannot:
the pipeline is *self-consistent* and *wrong*, in a way that only shows up when
the same input arrives differently ordered, differently spelled, or with an
invisible character inserted. Each test below applies a transformation whose
correct effect on the output is known exactly -- usually "none at all".
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime

import pytest

from _news_builders import record
from _nlp_builders import ANCHOR, CUTOFF, alias, language_codes, language_fixture, registry_of
from pramaanx.nlp.actors import ActorAliasRegistry
from pramaanx.nlp.normalize import normalise
from pramaanx.nlp.pipeline import (
    NlpOptions,
    batch_hash,
    document_text,
    run_batch,
    run_deterministic_nlp,
)
from pramaanx.nlp.sentence import segment_sentences
from pramaanx.nlp.temporal import extract_temporal_mentions

BODY = (
    "Security forces recovered an IED near the market in Kishtwar on 4 March 2026, "
    'police said. "We are still investigating," said Ravi Kumar.'
)


def article(index: int = 0, *, body: str = BODY):  # type: ignore[no-untyped-def]
    return record(
        url=f"https://example.test/story/{index}",
        headline="IED recovered in district search",
        body=body,
    )


class TestOrderInvariance:
    def test_reordering_a_batch_produces_identical_bytes(self) -> None:
        # Required behaviour 5. Not "the same set" -- the same bytes, because a
        # reproducibility claim that tolerates reordering cannot detect one.
        records = tuple(article(index) for index in range(5))
        forward = run_batch(records, cutoff=CUTOFF)
        backward = run_batch(tuple(reversed(records)), cutoff=CUTOFF)
        assert batch_hash(forward) == batch_hash(backward)
        assert [r.model_dump() for r in forward] == [r.model_dump() for r in backward]

    def test_reordering_the_alias_registry_changes_nothing(self) -> None:
        # Required behaviour 23.
        entries = [
            alias("Red Star Brigade", "actor_1"),
            alias("RSB", "actor_1"),
            alias("Blue Front", "actor_2"),
        ]
        rec = article(body="The RSB and the Blue Front spoke; Red Star Brigade denied it.")
        forward = run_deterministic_nlp(
            rec,
            cutoff=CUTOFF,
            options=NlpOptions(actor_registry=ActorAliasRegistry.from_entries(entries)),
        )
        backward = run_deterministic_nlp(
            rec,
            cutoff=CUTOFF,
            options=NlpOptions(actor_registry=ActorAliasRegistry.from_entries(reversed(entries))),
        )
        assert forward.output_hash == backward.output_hash

    def test_a_duplicate_record_does_not_duplicate_output(self) -> None:
        records = (article(0), article(0))
        assert len(run_batch(records, cutoff=CUTOFF)) == 1


class TestRepeatability:
    def test_the_same_input_gives_the_same_output_hash(self) -> None:
        # Required behaviour 24.
        rec = article()
        assert run_deterministic_nlp(rec, cutoff=CUTOFF).output_hash == (
            run_deterministic_nlp(rec, cutoff=CUTOFF).output_hash
        )

    @pytest.mark.parametrize("code", language_codes())
    def test_repeatable_in_every_supported_language(self, code: str) -> None:
        rec = article(body=language_fixture(code)["text"])
        first = run_deterministic_nlp(rec, cutoff=CUTOFF)
        second = run_deterministic_nlp(rec, cutoff=CUTOFF)
        assert first.output_hash == second.output_hash

    def test_identifiers_are_derived_not_drawn(self) -> None:
        # Two runs over the same evidence must produce the same identifiers, or
        # a reproducibility test cannot tell a real change from a fresh draw.
        assert article(0).observation_id == article(0).observation_id
        assert article(0).observation_id != article(1).observation_id


class TestInvisibleCharacters:
    def test_a_zero_width_space_does_not_move_evidence(self) -> None:
        # Required behaviour 4, as a property: the extracted words are the same
        # and every span still slices its own original.
        clean = "Security forces recovered an IED in Kishtwar district."
        dirty = "Security forces recovered an IED in Kish​twar district."

        clean_result = run_deterministic_nlp(article(body=clean), cutoff=CUTOFF)
        dirty_rec = article(body=dirty)
        dirty_result = run_deterministic_nlp(dirty_rec, cutoff=CUTOFF)

        dirty_text, _, _ = document_text(dirty_rec)
        assert dirty_result.verify_spans(dirty_text) == ()
        assert len(clean_result.sentence_spans) == len(dirty_result.sentence_spans)

    def test_a_zero_width_space_is_recorded_as_removed(self) -> None:
        view = normalise("Kish​twar")
        assert view.transformed_text == "Kishtwar"
        assert [span.text for span in view.removed_spans] == ["​"]

    def test_an_inserted_invisible_shifts_offsets_but_not_meaning(self) -> None:
        # The offsets in the dirty document are genuinely different -- that is
        # correct. What must not differ is which characters the spans quote.
        dirty_rec = article(body="Forces reached Kish​twar district on Sunday.")
        text, _, _ = document_text(dirty_rec)
        result = run_deterministic_nlp(dirty_rec, cutoff=CUTOFF)
        for mention in result.location_mentions:
            assert text[mention.span.start : mention.span.end] == mention.span.text


class TestNormalisationInvariance:
    @pytest.mark.parametrize("code", language_codes())
    def test_decomposed_input_normalises_to_the_composed_form(self, code: str) -> None:
        # Required behaviour 2, as a property across every script: the same
        # text composed two ways must reach the same canonical form.
        text = language_fixture(code)["text"]
        composed = unicodedata.normalize("NFC", text)
        decomposed = unicodedata.normalize("NFD", text)
        assert normalise(composed).transformed_text == normalise(decomposed).transformed_text

    def test_sentence_counts_survive_decomposition(self) -> None:
        text = language_fixture("hi")["text"]
        assert len(segment_sentences(unicodedata.normalize("NFC", text))) == len(
            segment_sentences(unicodedata.normalize("NFD", text))
        )

    def test_curly_and_straight_quotes_reach_the_same_canonical_form(self) -> None:
        assert normalise("“quoted”").transformed_text == normalise('"quoted"').transformed_text


class TestAnchorSensitivity:
    def test_moving_the_anchor_moves_relative_dates_only(self) -> None:
        # Absolute dates are anchor-invariant; relative ones are not. If an
        # absolute date moved with the anchor, the extractor would be resolving
        # it from context rather than reading it.
        text = "It happened on 4 March 2026, which was yesterday."
        early = extract_temporal_mentions(text, anchor=ANCHOR)
        later = extract_temporal_mentions(text, anchor=datetime(2026, 6, 1, tzinfo=UTC))

        absolute_early = [m for m in early if m.kind.value == "month_name_date"]
        absolute_later = [m for m in later if m.kind.value == "month_name_date"]
        assert [m.normalized_start for m in absolute_early] == [
            m.normalized_start for m in absolute_later
        ]

        relative_early = [m for m in early if m.kind.value == "relative_day"]
        relative_later = [m for m in later if m.kind.value == "relative_day"]
        assert [m.normalized_start for m in relative_early] != [
            m.normalized_start for m in relative_later
        ]


class TestContentInvariance:
    def test_renaming_an_actor_alias_does_not_change_other_extractions(self) -> None:
        rec = article(body="The Red Star Brigade attacked a post in Kishtwar district.")
        without = run_deterministic_nlp(rec, cutoff=CUTOFF)
        with_actors = run_deterministic_nlp(
            rec,
            cutoff=CUTOFF,
            options=NlpOptions(actor_registry=registry_of(alias("Red Star Brigade", "a1"))),
        )
        assert without.sentence_spans == with_actors.sentence_spans
        assert without.location_mentions == with_actors.location_mentions
        assert with_actors.actor_mentions and not without.actor_mentions

    def test_a_protected_trait_substitution_does_not_change_the_screen(self) -> None:
        # The same facts with different people in them must screen identically.
        base = article(body="Two men were arrested for chain snatching near the market.")
        variant = article(body="Two Muslim men were arrested for chain snatching near the market.")
        assert (
            run_deterministic_nlp(base, cutoff=CUTOFF).ordinary_crime_assessment.verdict
            is run_deterministic_nlp(variant, cutoff=CUTOFF).ordinary_crime_assessment.verdict
        )
