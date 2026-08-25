"""The point-in-time evidence ledger.

Bronze is append-only and content-addressed. Nothing in this module ever
rewrites an existing observation: a corrected story is a *new* observation with
its own ``first_observed_at``, which is the only way a backtest at an earlier
cutoff can stay honest about what was knowable then.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from pramaanx.clock import Clock, SystemClock
from pramaanx.config import Settings
from pramaanx.hashing import utc_isoformat
from pramaanx.ingest.base import Connector, ConnectorError, FetchWindow, RawItem, build_connector
from pramaanx.logging import get_logger, log_context
from pramaanx.schemas.event import EventMention, ResolvedEvent
from pramaanx.schemas.observation import Observation, SourceRecord
from pramaanx.schemas.outcome import OutcomeRecord
from pramaanx.storage import PayloadStore, RecordTable, TableSpec, WriteResult

log = get_logger(__name__)


def _observation_index(record: Observation) -> dict[str, Any]:
    # first_observed_at is stored as a canonical UTC string: fixed-width and
    # lexicographically ordered, so cutoff filtering is an exact string compare
    # with no timezone reinterpretation anywhere in the query engine.
    observed = utc_isoformat(record.first_observed_at)
    return {
        "observation_id": record.observation_id,
        "source_id": record.source_id,
        "source_type": record.source_type,
        "modality": str(record.modality),
        "first_observed_at": observed,
        "retrieved_at": utc_isoformat(record.retrieved_at),
        "observed_date": observed[:10],
        "raw_content_hash": record.raw_content_hash,
        "language": record.language or "",
    }


OBSERVATION_SPEC = TableSpec(
    name="observations",
    key_field="observation_id",
    index_builder=_observation_index,
    partition_fields=("source_id", "observed_date"),
)

SOURCE_SPEC = TableSpec(
    name="sources",
    key_field="source_id",
    index_builder=lambda record: {
        "source_id": record.source_id,
        "tier": record.tier,
        "source_version": record.source_version,
        "licence": record.licence,
    },
)

MENTION_SPEC = TableSpec(
    name="mentions",
    key_field="mention_id",
    index_builder=lambda record: {
        "mention_id": record.mention_id,
        "observation_id": record.observation_id,
        "event_type": record.event_type,
        "relation": record.relation,
        "modality": record.modality,
    },
    partition_fields=("event_type",),
)

RESOLVED_EVENT_SPEC = TableSpec(
    name="resolved_events",
    key_field="resolved_event_id",
    index_builder=lambda record: {
        "resolved_event_id": record.resolved_event_id,
        "event_type": record.event_type,
        "occurred_at": utc_isoformat(record.occurred_at),
        "occurred_date": utc_isoformat(record.occurred_at)[:10],
        "location_cell": record.location_cell or "",
    },
    partition_fields=("event_type",),
)

OUTCOME_SPEC = TableSpec(
    name="outcomes",
    key_field="outcome_id",
    index_builder=lambda record: {
        "outcome_id": record.outcome_id,
        "registry_version": record.registry_version,
        "event_type": record.event.event_type,
        "occurred_at": utc_isoformat(record.event.occurred_at),
        "first_legitimate_resolution_at": utc_isoformat(record.first_legitimate_resolution_at),
    },
    partition_fields=("registry_version",),
)


@dataclass(frozen=True)
class IngestReport:
    source_id: str
    window_start: str
    window_end: str
    fetched: int
    written: int
    skipped: int
    payload_bytes: int
    dry_run: bool
    plan: dict[str, Any]

    def to_manifest(self) -> dict[str, Any]:
        return {
            "kind": "ingest",
            "source_id": self.source_id,
            "window": {"start": self.window_start, "end": self.window_end},
            "fetched": self.fetched,
            "written": self.written,
            "skipped_existing": self.skipped,
            "payload_bytes": self.payload_bytes,
            "dry_run": self.dry_run,
            "plan": self.plan,
        }


class EvidenceLedger:
    """Read/write access to bronze, silver and gold tables."""

    def __init__(self, settings: Settings, clock: Clock | None = None) -> None:
        self.settings = settings
        self.clock = clock or SystemClock()
        storage = settings.storage
        compression = storage.parquet_compression
        self.payloads = PayloadStore(storage.bronze / "payloads", storage.payload_shard_depth)
        self.observations = RecordTable(storage.bronze, OBSERVATION_SPEC, compression)
        self.sources = RecordTable(storage.bronze, SOURCE_SPEC, compression)
        self.mentions = RecordTable(storage.silver, MENTION_SPEC, compression)
        self.resolved_events = RecordTable(storage.gold, RESOLVED_EVENT_SPEC, compression)
        self.outcomes = RecordTable(storage.gold, OUTCOME_SPEC, compression)

    # -- writing ---------------------------------------------------------
    def record_source(self, source: SourceRecord) -> WriteResult:
        return self.sources.append([source])

    def observation_from_item(self, item: RawItem, source: SourceRecord) -> Observation:
        content_hash, payload_ref = self.payloads.put(item.payload)
        first_observed = item.first_observed_at
        retrieved_at = max(self.clock.now(), first_observed)
        return Observation(
            observation_id=Observation.build_id(
                source.source_id, content_hash, utc_isoformat(first_observed)
            ),
            source_id=source.source_id,
            source_type=source.source_type,
            modality=item.modality,
            retrieved_at=retrieved_at,
            first_observed_at=first_observed,
            published_at=item.published_at,
            claimed_event_time=item.claimed_event_time,
            uri=item.uri,  # type: ignore[arg-type]
            raw_content_hash=content_hash,
            language=item.language,
            licence=item.licence or source.licence,
            payload_ref=payload_ref,
        )

    def ingest(
        self,
        source_id: str,
        window: FetchWindow,
        *,
        dry_run: bool = False,
        connector: Connector | None = None,
    ) -> IngestReport:
        """Acquire evidence from one source into bronze."""
        conn = connector or build_connector(source_id, self.settings)
        plan = conn.plan(window)
        with log_context(source_id=source_id, window_start=window.start.isoformat()):
            if dry_run:
                log.info("ingest.dry_run", **{k: v for k, v in plan.items() if k != "options"})
                return IngestReport(
                    source_id=source_id,
                    window_start=window.start.isoformat(),
                    window_end=window.end.isoformat(),
                    fetched=0,
                    written=0,
                    skipped=0,
                    payload_bytes=0,
                    dry_run=True,
                    plan=plan,
                )

            source = conn.source_record
            self.record_source(source)
            observations: list[Observation] = []
            payload_bytes = 0
            for item in conn.guarded_fetch(window):
                payload_bytes += len(item.payload)
                observations.append(self.observation_from_item(item, source))

            result = self.observations.append(observations)
            log.info(
                "ingest.complete",
                fetched=len(observations),
                written=result.written,
                skipped=result.skipped,
            )
            return IngestReport(
                source_id=source_id,
                window_start=window.start.isoformat(),
                window_end=window.end.isoformat(),
                fetched=len(observations),
                written=result.written,
                skipped=result.skipped,
                payload_bytes=payload_bytes,
                dry_run=False,
                plan=plan,
            )

    def write_mentions(self, mentions: Iterable[EventMention]) -> WriteResult:
        return self.mentions.append(list(mentions))

    def write_resolved_events(self, events: Iterable[ResolvedEvent]) -> WriteResult:
        return self.resolved_events.append(list(events))

    def write_outcomes(self, outcomes: Iterable[OutcomeRecord]) -> WriteResult:
        return self.outcomes.append(list(outcomes))

    # -- reading ---------------------------------------------------------
    def observations_frame(self) -> pl.DataFrame:
        return self.observations.read_frame()

    def read_observations(self, *, predicate: pl.Expr | None = None) -> list[Observation]:
        return self.observations.read_models(Observation, predicate=predicate)

    def observations_at_or_before(self, cutoff: datetime) -> list[Observation]:
        """Every observation legitimately available at ``cutoff`` (D_<=T)."""
        boundary = utc_isoformat(cutoff)
        return self.observations.read_models(
            Observation, predicate=pl.col("first_observed_at") <= boundary
        )

    def read_source_records(self) -> list[SourceRecord]:
        return self.sources.read_models(SourceRecord)

    def read_resolved_events(self) -> list[ResolvedEvent]:
        return self.resolved_events.read_models(ResolvedEvent)

    def read_outcomes(self) -> list[OutcomeRecord]:
        return self.outcomes.read_models(OutcomeRecord)

    def read_mentions(self) -> list[EventMention]:
        return self.mentions.read_models(EventMention)

    def payload_text(self, observation: Observation) -> str:
        raw = self.payloads.get(observation.payload_ref)
        if not self.payloads.verify(observation.payload_ref, observation.raw_content_hash):
            raise ConnectorError(
                f"payload for {observation.observation_id} no longer matches its recorded hash; "
                "bronze must be append-only and immutable"
            )
        return raw.decode("utf-8")

    @property
    def root(self) -> Path:
        return self.settings.storage.data_root
