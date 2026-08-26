"""Deterministic extraction from coded sources."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from pramaanx.extraction.structured import (
    CAMEO_ROOT_TYPES,
    ExtractionError,
    extract_gdelt,
    extract_synthetic,
)
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.schemas.observation import Modality, Observation

NOW = datetime(2026, 1, 15, tzinfo=UTC)


def observation(source_id: str = "synthetic") -> Observation:
    return Observation(
        observation_id="obs_1",
        source_id=source_id,
        source_type=source_id,
        modality=Modality.TABULAR,
        retrieved_at=NOW,
        first_observed_at=NOW,
        raw_content_hash="sha256:abc",
        payload_ref="ab/cd/abc.bin",
    )


class TestSynthetic:
    def test_fields_map_across(self) -> None:
        payload = {
            "headline": "workers announce action",
            "event_type": "protest",
            "actor": "Metro Workers Collective",
            "target": "Rail Interchange",
            "region": "IN-MH",
            "modality": "planned",
            "event_time_start": None,
            "event_time_end": None,
            "confidence": 0.61,
        }
        mention = extract_synthetic(observation(), payload)[0]
        assert mention.event_type == "protest"
        assert mention.subject == "Metro Workers Collective"
        assert mention.modality == "planned"
        assert mention.extraction_probability == 0.61
        assert "event_time" in mention.unresolved_fields

    def test_known_event_time_is_explicit(self) -> None:
        payload = {
            "headline": "h",
            "event_type": "flood",
            "actor": "a",
            "target": "t",
            "region": "IN-WB",
            "modality": "asserted",
            "event_time_start": NOW.isoformat(),
            "event_time_end": NOW.isoformat(),
            "confidence": 0.9,
        }
        mention = extract_synthetic(observation(), payload)[0]
        assert mention.event_time_start == NOW
        assert "event_time" in mention.explicit_fields

    def test_unknown_modality_is_an_error_not_a_guess(self) -> None:
        payload = {
            "headline": "h",
            "event_type": "protest",
            "actor": "a",
            "target": "t",
            "region": "r",
            "modality": "rumoured",
            "event_time_start": None,
            "event_time_end": None,
            "confidence": 0.5,
        }
        with pytest.raises(ExtractionError, match="unknown modality"):
            extract_synthetic(observation(), payload)


class TestGdelt:
    def test_cameo_root_becomes_an_event_type(self) -> None:
        mention = extract_gdelt(
            observation("gdelt"),
            {
                "event_root_code": "14",
                "event_base_code": "141",
                "actor1_name": "FARMERS UNION",
                "action_geo_fullname": "New Delhi, India",
                "event_date": "20260114",
                "num_sources": "3",
            },
        )[0]
        assert mention.event_type == CAMEO_ROOT_TYPES["14"] == "protest"
        assert mention.modality == "asserted"
        assert mention.extraction_probability == pytest.approx(0.7)

    def test_unknown_codes_are_marked_unresolved_not_invented(self) -> None:
        mention = extract_gdelt(observation("gdelt"), {"event_root_code": "99"})[0]
        assert "event_type" in mention.unresolved_fields
        assert "location" in mention.unresolved_fields
        assert "subject" in mention.unresolved_fields


class TestBatch:
    def test_unsupported_sources_are_skipped_not_guessed(self, ledger: EvidenceLedger) -> None:
        from pramaanx.extraction.structured import extract_mentions

        assert extract_mentions(ledger, [observation("acled")]) == []

    def test_strict_mode_refuses_unsupported_sources(self, ledger: EvidenceLedger) -> None:
        from pramaanx.extraction.structured import extract_mentions

        with pytest.raises(ExtractionError, match="no extractor registered"):
            extract_mentions(ledger, [observation("acled")], skip_unknown_sources=False)

    def test_extraction_is_deterministic(self, populated_ledger: EvidenceLedger) -> None:
        from pramaanx.extraction.structured import extract_mentions

        observations = populated_ledger.read_observations()[:50]
        first = extract_mentions(populated_ledger, observations)
        second = extract_mentions(populated_ledger, list(reversed(observations)))
        assert [item.mention_id for item in first] == [item.mention_id for item in second]

    def test_payload_hash_mismatch_is_fatal(self, populated_ledger: EvidenceLedger) -> None:
        # Reading evidence whose bytes no longer match the ledger would silently
        # substitute different evidence into a snapshot.
        from pramaanx.ingest.base import ConnectorError

        target = populated_ledger.read_observations()[0]
        (populated_ledger.payloads.root / target.payload_ref).write_bytes(b"{}")
        with pytest.raises(ConnectorError, match="append-only"):
            populated_ledger.payload_text(target)

    def test_synthetic_payloads_are_valid_json(self, populated_ledger: EvidenceLedger) -> None:
        target = populated_ledger.read_observations()[0]
        assert json.loads(populated_ledger.payload_text(target))["doc_id"]
