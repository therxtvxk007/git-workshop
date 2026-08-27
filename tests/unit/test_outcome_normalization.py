from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pramaanx.outcomes import IncidentColumnMap, normalize_incident_rows


def columns() -> IncidentColumnMap:
    return IncidentColumnMap(
        source_record_id="event_id_cnty",
        event_family="family",
        occurred_at="occurred_at",
        first_resolvable_at="first_seen_at",
        district_id="district_id",
    )


def test_normalization_requires_recorded_first_availability() -> None:
    with pytest.raises(ValueError, match="first_seen_at"):
        normalize_incident_rows(
            [
                {
                    "event_id_cnty": "IND1",
                    "family": "insurgency",
                    "occurred_at": "2026-01-02T00:00:00Z",
                    "district_id": "IND-D-1",
                }
            ],
            source="acled",
            source_version="2026.1",
            columns=columns(),
        )


def test_normalization_rejects_naive_time_and_preserves_source_version() -> None:
    row = {
        "event_id_cnty": "IND1",
        "family": "insurgency",
        "occurred_at": "2026-01-02T00:00:00",
        "first_seen_at": "2026-01-03T00:00:00Z",
        "district_id": "IND-D-1",
    }
    with pytest.raises(ValueError, match="timezone-naive"):
        normalize_incident_rows([row], source="acled", source_version="2026.1", columns=columns())
    row["occurred_at"] = datetime(2026, 1, 2, tzinfo=UTC)
    incidents = normalize_incident_rows(
        [row], source="acled", source_version="2026.1", columns=columns()
    )
    assert incidents[0].source_version == "2026.1"
