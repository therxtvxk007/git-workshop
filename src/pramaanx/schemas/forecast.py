"""Forecast records and the statuses the risk controller can assign."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.hashing import stable_id
from pramaanx.schemas.base import UtcDatetime, VersionedModel
from pramaanx.schemas.event import EventHypothesis


class ForecastStatus(StrEnum):
    """Uncertain cases are retained, never silently deleted."""

    ALERT = "alert"
    """Calibrated risk and evidence quality justify immediate analyst review."""

    WATCH = "watch"
    """Material risk, confirmation incomplete."""

    MONITOR = "monitor"
    """Weak, novel or early signal, retained to protect recall."""

    ABSTAIN = "abstain"
    """Model conflict or distribution shift makes the probability unreliable."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    """The candidate exists, but the evidence needed to assess it is unavailable."""


ACTIONABLE_STATUSES = frozenset({ForecastStatus.ALERT, ForecastStatus.WATCH})
RETAINED_STATUSES = frozenset(
    {
        ForecastStatus.ALERT,
        ForecastStatus.WATCH,
        ForecastStatus.MONITOR,
        ForecastStatus.INSUFFICIENT_EVIDENCE,
    }
)


class ForecastRecord(VersionedModel):
    forecast_id: str
    cutoff_at: UtcDatetime
    created_at: UtcDatetime
    hypothesis: EventHypothesis
    raw_probability: float = Field(ge=0.0, le=1.0)
    calibrated_probability: float = Field(ge=0.0, le=1.0)
    epistemic_uncertainty: float = Field(ge=0.0, le=1.0)
    status: ForecastStatus
    model_versions: dict[str, str] = Field(default_factory=dict)
    snapshot_hash: str

    @model_validator(mode="after")
    def _check_snapshot(self) -> ForecastRecord:
        # A forecast without a snapshot hash cannot be audited for leakage, and
        # an unauditable forecast is not a forecast.
        if not self.snapshot_hash.strip():
            raise ValueError("forecast requires a snapshot_hash")
        if self.created_at < self.cutoff_at:
            raise ValueError("created_at precedes cutoff_at")
        return self

    @property
    def is_actionable(self) -> bool:
        return self.status in ACTIONABLE_STATUSES

    def canonical_dict_stable(self) -> dict[str, object]:
        """Dump excluding wall-clock fields, for reproducibility comparisons."""
        return self.model_dump(mode="json", exclude={"created_at"})

    @staticmethod
    def build_id(snapshot_hash: str, event_id: str) -> str:
        return stable_id("fc", snapshot_hash, event_id)
