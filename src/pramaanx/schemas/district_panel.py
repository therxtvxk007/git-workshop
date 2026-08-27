"""The district outcome panel: incidents, labels and external benchmarks.

A statistical model cannot be trained on prose. It needs a rectangle -- one row
per district, per cutoff, per event family, *including every district where
nothing happened* -- and that rectangle is where most of this project's leakage
risk now lives. Three fields carry the weight:

``occurred_at``
    when the incident happened.

``first_resolvable_at``
    when this project could first have known it happened. For ACLED that is the
    API upload timestamp, not ``event_date``; for UCDP it is the release date of
    the version that first carried the row.

``label_status``
    whether the row's label is trustworthy *yet*. A horizon that has closed but
    whose reporting delay has not elapsed is right-censored, and scoring against
    it credits the model for knowing something nobody knew.

The panel keeps all three rather than collapsing to a bare 0/1, because the
difference between "nothing happened" and "nothing had been reported yet" is
invisible once collapsed and is the exact difference between an honest negative
and a manufactured one.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from pramaanx.hashing import stable_id
from pramaanx.schemas.base import UtcDatetime, VersionedModel


class LabelStatus(StrEnum):
    """How much of this row's label can be believed."""

    #: The horizon closed and the reporting-delay window has fully elapsed.
    RESOLVED = "resolved"
    #: The horizon closed but reporting is still arriving; the count is a floor.
    CENSORED = "censored"
    #: The horizon has not closed yet. Nothing to score.
    PENDING = "pending"
    #: Incidents were seen in this district-window but could not be placed.
    #: Kept separate from a zero: an unplaceable incident is not an absence.
    UNRESOLVED_LOCATION = "unresolved_location"


class DistrictIncident(VersionedModel):
    """One qualifying incident, placed in one district at one moment.

    This is a *normalised outcome*, not evidence. It exists only in the outcome
    store and is unreachable during a forecasting pass.
    """

    incident_id: str
    source_dataset: str
    source_record_id: str
    district_id: str
    state_id: str
    boundary_version: str
    event_family: str
    occurred_at: UtcDatetime
    #: When this project could first legitimately have learned of the incident.
    first_resolvable_at: UtcDatetime
    fatalities: int | None = Field(default=None, ge=0)
    actor_names: list[str] = Field(default_factory=list)
    #: True when the source row was revised after first publication. A revision
    #: that changes the district or the date changes which panel rows are right,
    #: so it is recorded rather than merged away.
    revised: bool = False
    notes: str | None = None

    @field_validator("actor_names")
    @classmethod
    def _sort_actors(cls, value: list[str]) -> list[str]:
        # Sorted and de-duplicated here rather than in a model validator: the
        # base config validates on assignment, so mutating a field from inside
        # an "after" validator re-enters validation without end.
        return sorted({name for name in (item.strip() for item in value) if name})

    @model_validator(mode="after")
    def _check_times(self) -> DistrictIncident:
        if self.first_resolvable_at < self.occurred_at:
            raise ValueError(
                f"{self.incident_id}: first_resolvable_at precedes occurred_at; "
                "an incident cannot be knowable before it happens"
            )
        return self

    @staticmethod
    def build_id(source_dataset: str, source_record_id: str) -> str:
        return stable_id("inc", source_dataset, source_record_id)


class UnplacedIncident(VersionedModel):
    """A qualifying incident whose district could not be determined.

    Dropping these would make coverage look complete. Counting them as zeros
    would make absence look confirmed. They are carried separately so the panel
    can mark the affected windows ``unresolved_location`` and the coverage
    metrics can report what fraction of incidents never landed anywhere.
    """

    source_dataset: str
    source_record_id: str
    event_family: str
    occurred_at: UtcDatetime
    first_resolvable_at: UtcDatetime
    #: ``unknown`` or ``ambiguous``, from the resolver.
    reason: str
    location_text: str
    state_hint: str | None = None
    candidates: list[str] = Field(default_factory=list)


class DistrictPanelRow(VersionedModel):
    """One district x one cutoff x one event family.

    Both targets live on the same row: ``incident_occurred`` is the binary
    target, ``incident_count`` the count target. They are derived from the same
    incident set at the same instant, so the two can never disagree about what
    the window contained.
    """

    district_id: str
    state_id: str
    boundary_version: str
    cutoff_at: UtcDatetime
    horizon_start: UtcDatetime
    horizon_end: UtcDatetime
    event_family: str

    incident_occurred: int = Field(ge=0, le=1)
    incident_count: int = Field(ge=0)
    first_incident_at: UtcDatetime | None = None
    #: The earliest moment any incident in this window became knowable. This is
    #: what the lead-time metric must use; ``first_incident_at`` would credit
    #: the system with a warning it could not have acted on.
    first_resolvable_at: UtcDatetime | None = None

    label_status: LabelStatus
    #: When the label becomes RESOLVED: horizon end plus the reporting delay.
    label_settles_at: UtcDatetime
    #: Incidents inside the window that could not be placed in any district.
    #: Non-zero anywhere in a cutoff means the negatives for that cutoff are
    #: softer than they look.
    unplaced_incidents: int = Field(default=0, ge=0)
    fatalities: int = Field(default=0, ge=0)
    #: Bumped when a source revision changes this row, so a corrected label is
    #: a new version rather than an overwrite.
    label_revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_row(self) -> DistrictPanelRow:
        if self.horizon_start < self.cutoff_at:
            raise ValueError("horizon_start precedes the cutoff")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("empty forecast horizon")
        if self.label_settles_at < self.horizon_end:
            raise ValueError("a label cannot settle before its horizon closes")
        if bool(self.incident_count) != bool(self.incident_occurred):
            raise ValueError(
                "incident_occurred and incident_count disagree: "
                f"{self.incident_occurred} vs {self.incident_count}"
            )
        if self.incident_count and self.first_incident_at is None:
            raise ValueError("a row with incidents must carry first_incident_at")
        if not self.incident_count and self.first_incident_at is not None:
            raise ValueError("a row with no incidents cannot carry first_incident_at")
        if self.first_incident_at is not None and not (
            self.horizon_start <= self.first_incident_at < self.horizon_end
        ):
            raise ValueError("first_incident_at falls outside the horizon")
        return self

    @property
    def is_scorable(self) -> bool:
        """Only RESOLVED rows may enter a metric.

        Censored and pending rows are kept in the panel -- dropping them would
        hide how much of a fold is unusable -- but scoring them treats "not yet
        reported" as "did not happen".
        """
        return self.label_status is LabelStatus.RESOLVED

    @staticmethod
    def build_id(district_id: str, cutoff_at: str, event_family: str) -> str:
        return stable_id("pnl", district_id, cutoff_at, event_family)


class ExternalForecastRecord(VersionedModel):
    """A third-party forecast (ACLED CAST, VIEWS) for the same target.

    Carried so the baseline ladder can include forecasters who already publish
    for India, and so a claim of improvement is measured against a real system
    rather than only against this project's own baselines.

    It is deliberately *not* an :class:`DistrictIncident` and never becomes one.
    A forecast is a prediction; using one as a label would train the system to
    imitate CAST instead of to predict the world, and the resulting metrics
    would look excellent.
    """

    provider: str
    provider_version: str
    district_id: str
    cutoff_at: UtcDatetime
    horizon_start: UtcDatetime
    horizon_end: UtcDatetime
    event_family: str
    #: Providers differ: CAST publishes expected counts, VIEWS publishes both.
    #: Whichever is absent stays None rather than being derived from the other.
    predicted_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    predicted_count: float | None = Field(default=None, ge=0.0)
    published_at: UtcDatetime
    retrieved_at: UtcDatetime
    licence: str
    notes: str | None = None

    @model_validator(mode="after")
    def _check_record(self) -> ExternalForecastRecord:
        if self.predicted_probability is None and self.predicted_count is None:
            raise ValueError("an external forecast must carry a probability or a count")
        if self.horizon_end <= self.horizon_start:
            raise ValueError("empty forecast horizon")
        if self.published_at < self.cutoff_at:
            raise ValueError(
                "an external forecast published before its own cutoff cannot be "
                "compared honestly; check the provider's release calendar"
            )
        return self

    def is_available_at(self, moment: UtcDatetime) -> bool:
        """Could this project have used the forecast at ``moment``?

        Publication time, not cutoff time. CAST for a given month is released
        after that month begins, so a naive join gives the ensemble a feature
        that did not exist when the forecast was due.
        """
        return self.published_at <= moment
