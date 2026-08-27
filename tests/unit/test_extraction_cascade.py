"""Prose extraction: the cascade, its stages and its consensus."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from _phase2_builders import at, observation

from pramaanx.extraction import (
    ExtractionCascade,
    MentionCandidate,
    PatternStage,
    detect_event_types,
    detect_modality,
    extract_date,
    extract_location,
    resolve_text,
    split_sentences,
)
from pramaanx.extraction.cascade import BaseStage
from pramaanx.schemas.observation import Observation


class TestSegmentation:
    def test_splits_on_terminators(self) -> None:
        assert len(split_sentences("A clash occurred. Aid arrived later.")) == 2

    def test_does_not_split_on_abbreviations(self) -> None:
        assert len(split_sentences("Dr. Rao confirmed the report was accurate.")) == 1

    def test_empty_text_yields_nothing(self) -> None:
        assert split_sentences("   ") == []


class TestTriggersAndModality:
    def test_multiple_triggers_are_all_returned(self) -> None:
        found = detect_event_types("The airstrike killed twelve people in the village")
        assert "shelling" in found
        assert "killing" in found

    def test_denial_outranks_planning(self) -> None:
        assert detect_modality("Officials denied plans to withdraw troops") == "denied"

    def test_planned_outranks_hedging(self) -> None:
        assert detect_modality("The rally is scheduled for next week") == "planned"

    def test_hedged_claims_are_possible(self) -> None:
        assert detect_modality("Fighting reportedly broke out near the border") == "possible"

    def test_plain_report_is_asserted(self) -> None:
        assert detect_modality("Fighting broke out near the border") == "asserted"


class TestDates:
    def test_iso_date_is_taken_literally(self) -> None:
        found = extract_date("A clash on 2025-03-12", reference=at(400), allow_future=False)
        assert found is not None
        assert found.year == 2025
        assert found.month == 3

    def test_relative_dates_resolve_against_availability_not_a_clock(self) -> None:
        """"Yesterday" means the day before the document became available."""
        reference = at(100)
        found = extract_date("Fighting erupted yesterday", reference=reference, allow_future=False)
        assert found is not None
        assert (reference - found).days == 1

    def test_bare_dates_resolve_backwards_for_asserted_claims(self) -> None:
        reference = at(60)  # 2025-03-02
        found = extract_date("A clash on 12 December", reference=reference, allow_future=False)
        assert found is not None
        assert found < reference

    def test_bare_dates_may_resolve_forward_when_planned(self) -> None:
        reference = at(60)
        found = extract_date("The poll is scheduled for 12 December", reference=reference,
                             allow_future=True)
        assert found is not None
        assert found > reference

    def test_naive_reference_is_rejected(self) -> None:
        from datetime import datetime

        with pytest.raises(ValueError, match="timezone-aware"):
            extract_date("yesterday", reference=datetime(2025, 1, 1), allow_future=False)  # noqa: DTZ001

    def test_no_date_expression_returns_none(self) -> None:
        assert extract_date("A clash occurred", reference=at(10), allow_future=False) is None


class TestLocation:
    def test_marker_is_required(self) -> None:
        assert extract_location("Bastar saw fighting") is None
        assert extract_location("Fighting broke out in Bastar") == "Bastar"

    def test_longest_marker_wins(self) -> None:
        assert extract_location("Fighting in the district of Bastar") == "Bastar"


class TestCascade:
    def test_extracts_a_mention_from_prose(self) -> None:
        obs = observation(observed_days=100)
        text = "Security forces clashed with Maoist fighters in Bastar yesterday."
        mentions = ExtractionCascade().extract(obs, text)
        assert mentions
        assert mentions[0].event_type == "armed_clash"
        assert mentions[0].location_text == "Bastar"

    def test_observed_at_comes_from_the_observation(self) -> None:
        obs = observation(observed_days=100)
        mentions = ExtractionCascade().extract(obs, "A clash was reported in Bastar.")
        assert all(mention.observed_at == obs.first_observed_at for mention in mentions)

    def test_two_triggers_in_one_sentence_yield_distinct_ids(self) -> None:
        obs = observation(observed_days=100)
        text = "The airstrike killed twelve people in Kandahar on 12 March."
        mentions = ExtractionCascade().extract(obs, text)
        ids = {mention.mention_id for mention in mentions}
        assert len(ids) == len(mentions) >= 2

    def test_empty_text_yields_nothing(self) -> None:
        assert ExtractionCascade().extract(observation(observed_days=1), "   ") == []

    def test_untriggered_text_yields_nothing(self) -> None:
        obs = observation(observed_days=10)
        assert ExtractionCascade().extract(obs, "The committee published its annual budget.") == []

    def test_duplicate_stage_names_are_refused(self) -> None:
        with pytest.raises(ValueError, match="duplicate stage names"):
            ExtractionCascade([PatternStage(), PatternStage()])

    def test_single_stage_cannot_manufacture_corroboration(self) -> None:
        obs = observation(observed_days=100)
        text = "Security forces clashed with Maoist fighters in Bastar yesterday."
        mentions = ExtractionCascade().extract(obs, text)
        assert all(mention.extraction_probability < 1.0 for mention in mentions)


class _DisagreeingStage(BaseStage):
    """A second stage that reads the same sentence differently."""

    name = "contrarian"

    def propose(self, observation: Observation, text: str) -> Sequence[MentionCandidate]:
        del observation
        sentences = split_sentences(text)
        if not sentences:
            return []
        return [
            MentionCandidate(
                stage_name=self.name,
                span=sentences[0][:512],
                event_type="armed_clash",
                subject="Somebody Else",
                object=None,
                location_text="Elsewhere",
                event_time_start=None,
                event_time_end=None,
                modality="asserted",
                confidence=0.6,
                explicit_fields={"event_type", "subject", "location"},
            )
        ]


class TestConsensus:
    def test_disagreement_marks_fields_unresolved_rather_than_voting(self) -> None:
        obs = observation(observed_days=100)
        text = "Security forces clashed with Maoist fighters in Bastar yesterday."
        cascade = ExtractionCascade([PatternStage(), _DisagreeingStage()])
        mentions = cascade.extract(obs, text)
        clash = [m for m in mentions if m.event_type == "armed_clash"]
        assert clash
        disputed = clash[0].unresolved_fields
        assert "subject" in disputed
        assert "location" in disputed

    def test_disputed_fields_are_never_also_explicit(self) -> None:
        obs = observation(observed_days=100)
        cascade = ExtractionCascade([PatternStage(), _DisagreeingStage()])
        for mention in cascade.extract(obs, "Forces clashed with fighters in Bastar yesterday."):
            assert not (mention.explicit_fields & mention.unresolved_fields)

    def test_versions_report_every_stage(self) -> None:
        cascade = ExtractionCascade([PatternStage(), _DisagreeingStage()])
        assert set(cascade.versions) == {"pattern", "contrarian"}


class TestPayloadResolution:
    def test_dotted_paths_are_followed(self) -> None:
        payload = {"fields": {"body": "A clash occurred."}, "title": "Report"}
        assert resolve_text(payload, ["title", "fields.body"]) == "Report\nA clash occurred."

    def test_missing_paths_are_skipped(self) -> None:
        assert resolve_text({"title": "Only this"}, ["title", "fields.body"]) == "Only this"

    def test_nested_objects_are_not_stringified(self) -> None:
        payload = {"fields": {"body": {"nested": "value"}}}
        assert resolve_text(payload, ["fields.body"]) == ""

    def test_string_lists_are_joined(self) -> None:
        assert resolve_text({"tags": ["one", "two"]}, ["tags"]) == "one\ntwo"
