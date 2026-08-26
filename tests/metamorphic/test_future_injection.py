"""The M0 gate.

Inject correctly-labelled future documents into the physical data directory.
Forecast outputs for cutoff T must remain byte-identical, because the snapshot
excludes them.

The negative controls matter as much as the positive one: a test that passes
because nothing was actually injected, or because the pipeline ignores its
evidence entirely, would prove nothing. Each property below is paired with a
case that must *fail* to change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.clock import FixedClock
from pramaanx.config import Settings
from pramaanx.hashing import canonical_bytes
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.pipeline import run_cutoff
from pramaanx.timeguard.snapshots import SnapshotBuilder

WORLD_START = datetime(2025, 1, 1, tzinfo=UTC)
CUTOFF = datetime(2025, 6, 1, tzinfo=UTC)
PAST_END = CUTOFF
FUTURE_END = CUTOFF + timedelta(days=120)


def forecast_bytes(settings: Settings, ledger: EvidenceLedger, clock: FixedClock) -> bytes:
    """Canonical bytes of the full forecast set for CUTOFF."""
    snapshot = SnapshotBuilder(settings, ledger, clock=clock).build(CUTOFF, persist=False)
    run = run_cutoff(settings, ledger, snapshot, clock=clock)
    return canonical_bytes(
        {
            "snapshot_hash": snapshot.snapshot_hash,
            "forecasts": [item.model_dump(mode="json") for item in run.forecasts],
        }
    )


@pytest.fixture
def past_only(ledger: EvidenceLedger) -> EvidenceLedger:
    ledger.ingest("synthetic", FetchWindow(WORLD_START, PAST_END))
    return ledger


class TestFutureInjection:
    def test_future_documents_do_not_change_a_past_snapshot(
        self, settings: Settings, past_only: EvidenceLedger, clock: FixedClock
    ) -> None:
        builder = SnapshotBuilder(settings, past_only, clock=clock)
        before = builder.build(CUTOFF, persist=False)

        added = past_only.ingest("synthetic", FetchWindow(PAST_END, FUTURE_END))
        assert added.written > 0, "the injection must actually add documents"

        after = builder.build(CUTOFF, persist=False)
        assert after.snapshot_hash == before.snapshot_hash
        assert after.manifest.observation_hashes == before.manifest.observation_hashes
        assert len(after) == len(before)

    def test_forecasts_are_byte_identical_after_injection(
        self, settings: Settings, past_only: EvidenceLedger, clock: FixedClock
    ) -> None:
        before = forecast_bytes(settings, past_only, clock)
        past_only.ingest("synthetic", FetchWindow(PAST_END, FUTURE_END))
        after = forecast_bytes(settings, past_only, clock)
        assert after == before

    def test_injection_is_visible_at_a_later_cutoff(
        self, settings: Settings, past_only: EvidenceLedger, clock: FixedClock
    ) -> None:
        # Negative control. If a later cutoff also ignored the new documents,
        # the test above would be passing for the wrong reason.
        builder = SnapshotBuilder(settings, past_only, clock=clock)
        later = CUTOFF + timedelta(days=60)
        before = builder.build(later, persist=False)
        past_only.ingest("synthetic", FetchWindow(PAST_END, FUTURE_END))
        after = builder.build(later, persist=False)
        assert after.snapshot_hash != before.snapshot_hash
        assert len(after) > len(before)

    def test_backdated_evidence_does_change_the_snapshot(
        self, settings: Settings, past_only: EvidenceLedger, clock: FixedClock
    ) -> None:
        # Second negative control: the guard filters on first_observed_at, so
        # evidence that claims a pre-cutoff observation time is admitted. This
        # is exactly why back-dating is a leak the ledger cannot catch alone,
        # and why the leakage auditor screens for duplicate content.
        from pramaanx.ingest.base import RawItem
        from pramaanx.schemas.observation import Modality

        builder = SnapshotBuilder(settings, past_only, clock=clock)
        before = builder.build(CUTOFF, persist=False)

        source = past_only.read_source_records()[0]
        item = RawItem(
            payload=b'{"doc_id": "smuggled", "note": "written after, dated before"}',
            first_observed_at=CUTOFF - timedelta(days=1),
            modality=Modality.TEXT,
        )
        past_only.observations.append([past_only.observation_from_item(item, source)])

        after = builder.build(CUTOFF, persist=False)
        assert after.snapshot_hash != before.snapshot_hash


class TestDeterminism:
    def test_two_snapshots_of_the_same_evidence_agree(
        self, settings: Settings, past_only: EvidenceLedger, clock: FixedClock
    ) -> None:
        builder = SnapshotBuilder(settings, past_only, clock=clock)
        assert builder.build(CUTOFF, persist=False).snapshot_hash == (
            builder.build(CUTOFF, persist=False).snapshot_hash
        )

    def test_forecasts_are_reproducible(
        self, settings: Settings, past_only: EvidenceLedger, clock: FixedClock
    ) -> None:
        assert forecast_bytes(settings, past_only, clock) == forecast_bytes(
            settings, past_only, clock
        )

    def test_ingestion_is_chunk_invariant(
        self, settings: Settings, tmp_path_factory: pytest.TempPathFactory, clock: FixedClock
    ) -> None:
        """One window or three, the ledger must end up identical."""
        from pramaanx.config import StorageConfig

        def build(chunks: list[tuple[datetime, datetime]]) -> set[str]:
            root = tmp_path_factory.mktemp("chunked")
            chunk_settings = settings.model_copy(
                update={"storage": StorageConfig(data_root=root / "data", run_root=root / "runs")}
            )
            chunk_ledger = EvidenceLedger(chunk_settings, clock=clock)
            for start, end in chunks:
                chunk_ledger.ingest("synthetic", FetchWindow(start, end))
            return {item.raw_content_hash for item in chunk_ledger.read_observations()}

        mid_one = WORLD_START + timedelta(days=60)
        mid_two = WORLD_START + timedelta(days=100)
        single = build([(WORLD_START, PAST_END)])
        split = build([(WORLD_START, mid_one), (mid_one, mid_two), (mid_two, PAST_END)])
        assert single == split
        assert len(single) > 0

    def test_reingesting_the_same_window_writes_nothing_new(
        self, past_only: EvidenceLedger
    ) -> None:
        # Bronze is append-only; a repeated fetch must be a no-op, not a
        # duplicate that quietly doubles every base rate.
        before = past_only.observations.count()
        repeat = past_only.ingest("synthetic", FetchWindow(WORLD_START, PAST_END))
        assert repeat.written == 0
        assert repeat.skipped == repeat.fetched
        assert past_only.observations.count() == before
