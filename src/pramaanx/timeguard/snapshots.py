"""Immutable cutoff snapshots.

A snapshot is the answer to "what did this project know at time T?", frozen and
hashed. A forecast without a snapshot hash is invalid, because there is then no
way to check afterwards what evidence it actually had.

The snapshot hash is computed over content only -- the sorted observation
hashes, source versions, code hash and config hash -- and never over wall-clock
time or file layout. That is what makes the leakage test meaningful: adding
correctly-dated future documents to the data directory must leave the snapshot
hash for an earlier cutoff untouched.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from pramaanx.clock import Clock, SystemClock
from pramaanx.config import Settings
from pramaanx.hashing import (
    canonical_bytes,
    hash_object,
    hash_tree,
    merkle_root,
    stable_id,
    utc_isoformat,
)
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.logging import get_logger
from pramaanx.schemas.base import UtcDatetime, VersionedModel
from pramaanx.schemas.observation import Observation
from pramaanx.timeguard.cutoff import CutoffGuard

log = get_logger(__name__)

SNAPSHOT_DIR_NAME = "snapshots"


def code_hash() -> str:
    """Hash of the pramaanx source tree that produced a snapshot."""
    return hash_tree(Path(__file__).resolve().parents[1])


class SnapshotManifest(VersionedModel):
    """Everything needed to reconstruct and audit one point-in-time view."""

    snapshot_id: str
    cutoff_at: UtcDatetime
    created_at: UtcDatetime
    observation_count: int = Field(ge=0)
    #: ``observation_id:raw_content_hash`` pairs, sorted. The spec requires the
    #: manifest to carry the hashes themselves, not merely a digest of them.
    observation_hashes: list[str] = Field(default_factory=list)
    observation_hash_root: str
    source_versions: dict[str, str] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    earliest_observation_at: UtcDatetime | None = None
    latest_observation_at: UtcDatetime | None = None
    max_future_skew_seconds: int = 0
    strict_mode: bool = True
    rejected_count: int = 0
    code_hash: str
    config_hash: str
    pramaanx_version: str

    def content_fingerprint(self) -> dict[str, object]:
        """The fields the snapshot hash is computed over.

        ``created_at`` and ``snapshot_id`` are excluded on purpose: two runs over
        identical evidence must agree, even a week apart.
        """
        return {
            "cutoff_at": utc_isoformat(self.cutoff_at),
            "observation_count": self.observation_count,
            "observation_hash_root": self.observation_hash_root,
            "observation_hashes": sorted(self.observation_hashes),
            "source_versions": dict(sorted(self.source_versions.items())),
            "source_counts": dict(sorted(self.source_counts.items())),
            "max_future_skew_seconds": self.max_future_skew_seconds,
            "strict_mode": self.strict_mode,
            "code_hash": self.code_hash,
            "config_hash": self.config_hash,
            "schema_version": self.schema_version,
        }

    @property
    def snapshot_hash(self) -> str:
        return hash_object(self.content_fingerprint())

    def to_json(self) -> str:
        return canonical_bytes(self.model_dump(mode="json")).decode("utf-8")


class Snapshot:
    """A manifest plus the observations it admits."""

    def __init__(self, manifest: SnapshotManifest, observations: Sequence[Observation]) -> None:
        self.manifest = manifest
        self._observations = tuple(observations)

    @property
    def observations(self) -> tuple[Observation, ...]:
        return self._observations

    @property
    def snapshot_id(self) -> str:
        return self.manifest.snapshot_id

    @property
    def snapshot_hash(self) -> str:
        return self.manifest.snapshot_hash

    @property
    def cutoff_at(self) -> datetime:
        return self.manifest.cutoff_at

    def __len__(self) -> int:
        return len(self._observations)

    def __repr__(self) -> str:
        return (
            f"Snapshot(id={self.manifest.snapshot_id!r}, "
            f"cutoff={utc_isoformat(self.cutoff_at)!r}, n={len(self)})"
        )


def _observation_fingerprints(observations: Iterable[Observation]) -> list[str]:
    return sorted(f"{item.observation_id}:{item.raw_content_hash}" for item in observations)


class SnapshotBuilder:
    """Builds, writes and reads cutoff snapshots."""

    def __init__(
        self,
        settings: Settings,
        ledger: EvidenceLedger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger or EvidenceLedger(settings)
        self.clock = clock or SystemClock()
        self.root = settings.storage.snapshots

    def build(self, cutoff_at: datetime, *, persist: bool = True) -> Snapshot:
        """Freeze the evidence available at ``cutoff_at``."""
        guard = CutoffGuard(cutoff_at, self.settings.timeguard)
        # Read the cheap way first (a bounded Parquet predicate), then let the
        # guard re-check every record. The predicate is an optimisation; the
        # guard is the authority.
        candidates = self.ledger.observations_at_or_before(guard.boundary)
        report = guard.screen(candidates)
        admitted = report.admitted

        fingerprints = _observation_fingerprints(admitted)
        sources = {item.source_id for item in admitted}
        source_versions = {
            record.source_id: record.source_version
            for record in self.ledger.read_source_records()
            if record.source_id in sources
        }
        source_counts: dict[str, int] = {}
        for item in admitted:
            source_counts[item.source_id] = source_counts.get(item.source_id, 0) + 1

        manifest = SnapshotManifest(
            snapshot_id="pending",
            cutoff_at=cutoff_at,
            created_at=self.clock.now(),
            observation_count=len(admitted),
            observation_hashes=fingerprints,
            observation_hash_root=merkle_root(item.raw_content_hash for item in admitted),
            source_versions=dict(sorted(source_versions.items())),
            source_counts=dict(sorted(source_counts.items())),
            earliest_observation_at=admitted[0].first_observed_at if admitted else None,
            latest_observation_at=admitted[-1].first_observed_at if admitted else None,
            max_future_skew_seconds=self.settings.timeguard.max_future_skew_seconds,
            strict_mode=self.settings.timeguard.strict,
            rejected_count=report.rejected_count,
            code_hash=code_hash(),
            config_hash=self.settings.config_hash,
            pramaanx_version=_version(),
        )
        manifest.snapshot_id = stable_id("snap", manifest.snapshot_hash, length=20)

        snapshot = Snapshot(manifest, admitted)
        if persist:
            self.write(manifest)
        log.info(
            "snapshot.built",
            snapshot_id=manifest.snapshot_id,
            cutoff=utc_isoformat(cutoff_at),
            observations=len(admitted),
            rejected=report.rejected_count,
        )
        return snapshot

    def write(self, manifest: SnapshotManifest) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{manifest.snapshot_id}.json"
        if target.exists():
            # Snapshots are immutable. An identical rebuild is a no-op; a
            # differing one means the evidence under a fixed cutoff changed,
            # which is exactly the situation that must never pass silently.
            existing = SnapshotManifest.model_validate_json(target.read_text(encoding="utf-8"))
            if existing.snapshot_hash != manifest.snapshot_hash:
                raise ValueError(
                    f"snapshot {manifest.snapshot_id} already exists with a different content "
                    "hash; snapshots are immutable"
                )
            return target
        target.write_text(manifest.to_json(), encoding="utf-8")
        return target

    def read(self, snapshot_id: str) -> SnapshotManifest:
        target = self.root / f"{snapshot_id}.json"
        if not target.exists():
            raise FileNotFoundError(f"unknown snapshot: {snapshot_id}")
        return SnapshotManifest.model_validate_json(target.read_text(encoding="utf-8"))

    def load(self, snapshot_id: str) -> Snapshot:
        """Rehydrate a snapshot and verify it still describes the same evidence."""
        manifest = self.read(snapshot_id)
        guard = CutoffGuard(manifest.cutoff_at, self.settings.timeguard)
        admitted = guard.filter(self.ledger.observations_at_or_before(guard.boundary))
        expected = set(manifest.observation_hashes)
        actual = set(_observation_fingerprints(admitted))
        if expected != actual:
            missing = len(expected - actual)
            extra = len(actual - expected)
            raise ValueError(
                f"snapshot {snapshot_id} no longer matches the ledger "
                f"({missing} missing, {extra} unexpected). Bronze must be append-only."
            )
        return Snapshot(manifest, admitted)

    def list_snapshots(self) -> list[SnapshotManifest]:
        if not self.root.exists():
            return []
        manifests = [
            SnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.root.glob("snap_*.json"))
        ]
        return sorted(manifests, key=lambda item: (item.cutoff_at, item.snapshot_id))

    def latest(self) -> SnapshotManifest | None:
        manifests = self.list_snapshots()
        return manifests[-1] if manifests else None


def _version() -> str:
    from pramaanx import __version__

    return __version__


def parse_cutoff(value: str) -> datetime:
    """Parse a CLI cutoff string into an aware UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
