"""Contracts for the district-panel forecasting stream."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from pramaanx.schemas import (
    DistrictRef,
    DistrictRiskForecast,
    DistrictRiskTarget,
    ForecastStatus,
)

CUTOFF = datetime(2026, 8, 1, tzinfo=UTC)


def make_target(**overrides: object) -> DistrictRiskTarget:
    values = {
        "district": DistrictRef(
            district_id="IND-KL-TSR",
            district_name="Thrissur",
            state_id="IND-KL",
            state_name="Kerala",
            boundary_version="india-districts@2026-01-01",
        ),
        "cutoff_at": CUTOFF,
        "horizon_start": CUTOFF + timedelta(microseconds=1),
        "horizon_end": CUTOFF + timedelta(days=30),
        "event_family": "terrorism",
    }
    return DistrictRiskTarget(**{**values, **overrides})  # type: ignore[arg-type]


def make_forecast(**overrides: object) -> DistrictRiskForecast:
    target = make_target()
    values = {
        "forecast_id": DistrictRiskForecast.build_id(target, "sha256:snapshot"),
        "target": target,
        "raw_probability": 0.2,
        "calibrated_probability": 0.15,
        "expected_incident_count": 0.18,
        "probability_lower": 0.05,
        "probability_upper": 0.31,
        "count_lower": 0.0,
        "count_upper": 0.5,
        "status": ForecastStatus.MONITOR,
        "spatial_model_version": "district-rate@1",
        "ensemble_version": "spatial-only@1",
        "calibration_version": "identity@1",
        "policy_version": "research-only@1",
        "evidence_ids": ["obs_2", "obs_1"],
        "contradiction_ids": ["obs_3"],
        "snapshot_hash": "sha256:snapshot",
    }
    return DistrictRiskForecast(**{**values, **overrides})  # type: ignore[arg-type]


def test_round_trip_and_canonical_evidence_order() -> None:
    forecast = make_forecast()
    assert forecast.evidence_ids == ["obs_1", "obs_2"]
    assert DistrictRiskForecast.model_validate_json(forecast.model_dump_json()) == forecast


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_probability", 1.01),
        ("expected_incident_count", -0.01),
        ("probability_lower", -0.01),
        ("count_upper", -1.0),
    ],
)
def test_invalid_probability_and_count_values_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_forecast(**{field: value})


def test_target_horizon_must_be_strictly_future() -> None:
    with pytest.raises(ValidationError, match="horizon_start"):
        make_target(horizon_start=CUTOFF)


def test_partial_or_reversed_intervals_are_rejected() -> None:
    with pytest.raises(ValidationError, match="both lower and upper"):
        make_forecast(probability_upper=None)
    with pytest.raises(ValidationError, match="cannot exceed"):
        make_forecast(count_lower=1.0, count_upper=0.5)


def test_abstention_requires_a_reason_and_actionable_status_rejects_one() -> None:
    with pytest.raises(ValidationError, match="abstention_reason"):
        make_forecast(status=ForecastStatus.ABSTAIN)
    with pytest.raises(ValidationError, match="only valid"):
        make_forecast(status=ForecastStatus.WATCH, abstention_reason="model conflict")

    forecast = make_forecast(
        status=ForecastStatus.ABSTAIN,
        abstention_reason="out-of-distribution district",
    )
    assert forecast.status is ForecastStatus.ABSTAIN


def test_forecast_id_is_target_and_snapshot_specific() -> None:
    target = make_target()
    assert DistrictRiskForecast.build_id(target, "sha256:a") != DistrictRiskForecast.build_id(
        target, "sha256:b"
    )
