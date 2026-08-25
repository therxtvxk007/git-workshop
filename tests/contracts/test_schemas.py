"""Schema contracts: round-trips, validation and versioning.

M0 gate: schema round-trip tests are stable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pramaanx.schemas import (
    SCHEMA_VERSION,
    EventHypothesis,
    EventMention,
    EvidenceRef,
    ForecastRecord,
    ForecastStatus,
    Modality,
    Observation,
    OutcomeRecord,
    ResolvedEvent,
)
from pramaanx.schemas.outcome import MatchTolerance

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def make_observation(**overrides: object) -> Observation:
    defaults = {
        "observation_id": "obs_1",
        "source_id": "synthetic",
        "source_type": "synthetic",
        "modality": Modality.TEXT,
        "retrieved_at": NOW,
        "first_observed_at": NOW,
        "raw_content_hash": "sha256:abc",
        "payload_ref": "ab/cd/abc.bin",
    }
    return Observation(**{**defaults, **overrides})  # type: ignore[arg-type]


def make_hypothesis(**overrides: object) -> EventHypothesis:
    defaults = {
        "event_id": "evt_1",
        "event_type": "protest",
        "actor_ids": ["Farmers Union Federation"],
        "location_cells": {"IN-DL": 1.0},
        "time_bucket_probabilities": {"0-1d": 0.4, "2-3d": 0.6},
    }
    return EventHypothesis(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestRoundTrips:
    """Serialise -> deserialise must be lossless for every persisted record."""

    def test_observation(self) -> None:
        original = make_observation(language="en", licence="CC0-1.0")
        assert Observation.model_validate_json(original.model_dump_json()) == original

    def test_event_mention(self) -> None:
        original = EventMention(
            mention_id="men_1",
            observation_id="obs_1",
            subject="Metro Workers Collective",
            relation="participates_in",
            object="Rail Interchange",
            event_type="protest",
            location_text="IN-MH",
            event_time_start=NOW,
            event_time_end=NOW,
            modality="planned",
            extraction_probability=0.7,
            supporting_span="workers announce action",
            explicit_fields={"event_type", "subject"},
            unresolved_fields={"target"},
        )
        assert EventMention.model_validate_json(original.model_dump_json()) == original

    def test_event_hypothesis_sets_survive(self) -> None:
        original = make_hypothesis(generated_by={"base_rate", "analogy"})
        restored = EventHypothesis.model_validate_json(original.model_dump_json())
        assert restored == original
        assert restored.generated_by == {"base_rate", "analogy"}

    def test_forecast_record(self) -> None:
        original = ForecastRecord(
            forecast_id="fc_1",
            cutoff_at=NOW,
            created_at=NOW,
            hypothesis=make_hypothesis(),
            raw_probability=0.4,
            calibrated_probability=0.4,
            epistemic_uncertainty=0.2,
            status=ForecastStatus.WATCH,
            model_versions={"base_rate": "base_rate@0.1.0"},
            snapshot_hash="sha256:deadbeef",
        )
        assert ForecastRecord.model_validate_json(original.model_dump_json()) == original

    def test_outcome_record(self) -> None:
        event = ResolvedEvent(
            resolved_event_id="rev_1",
            event_type="flood",
            location_cell="IN-WB",
            occurred_at=NOW,
        )
        original = OutcomeRecord(
            outcome_id="out_1",
            registry_version="auto-v1",
            event=event,
            first_legitimate_resolution_at=NOW,
            tolerance=MatchTolerance(event_family="flood"),
        )
        assert OutcomeRecord.model_validate_json(original.model_dump_json()) == original


class TestTimezoneDiscipline:
    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_observation(first_observed_at=datetime(2026, 1, 15, 12, 0))  # noqa: DTZ001

    def test_offsets_normalise_to_utc(self) -> None:
        from datetime import timedelta, timezone

        ist = timezone(timedelta(hours=5, minutes=30))
        observation = make_observation(first_observed_at=NOW.astimezone(ist))
        assert observation.first_observed_at.tzinfo is UTC
        assert observation.first_observed_at == NOW


class TestValidation:
    def test_distribution_must_sum_to_one(self) -> None:
        with pytest.raises(ValidationError, match=r"must sum to 1\.0"):
            make_hypothesis(time_bucket_probabilities={"0-1d": 0.3, "2-3d": 0.3})

    def test_empty_distribution_means_no_opinion(self) -> None:
        assert make_hypothesis(severity_distribution={}).severity_distribution == {}

    def test_negative_probability_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_hypothesis(location_cells={"IN-DL": 1.5, "IN-MH": -0.5})

    def test_observation_cannot_be_available_before_retrieval(self) -> None:
        from datetime import timedelta

        with pytest.raises(ValidationError, match="after retrieved_at"):
            make_observation(first_observed_at=NOW + timedelta(days=1), retrieved_at=NOW)

    def test_forecast_requires_snapshot_hash(self) -> None:
        with pytest.raises(ValidationError, match="snapshot_hash"):
            ForecastRecord(
                forecast_id="fc_1",
                cutoff_at=NOW,
                created_at=NOW,
                hypothesis=make_hypothesis(),
                raw_probability=0.4,
                calibrated_probability=0.4,
                epistemic_uncertainty=0.1,
                status=ForecastStatus.MONITOR,
                snapshot_hash="   ",
            )

    def test_outcome_cannot_resolve_before_it_occurs(self) -> None:
        from datetime import timedelta

        event = ResolvedEvent(resolved_event_id="rev_1", event_type="flood", occurred_at=NOW)
        with pytest.raises(ValidationError, match="before the event occurs"):
            OutcomeRecord(
                outcome_id="out_1",
                registry_version="auto-v1",
                event=event,
                first_legitimate_resolution_at=NOW - timedelta(days=1),
                tolerance=MatchTolerance(event_family="flood"),
            )

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_observation(unexpected_field="surprise")

    def test_mention_fields_cannot_be_explicit_and_unresolved(self) -> None:
        with pytest.raises(ValidationError, match="both explicit and unresolved"):
            EventMention(
                mention_id="men_1",
                observation_id="obs_1",
                subject=None,
                relation="r",
                object=None,
                event_type="protest",
                location_text=None,
                event_time_start=None,
                event_time_end=None,
                modality="unknown",
                extraction_probability=0.5,
                supporting_span="span",
                explicit_fields={"location"},
                unresolved_fields={"location"},
            )


class TestVersioning:
    def test_records_carry_a_schema_version(self) -> None:
        assert make_observation().schema_version == SCHEMA_VERSION

    def test_version_survives_round_trip(self) -> None:
        payload = make_observation().model_dump(mode="json")
        payload["schema_version"] = 0  # an older record
        assert Observation.model_validate(payload).schema_version == 0


class TestEvidence:
    def test_cluster_key_falls_back_to_observation(self) -> None:
        ref = EvidenceRef(observation_id="obs_1", claim="c", stance="supports", reliability=0.5)
        assert ref.cluster_key == "obs_1"
        clustered = ref.model_copy(update={"independence_cluster": "wire_service"})
        assert clustered.cluster_key == "wire_service"
