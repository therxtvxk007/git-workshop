"""Outcome registry entries and match results.

Open-world forecasting cannot be scored by string equality. Outcomes therefore
carry explicit per-family tolerances and a human adjudication record, and the
matcher that consumes them is itself validated against blinded dual-human
labels before any headline metric is believed.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.schemas.base import Probability, UtcDatetime, VersionedModel
from pramaanx.schemas.event import ResolvedEvent


class AdjudicationDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PENDING = "pending"
    DISPUTED = "disputed"


class MatchTolerance(VersionedModel):
    """Event-family-specific matching rules."""

    event_family: str
    time_tolerance_days: float = Field(default=3.0, ge=0.0)
    require_actor_match: bool = True
    require_target_match: bool = False
    #: When the outcome names a place, a forecast that named a different place
    #: did not predict it. Families where location is genuinely diffuse can
    #: turn this off per family.
    require_location_match: bool = True
    location_levels: list[str] = Field(default_factory=lambda: ["cell", "district", "country"])
    max_location_level_gap: int = Field(default=1, ge=0)
    min_semantic_score: Probability = 0.6


class HumanAdjudication(VersionedModel):
    adjudicator_id: str
    decided_at: UtcDatetime
    decision: AdjudicationDecision
    rationale: str
    blinded: bool = False


class OutcomeRecord(VersionedModel):
    """One canonical resolved event plus everything needed to score against it."""

    outcome_id: str
    registry_version: str
    event: ResolvedEvent
    resolution_sources: list[str] = Field(default_factory=list)
    first_legitimate_resolution_at: UtcDatetime
    tolerance: MatchTolerance
    adjudications: list[HumanAdjudication] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _check_resolution(self) -> OutcomeRecord:
        if self.first_legitimate_resolution_at < self.event.occurred_at:
            raise ValueError("an outcome cannot be resolvable before the event occurs")
        return self

    @property
    def decision(self) -> AdjudicationDecision:
        """Latest human decision; PENDING when nobody has adjudicated yet."""
        if not self.adjudications:
            return AdjudicationDecision.PENDING
        latest = max(self.adjudications, key=lambda item: item.decided_at)
        return latest.decision


class MatchResult(VersionedModel):
    """Why a forecast was or was not counted as a hit."""

    forecast_id: str
    outcome_id: str | None
    matched: bool
    score: Probability
    field_scores: dict[str, float] = Field(default_factory=dict)
    lead_time_days: float | None = None
    requires_human_review: bool = False
    reason: str = ""
