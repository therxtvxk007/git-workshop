from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.evaluation import compare_district_arms
from pramaanx.outcomes import DistrictOutcomeRow, LabelStatus
from pramaanx.schemas import (
    DistrictRef,
    DistrictRiskForecast,
    DistrictRiskTarget,
    ForecastStatus,
)

CUTOFF = datetime(2026, 1, 1, tzinfo=UTC)


def forecast(district_id: str, probability: float, arm: str) -> DistrictRiskForecast:
    target = DistrictRiskTarget(
        district=DistrictRef(
            district_id=district_id,
            district_name=district_id,
            state_id="state",
            state_name="State",
            boundary_version="v1",
        ),
        cutoff_at=CUTOFF,
        horizon_start=CUTOFF + timedelta(microseconds=1),
        horizon_end=CUTOFF + timedelta(days=30),
        event_family="insurgency",
    )
    return DistrictRiskForecast(
        forecast_id=f"{arm}-{district_id}",
        target=target,
        raw_probability=probability,
        calibrated_probability=probability,
        expected_incident_count=probability,
        status=ForecastStatus.MONITOR,
        spatial_model_version="spatial@1",
        semantic_model_version="semantic@1" if arm == "combined" else None,
        ensemble_version=arm,
        calibration_version="identity@1",
        policy_version="policy@1",
        snapshot_hash="sha256:snapshot",
    )


def outcome(district_id: str, positive: bool) -> DistrictOutcomeRow:
    return DistrictOutcomeRow(
        district_id=district_id,
        cutoff_at=CUTOFF,
        horizon_end=CUTOFF + timedelta(days=30),
        event_family="insurgency",
        incident_occurred=positive,
        incident_count=int(positive),
        first_incident_at=CUTOFF + timedelta(days=1) if positive else None,
        first_resolvable_at=CUTOFF + timedelta(days=2) if positive else None,
        label_status=LabelStatus.OBSERVED if positive else LabelStatus.ZERO,
        boundary_version="v1",
        incident_ids=[f"inc-{district_id}"] if positive else [],
    )


def test_comparison_reports_improvement_only_when_metrics_improve() -> None:
    outcomes = [outcome("d1", True), outcome("d2", False)]
    spatial = [forecast("d1", 0.6, "spatial"), forecast("d2", 0.4, "spatial")]
    combined = [forecast("d1", 0.9, "combined"), forecast("d2", 0.1, "combined")]
    result = compare_district_arms(spatial, combined, outcomes, budgets=[1])
    assert result.combined_brier_improved
    assert result.combined_log_loss_improved
    assert result.spatial_plus_llm.recall_at_k[1] == 1.0


def test_comparison_refuses_different_targets() -> None:
    with pytest.raises(ValueError, match="identical targets"):
        compare_district_arms(
            [forecast("d1", 0.5, "spatial")],
            [forecast("d2", 0.5, "combined")],
            [outcome("d1", True)],
        )
