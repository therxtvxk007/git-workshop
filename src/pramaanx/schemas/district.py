"""District-level forecasting records."""
from __future__ import annotations
from pydantic import Field, model_validator
from pramaanx.hashing import stable_id
from pramaanx.schemas.base import UtcDatetime, VersionedModel
from pramaanx.schemas.forecast import ForecastStatus

class DistrictRef(VersionedModel):
    district_id: str
    district_name: str
    state_id: str
    state_name: str
    boundary_version: str
    valid_from: UtcDatetime
    valid_until: UtcDatetime | None = None

    @model_validator(mode="after")
    def _validity(self) -> "DistrictRef":
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self

class DistrictRiskTarget(VersionedModel):
    district: DistrictRef
    cutoff_at: UtcDatetime
    horizon_start: UtcDatetime
    horizon_end: UtcDatetime
    event_family: str

    @model_validator(mode="after")
    def _window(self) -> "DistrictRiskTarget":
        if self.horizon_start < self.cutoff_at:
            raise ValueError("horizon_start precedes cutoff")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("empty forecast horizon")
        return self

class DistrictRiskForecast(VersionedModel):
    forecast_id: str
    target: DistrictRiskTarget
    raw_probability: float = Field(ge=0.0, le=1.0)
    calibrated_probability: float = Field(ge=0.0, le=1.0)
    expected_incident_count: float = Field(ge=0.0)
    probability_lower: float | None = Field(default=None, ge=0.0, le=1.0)
    probability_upper: float | None = Field(default=None, ge=0.0, le=1.0)
    status: ForecastStatus
    abstention_reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    contradiction_ids: list[str] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    snapshot_hash: str

    @model_validator(mode="after")
    def _interval(self) -> "DistrictRiskForecast":
        if self.probability_lower is not None and self.probability_upper is not None:
            if self.probability_lower > self.probability_upper:
                raise ValueError("probability interval is reversed")
            if not self.probability_lower <= self.calibrated_probability <= self.probability_upper:
                raise ValueError("probability outside interval")
        if not self.snapshot_hash:
            raise ValueError("snapshot_hash is required")
        return self

    @staticmethod
    def build_id(snapshot_hash: str, target: DistrictRiskTarget) -> str:
        return stable_id("dfr", snapshot_hash, target.district.district_id, target.cutoff_at, target.event_family)
