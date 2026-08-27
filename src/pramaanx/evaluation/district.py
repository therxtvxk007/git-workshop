"""Fair arm comparison for district forecasts on identical frozen targets."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import Field

from pramaanx.evaluation.metrics import brier_score, log_loss, recall_at_budget
from pramaanx.outcomes import DistrictOutcomeRow, LabelStatus
from pramaanx.schemas import DistrictRiskForecast
from pramaanx.schemas.base import PramaanModel


class DistrictArmMetrics(PramaanModel):
    brier_score: float
    log_loss: float
    recall_at_k: dict[int, float | None] = Field(default_factory=dict)


class DistrictArmComparison(PramaanModel):
    rows: int
    spatial_only: DistrictArmMetrics
    spatial_plus_llm: DistrictArmMetrics
    combined_brier_improved: bool
    combined_log_loss_improved: bool


def _forecast_key(forecast: DistrictRiskForecast) -> tuple[str, datetime, str]:
    return (
        forecast.target.district.district_id,
        forecast.target.cutoff_at,
        forecast.target.event_family,
    )


def _metrics(
    probabilities: list[float], outcomes: list[int], budgets: Sequence[int]
) -> DistrictArmMetrics:
    brier = brier_score(probabilities, outcomes)
    loss = log_loss(probabilities, outcomes)
    if brier is None or loss is None:
        raise ValueError("cannot evaluate an empty district arm")
    return DistrictArmMetrics(
        brier_score=brier,
        log_loss=loss,
        recall_at_k={
            budget: recall_at_budget(probabilities, outcomes, budget).recall for budget in budgets
        },
    )


def compare_district_arms(
    spatial_only: Sequence[DistrictRiskForecast],
    spatial_plus_llm: Sequence[DistrictRiskForecast],
    outcomes: Sequence[DistrictOutcomeRow],
    *,
    budgets: Sequence[int] = (5, 10, 20),
) -> DistrictArmComparison:
    """Compare arms only after proving target and label identity."""
    spatial = {_forecast_key(forecast): forecast for forecast in spatial_only}
    combined = {_forecast_key(forecast): forecast for forecast in spatial_plus_llm}
    if set(spatial) != set(combined):
        raise ValueError("forecast arms do not contain identical targets")
    labels = {
        (row.district_id, row.cutoff_at, row.event_family): int(row.incident_occurred)
        for row in outcomes
        if row.label_status in {LabelStatus.OBSERVED, LabelStatus.ZERO}
    }
    if set(spatial) != set(labels):
        raise ValueError("forecast targets and complete outcome targets do not match")

    keys = sorted(spatial, key=lambda key: (str(key[1]), key[2], key[0]))
    truth = [labels[key] for key in keys]
    spatial_metrics = _metrics(
        [spatial[key].calibrated_probability for key in keys], truth, budgets
    )
    combined_metrics = _metrics(
        [combined[key].calibrated_probability for key in keys], truth, budgets
    )
    return DistrictArmComparison(
        rows=len(keys),
        spatial_only=spatial_metrics,
        spatial_plus_llm=combined_metrics,
        combined_brier_improved=combined_metrics.brier_score < spatial_metrics.brier_score,
        combined_log_loss_improved=combined_metrics.log_loss < spatial_metrics.log_loss,
    )
