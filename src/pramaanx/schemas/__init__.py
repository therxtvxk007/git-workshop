"""Canonical data contracts.

These are implemented before connectors and models on purpose: every later
stage is defined by what it may read and what it must emit.

Timestamps are timezone-aware UTC everywhere, and schemas are versioned. A
field is never silently reinterpreted -- see :mod:`pramaanx.schemas.base`.
"""

from __future__ import annotations

from pramaanx.schemas.base import (
    SCHEMA_VERSION,
    PramaanModel,
    Probability,
    UtcDatetime,
    VersionedModel,
    normalised_distribution,
)
from pramaanx.schemas.event import (
    EventHypothesis,
    EventMention,
    EventModality,
    ResolvedEvent,
)
from pramaanx.schemas.evidence import EvidenceRef, Stance
from pramaanx.schemas.forecast import (
    ACTIONABLE_STATUSES,
    RETAINED_STATUSES,
    ForecastRecord,
    ForecastStatus,
)
from pramaanx.schemas.observation import Modality, Observation, SourceRecord
from pramaanx.schemas.outcome import (
    AdjudicationDecision,
    HumanAdjudication,
    MatchResult,
    MatchTolerance,
    OutcomeRecord,
)

__all__ = [
    "ACTIONABLE_STATUSES",
    "RETAINED_STATUSES",
    "SCHEMA_VERSION",
    "AdjudicationDecision",
    "EventHypothesis",
    "EventMention",
    "EventModality",
    "EvidenceRef",
    "ForecastRecord",
    "ForecastStatus",
    "HumanAdjudication",
    "MatchResult",
    "MatchTolerance",
    "Modality",
    "Observation",
    "OutcomeRecord",
    "PramaanModel",
    "Probability",
    "ResolvedEvent",
    "SourceRecord",
    "Stance",
    "UtcDatetime",
    "VersionedModel",
    "normalised_distribution",
]
