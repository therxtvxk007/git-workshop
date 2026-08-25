"""Snapshot immutability and the mechanical leakage audit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.timeguard.leakage_audit import FindingKind, LeakageAuditor, Severity
from pramaanx.timeguard.snapshots import SnapshotBuilder

CUTOFF = datetime(2025, 6, 1, tzinfo=UTC)


class TestSnapshotManifest:
    def test_manifest_carries_the_required_provenance(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        manifest = SnapshotBuilder(settings, populated_ledger).build(CUTOFF).manifest
        assert manifest.observation_hashes == sorted(manifest.observation_hashes)
        assert len(manifest.observation_hashes) == manifest.observation_count
        assert manifest.source_versions["synthetic"].startswith("world-v1-seed")
        assert manifest.code_hash.startswith("sha256:")
        assert manifest.config_hash == settings.config_hash

    def test_snapshot_hash_ignores_creation_time(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        from pramaanx.clock import FixedClock

        early = SnapshotBuilder(
            settings, populated_ledger, clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
        ).build(CUTOFF, persist=False)
        late = SnapshotBuilder(
            settings, populated_ledger, clock=FixedClock(datetime(2026, 12, 1, tzinfo=UTC))
        ).build(CUTOFF, persist=False)
        assert early.snapshot_hash == late.snapshot_hash

    def test_snapshots_round_trip_through_disk(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        builder = SnapshotBuilder(settings, populated_ledger)
        built = builder.build(CUTOFF)
        loaded = builder.load(built.snapshot_id)
        assert loaded.snapshot_hash == built.snapshot_hash
        assert len(loaded) == len(built)

    def test_loading_detects_a_ledger_that_changed_underneath(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        from pramaanx.ingest.base import RawItem

        builder = SnapshotBuilder(settings, populated_ledger)
        built = builder.build(CUTOFF)
        builder.load(built.snapshot_id)  # unchanged ledger reloads cleanly

        # Back-dated evidence added after the fact. Bronze is meant to be
        # append-only *in the past*, and a snapshot must refuse to pretend it
        # still describes the evidence it was built from.
        source = populated_ledger.read_source_records()[0]

        populated_ledger.observations.append(
            [
                populated_ledger.observation_from_item(
                    RawItem(payload=b'{"x": 1}', first_observed_at=CUTOFF - timedelta(days=5)),
                    source,
                )
            ]
        )
        with pytest.raises(ValueError, match="no longer matches the ledger"):
            builder.load(built.snapshot_id)

    def test_unknown_snapshot_raises(self, settings: Settings) -> None:
        with pytest.raises(FileNotFoundError, match="unknown snapshot"):
            SnapshotBuilder(settings).read("snap_missing")

    def test_listing_is_ordered_by_cutoff(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        builder = SnapshotBuilder(settings, populated_ledger)
        builder.build(CUTOFF)
        builder.build(CUTOFF - timedelta(days=30))
        cutoffs = [item.cutoff_at for item in builder.list_snapshots()]
        assert cutoffs == sorted(cutoffs)


class TestLeakageAudit:
    def test_a_healthy_ledger_is_mechanically_clean(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        observations = populated_ledger.read_observations()
        report = LeakageAuditor(populated_ledger).audit(observations, cutoff_at=CUTOFF)
        assert report.clean
        assert report.observations_checked == len(observations)
        # "Clean" is never claimed to mean leak-free.
        assert "Automated screening only" in str(report.to_dict()["caveat"])

    def test_mutated_payload_is_critical(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        observations = populated_ledger.read_observations()[:5]
        target = observations[0]
        (populated_ledger.payloads.root / target.payload_ref).write_bytes(b"rewritten")
        report = LeakageAuditor(populated_ledger).audit(observations)
        assert not report.clean
        assert report.critical[0].kind is FindingKind.MUTATED_PAYLOAD

    def test_missing_payload_is_critical(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        observations = populated_ledger.read_observations()[:3]
        (populated_ledger.payloads.root / observations[0].payload_ref).unlink()
        report = LeakageAuditor(populated_ledger).audit(observations)
        assert report.critical[0].kind is FindingKind.MISSING_PAYLOAD

    def test_retrospective_language_about_a_future_event_is_flagged(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        # The suspicious pattern: the document dates its event at or after the
        # moment it was itself observed, yet describes it as already over.
        from pramaanx.ingest.base import RawItem

        source = populated_ledger.read_source_records()[0]
        suspicious = populated_ledger.observation_from_item(
            RawItem(
                payload=b'{"body": "In the aftermath, the death toll rose sharply."}',
                first_observed_at=CUTOFF,
                claimed_event_time=CUTOFF + timedelta(days=3),
            ),
            source,
        )
        report = LeakageAuditor(populated_ledger).audit([suspicious])
        findings = [
            item for item in report.findings if item.kind is FindingKind.RETROSPECTIVE_LANGUAGE
        ]
        assert len(findings) == 1
        assert findings[0].severity is Severity.WARNING
        # A warning is a review queue, not a failure.
        assert report.clean

    def test_ordinary_reporting_of_a_past_event_is_not_flagged(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        # Screening every document containing "in the aftermath" would flag most
        # of a news corpus, and a queue nobody can read protects nothing.
        observations = populated_ledger.read_observations()
        report = LeakageAuditor(populated_ledger).audit(observations)
        assert FindingKind.RETROSPECTIVE_LANGUAGE not in {item.kind for item in report.findings}
        assert report.clean

    def test_backdated_duplicates_are_flagged(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        from pramaanx.ingest.base import RawItem

        source = populated_ledger.read_source_records()[0]
        payload = b'{"doc_id": "same-bytes-two-dates"}'
        originals = [
            populated_ledger.observation_from_item(
                RawItem(payload=payload, first_observed_at=CUTOFF - timedelta(days=offset)),
                source,
            )
            for offset in (2, 60)
        ]
        report = LeakageAuditor(populated_ledger).audit(originals)
        assert FindingKind.BACKDATED_DUPLICATE in {item.kind for item in report.findings}
