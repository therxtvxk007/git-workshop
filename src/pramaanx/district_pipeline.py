"""Separate end-to-end pipeline for district-panel forecasts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

import numpy as np
from pydantic import Field, field_validator

from pramaanx.calibration.base import (
    Calibrator,
    FixedThresholdController,
    IdentityCalibrator,
    RiskController,
)
from pramaanx.config import Settings
from pramaanx.models.ensemble import SpatialOnlyEnsemble
from pramaanx.models.spatial import SpatialDataset, SpatialFeatureRow
from pramaanx.schemas import (
    DistrictRef,
    DistrictRiskForecast,
    DistrictRiskTarget,
    ForecastStatus,
)
from pramaanx.schemas.base import Probability, UtcDatetime, VersionedModel


class SemanticSignal(VersionedModel):
    district_id: str
    cutoff_at: UtcDatetime
    event_family: str
    probability: Probability
    model_version: str
    evidence_ids: list[str] = Field(default_factory=list)
    contradiction_ids: list[str] = Field(default_factory=list)
    disagreement: Probability = 0.0

    @field_validator("evidence_ids", "contradiction_ids")
    @classmethod
    def _canonical_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @property
    def key(self) -> tuple[str, datetime, str]:
        return (self.district_id, self.cutoff_at, self.event_family)


@runtime_checkable
class OccurrenceModel(Protocol):
    version: str

    def predict_proba(self, dataset: SpatialDataset) -> np.ndarray: ...


@runtime_checkable
class CountModel(Protocol):
    version: str

    def predict_count(self, dataset: SpatialDataset) -> np.ndarray: ...


@runtime_checkable
class EnsembleModel(Protocol):
    version: str
    fitted: bool

    def predict(
        self, spatial_probabilities: np.ndarray, semantic_probabilities: np.ndarray | None = None
    ) -> np.ndarray: ...


@dataclass(frozen=True)
class DistrictCutoffRun:
    cutoff_at: datetime
    snapshot_hash: str
    forecasts: tuple[DistrictRiskForecast, ...]


def _reason_for(status: ForecastStatus, disagreement: float) -> str | None:
    if status is ForecastStatus.ABSTAIN:
        return (
            "excessive semantic disagreement"
            if disagreement >= 0.5
            else "risk controller abstained"
        )
    if status is ForecastStatus.INSUFFICIENT_EVIDENCE:
        return "no independently supported semantic evidence"
    return None


def run_district_cutoff(
    settings: Settings,
    *,
    cutoff_at: datetime,
    snapshot_hash: str,
    districts: Sequence[DistrictRef],
    feature_rows: Sequence[SpatialFeatureRow],
    spatial_model: OccurrenceModel,
    count_model: CountModel,
    semantic_signals: Sequence[SemanticSignal] | None = None,
    ensemble: EnsembleModel | None = None,
    calibrator: Calibrator | None = None,
    controller: RiskController | None = None,
) -> DistrictCutoffRun:
    """Forecast one frozen district cutoff without touching outcome storage."""
    if cutoff_at.tzinfo is None:
        raise ValueError("cutoff_at must be timezone-aware")
    if not snapshot_hash.strip():
        raise ValueError("snapshot_hash cannot be blank")
    if any(row.cutoff_at != cutoff_at for row in feature_rows):
        raise ValueError("all district feature rows must match the requested cutoff")

    district_by_key = {
        (district.district_id, district.boundary_version): district for district in districts
    }
    for row in feature_rows:
        if (row.district_id, row.boundary_version) not in district_by_key:
            raise ValueError(f"feature row has no matching district reference: {row.district_id}")

    dataset = SpatialDataset(feature_rows)
    spatial_probabilities = np.asarray(spatial_model.predict_proba(dataset), dtype=float)
    expected_counts = np.asarray(count_model.predict_count(dataset), dtype=float)
    if len(spatial_probabilities) != len(feature_rows) or len(expected_counts) != len(feature_rows):
        raise ValueError("spatial models returned the wrong number of predictions")
    if np.any((spatial_probabilities < 0.0) | (spatial_probabilities > 1.0)):
        raise ValueError("spatial occurrence model returned an invalid probability")
    if np.any(expected_counts < 0.0):
        raise ValueError("count model returned a negative expected count")

    signals_by_key = {signal.key: signal for signal in semantic_signals or ()}
    semantic_probabilities: np.ndarray | None = None
    if semantic_signals is not None:
        missing = [row.key for row in feature_rows if row.key not in signals_by_key]
        if missing:
            raise ValueError(f"semantic signals are missing {len(missing)} district targets")
        semantic_probabilities = np.asarray(
            [signals_by_key[row.key].probability for row in feature_rows], dtype=float
        )

    selected_ensemble = ensemble or SpatialOnlyEnsemble()
    if not selected_ensemble.fitted:
        raise ValueError("district ensemble must be fitted before forecasting")
    if semantic_signals is not None and isinstance(selected_ensemble, SpatialOnlyEnsemble):
        raise ValueError("semantic signals require an explicitly fitted ensemble")
    raw_probabilities = np.asarray(
        selected_ensemble.predict(spatial_probabilities, semantic_probabilities), dtype=float
    )
    if np.any((raw_probabilities < 0.0) | (raw_probabilities > 1.0)):
        raise ValueError("ensemble returned an invalid probability")

    selected_calibrator = calibrator or IdentityCalibrator()
    selected_controller = controller or FixedThresholdController(settings.alerting)
    forecasts: list[DistrictRiskForecast] = []
    for index, row in enumerate(feature_rows):
        district = district_by_key[(row.district_id, row.boundary_version)]
        signal = signals_by_key.get(row.key)
        evidence_ids = signal.evidence_ids if signal else []
        contradiction_ids = signal.contradiction_ids if signal else []
        disagreement = signal.disagreement if signal else 0.0
        raw = float(raw_probabilities[index])
        calibrated = selected_calibrator.apply(raw)
        status = selected_controller.assign(
            calibrated,
            uncertainty=disagreement,
            evidence_count=len(evidence_ids),
            novelty=0.0,
        )
        target = DistrictRiskTarget(
            district=district,
            cutoff_at=cutoff_at,
            horizon_start=cutoff_at + timedelta(microseconds=1),
            horizon_end=cutoff_at + timedelta(days=settings.district_forecasting.horizon_days),
            event_family=row.event_family,
        )
        forecasts.append(
            DistrictRiskForecast(
                forecast_id=DistrictRiskForecast.build_id(target, snapshot_hash),
                target=target,
                raw_probability=raw,
                calibrated_probability=calibrated,
                expected_incident_count=float(expected_counts[index]),
                status=status,
                abstention_reason=_reason_for(status, disagreement),
                spatial_model_version=spatial_model.version,
                semantic_model_version=signal.model_version if signal else None,
                ensemble_version=selected_ensemble.version,
                calibration_version=selected_calibrator.version,
                policy_version=selected_controller.version,
                evidence_ids=evidence_ids,
                contradiction_ids=contradiction_ids,
                snapshot_hash=snapshot_hash,
            )
        )
    forecasts.sort(key=lambda forecast: forecast.forecast_id)
    return DistrictCutoffRun(cutoff_at, snapshot_hash, tuple(forecasts))
