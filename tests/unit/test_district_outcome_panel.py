from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from pramaanx.geography import DistrictRegistry, DistrictRegistryEntry
from pramaanx.isolation import OutcomeAccessError, forecasting_pass
from pramaanx.outcomes import (
    LabelStatus,
    LocationStatus,
    NormalizedIncident,
    build_district_outcome_panel,
)
from pramaanx.schemas import DistrictRef

CUTOFF = datetime(2026, 1, 1, tzinfo=UTC)


def registry() -> DistrictRegistry:
    return DistrictRegistry(
        [
            DistrictRegistryEntry(
                district=DistrictRef(
                    district_id=f"IND-D-{code}",
                    district_name=name,
                    state_id="IND-S-1",
                    state_name="State",
                    boundary_version="lgd@2026-01-01",
                ),
                lgd_district_code=code,
                valid_from=date(2026, 1, 1),
                source_hash="sha256:lgd",
            )
            for code, name in [("1", "One"), ("2", "Two")]
        ]
    )


def incident(*, district_id: str | None = "IND-D-1", report_day: int = 4) -> NormalizedIncident:
    return NormalizedIncident(
        incident_id=f"inc-{district_id}-{report_day}",
        source="acled",
        source_version="2026.1",
        event_family="insurgency",
        occurred_at=CUTOFF + timedelta(days=3),
        first_resolvable_at=CUTOFF + timedelta(days=report_day),
        district_id=district_id,
        location_status=(LocationStatus.RESOLVED if district_id else LocationStatus.UNRESOLVED),
        correction_version="original",
        source_record_id="source-1",
    )


def build(incidents: list[NormalizedIncident], **overrides: object) -> list[object]:
    values = {
        "registry": registry(),
        "incidents": incidents,
        "cutoffs": [CUTOFF],
        "event_families": ["insurgency"],
        "horizon_days": 30,
        "observation_end": CUTOFF + timedelta(days=40),
        "reporting_delay_days": 7,
    }
    return build_district_outcome_panel(**{**values, **overrides})  # type: ignore[arg-type]


def test_panel_contains_positive_and_all_negative_districts() -> None:
    rows = build([incident()])
    assert len(rows) == 2
    positive, negative = rows
    assert positive.incident_count == 1  # type: ignore[attr-defined]
    assert positive.label_status is LabelStatus.OBSERVED  # type: ignore[attr-defined]
    assert negative.incident_count == 0  # type: ignore[attr-defined]
    assert negative.label_status is LabelStatus.ZERO  # type: ignore[attr-defined]


def test_unresolved_location_prevents_fictional_zero_labels() -> None:
    rows = build([incident(district_id=None)])
    assert {row.label_status for row in rows} == {LabelStatus.UNRESOLVED_LOCATION}  # type: ignore[attr-defined]


def test_incomplete_reveal_window_is_right_censored() -> None:
    rows = build([], observation_end=CUTOFF + timedelta(days=31))
    assert {row.label_status for row in rows} == {LabelStatus.RIGHT_CENSORED}  # type: ignore[attr-defined]


def test_outcome_panel_is_sealed_during_forecasting() -> None:
    with forecasting_pass("district"), pytest.raises(OutcomeAccessError):
        build([incident()])
