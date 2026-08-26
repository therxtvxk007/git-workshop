"""The immutable forecast ledger.

Forecasts are written once, with their snapshot hash, before any outcome is
known. That ordering is the whole point: a forecast that can be edited after
resolution is not evidence of anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

import polars as pl

from pramaanx.config import Settings
from pramaanx.hashing import utc_isoformat
from pramaanx.logging import get_logger
from pramaanx.schemas.forecast import ForecastRecord, ForecastStatus
from pramaanx.storage import RecordTable, TableSpec, WriteResult

log = get_logger(__name__)

FORECAST_SPEC = TableSpec(
    name="forecasts",
    key_field="forecast_id",
    index_builder=lambda record: {
        "forecast_id": record.forecast_id,
        "cutoff_at": utc_isoformat(record.cutoff_at),
        "cutoff_date": utc_isoformat(record.cutoff_at)[:10],
        "snapshot_hash": record.snapshot_hash,
        "event_type": record.hypothesis.event_type,
        "status": str(record.status),
        "calibrated_probability": record.calibrated_probability,
    },
    partition_fields=("cutoff_date",),
)


class ForecastLedger:
    """Append-only storage for forecast records."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.table = RecordTable(
            settings.storage.gold, FORECAST_SPEC, settings.storage.parquet_compression
        )

    def append(self, forecasts: Iterable[ForecastRecord]) -> WriteResult:
        records = list(forecasts)
        result = self.table.append(records)
        if result.skipped:
            # Same forecast id means same snapshot and same hypothesis, so a
            # re-run is a no-op rather than a conflict. Worth logging: it is
            # also what a duplicated pipeline invocation looks like.
            log.info("forecasts.skipped_existing", skipped=result.skipped)
        return result

    def read(self, *, predicate: pl.Expr | None = None) -> list[ForecastRecord]:
        return self.table.read_models(ForecastRecord, predicate=predicate)

    def for_cutoff(self, cutoff_at: datetime) -> list[ForecastRecord]:
        return self.read(predicate=pl.col("cutoff_at") == utc_isoformat(cutoff_at))

    def for_snapshot(self, snapshot_hash: str) -> list[ForecastRecord]:
        return self.read(predicate=pl.col("snapshot_hash") == snapshot_hash)

    def count(self) -> int:
        return self.table.count()

    def status_counts(self) -> dict[str, int]:
        frame = self.table.read_frame()
        if frame.is_empty():
            return {}
        grouped = frame.group_by("status").len().sort("status")
        return {row[0]: int(row[1]) for row in grouped.iter_rows()}


def status_breakdown(forecasts: Sequence[ForecastRecord]) -> dict[str, int]:
    counts = {str(status): 0 for status in ForecastStatus}
    for forecast in forecasts:
        counts[str(forecast.status)] += 1
    return counts
