"""A deterministic synthetic world.

Why a synthetic source exists at all: every guarantee this project makes about
cutoff safety and reproducibility has to be testable without a network, without
credentials and without redistributing anyone's licensed data. The world below
is generated from a seed, so the same seed and window always yield the same
bytes, and a test can therefore assert byte-identical forecasts rather than
merely similar ones.

The world is not a claim about reality. It contains just enough structure --
latent events, precursor chatter, reporting delay, denials and background noise
-- to exercise discovery, adjudication, calibration and scoring end to end.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pramaanx.config import SyntheticSourceConfig
from pramaanx.hashing import canonical_bytes, hash_object, short_hash, stable_id
from pramaanx.ingest.base import (
    Connector,
    ConnectorError,
    FetchWindow,
    RawItem,
    register_connector,
)
from pramaanx.schemas.observation import Modality, SourceRecord

REGIONS: tuple[str, ...] = (
    "IN-DL",
    "IN-MH",
    "IN-TN",
    "IN-WB",
    "GB-LND",
    "US-NY",
    "KE-NBO",
    "BR-SP",
)

EVENT_TYPES: tuple[str, ...] = (
    "protest",
    "armed_clash",
    "flood",
    "disease_outbreak",
    "policy_announcement",
    "market_shock",
    "cyber_incident",
    "transport_disruption",
)

ACTORS: tuple[str, ...] = (
    "Farmers Union Federation",
    "Metro Workers Collective",
    "Coastal Fisheries Board",
    "Northern Trade Alliance",
    "City Transport Authority",
    "Riverside Health Directorate",
    "Regional Grid Operator",
    "Student Assembly Network",
)

TARGETS: tuple[str, ...] = (
    "State Secretariat",
    "Central Highway 44",
    "Port Terminal 3",
    "District Hospital",
    "Regional Exchange",
    "Municipal Water Board",
    "Rail Interchange",
    "Power Substation 11",
)

SEVERITIES: tuple[str, ...] = ("minor", "moderate", "major")

# Per-day base rates by event type. Rare types are kept genuinely rare so the
# recall-first controller has something hard to do.
BASE_RATES: dict[str, float] = {
    "protest": 0.055,
    "armed_clash": 0.012,
    "flood": 0.020,
    "disease_outbreak": 0.008,
    "policy_announcement": 0.045,
    "market_shock": 0.014,
    "cyber_incident": 0.010,
    "transport_disruption": 0.030,
}

# Months (1-12) in which each type is more likely, and by how much.
SEASONALITY: dict[str, tuple[tuple[int, ...], float]] = {
    "flood": ((6, 7, 8, 9), 3.5),
    "disease_outbreak": ((1, 2, 11, 12), 2.0),
    "protest": ((2, 3, 9, 10), 1.6),
    "transport_disruption": ((6, 7, 12), 1.4),
}


def _stable_unit(*parts: str) -> float:
    """A deterministic value in [0, 1) derived from strings.

    Python's built-in ``hash`` is salted per process, so it must never appear in
    anything whose output has to be reproducible across runs.
    """
    return int(short_hash(hash_object(list(parts)), 8), 16) / 0x100000000


def _preference(left: str, right: str, options: tuple[str, ...]) -> list[float]:
    """A stable, skewed weighting over ``options`` for one context.

    Cubing a uniform value concentrates most of the mass on two or three
    options while leaving the rest possible, which is roughly how organisations
    distribute across a place and an event type.
    """
    return [0.05 + _stable_unit(left, right, option) ** 3 * 3.0 for option in options]


@dataclass(frozen=True)
class LatentEvent:
    """An event the world decided will happen. Never exposed directly."""

    event_key: str
    event_type: str
    actor: str
    target: str
    region: str
    occurred_at: datetime
    severity: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "event_type": self.event_type,
            "actor": self.actor,
            "target": self.target,
            "region": self.region,
            "occurred_at": self.occurred_at.isoformat(),
            "severity": self.severity,
        }


#: Generated worlds, keyed by the parameters that determine them. The world is a
#: pure function of those parameters, so this changes speed and nothing else.
_WORLD_CACHE: dict[tuple[int, str, str, float], list[SyntheticDoc]] = {}


@dataclass(frozen=True)
class SyntheticDoc:
    """One document the world publishes."""

    first_observed_at: datetime
    payload: dict[str, Any]

    @property
    def bytes(self) -> bytes:
        return canonical_bytes(self.payload)


@register_connector
class SyntheticConnector(Connector):
    """Generates a reproducible evidence stream with known ground truth."""

    source_id = "synthetic"
    tier = 0

    DEFAULT_WORLD_START = datetime(2025, 1, 1, tzinfo=UTC)
    DEFAULT_WORLD_END = datetime(2026, 7, 1, tzinfo=UTC)

    @property
    def source_record(self) -> SourceRecord:
        return SourceRecord(
            source_id=self.source_id,
            source_type="synthetic",
            display_name="Synthetic evidence world",
            tier=0,
            licence="CC0-1.0",
            redistributable=True,
            source_version=f"world-v1-seed{self._seed}",
            reliability_prior=0.8,
            notes=(
                "Generated locally from a seed. Contains no real-world claims and must "
                "never be mixed into evaluation runs that report real-world accuracy."
            ),
        )

    # -- world parameters -------------------------------------------------
    @property
    def _options(self) -> SyntheticSourceConfig:
        assert isinstance(self.options, SyntheticSourceConfig)
        return self.options

    @property
    def _seed(self) -> int:
        # Falls back to the global seed so one setting makes a whole run
        # reproducible.
        return self._options.seed if self._options.seed is not None else self.settings.random_seed

    @property
    def _world_start(self) -> datetime:
        return self._as_datetime(self._options.world_start, self.DEFAULT_WORLD_START)

    @property
    def _world_end(self) -> datetime:
        return self._as_datetime(self._options.world_end, self.DEFAULT_WORLD_END)

    @property
    def _noise_per_day(self) -> float:
        return self._options.noise_per_day

    @staticmethod
    def _as_datetime(value: Any, default: datetime) -> datetime:
        if value is None:
            return default
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def plan(self, window: FetchWindow) -> dict[str, Any]:
        plan = super().plan(window)
        plan.update(
            {
                "seed": self._seed,
                "world_start": self._world_start.isoformat(),
                "world_end": self._world_end.isoformat(),
                "regions": len(REGIONS),
                "event_types": len(EVENT_TYPES),
                "expected_docs": round(self._expected_docs(window), 1),
            }
        )
        return plan

    def _expected_docs(self, window: FetchWindow) -> float:
        latent_per_day = sum(BASE_RATES.values()) * len(REGIONS)
        docs_per_latent = 4.5  # precursors + reports, averaged
        return window.days * (self._noise_per_day + latent_per_day * docs_per_latent)

    # -- generation -------------------------------------------------------
    @property
    def _world_key(self) -> tuple[int, str, str, float]:
        return (
            self._seed,
            self._world_start.isoformat(),
            self._world_end.isoformat(),
            self._noise_per_day,
        )

    def _latent_events(self) -> list[LatentEvent]:
        """Generate the full latent event set once, for the whole world span.

        Generating the entire world and then filtering means the output for a
        window never depends on how callers chunk their ingestion.
        """
        rng = random.Random(f"latent:{self._seed}")
        events: list[LatentEvent] = []
        day = self._world_start
        while day < self._world_end:
            for region in REGIONS:
                for event_type in EVENT_TYPES:
                    rate = BASE_RATES[event_type]
                    months, boost = SEASONALITY.get(event_type, ((), 1.0))
                    if day.month in months:
                        rate *= boost
                    # Regions differ systematically; the same region is always
                    # the same multiplier, so base rates are learnable.
                    rate *= 0.6 + _stable_unit(region, event_type) * 0.8
                    if rng.random() >= rate:
                        continue
                    occurred = day + timedelta(
                        hours=rng.randrange(24), minutes=rng.randrange(0, 60, 5)
                    )
                    # Actors are not interchangeable. Each (region, event type)
                    # has a stable preference over actors, so per-stream base
                    # rates genuinely differ and a rate estimator has something
                    # real to learn. Drawing actors uniformly would make every
                    # stream identical and any ranking pure noise.
                    actor = rng.choices(ACTORS, weights=_preference(region, event_type, ACTORS))[0]
                    target = rng.choices(TARGETS, weights=_preference(region, actor, TARGETS))[0]
                    severity = rng.choices(SEVERITIES, weights=(0.55, 0.32, 0.13))[0]
                    events.append(
                        LatentEvent(
                            event_key=stable_id(
                                "wev", event_type, actor, region, occurred.isoformat()
                            ),
                            event_type=event_type,
                            actor=actor,
                            target=target,
                            region=region,
                            occurred_at=occurred,
                            severity=severity,
                        )
                    )
            day += timedelta(days=1)
        return sorted(events, key=lambda item: (item.occurred_at, item.event_key))

    def _documents(self) -> list[SyntheticDoc]:
        """The whole world, generated once per parameter set.

        Generating everything and then filtering is what makes ingestion
        chunk-invariant, but it also means an unmemoised generator re-derives
        547 days of world for every window a caller asks for. The result is a
        pure function of the four parameters below, so it is cached: chunked
        ingestion goes from O(chunks x world) to O(world), and a test suite that
        ingests dozens of times pays for it once.
        """
        cached = _WORLD_CACHE.get(self._world_key)
        if cached is not None:
            return cached
        docs: list[SyntheticDoc] = []
        for event in self._latent_events():
            docs.extend(self._precursors(event))
            docs.extend(self._reports(event))
        docs.extend(self._noise())
        ordered = sorted(docs, key=lambda doc: (doc.first_observed_at, doc.payload["doc_id"]))
        _WORLD_CACHE[self._world_key] = ordered
        return ordered

    def _precursors(self, event: LatentEvent) -> Iterator[SyntheticDoc]:
        """Chatter before the event. Some events leave no trace at all."""
        rng = random.Random(f"pre:{self._seed}:{event.event_key}")
        count = rng.choices((0, 1, 2, 3, 4), weights=(0.30, 0.28, 0.20, 0.14, 0.08))[0]
        for index in range(count):
            lead_days = rng.choices(
                (1, 2, 4, 7, 12, 21, 45), weights=(0.20, 0.18, 0.18, 0.16, 0.13, 0.10, 0.05)
            )[0]
            observed = event.occurred_at - timedelta(days=lead_days, hours=rng.randrange(24))
            if observed < self._world_start:
                continue
            # A denial is still evidence: it tells the adjudicator someone
            # thought the event was plausible enough to deny.
            modality = rng.choices(("planned", "possible", "denied"), weights=(0.42, 0.48, 0.10))[0]
            payload = {
                "doc_id": stable_id("doc", event.event_key, "pre", index),
                "kind": "precursor",
                "headline": (
                    f"{event.actor} signals possible {event.event_type.replace('_', ' ')} "
                    f"near {event.target} in {event.region}"
                ),
                "body": (
                    f"Local coordination reported around {event.target}. Observers in "
                    f"{event.region} describe preparations consistent with a "
                    f"{event.event_type.replace('_', ' ')} within the coming weeks."
                ),
                "event_type": event.event_type,
                "actor": event.actor,
                "target": event.target,
                "region": event.region,
                "modality": modality,
                "event_time_start": None,
                "event_time_end": None,
                "confidence": round(rng.uniform(0.35, 0.85), 4),
                "world_event_key": event.event_key,
                "severity": None,
            }
            yield SyntheticDoc(observed, payload)

    def _reports(self, event: LatentEvent) -> Iterator[SyntheticDoc]:
        """Reporting after the fact. These become the outcome registry."""
        rng = random.Random(f"rep:{self._seed}:{event.event_key}")
        count = rng.choices((1, 2, 3), weights=(0.45, 0.35, 0.20))[0]
        for index in range(count):
            delay = timedelta(hours=rng.choices((2, 6, 14, 30, 54), weights=(3, 4, 3, 2, 1))[0])
            observed = event.occurred_at + delay
            payload = {
                "doc_id": stable_id("doc", event.event_key, "rep", index),
                "kind": "report",
                "headline": (
                    f"{event.event_type.replace('_', ' ').title()} confirmed at "
                    f"{event.target}, {event.region}"
                ),
                "body": (
                    f"Authorities in {event.region} confirmed a {event.severity} "
                    f"{event.event_type.replace('_', ' ')} involving {event.actor}. "
                    f"The incident occurred at {event.target}."
                ),
                "event_type": event.event_type,
                "actor": event.actor,
                "target": event.target,
                "region": event.region,
                "modality": "asserted",
                "event_time_start": event.occurred_at.isoformat(),
                "event_time_end": event.occurred_at.isoformat(),
                "confidence": round(rng.uniform(0.80, 0.99), 4),
                "world_event_key": event.event_key,
                "severity": event.severity,
            }
            yield SyntheticDoc(observed, payload)

    def _noise(self) -> Iterator[SyntheticDoc]:
        """Background documents that resolve to nothing.

        Without these, precision is free and the alert budget means nothing.
        """
        rng = random.Random(f"noise:{self._seed}")
        day = self._world_start
        while day < self._world_end:
            for index in range(int(self._noise_per_day)):
                region = rng.choice(REGIONS)
                event_type = rng.choice(EVENT_TYPES)
                actor = rng.choice(ACTORS)
                target = rng.choice(TARGETS)
                observed = day + timedelta(hours=rng.randrange(24), minutes=rng.randrange(60))
                payload = {
                    "doc_id": stable_id("doc", "noise", day.date().isoformat(), index),
                    "kind": "background",
                    "headline": (
                        f"{actor} publishes routine bulletin on {event_type.replace('_', ' ')} "
                        f"readiness in {region}"
                    ),
                    "body": (
                        f"Routine administrative update from {actor} concerning {target}. "
                        f"No specific plans were announced."
                    ),
                    "event_type": event_type,
                    "actor": actor,
                    "target": target,
                    "region": region,
                    "modality": "unknown",
                    "event_time_start": None,
                    "event_time_end": None,
                    "confidence": round(rng.uniform(0.05, 0.35), 4),
                    "world_event_key": None,
                    "severity": None,
                }
                yield SyntheticDoc(observed, payload)
            day += timedelta(days=1)

    # -- connector API ----------------------------------------------------
    def fetch(self, window: FetchWindow) -> Iterator[RawItem]:
        if window.start < self._world_start or window.end > self._world_end + timedelta(days=1):
            raise ConnectorError(
                f"requested window [{window.start.isoformat()}, {window.end.isoformat()}) "
                f"falls outside the synthetic world span "
                f"[{self._world_start.isoformat()}, {self._world_end.isoformat()})"
            )
        for doc in self._documents():
            if not window.contains(doc.first_observed_at):
                continue
            yield RawItem(
                payload=doc.bytes,
                first_observed_at=doc.first_observed_at,
                modality=Modality.TABULAR,
                published_at=doc.first_observed_at,
                claimed_event_time=(
                    datetime.fromisoformat(doc.payload["event_time_start"])
                    if doc.payload["event_time_start"]
                    else None
                ),
                uri=None,
                language="en",
                licence="CC0-1.0",
                source_version=f"world-v1-seed{self._seed}",
                metadata={"kind": doc.payload["kind"]},
            )

    def ground_truth(self) -> list[LatentEvent]:
        """Latent events, for test assertions only.

        The pipeline never calls this. Ground truth reaches gold the same way it
        would in production: by deriving it from post-event reporting.
        """
        return self._latent_events()
