"""Domain types for the PRAMAAN-X cascade.

Deliberately dataclasses rather than pydantic models: these move through hot
loops in stages 0-2 where validation cost is not free. Pydantic is used at the
boundaries that actually need it -- LLM structured output (stage 3) and the
HTTP API -- where malformed input is a real risk.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class Modality(enum.StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    SCREENSHOT = "screenshot"


class Tier(enum.StrEnum):
    """Analyst-facing output tiers."""

    ALERT = "alert"      # high probability, independently corroborated
    WATCH = "watch"      # plausible, incomplete evidence
    MONITOR = "monitor"  # weak or unknown anomaly, retained for accumulation


class Branch(enum.StrEnum):
    """Which generator proposed a candidate. Kept for provenance and for the
    diversity selector, which must not collapse four branches into one."""

    LLM = "llm_scatter"
    GRAPH = "temporal_kg"
    HAZARD = "classical_hazard"
    OPENSET = "open_set_anomaly"


@dataclass(slots=True)
class Document:
    doc_id: str
    source_id: str
    text: str
    published_at: datetime
    title: str = ""
    url: str = ""
    language: str = "en"
    modality: Modality = Modality.TEXT
    retrieved_at: datetime | None = None
    content_hash: str = ""
    # Populated by stage 0.
    cluster_id: str | None = None          # near-duplicate cluster
    is_canonical: bool = True              # cluster representative
    boilerplate_stripped: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return f"{self.title}\n{self.text}" if self.title else self.text


@dataclass(slots=True)
class EventTuple:
    """The extraction schema. `publication_cutoff_valid` carries the leakage
    guarantee down to the individual tuple -- a tuple whose supporting document
    postdates the forecast origin must never reach the graph."""

    subject: str
    relation: str
    object: str
    event_type: str
    event_time: datetime | None
    location: str
    source_id: str
    doc_id: str
    extractor_confidence: float
    supporting_span: str
    publication_cutoff_valid: bool = True
    extractors: tuple[str, ...] = ()       # which extractors agreed
    conflict: bool = False                 # retained disagreement, not resolved

    def key(self) -> tuple[str, str, str, str]:
        return (self.subject.lower(), self.relation.lower(),
                self.object.lower(), self.event_type)


@dataclass(slots=True)
class Target:
    """A forecastable unit: 'this event type, at this place, in this window'."""

    location: str
    event_type: str

    def key(self) -> str:
        return f"{self.location}|{self.event_type}"


@dataclass(slots=True)
class Candidate:
    target: Target
    branch: Branch
    raw_score: float = 0.0                 # branch-local, not comparable
    probability: float = 0.0               # calibrated, comparable
    horizon_days: int = 7
    evidence_doc_ids: tuple[str, ...] = ()
    features: dict[str, float] = field(default_factory=dict)
    rationale: str = ""
    novelty: float = 0.0                   # open-set score
    tier: Tier | None = None

    def key(self) -> str:
        return self.target.key()


@dataclass(slots=True)
class Forecast:
    as_of: datetime
    horizon_days: int
    candidates: list[Candidate]
    crc_lambda: float
    fnr_bound: float                       # certified upper bound on FN risk
    delta: float
    epsilon: float
    set_size: int
    ledger_hash: str = ""
    stage_costs: dict[str, float] = field(default_factory=dict)

    def by_tier(self, tier: Tier) -> list[Candidate]:
        return [c for c in self.candidates if c.tier is tier]


@dataclass(slots=True)
class Evidence:
    """A retrieved, scored piece of support for a candidate."""

    doc_id: str
    score: float
    components: dict[str, float] = field(default_factory=dict)
    span: str = ""
    published_at: datetime | None = None
    source_id: str = ""
