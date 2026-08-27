"""Cutoff-safe district forecasting alongside the open-world event pipeline."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from math import exp, log
from pramaanx.adjudication.schemas import SupervisorAssessment
from pramaanx.schemas.base import UtcDatetime
from pramaanx.schemas.district import DistrictRef, DistrictRiskForecast, DistrictRiskTarget
from pramaanx.schemas.forecast import ForecastStatus

@dataclass(frozen=True)
class DistrictSignal:
    district: DistrictRef
    spatial_probability: float
    expected_count: float
    evidence_ids: tuple[str, ...] = ()
    contradiction_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class DistrictCutoffRun:
    forecasts: tuple[DistrictRiskForecast, ...]

def _combine(spatial: float, semantic: float | None) -> float:
    if semantic is None:
        return spatial
    eps = 1e-6
    s, m = min(max(spatial, eps), 1-eps), min(max(semantic, eps), 1-eps)
    logit = -0.5 + 0.75 * log(s / (1-s)) + 0.25 * log(m / (1-m))
    return 1.0 / (1.0 + exp(-logit))

def run_district_cutoff(*, cutoff_at: UtcDatetime, snapshot_hash: str, event_family: str,
    signals: list[DistrictSignal],
    semantic_assessor: Callable[[DistrictSignal], SupervisorAssessment | None] | None = None,
    horizon_days: int = 30) -> DistrictCutoffRun:
    forecasts: list[DistrictRiskForecast] = []
    for signal in sorted(signals, key=lambda x: x.district.district_id):
        semantic = semantic_assessor(signal) if semantic_assessor else None
        probability = _combine(signal.spatial_probability, semantic.semantic_score if semantic else None)
        abstain = bool(semantic and semantic.abstain)
        status = ForecastStatus.ABSTAIN if abstain else (ForecastStatus.ALERT if probability >= 0.60 else
                 ForecastStatus.WATCH if probability >= 0.25 else ForecastStatus.MONITOR)
        target = DistrictRiskTarget(district=signal.district, cutoff_at=cutoff_at,
            horizon_start=cutoff_at, horizon_end=cutoff_at + timedelta(days=horizon_days),
            event_family=event_family)
        forecasts.append(DistrictRiskForecast(forecast_id=DistrictRiskForecast.build_id(snapshot_hash, target),
            target=target, raw_probability=signal.spatial_probability,
            calibrated_probability=probability, expected_incident_count=signal.expected_count,
            probability_lower=max(0.0, probability-0.10), probability_upper=min(1.0, probability+0.10),
            status=status, abstention_reason="expert_disagreement" if abstain else None,
            evidence_ids=list(signal.evidence_ids), contradiction_ids=list(signal.contradiction_ids),
            model_versions={"spatial": "external", "semantic": "none" if semantic is None else "six-expert@0.1.0",
                            "ensemble": "logit-stack@0.1.0"}, snapshot_hash=snapshot_hash))
    return DistrictCutoffRun(tuple(forecasts))

def compare_spatial_and_semantic(labels: list[int], spatial: list[float], combined: list[float]) -> dict[str, float]:
    if not (len(labels) == len(spatial) == len(combined)):
        raise ValueError("evaluation vectors differ in length")
    if not labels:
        raise ValueError("evaluation vectors are empty")
    def brier(values: list[float]) -> float:
        return sum((p-y)**2 for p, y in zip(values, labels, strict=True)) / len(labels)
    s, c = brier(spatial), brier(combined)
    return {"spatial_brier": s, "combined_brier": c, "brier_delta": s-c}
