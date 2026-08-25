"""Building the outcome registry from post-event reporting.

Ground truth is *derived* here, not injected. A synthetic run and a GDELT run
both reach gold the same way: by reading reports that were themselves observed
after the event, which is how a real analyst learns an event happened.

One thing this module explicitly does not do is decide whether an ambiguous
event occurred. Every record it writes carries no human adjudication, so its
:attr:`~pramaanx.schemas.outcome.OutcomeRecord.decision` is ``PENDING``, and
every report that consumes the registry states how much of it is unadjudicated.
Deciding whether two reports describe the same event, or whether an event
counts at all, is human work; the matcher is validated against blinded
dual-human labels before any headline number is believed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pramaanx.config import Settings
from pramaanx.hashing import stable_id
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.logging import get_logger
from pramaanx.schemas.event import ResolvedEvent
from pramaanx.schemas.observation import Observation
from pramaanx.schemas.outcome import MatchTolerance, OutcomeRecord

log = get_logger(__name__)

AUTO_REGISTRY_VERSION = "auto-v1"

AUTO_REGISTRY_NOTE = (
    "Machine-derived from post-event reporting. No human adjudication has been "
    "recorded, so this outcome is PENDING and must not be treated as gold."
)

#: Per-family matching tolerances. These are defaults to argue with, not
#: settled science: how close in time and place two descriptions must be before
#: they are "the same event" is a decision for the people who will act on the
#: alerts.
FAMILY_TOLERANCES: dict[str, MatchTolerance] = {
    "flood": MatchTolerance(
        event_family="flood", time_tolerance_days=5.0, require_actor_match=False
    ),
    "disease_outbreak": MatchTolerance(
        event_family="disease_outbreak", time_tolerance_days=14.0, require_actor_match=False
    ),
    "market_shock": MatchTolerance(
        event_family="market_shock", time_tolerance_days=2.0, require_actor_match=False
    ),
}
DEFAULT_TOLERANCE = MatchTolerance(event_family="default")


def tolerance_for(event_type: str) -> MatchTolerance:
    return FAMILY_TOLERANCES.get(
        event_type, DEFAULT_TOLERANCE.model_copy(update={"event_family": event_type})
    )


@dataclass(frozen=True)
class _Report:
    observation: Observation
    payload: dict[str, Any]

    @property
    def observed_at(self) -> datetime:
        return self.observation.first_observed_at


def _group_key(observation: Observation, payload: dict[str, Any]) -> str | None:
    """The identifier that links several reports to one real-world event.

    Synthetic documents carry an explicit key. GDELT rows carry a global event
    id. Free text carries neither, which is why event coreference (Phase 2) is a
    prerequisite for extending this beyond structured sources -- rather than
    guessing here and calling the guesses ground truth.
    """
    if observation.source_id == "synthetic":
        key = payload.get("world_event_key")
        return str(key) if key else None
    if observation.source_id == "gdelt":
        key = payload.get("global_event_id")
        return f"gdelt:{key}" if key else None
    return None


def _resolved_event(key: str, reports: Sequence[_Report]) -> ResolvedEvent | None:
    ordered = sorted(reports, key=lambda item: (item.observed_at, item.observation.observation_id))
    first = ordered[0]
    payload = first.payload
    occurred_raw = payload.get("event_time_start") or payload.get("event_date")
    if not occurred_raw:
        return None
    try:
        text = str(occurred_raw)
        if text.isdigit() and len(text) == 8:  # GDELT YYYYMMDD
            text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        occurred = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        log.warning("outcomes.unparsable_time", key=key, value=str(occurred_raw))
        return None
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=first.observed_at.tzinfo)

    first_resolvable = max(ordered[0].observed_at, occurred)
    actor = payload.get("actor") or payload.get("actor1_name")
    target = payload.get("target") or payload.get("actor2_name")
    region = payload.get("region") or payload.get("action_geo_country_code")

    return ResolvedEvent(
        resolved_event_id=stable_id("rev", key),
        event_type=str(payload.get("event_type", "unknown")),
        actor_ids=[str(actor)] if actor else [],
        target_ids=[str(target)] if target else [],
        location_cell=str(region) if region else None,
        occurred_at=occurred,
        severity=str(payload["severity"]) if payload.get("severity") else None,
        resolution_sources=sorted({item.observation.source_id for item in ordered}),
        first_resolvable_at=first_resolvable,
    )


def build_outcome_registry(
    ledger: EvidenceLedger,
    observations: Iterable[Observation],
    *,
    registry_version: str = AUTO_REGISTRY_VERSION,
) -> list[OutcomeRecord]:
    """Derive provisional outcome records from asserted reporting."""
    grouped: dict[str, list[_Report]] = {}
    for observation in observations:
        if observation.source_id not in {"synthetic", "gdelt"}:
            continue
        payload = json.loads(ledger.payload_text(observation))
        if observation.source_id == "synthetic" and payload.get("modality") != "asserted":
            continue
        key = _group_key(observation, payload)
        if key is None:
            continue
        grouped.setdefault(key, []).append(_Report(observation, payload))

    outcomes: list[OutcomeRecord] = []
    for key, reports in sorted(grouped.items()):
        event = _resolved_event(key, reports)
        if event is None:
            continue
        first_resolvable = max(
            min(item.observed_at for item in reports),
            event.occurred_at,
        )
        outcomes.append(
            OutcomeRecord(
                outcome_id=stable_id("out", registry_version, key),
                registry_version=registry_version,
                event=event,
                resolution_sources=sorted({item.observation.observation_id for item in reports}),
                first_legitimate_resolution_at=first_resolvable,
                tolerance=tolerance_for(event.event_type),
                adjudications=[],
                notes=AUTO_REGISTRY_NOTE,
            )
        )
    outcomes.sort(key=lambda item: (item.event.occurred_at, item.outcome_id))
    log.info("outcomes.built", registry_version=registry_version, outcomes=len(outcomes))
    return outcomes


def refresh_registry(
    settings: Settings, ledger: EvidenceLedger | None = None
) -> list[OutcomeRecord]:
    """Rebuild the registry over the whole ledger and persist it to gold."""
    store = ledger or EvidenceLedger(settings)
    outcomes = build_outcome_registry(store, store.read_observations())
    store.write_outcomes(outcomes)
    return outcomes


def adjudication_summary(outcomes: Sequence[OutcomeRecord]) -> dict[str, object]:
    """How much of the registry a human has actually looked at."""
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[str(outcome.decision)] = counts.get(str(outcome.decision), 0) + 1
    total = len(outcomes)
    pending = counts.get("pending", 0)
    return {
        "total": total,
        "by_decision": dict(sorted(counts.items())),
        "unadjudicated_fraction": round(pending / total, 6) if total else 0.0,
        "caveat": (
            "Metrics computed against an unadjudicated registry measure agreement with "
            "automated resolution, not with reality."
        ),
    }
