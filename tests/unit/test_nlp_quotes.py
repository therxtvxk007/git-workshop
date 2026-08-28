"""Quotations keep their attribution, or keep none at all."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from _nlp_builders import alias, registry_of
from pramaanx.nlp.actors import extract_actor_mentions
from pramaanx.nlp.quotes import extract_quotations
from pramaanx.nlp.schemas import AttributionStatus, QuotedStatement, TextSpan

WHEN = datetime(2026, 3, 5, tzinfo=UTC)


class TestQuoteDetection:
    def test_a_straight_double_quote_is_found(self) -> None:
        text = '"The road remains closed," the officer said.'
        quotes = extract_quotations(text)
        assert len(quotes) == 1
        assert quotes[0].quote_span.text == "The road remains closed,"

    def test_a_curly_quote_is_found(self) -> None:
        text = "“The road remains closed,” the officer said."
        assert len(extract_quotations(text)) == 1

    def test_the_quote_span_excludes_the_marks(self) -> None:
        text = '"The road remains closed," he said.'
        quote = extract_quotations(text)[0]
        assert not quote.quote_span.text.startswith('"')
        assert text[quote.quote_span.start : quote.quote_span.end] == quote.quote_span.text

    def test_journalist_prose_is_not_part_of_the_quotation(self) -> None:
        text = '"We are investigating," said the officer, adding that traffic was normal.'
        quote = extract_quotations(text)[0]
        assert "adding that traffic" not in quote.quote_span.text

    def test_an_apostrophe_is_not_a_quotation(self) -> None:
        # Below the minimum length, a pair of apostrophes is possessive or an
        # abbreviation far more often than it is a quote.
        assert extract_quotations("The officer's car and the driver's seat.") == ()

    def test_text_with_no_quotes_yields_nothing(self) -> None:
        assert extract_quotations("The road remains closed.") == ()

    def test_two_quotations_are_both_found(self) -> None:
        text = '"First statement here," he said. "Second statement here," she added.'
        assert len(extract_quotations(text)) == 2

    def test_spans_slice_the_original(self) -> None:
        text = '"The road remains closed," said Superintendent of Police Ravi Kumar.'
        for quote in extract_quotations(text):
            assert text[quote.quote_span.start : quote.quote_span.end] == quote.quote_span.text
            if quote.attribution_span is not None:
                span = quote.attribution_span
                assert text[span.start : span.end] == span.text


class TestAttribution:
    def test_a_trailing_attribution_is_captured(self) -> None:
        text = '"The road remains closed," said Ravi Kumar.'
        quote = extract_quotations(text)[0]
        assert quote.status is AttributionStatus.ATTRIBUTED
        assert quote.attribution_text == "Ravi Kumar"

    def test_a_designation_is_captured_with_the_name(self) -> None:
        # Capturing only the rank would attribute the claim to an office
        # rather than to the person the article credited.
        text = '"The road remains closed," said Superintendent of Police Ravi Kumar.'
        quote = extract_quotations(text)[0]
        assert quote.attribution_text is not None
        assert "Ravi Kumar" in quote.attribution_text

    def test_a_leading_attribution_is_captured(self) -> None:
        text = 'Ravi Kumar said, "The road remains closed for now."'
        quote = extract_quotations(text)[0]
        assert quote.status is AttributionStatus.ATTRIBUTED
        assert quote.attribution_text == "Ravi Kumar"

    def test_an_impersonal_attribution_is_still_an_attribution(self) -> None:
        # "according to police sources" credits something. It must not be
        # upgraded into a named person, and must not be discarded either.
        text = '"The road remains closed," according to police sources.'
        quote = extract_quotations(text)[0]
        assert quote.status is AttributionStatus.ATTRIBUTED
        assert quote.attributed_actor_id is None


class TestNoInventedSpeakers:
    def test_a_quote_with_no_attribution_stays_unattributed(self) -> None:
        # Required behaviour 17, and the rule that governs this module.
        text = 'The situation was tense. "The road remains closed for now."'
        quote = extract_quotations(text)[0]
        assert quote.status is AttributionStatus.UNATTRIBUTED
        assert quote.attribution_span is None
        assert quote.attributed_actor_id is None

    def test_a_nearby_named_person_is_not_borrowed(self) -> None:
        # The tempting heuristic: no "said X", so use the nearest name. It is
        # right often enough to be trusted and wrong often enough to matter.
        registry = registry_of(alias("Red Star Brigade", "actor_1"))
        text = 'The Red Star Brigade was active nearby. "The road remains closed for now."'
        actors = extract_actor_mentions(text, registry=registry, as_of=WHEN)
        quote = extract_quotations(text, actor_mentions=actors)[0]
        assert quote.status is AttributionStatus.UNATTRIBUTED
        assert quote.attributed_actor_id is None

    def test_an_actor_is_linked_only_when_it_is_the_attribution(self) -> None:
        registry = registry_of(alias("Red Star Brigade", "actor_1"))
        text = '"We carried out the action," said Red Star Brigade in a statement.'
        actors = extract_actor_mentions(text, registry=registry, as_of=WHEN)
        quote = extract_quotations(text, actor_mentions=actors)[0]
        assert quote.attributed_actor_id == "actor_1"

    def test_the_model_refuses_a_speaker_without_an_attribution_span(self) -> None:
        with pytest.raises(ValueError, match="is invented"):
            QuotedStatement(
                quote_span=TextSpan(start=0, end=5, text="abcde"),
                attributed_actor_id="actor_1",
                status=AttributionStatus.UNATTRIBUTED,
            )

    def test_the_model_refuses_an_attribution_with_no_span(self) -> None:
        with pytest.raises(ValueError, match="must point at the attribution"):
            QuotedStatement(
                quote_span=TextSpan(start=0, end=5, text="abcde"),
                status=AttributionStatus.ATTRIBUTED,
            )


class TestDeterminism:
    def test_extraction_is_repeatable(self) -> None:
        text = '"First statement here," he said. "Second statement here," she added.'
        assert [q.model_dump() for q in extract_quotations(text)] == [
            q.model_dump() for q in extract_quotations(text)
        ]

    def test_quotes_come_back_in_document_order(self) -> None:
        text = '"First statement here," he said. "Second statement here," she added.'
        starts = [q.quote_span.start for q in extract_quotations(text)]
        assert starts == sorted(starts)
