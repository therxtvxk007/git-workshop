"""Contracts for the parallel district-panel forecasting stream."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from pramaanx.hashing import stable_id
from pramaanx.schemas.base import Probability, UtcDatetime, VersionedModel
from pramaanx.schemas.forecast import ForecastStatus
from pramaanx.schemas.geography import DistrictRef


class DistrictRiskTarget(VersionedModel):
    """One district, event family, cutoff, and future prediction window."""

    district: DistrictRef
    cutoff_at: UtcDatetime
    horizon_start: UtcDatetime
    horizon_end: UtcDatetime
    event_family: str

    @field_validator("event_family")
    @classmethod
    def _require_event_family(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("event_family cannot be blank")
        return value

    @model_validator(mode="after")
    def _check_horizon(self) -> DistrictRiskTarget:
        if self.horizon_start <= self.cutoff_at:
            raise ValueError("horizon_start must be after cutoff_at")
        if self.horizon_end < self.horizon_start:
            raise ValueError("horizon_end must not precede horizon_start")
        return self


class DistrictRiskForecast(VersionedModel):
    """Auditable occurrence and count forecast for a district target."""

    forecast_id: str
    target: DistrictRiskTarget

    raw_probability: Probability
    calibrated_probability: Probability
    expected_incident_count: float = Field(ge=0.0)

    probability_lower: Probability | None = None
    probability_upper: Probability | None = None
    count_lower: float | None = Field(default=None, ge=0.0)
    count_upper: float | None = Field(default=None, ge=0.0)

    status: ForecastStatus
    abstention_reason: str | None = None

    spatial_model_version: str
    semantic_model_version: str | None = None
    ensemble_version: str
    calibration_version: str
    policy_version: str

    evidence_ids: list[str] = Field(default_factory=list)
    contradiction_ids: list[str] = Field(default_factory=list)
    snapshot_hash: str

    @field_validator(
        "forecast_id",
        "spatial_model_version",
        "ensemble_version",
        "calibration_version",
        "policy_version",
        "snapshot_hash",
    )
    @classmethod
    def _require_provenance(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("forecast identifiers, versions, and snapshot hash cannot be blank")
        return value

    @field_validator("semantic_model_version")
    @classmethod
    def _reject_blank_semantic_version(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("semantic_model_version cannot be blank when supplied")
        return value

    @field_validator("evidence_ids", "contradiction_ids")
    @classmethod
    def _canonical_refs(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("evidence references cannot be blank")
        if len(value) != len(set(value)):
            raise ValueError("evidence references must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _check_intervals_and_status(self) -> DistrictRiskForecast:
        if (self.probability_lower is None) != (self.probability_upper is None):
            raise ValueError("probability interval requires both lower and upper bounds")
        if (
            self.probability_lower is not None
            and self.probability_upper is not None
            and self.probability_lower > self.probability_upper
        ):
            raise ValueError("probability_lower cannot exceed probability_upper")

        if (self.count_lower is None) != (self.count_upper is None):
            raise ValueError("count interval requires both lower and upper bounds")
        if (
            self.count_lower is not None
            and self.count_upper is not None
            and self.count_lower > self.count_upper
        ):
            raise ValueError("count_lower cannot exceed count_upper")

        needs_reason = self.status in {
            ForecastStatus.ABSTAIN,
            ForecastStatus.INSUFFICIENT_EVIDENCE,
        }
        if needs_reason and not (self.abstention_reason and self.abstention_reason.strip()):
            raise ValueError("abstaining forecasts require an abstention_reason")
        if not needs_reason and self.abstention_reason is not None:
            raise ValueError(
                "abstention_reason is only valid for non-actionable abstention statuses"
            )
        return self

    @staticmethod
    def build_id(target: DistrictRiskTarget, snapshot_hash: str) -> str:
        """Build a deterministic identifier from the complete target identity."""
        return stable_id(
            "dxf",
            target.district.district_id,
            target.district.boundary_version,
            target.cutoff_at.isoformat(),
            target.horizon_start.isoformat(),
            target.horizon_end.isoformat(),
            target.event_family,
            snapshot_hash,
        )
