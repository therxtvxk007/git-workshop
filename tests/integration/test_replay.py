"""Deterministic replay of bronze, and the ways a corpus can quietly shrink.

Each damage case here is a way stored evidence can change between an ingestion
and a replay *without anything failing*: a payload deleted, its bytes altered
underneath a reference that still resolves, a source record lost, an acquisition
that stopped halfway. All of them read, to naive code, as a smaller corpus --
and a smaller corpus produces a forecast from less evidence than the run it
claims to reproduce, while looking exactly like a legitimate one.

The assertions are therefore mostly about *refusal*.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pramaanx.clock import FixedClock
from pramaanx.config import Settings
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.ingest.replay import (
    BronzeReplay,
    ReplayDefect,
    ReplayIntegrityError,
    ReplayManifest,
    dependency_lock_hash,
    replayed_evidence_fingerprint,
)
from pramaanx.schemas.observation import Modality, Observation, SourceRecord
from pramaanx.timeguard.snapshots import SnapshotBuilder

CUTOFF = datetime(2025, 7, 1, tzinfo=UTC)
LATER = datetime(2026, 1, 1, tzinfo=UTC)


def _observation(
    ledger: EvidenceLedger,
    *,
    source_id: str = "synthetic",
    payload: bytes = b"a report",
    first_observed_at: datetime = datetime(2025, 3, 1, tzinfo=UTC),
    retrieved_at: datetime | None = None,
) -> Observation:
    """Write one observation straight into bronze, bypassing a connector."""
    content_hash, payload_ref = ledger.payloads.put(payload)
    observed = first_observed_at
    observation = Observation(
        observation_id=Observation.build_id(source_id, content_hash, observed.isoformat()),
        source_id=source_id,
        source_type="test",
        modality=Modality.TEXT,
        retrieved_at=retrieved_at or max(observed, LATER),
        first_observed_at=observed,
        raw_content_hash=content_hash,
        payload_ref=payload_ref,
    )
    ledger.observations.append([observation])
    return observation


def _source(ledger: EvidenceLedger, source_id: str) -> None:
    ledger.record_source(
        SourceRecord(
            source_id=source_id,
            source_type="test",
            display_name=source_id,
            tier=0,
            licence="CC0-1.0",
            source_version="test-v1",
        )
    )


class TestDeterminism:
    def test_two_replays_of_the_same_bronze_agree(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        replay = BronzeReplay(settings, populated_ledger)
        first = replay.replay()
        second = replay.replay()
        assert first.replay_hash == second.replay_hash
        assert [item.observation_id for item in first.observations] == [
            item.observation_id for item in second.observations
        ]

    def test_the_replay_hash_ignores_when_the_replay_happened(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        early = BronzeReplay(
            settings, populated_ledger, clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
        ).replay()
        late = BronzeReplay(
            settings, populated_ledger, clock=FixedClock(datetime(2026, 8, 27, tzinfo=UTC))
        ).replay()
        assert early.replay_hash == late.replay_hash
        assert early.manifest.created_at != late.manifest.created_at

    def test_replay_reproduces_the_snapshot_evidence_exactly(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        """The property Stage 2.3 is actually about.

        Not that replay returns *a* corpus, but that a snapshot built from the
        replayed one admits byte-identical evidence at the same cutoff.
        """
        manifest = SnapshotBuilder(settings, populated_ledger).build(CUTOFF).manifest
        result = BronzeReplay(settings, populated_ledger).replay()
        rebuilt = replayed_evidence_fingerprint(result, CUTOFF, settings=settings)

        assert rebuilt["observation_count"] == manifest.observation_count
        assert rebuilt["observation_hashes"] == sorted(manifest.observation_hashes)
        assert rebuilt["observation_hash_root"] == manifest.observation_hash_root
        assert rebuilt["source_counts"] == manifest.source_counts

    def test_the_manifest_pins_config_code_and_dependencies(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        manifest = BronzeReplay(settings, populated_ledger).replay().manifest
        assert manifest.config_hash == settings.config_hash
        assert manifest.code_hash.startswith("sha256:")
        assert manifest.dependency_lock_hash.startswith("sha256:") or (
            manifest.dependency_lock_hash == "absent"
        )
        assert manifest.source_contracts == {"synthetic": "synthetic@1.0.0/synthetic"}

    def test_a_different_dependency_set_is_a_different_replay(self) -> None:
        """Two environments with different locks are not comparable, and say so."""
        base = {
            "replay_id": "pending",
            "created_at": LATER,
            "observation_count": 1,
            "observation_hash_root": "sha256:aa",
            "payload_bytes": 8,
            "config_hash": "sha256:cc",
            "code_hash": "sha256:dd",
        }
        locked = ReplayManifest(**base, dependency_lock_hash="sha256:ee")
        unlocked = ReplayManifest(**base, dependency_lock_hash="absent")
        assert locked.replay_hash != unlocked.replay_hash

    def test_a_missing_lock_file_is_recorded_not_guessed(self, tmp_path: Path) -> None:
        assert dependency_lock_hash(tmp_path) == "absent"


class TestFailsClosed:
    def test_a_deleted_payload_refuses_the_replay(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        _source(ledger, "synthetic")
        observation = _observation(ledger)
        (ledger.payloads.root / observation.payload_ref).unlink()

        replay = BronzeReplay(settings, ledger)
        (finding,) = replay.verify()
        assert finding.defect is ReplayDefect.MISSING_PAYLOAD
        with pytest.raises(ReplayIntegrityError, match="missing_payload"):
            replay.replay()

    def test_altered_payload_bytes_refuse_the_replay(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        """A reference that still resolves is not the same as evidence intact."""
        _source(ledger, "synthetic")
        observation = _observation(ledger, payload=b"the original report")
        (ledger.payloads.root / observation.payload_ref).write_bytes(b"a different report")

        replay = BronzeReplay(settings, ledger)
        (finding,) = replay.verify()
        assert finding.defect is ReplayDefect.PAYLOAD_HASH_MISMATCH
        with pytest.raises(ReplayIntegrityError, match="payload_hash_mismatch"):
            replay.replay()

    def test_an_observation_with_no_source_record_refuses_the_replay(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        """A partial acquisition: observations written, source record lost."""
        _observation(ledger, source_id="orphan")
        replay = BronzeReplay(settings, ledger)
        (finding,) = replay.verify()
        assert finding.defect is ReplayDefect.UNKNOWN_SOURCE
        with pytest.raises(ReplayIntegrityError, match="unknown_source"):
            replay.replay()

    def test_triage_mode_returns_the_corpus_and_still_counts_the_damage(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        _source(ledger, "synthetic")
        observation = _observation(ledger)
        (ledger.payloads.root / observation.payload_ref).unlink()

        result = BronzeReplay(settings, ledger).replay(strict=False)
        assert len(result) == 1
        # The lost payload contributes no bytes, so the manifest cannot be
        # mistaken for one taken over intact evidence.
        assert result.manifest.payload_bytes == 0

    def test_the_error_names_every_defect_class_it_found(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        first = _observation(ledger, payload=b"one", source_id="orphan")
        (ledger.payloads.root / first.payload_ref).unlink()

        with pytest.raises(ReplayIntegrityError) as excinfo:
            BronzeReplay(settings, ledger).replay()
        message = str(excinfo.value)
        assert "missing_payload=1" in message
        assert "unknown_source=1" in message


class TestEvidenceLifecycle:
    def test_a_revised_report_is_a_new_observation_not_an_overwrite(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        """Bronze is append-only, and a correction must not rewrite the past."""
        _source(ledger, "synthetic")
        original = _observation(ledger, payload=b"six killed")
        revised = _observation(
            ledger,
            payload=b"eight killed",
            first_observed_at=datetime(2025, 3, 4, tzinfo=UTC),
        )
        assert original.observation_id != revised.observation_id

        result = BronzeReplay(settings, ledger).replay()
        assert len(result) == 2

    def test_a_delayed_report_does_not_reach_an_earlier_cutoff(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        """Availability, not publication, decides what a cutoff can see."""
        _source(ledger, "synthetic")
        _observation(ledger, payload=b"early", first_observed_at=datetime(2025, 3, 1, tzinfo=UTC))
        _observation(ledger, payload=b"late", first_observed_at=datetime(2025, 9, 1, tzinfo=UTC))

        result = BronzeReplay(settings, ledger).replay()
        assert len(result) == 2

        admitted = replayed_evidence_fingerprint(result, CUTOFF, settings=settings)
        assert admitted["observation_count"] == 1

    def test_the_same_bytes_from_two_sources_stay_two_observations(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        """A syndicated wire story is two acquisitions, not one.

        Collapsing them here would destroy the only record that two sources
        carried it -- and independence is what stops a hundred reprints counting
        as a hundred confirmations further downstream.
        """
        _source(ledger, "wire_a")
        _source(ledger, "wire_b")
        first = _observation(ledger, source_id="wire_a", payload=b"identical wire copy")
        second = _observation(ledger, source_id="wire_b", payload=b"identical wire copy")

        assert first.raw_content_hash == second.raw_content_hash
        assert first.observation_id != second.observation_id
        assert first.payload_ref == second.payload_ref

        result = BronzeReplay(settings, ledger).replay()
        assert len(result) == 2
        assert result.manifest.source_counts == {"wire_a": 1, "wire_b": 1}
        # Neither is a registered connector, and the manifest says so rather
        # than raising or leaving a blank that reads like a verified source.
        assert result.manifest.source_contracts == {
            "wire_a": "wire_a@undeclared",
            "wire_b": "wire_b@undeclared",
        }

    def test_an_empty_source_replays_as_an_empty_corpus(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        """A source outage is a real, valid state -- not a failure to detect."""
        _source(ledger, "silent")
        result = BronzeReplay(settings, ledger).replay()
        assert len(result) == 0
        assert result.manifest.observation_count == 0
        assert result.manifest.source_counts == {}


class TestMalformedRecords:
    @pytest.mark.parametrize(
        "field",
        ["retrieved_at", "first_observed_at"],
    )
    def test_naive_timestamps_are_refused_at_construction(self, field: str) -> None:
        payload: dict[str, object] = {
            "observation_id": "obs_x",
            "source_id": "synthetic",
            "source_type": "test",
            "modality": Modality.TEXT,
            "retrieved_at": LATER,
            "first_observed_at": datetime(2025, 3, 1, tzinfo=UTC),
            "raw_content_hash": "sha256:aa",
            "payload_ref": "ab/cd.bin",
        }
        payload[field] = datetime(2025, 3, 1)  # noqa: DTZ001 -- the point of the test
        with pytest.raises(ValueError, match="timezone-aware"):
            Observation(**payload)

    def test_an_impossible_timeline_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match="cannot become available later"):
            Observation(
                observation_id="obs_x",
                source_id="synthetic",
                source_type="test",
                modality=Modality.TEXT,
                retrieved_at=datetime(2025, 3, 1, tzinfo=UTC),
                first_observed_at=datetime(2025, 6, 1, tzinfo=UTC),
                raw_content_hash="sha256:aa",
                payload_ref="ab/cd.bin",
            )

    def test_replay_re_checks_the_timeline_it_reads_back(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        """The schema rejects this, so only a bypassing writer can produce it.

        Checked anyway: replay is the last point before a cutoff filter trusts
        the timestamp, and a record that reached disk without passing the schema
        is exactly the case where trusting it is unsafe.
        """
        _source(ledger, "synthetic")
        observation = _observation(ledger)
        # model_copy does not re-validate, which is the only way to build the
        # record the schema exists to prevent.
        broken = observation.model_copy(
            update={"first_observed_at": observation.retrieved_at + timedelta(days=30)}
        )

        findings = BronzeReplay(settings, ledger)._findings_for([broken], {"synthetic"})
        assert [finding.defect for finding in findings] == [ReplayDefect.IMPOSSIBLE_TIMELINE]

    def test_findings_are_ordered_the_same_way_every_run(
        self, settings: Settings, ledger: EvidenceLedger
    ) -> None:
        for index in range(4):
            _observation(ledger, source_id="orphan", payload=f"report {index}".encode())
        replay = BronzeReplay(settings, ledger)
        assert [str(f) for f in replay.verify()] == [str(f) for f in replay.verify()]


class TestPersistence:
    def test_a_persisted_manifest_round_trips(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        engine = BronzeReplay(settings, populated_ledger)
        result = engine.replay(persist=True)
        target = engine.root / f"{result.manifest.replay_id}.json"

        reloaded = ReplayManifest.model_validate_json(target.read_text(encoding="utf-8"))
        assert reloaded.replay_hash == result.replay_hash

    def test_persisting_the_same_replay_twice_is_idempotent(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        engine = BronzeReplay(settings, populated_ledger)
        first = engine.write(engine.replay().manifest)
        second = engine.write(engine.replay().manifest)
        assert first == second

    def test_an_id_that_disagrees_with_its_content_is_refused(
        self, settings: Settings, populated_ledger: EvidenceLedger
    ) -> None:
        """Replay ids are derived from the hash, so a mismatch means one lied."""
        engine = BronzeReplay(settings, populated_ledger)
        manifest = engine.replay().manifest
        engine.write(manifest)

        forged = manifest.model_copy(update={"observation_count": manifest.observation_count + 1})
        with pytest.raises(ValueError, match="different content hash"):
            engine.write(forged)


class TestReplayCommand:
    def test_dry_run_reports_defects_without_writing_a_manifest(
        self, settings: Settings, ledger: EvidenceLedger, tmp_path: Path
    ) -> None:
        from typer.testing import CliRunner

        from pramaanx.cli._app import app

        _observation(ledger, source_id="orphan")
        config = tmp_path / "replay.yaml"
        config.write_text(
            "storage:\n"
            f"  data_root: {settings.storage.data_root}\n"
            f"  run_root: {settings.storage.run_root}\n",
            encoding="utf-8",
        )

        result = CliRunner().invoke(app, ["replay", "--config", str(config), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "unknown_source" in result.output
        assert not (settings.storage.data_root / "replays").exists()
