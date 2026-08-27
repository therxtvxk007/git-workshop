"""Deterministic extraction from already-structured sources.

This is not the Phase-2 extraction cascade. There is no GLiNER-Relex here, no
event-type classifier and no LLM verifier; those arrive with a gold set and an
error taxonomy to justify them. What this module does is map sources that are
*already* structured -- the synthetic world's JSON documents, GDELT's coded
event rows -- onto :class:`~pramaanx.schemas.event.EventMention`.

Keeping it deterministic matters for M0: the base-rate generator and the
backtest need mentions to exist, and a rule-based mapping cannot introduce
model non-determinism into a reproducibility test.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.logging import get_logger
from pramaanx.schemas.event import EventMention
from pramaanx.schemas.observation import Observation

log = get_logger(__name__)

VALID_MODALITIES = frozenset({"asserted", "planned", "possible", "denied", "unknown"})

#: CAMEO event root codes to coarse event types.
CAMEO_ROOT_TYPES: dict[str, str] = {
    "01": "public_statement",
    "02": "appeal",
    "03": "intent_to_cooperate",
    "04": "consultation",
    "05": "diplomatic_cooperation",
    "06": "material_cooperation",
    "07": "provide_aid",
    "08": "yield",
    "09": "investigate",
    "10": "demand",
    "11": "disapprove",
    "12": "reject",
    "13": "threaten",
    "14": "protest",
    "15": "force_posture",
    "16": "reduce_relations",
    "17": "coerce",
    "18": "assault",
    "19": "fight",
    "20": "mass_violence",
}


class ExtractionError(RuntimeError):
    """A payload could not be mapped onto a mention."""


def _parse_optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _mention(
    observation: Observation,
    *,
    subject: str | None,
    relation: str,
    obj: str | None,
    event_type: str,
    location_text: str | None,
    start: datetime | None,
    end: datetime | None,
    modality: str,
    probability: float,
    span: str,
    explicit: set[str],
    unresolved: set[str],
) -> EventMention:
    return EventMention(
        mention_id=EventMention.build_id(observation.observation_id, relation, span),
        observation_id=observation.observation_id,
        # Availability, taken straight from the observation. Never the event
        # time, and never a wall clock.
        observed_at=observation.first_observed_at,
        subject=subject,
        relation=relation,
        object=obj,
        event_type=event_type,
        location_text=location_text,
        event_time_start=start,
        event_time_end=end,
        modality=modality,  # type: ignore[arg-type]
        extraction_probability=probability,
        supporting_span=span,
        explicit_fields=explicit,
        unresolved_fields=unresolved,
    )


def extract_synthetic(observation: Observation, payload: dict[str, Any]) -> list[EventMention]:
    """Map one synthetic-world document onto a mention."""
    modality = str(payload.get("modality", "unknown"))
    if modality not in VALID_MODALITIES:
        raise ExtractionError(f"unknown modality {modality!r} in {observation.observation_id}")

    explicit = {"event_type", "subject", "location"}
    unresolved: set[str] = set()
    start = _parse_optional_datetime(payload.get("event_time_start"))
    if start is None:
        unresolved.add("event_time")
    else:
        explicit.add("event_time")

    return [
        _mention(
            observation,
            subject=payload.get("actor"),
            relation="participates_in",
            obj=payload.get("target"),
            event_type=str(payload["event_type"]),
            location_text=payload.get("region"),
            start=start,
            end=_parse_optional_datetime(payload.get("event_time_end")),
            modality=modality,
            probability=float(payload.get("confidence", 0.5)),
            span=str(payload.get("headline", ""))[:512],
            explicit=explicit,
            unresolved=unresolved,
        )
    ]


def extract_gdelt(observation: Observation, payload: dict[str, Any]) -> list[EventMention]:
    """Map one GDELT event row onto a mention.

    GDELT codes events that have already been reported, so the modality is
    ``asserted``. ``extraction_probability`` is a coarse confidence built from
    corroboration (``num_sources``), not a claim about coding accuracy.
    """
    root = str(payload.get("event_root_code", "")).zfill(2)
    event_type = CAMEO_ROOT_TYPES.get(root)
    unresolved: set[str] = set()
    if event_type is None:
        event_type = f"cameo_{root}" if root.strip("0") else "unknown"
        unresolved.add("event_type")

    location = payload.get("action_geo_fullname") or payload.get("action_geo_country_code")
    if not location:
        unresolved.add("location")

    subject = payload.get("actor1_name") or payload.get("actor1_code")
    if not subject:
        unresolved.add("subject")

    event_time = _parse_optional_datetime(
        f"{payload['event_date'][:4]}-{payload['event_date'][4:6]}-{payload['event_date'][6:8]}"
        if str(payload.get("event_date", "")).isdigit() and len(str(payload["event_date"])) == 8
        else None
    )
    if event_time is None:
        unresolved.add("event_time")

    try:
        sources = int(payload.get("num_sources", 1))
    except (TypeError, ValueError):
        sources = 1
    probability = min(0.5 + 0.1 * max(sources - 1, 0), 0.95)

    explicit = {"event_type", "subject", "location", "event_time"} - unresolved
    span = f"CAMEO {payload.get('event_code', root)} {payload.get('source_url', '')}".strip()
    return [
        _mention(
            observation,
            subject=subject,
            relation=f"cameo_{payload.get('event_base_code', root)}",
            obj=payload.get("actor2_name") or payload.get("actor2_code"),
            event_type=event_type,
            location_text=str(location) if location else None,
            start=event_time,
            end=event_time,
            modality="asserted",
            probability=probability,
            span=span[:512],
            explicit=explicit,
            unresolved=unresolved,
        )
    ]


def extract_acled(observation: Observation, payload: dict[str, Any]) -> list[EventMention]:
    """Map one already-coded ACLED event onto a deterministic mention."""
    event = payload.get("event")
    if not isinstance(event, dict):
        raise ExtractionError(f"ACLED payload has no event object: {observation.observation_id}")

    event_type = str(event.get("event_type", "")).strip()
    sub_event_type = str(event.get("sub_event_type", "")).strip()
    if not event_type or not sub_event_type:
        raise ExtractionError(f"ACLED payload lacks event taxonomy: {observation.observation_id}")
    normalized_type = re.sub(r"[^a-z0-9]+", "_", event_type.lower()).strip("_")
    relation = re.sub(r"[^a-z0-9]+", "_", sub_event_type.lower()).strip("_")

    location = next(
        (
            str(event.get(name)).strip()
            for name in ("location", "admin1", "country")
            if str(event.get(name, "")).strip()
        ),
        None,
    )
    subject = str(event.get("actor1", "")).strip() or None
    obj = str(event.get("actor2", "")).strip() or None
    event_time = _parse_optional_datetime(event.get("event_date"))
    unresolved = {
        name
        for name, value in (
            ("subject", subject),
            ("location", location),
            ("event_time", event_time),
        )
        if value is None
    }
    explicit = {"event_type", "subject", "location", "event_time"} - unresolved
    notes = str(event.get("notes", "")).strip()
    span = notes or f"{event_type}: {sub_event_type}"
    return [
        _mention(
            observation,
            subject=subject,
            relation=relation,
            obj=obj,
            event_type=normalized_type,
            location_text=location,
            start=event_time,
            end=event_time,
            modality="asserted",
            # This is certainty in copying structured fields, not confidence
            # that the reported event is ontologically true.
            probability=1.0,
            span=span[:512],
            explicit=explicit,
            unresolved=unresolved,
        )
    ]


EXTRACTORS = {
    "synthetic": extract_synthetic,
    "gdelt": extract_gdelt,
    "acled": extract_acled,
}


def extract_mentions(
    ledger: EvidenceLedger,
    observations: Sequence[Observation],
    *,
    skip_unknown_sources: bool = True,
) -> list[EventMention]:
    """Extract mentions for every observation from a supported source.

    Ordering is deterministic (by mention id) so downstream aggregation is
    reproducible.
    """
    mentions: list[EventMention] = []
    skipped: dict[str, int] = {}
    for observation in observations:
        extractor = EXTRACTORS.get(observation.source_id)
        if extractor is None:
            if not skip_unknown_sources:
                raise ExtractionError(f"no extractor registered for {observation.source_id!r}")
            skipped[observation.source_id] = skipped.get(observation.source_id, 0) + 1
            continue
        payload = json.loads(ledger.payload_text(observation))
        mentions.extend(extractor(observation, payload))
    if skipped:
        log.warning("extraction.skipped_sources", **skipped)
    mentions.sort(key=lambda item: item.mention_id)
    return mentions


def mentions_for_cutoff(
    ledger: EvidenceLedger, observations: Iterable[Observation]
) -> list[EventMention]:
    """Convenience wrapper used by the generator and the backtest."""
    return extract_mentions(ledger, list(observations))
