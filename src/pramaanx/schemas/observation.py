"""The atomic unit of evidence.

An :class:`Observation` records *when this project could legitimately have seen
something*, which is a different question from when the underlying event
happened or when a publisher claims to have published. Cutoff filtering uses
``first_observed_at`` and nothing else.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, HttpUrl, model_validator

from pramaanx.hashing import stable_id
from pramaanx.schemas.base import UtcDatetime, VersionedModel


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    SENSOR = "sensor"
    TABULAR = "tabular"


class Observation(VersionedModel):
    observation_id: str
    source_id: str
    source_type: str
    modality: Modality
    retrieved_at: UtcDatetime
    first_observed_at: UtcDatetime
    published_at: UtcDatetime | None = None
    claimed_event_time: UtcDatetime | None = None
    uri: HttpUrl | None = None
    raw_content_hash: str
    language: str | None = None
    licence: str | None = None
    payload_ref: str

    @model_validator(mode="after")
    def _check_timeline(self) -> Observation:
        if self.first_observed_at > self.retrieved_at:
            raise ValueError(
                "first_observed_at is after retrieved_at: an observation cannot become "
                "available later than the moment it was fetched"
            )
        return self

    @staticmethod
    def build_id(source_id: str, raw_content_hash: str, first_observed_at: str) -> str:
        """Deterministic identifier: same bytes from the same source, same id."""
        return stable_id("obs", source_id, raw_content_hash, first_observed_at)


class SourceRecord(VersionedModel):
    """Provenance for a source, versioned so a feed change is visible in diffs."""

    source_id: str
    source_type: str
    display_name: str
    tier: int = Field(ge=0, le=2)
    licence: str
    licence_url: str | None = None
    redistributable: bool = False
    base_url: str | None = None
    source_version: str = "unversioned"
    reliability_prior: float = Field(default=0.5, ge=0.0, le=1.0)
    notes: str | None = None
