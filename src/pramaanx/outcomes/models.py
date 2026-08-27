"""Typed records for district outcome labels."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from pramaanx.schemas.base import UtcDatetime, VersionedModel


class LocationStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class LabelStatus(StrEnum):
    OBSERVED = "observed"
    ZERO = "zero"
    UNRESOLVED_LOCATION = "unresolved_location"
    RIGHT_CENSORED = "right_censored"


class NormalizedIncident(VersionedModel):
    """A source event normalized without inventing availability time."""

    incident_id: str
    source: str
    source_version: str
    event_family: str
    occurred_at: UtcDatetime
    first_resolvable_at: UtcDatetime
    district_id: str | None = None
    location_status: LocationStatus
    correction_version: str
    source_record_id: str

    @field_validator(
        "incident_id",
        "source",
        "source_version",
        "event_family",
        "correction_version",
        "source_record_id",
    )
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("incident identifiers, family, source, and versions cannot be blank")
        return value

    @model_validator(mode="after")
    def _check_availability_and_location(self) -> NormalizedIncident:
        if self.first_resolvable_at < self.occurred_at:
            raise ValueError("first_resolvable_at cannot precede occurred_at")
        if self.location_status is LocationStatus.RESOLVED and not self.district_id:
            raise ValueError("resolved incident requires district_id")
        if self.location_status is LocationStatus.UNRESOLVED and self.district_id is not None:
            raise ValueError("unresolved incident cannot carry district_id")
        return self


class DistrictOutcomeRow(VersionedModel):
    """One district x cutoff x event-family supervised-learning row."""

    district_id: str
    cutoff_at: UtcDatetime
    horizon_end: UtcDatetime
    event_family: str
    incident_occurred: bool
    incident_count: int = Field(ge=0)
    first_incident_at: UtcDatetime | None = None
    first_resolvable_at: UtcDatetime | None = None
    label_status: LabelStatus
    boundary_version: str
    incident_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_label(self) -> DistrictOutcomeRow:
        if self.horizon_end <= self.cutoff_at:
            raise ValueError("horizon_end must be after cutoff_at")
        if self.incident_occurred != (self.incident_count > 0):
            raise ValueError("incident_occurred must equal incident_count > 0")
        if self.incident_count != len(self.incident_ids):
            raise ValueError("incident_count must equal the number of incident_ids")
        has_times = self.first_incident_at is not None and self.first_resolvable_at is not None
        if self.incident_count > 0 and not has_times:
            raise ValueError("positive rows require first incident and resolvable times")
        if self.incident_count == 0 and (
            self.first_incident_at is not None or self.first_resolvable_at is not None
        ):
            raise ValueError("zero rows cannot carry incident times")
        if self.label_status is LabelStatus.OBSERVED and self.incident_count == 0:
            raise ValueError("observed status requires at least one incident")
        if self.label_status is LabelStatus.ZERO and self.incident_count != 0:
            raise ValueError("zero status cannot carry incidents")
        return self
