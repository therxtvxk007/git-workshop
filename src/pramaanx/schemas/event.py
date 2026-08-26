"""Event mentions and event hypotheses.

A *mention* is what one observation says. A *hypothesis* is a possible future
event assembled from many mentions by a generator. Keeping them separate is
what makes it possible to say which branch proposed a candidate and on what
basis, which the union stage is forbidden from erasing.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from pramaanx.hashing import stable_id
from pramaanx.schemas.base import (
    UtcDatetime,
    VersionedModel,
    normalised_distribution,
)
from pramaanx.schemas.evidence import EvidenceRef


class EventModality(StrEnum):
    """What the text actually claims about the event's status."""

    ASSERTED = "asserted"
    PLANNED = "planned"
    POSSIBLE = "possible"
    DENIED = "denied"
    UNKNOWN = "unknown"


class EventMention(VersionedModel):
    mention_id: str
    observation_id: str
    #: When the claim became available -- the ``first_observed_at`` of the
    #: observation this mention was extracted from.
    #:
    #: Carried on the mention rather than looked up later because it answers a
    #: different question from ``event_time_start``. "Is this chatter recent?"
    #: is about when somebody said it; "when will the event happen?" is about
    #: the event. Filtering recency on event time silently drops every undated
    #: claim and lets a claim about a distant future event look stale.
    observed_at: UtcDatetime
    subject: str | None
    relation: str
    object: str | None
    event_type: str
    location_text: str | None
    event_time_start: UtcDatetime | None
    event_time_end: UtcDatetime | None
    modality: Literal["asserted", "planned", "possible", "denied", "unknown"]
    extraction_probability: float = Field(ge=0.0, le=1.0)
    supporting_span: str
    explicit_fields: set[str] = Field(default_factory=set)
    unresolved_fields: set[str] = Field(default_factory=set)

    @model_validator(mode="after")
    def _check_interval(self) -> EventMention:
        start, end = self.event_time_start, self.event_time_end
        if start and end and end < start:
            raise ValueError("event_time_end precedes event_time_start")
        overlap = self.explicit_fields & self.unresolved_fields
        if overlap:
            raise ValueError(f"fields cannot be both explicit and unresolved: {sorted(overlap)}")
        return self

    def is_recent(self, *, window_start: datetime, cutoff_at: datetime) -> bool:
        """Was this claim made inside the trailing activity window?

        Judged purely on availability. An undated claim from last week counts;
        a claim from last year does not, whatever event date it carries.
        """
        return window_start <= self.observed_at <= cutoff_at

    @staticmethod
    def build_id(observation_id: str, relation: str, span: str) -> str:
        return stable_id("men", observation_id, relation, span)


class EventHypothesis(VersionedModel):
    """A possible future event, before any calibrated probability is attached."""

    event_id: str
    event_type: str
    actor_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    location_cells: dict[str, float] = Field(default_factory=dict)
    time_bucket_probabilities: dict[str, float] = Field(default_factory=dict)
    severity_distribution: dict[str, float] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    generated_by: set[str] = Field(default_factory=set)
    novelty_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("location_cells")
    @classmethod
    def _check_locations(cls, value: dict[str, float]) -> dict[str, float]:
        return normalised_distribution(value, field_name="location_cells")

    @field_validator("time_bucket_probabilities")
    @classmethod
    def _check_buckets(cls, value: dict[str, float]) -> dict[str, float]:
        return normalised_distribution(value, field_name="time_bucket_probabilities")

    @field_validator("severity_distribution")
    @classmethod
    def _check_severity(cls, value: dict[str, float]) -> dict[str, float]:
        return normalised_distribution(value, field_name="severity_distribution")

    @field_validator("actor_ids", "target_ids")
    @classmethod
    def _sort_ids(cls, value: list[str]) -> list[str]:
        # Sorted so two generators proposing the same actors hash identically.
        return sorted(set(value))

    def most_likely_location(self) -> str | None:
        if not self.location_cells:
            return None
        return max(sorted(self.location_cells.items()), key=lambda kv: kv[1])[0]

    def most_likely_bucket(self) -> str | None:
        if not self.time_bucket_probabilities:
            return None
        return max(sorted(self.time_bucket_probabilities.items()), key=lambda kv: kv[1])[0]

    @staticmethod
    def build_id(event_type: str, actors: list[str], targets: list[str], anchor: str) -> str:
        return stable_id("evt", event_type, sorted(set(actors)), sorted(set(targets)), anchor)


class ResolvedEvent(VersionedModel):
    """A real event that occurred, used as the target of outcome matching."""

    resolved_event_id: str
    event_type: str
    actor_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    location_cell: str | None = None
    occurred_at: UtcDatetime
    severity: str | None = None
    resolution_sources: list[str] = Field(default_factory=list)
    first_resolvable_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check_resolution_time(self) -> ResolvedEvent:
        if self.first_resolvable_at and self.first_resolvable_at < self.occurred_at:
            raise ValueError("an event cannot be resolvable before it occurs")
        return self

    def as_datetime(self) -> datetime:
        return self.occurred_at
