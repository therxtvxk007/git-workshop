"""Builders for the downstream-stage tests.

Not collected by pytest (the leading underscore keeps it out of discovery).
Every builder is explicit about availability, because the invariant most of
these tests exist to protect is the difference between when something happened
and when it became knowable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pramaanx.hashing import stable_id
from pramaanx.schemas.event import EventMention
from pramaanx.schemas.observation import Modality, Observation

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def at(days: float) -> datetime:
    """An instant ``days`` after the shared base date."""
    return BASE + timedelta(days=days)


def mention(
    *,
    observed_days: float,
    event_days: float | None = None,
    subject: str | None = "Maoists",
    obj: str | None = None,
    event_type: str = "armed_clash",
    location: str | None = "Bastar",
    modality: str = "asserted",
    span: str = "a clash was reported",
    probability: float = 0.8,
    observation_id: str | None = None,
    relation: str = "participates_in",
) -> EventMention:
    """One mention, with availability and event time set independently."""
    obs_id = observation_id or stable_id("obs", span, str(observed_days), subject or "")
    start = at(event_days) if event_days is not None else None
    return EventMention(
        mention_id=EventMention.build_id(obs_id, relation, span),
        observation_id=obs_id,
        observed_at=at(observed_days),
        subject=subject,
        relation=relation,
        object=obj,
        event_type=event_type,
        location_text=location,
        event_time_start=start,
        event_time_end=start,
        modality=modality,  # type: ignore[arg-type]
        extraction_probability=probability,
        supporting_span=span,
        explicit_fields=set(),
        unresolved_fields=set(),
    )


def observation(*, observed_days: float, source_id: str = "reliefweb") -> Observation:
    """A text observation available at ``observed_days``."""
    instant = at(observed_days)
    content_hash = stable_id("raw", source_id, str(observed_days))
    return Observation(
        observation_id=Observation.build_id(source_id, content_hash, instant.isoformat()),
        source_id=source_id,
        source_type="humanitarian",
        modality=Modality.TEXT,
        retrieved_at=instant,
        first_observed_at=instant,
        raw_content_hash=content_hash,
        payload_ref=f"{source_id}/{content_hash}.json",
    )


def series_of(
    *,
    count: int,
    spacing_days: float,
    start_day: float = 10.0,
    reporting_lag_days: float = 1.0,
    event_type: str = "armed_clash",
    subject: str = "Maoists",
    location: str = "Bastar",
) -> list[EventMention]:
    """A regularly spaced run of events, each reported after it happened."""
    return [
        mention(
            observed_days=start_day + index * spacing_days + reporting_lag_days,
            event_days=start_day + index * spacing_days,
            subject=subject,
            event_type=event_type,
            location=location,
            span=f"clash number {index} in {location}",
        )
        for index in range(count)
    ]
