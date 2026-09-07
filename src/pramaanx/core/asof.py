"""The as-of revision store: point-in-time reads with a published commit.

This is the chokepoint. Everything a forecaster may see comes through
:meth:`RevisionStore.read`, and the order of operations inside it is not an
implementation detail -- it is the correctness argument (revision plan S30.1):

1. resolve the exact immutable manifest the context names;
2. verify the referenced blobs still hash to what the manifest published;
3. keep the revisions eligible under the run's information profile;
4. *within those*, take the latest revision of each source entity;
5. drop tombstones, then apply source tier, shadow and firewall gates;
6. join and project.

Each reordering is a specific bug. Removing tombstones before step 4 resurrects
deleted rows, because the deletion is a later revision than the thing it
deletes. Taking today's latest revision before step 3 erases history, because
today's latest may not have existed at the cutoff. Applying a source gate
before step 4 resurrects a *superseded* row from a source that is now blocked,
because the block removes the newest revision and the ranking then promotes an
older one.

Durability follows the same discipline. Blobs are written to a temporary path,
verified, then renamed into a content-addressed location; the manifest is
published only once every blob it names verifies; the catalogue receipt is
written last, under a single writer lock. A reader consumes receipts, so a
crash anywhere before the last step leaves recoverable litter and no visible
half-commit.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import polars as pl
from pydantic import Field

from pramaanx.clock import Clock, SystemClock
from pramaanx.core.contexts import (
    AvailabilityBasis,
    FitContext,
    ForecastContext,
    InformationProfile,
    ScoreContext,
)
from pramaanx.core.errors import (
    ContractViolationError,
    EligibilityError,
    IdempotencyConflictError,
    RedactedArtifactError,
    StoreCorruptionError,
    WriterLockError,
)
from pramaanx.core.revisions import REVISION_COLUMNS, Revision, check_order_collisions
from pramaanx.hashing import canonical_json, hash_file, hash_object, short_hash, utc_isoformat
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel

log = get_logger(__name__)

_DT = pl.Datetime(time_unit="us", time_zone="UTC")

#: Explicit, not inferred. An all-null timestamp column in one batch and a
#: populated one in the next must not produce two different parquet schemas.
REVISION_SCHEMA: dict[str, Any] = {
    "table": pl.Utf8,
    "source_id": pl.Utf8,
    "entity_id": pl.Utf8,
    "revision_id": pl.Utf8,
    "source_revision_order": pl.Int64,
    "operation": pl.Utf8,
    "valid_time_start": _DT,
    "valid_time_end": _DT,
    "publish_time": _DT,
    "available_time": _DT,
    "retrieved_time": _DT,
    "ingested_at": _DT,
    "availability_basis": pl.Utf8,
    "availability_evidence_ref": pl.Utf8,
    "payload_json": pl.Utf8,
    "payload_hash": pl.Utf8,
    "schema_version": pl.Int32,
}

#: Bumped when the canonical part layout changes. Part of the manifest hash, so
#: a serialisation change cannot masquerade as unchanged content.
CANONICAL_LAYOUT_VERSION = 1

AnyContext = ForecastContext | FitContext | ScoreContext


class _Head:
    """Sentinel for "continue from the catalogue head".

    Needed because ``None`` has to keep its literal meaning -- *no parent*, a
    fresh chain -- which a lockbox seal and an independent fixture both want.
    A single ``None`` default would have made those two indistinguishable.
    """

    def __repr__(self) -> str:
        return "HEAD"


HEAD = _Head()


class ReadPolicy(Protocol):
    """Step 5's gate. Returns a denial reason, or ``None`` to admit."""

    def deny_reason(self, source_id: str) -> str | None: ...


class AllowAllSources:
    """The default policy: no source is withheld.

    Named rather than implied. A run whose policy is "everything" should say so
    in its policy hash, so a later run with a shadow source is a different read.
    """

    def deny_reason(self, source_id: str) -> str | None:  # noqa: ARG002
        return None


@dataclass(frozen=True)
class WithheldSources:
    """Withhold named sources and every read that would reach them.

    Used for shadow-source audits and the evaluation firewall. It withholds by
    source, which is necessary and not sufficient: a translated or cached
    descendant of a withheld source is withheld by lineage, which
    :mod:`pramaanx.core.artifacts` tracks, not by this policy.
    """

    sources: frozenset[str]
    reason: str = "withheld_source"

    def deny_reason(self, source_id: str) -> str | None:
        return self.reason if source_id in self.sources else None


class PartRef(PramaanModel):
    """One immutable parquet part, named by the hash of its bytes."""

    blob_hash: str
    path: str
    table: str
    rows: int = Field(ge=0)
    min_available_time: UtcDatetime | None = None
    max_available_time: UtcDatetime | None = None

    def identity(self) -> dict[str, Any]:
        return {"blob_hash": self.blob_hash, "table": self.table, "rows": self.rows}


class StoreManifest(VersionedModel):
    """The pinned set of parts one context may read. Immutable once published.

    A manifest is a chain: each commit publishes parent parts plus its own. So
    ``replay(hash)`` is exact by construction, and a later commit cannot alter
    what an earlier manifest resolves to.
    """

    manifest_hash: str = ""
    parent_manifest: str | None = None
    created_at: UtcDatetime
    parts: tuple[PartRef, ...] = ()
    layout_version: int = CANONICAL_LAYOUT_VERSION

    def fingerprint(self) -> dict[str, Any]:
        """What the manifest hash covers.

        ``created_at`` is excluded so two identical commits agree. The table
        each part belongs to is included, because moving the same bytes to a
        different table is a different snapshot (S30.2).
        """
        return {
            "layout_version": self.layout_version,
            "parent_manifest": self.parent_manifest,
            "parts": sorted(
                (part.identity() for part in self.parts),
                key=lambda item: (item["table"], item["blob_hash"]),
            ),
            "schema_version": self.schema_version,
        }

    def with_hash(self) -> StoreManifest:
        return self.model_copy(update={"manifest_hash": hash_object(self.fingerprint())})

    def parts_for(self, table: str) -> tuple[PartRef, ...]:
        return tuple(part for part in self.parts if part.table == table)

    def tables(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for part in self.parts:
            counts[part.table] = counts.get(part.table, 0) + part.rows
        return dict(sorted(counts.items()))


class CommitReceipt(VersionedModel):
    """Proof that one commit reached durable storage."""

    idempotency_key: str
    manifest_hash: str
    parent_manifest: str | None
    committed_at: UtcDatetime
    rows: int = Field(ge=0)
    tables: dict[str, int] = Field(default_factory=dict)
    #: Digest of the committed revisions. A retry under the same key must carry
    #: the same payload; a different one is a caller bug, not a retry.
    payload_digest: str
    replayed: bool = False
    """True when this receipt was returned to a retry rather than freshly written."""


@dataclass(frozen=True)
class EligibleTable:
    """The result of one as-of read: rows plus what it took to produce them."""

    table: str
    frame: pl.DataFrame
    manifest_hash: str
    context_identity: str
    denied_sources: tuple[str, ...] = ()
    tombstoned: int = 0
    ineligible: int = 0

    @property
    def rows(self) -> int:
        return self.frame.height

    def payloads(self) -> pl.DataFrame:
        """Decode the payload column into real columns.

        Kept lazy rather than done in :meth:`read` because a caller that only
        needs entity ids should not pay to decode every payload.
        """
        if self.frame.is_empty():
            return pl.DataFrame()
        decoded = self.frame["payload_json"].str.json_decode()
        return (
            pl.DataFrame({"entity_id": self.frame["entity_id"]})
            .with_columns(decoded.alias("payload"))
            .unnest("payload")
        )

    def records(self) -> list[dict[str, Any]]:
        return [json.loads(item) for item in self.frame["payload_json"].to_list()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "rows": self.rows,
            "manifest_hash": self.manifest_hash,
            "context_identity": self.context_identity,
            "denied_sources": list(self.denied_sources),
            "tombstoned": self.tombstoned,
            "ineligible": self.ineligible,
        }


@dataclass(frozen=True)
class RecoveryReport:
    """What a crash left behind, by kind. Deliberately five kinds, not one.

    Lumping these together is how a partially written blob becomes a published
    snapshot. Each has a different safe action, and only two are ever deleted.
    """

    temp_files: tuple[str, ...] = ()
    orphan_blobs: tuple[str, ...] = ()
    orphan_manifests: tuple[str, ...] = ()
    missing_blobs: tuple[str, ...] = ()
    corrupt_blobs: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    dry_run: bool = True

    @property
    def healthy(self) -> bool:
        """Reachable data is intact. Litter is untidy, not unsafe."""
        return not self.missing_blobs and not self.corrupt_blobs

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "healthy": self.healthy,
            "temp_files": list(self.temp_files),
            "orphan_blobs": list(self.orphan_blobs),
            "orphan_manifests": list(self.orphan_manifests),
            "missing_blobs": list(self.missing_blobs),
            "corrupt_blobs": list(self.corrupt_blobs),
            "removed": list(self.removed),
        }


class _WriterLock:
    """One writer owns the catalogue. Workers hand back artefacts instead.

    An exclusive-create lock file, with a bounded wait. Bounded because a
    forecast run that blocks forever on a stale lock is indistinguishable from
    one that is working, and the plan asks for an explicit failure instead.
    """

    def __init__(self, path: Path, *, timeout_seconds: float = 30.0, poll: float = 0.05) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.poll = poll
        self._fd: int | None = None

    def __enter__(self) -> _WriterLock:
        deadline = time.monotonic() + self.timeout_seconds
        owner = canonical_json({"pid": os.getpid(), "acquired_at": time.time()})
        while True:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, owner.encode("utf-8"))
                self._fd = fd
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise WriterLockError(
                        "another process owns the store writer lock",
                        lock=self.path.as_posix(),
                        waited_seconds=self.timeout_seconds,
                    ) from None
                time.sleep(self.poll)

    def __exit__(self, *_: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.path.unlink(missing_ok=True)


class RevisionStore:
    """Point-in-time reads, atomic commits, and a recoverable layout."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Clock | None = None,
        policy: ReadPolicy | None = None,
        verify_on_read: bool = True,
        lock_timeout_seconds: float = 30.0,
    ) -> None:
        self.root = Path(root)
        self.clock = clock or SystemClock()
        self.policy = policy or AllowAllSources()
        self.verify_on_read = verify_on_read
        self.lock_timeout_seconds = lock_timeout_seconds
        self._verified: set[str] = set()

    # -- layout ----------------------------------------------------------
    @property
    def blobs(self) -> Path:
        return self.root / "blobs"

    @property
    def manifests(self) -> Path:
        return self.root / "manifests"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    @property
    def catalogue_path(self) -> Path:
        return self.root / "catalogue.json"

    @property
    def lock_path(self) -> Path:
        return self.root / ".writer.lock"

    @property
    def read_log_path(self) -> Path:
        return self.root / "reads.jsonl"

    def _blob_path(self, blob_hash: str) -> Path:
        digest = blob_hash.removeprefix("sha256:")
        return self.blobs / digest[:2] / f"{digest}.parquet"

    def _manifest_path(self, manifest_hash: str) -> Path:
        return self.manifests / f"{short_hash(manifest_hash, 64)}.json"

    # -- catalogue -------------------------------------------------------
    def _load_catalogue(self) -> dict[str, Any]:
        if not self.catalogue_path.exists():
            return {"head": None, "receipts": {}, "manifests": []}
        return json.loads(self.catalogue_path.read_text(encoding="utf-8"))

    def _save_catalogue(self, catalogue: dict[str, Any]) -> None:
        """Replace the catalogue atomically.

        A single file swapped by rename, rather than a database transaction
        spanning parquet and a catalogue that cannot share one. The rename is
        the commit point: a reader either sees the old catalogue or the new one.
        """
        self.tmp.mkdir(parents=True, exist_ok=True)
        tmp = self.tmp / f"catalogue-{os.getpid()}.json.tmp"
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(canonical_json(catalogue))
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(self.catalogue_path)

    @property
    def head(self) -> str | None:
        """The newest committed manifest, or ``None`` on an empty store.

        A context must pin a hash, not ``HEAD``. This exists so a caller can
        resolve one *before* building the context, which is the point at which
        pinning is still meaningful.
        """
        head = self._load_catalogue().get("head")
        return str(head) if head else None

    def receipts(self) -> list[CommitReceipt]:
        catalogue = self._load_catalogue()
        return [
            CommitReceipt.model_validate(item)
            for _, item in sorted(catalogue.get("receipts", {}).items())
        ]

    # -- commit ----------------------------------------------------------
    def commit(
        self,
        revisions: Iterable[Revision],
        *,
        idempotency_key: str,
        parent_manifest: str | _Head | None = HEAD,
    ) -> CommitReceipt:
        """Publish a batch. Returns the same receipt when replayed after a crash."""
        batch = sorted(
            revisions,
            key=lambda item: (
                item.table,
                item.source_id,
                item.entity_id,
                item.source_revision_order,
                item.revision_id,
            ),
        )
        check_order_collisions(batch)
        payload_digest = hash_object([item.revision_id for item in batch])

        with _WriterLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            catalogue = self._load_catalogue()
            existing = catalogue.get("receipts", {}).get(idempotency_key)
            if existing is not None:
                receipt = CommitReceipt.model_validate(existing)
                if receipt.payload_digest != payload_digest:
                    raise IdempotencyConflictError(
                        "idempotency key already committed a different payload",
                        idempotency_key=idempotency_key,
                        committed_digest=receipt.payload_digest,
                        offered_digest=payload_digest,
                    )
                return receipt.model_copy(update={"replayed": True})

            if isinstance(parent_manifest, _Head):
                parent = catalogue.get("head")
            else:
                parent = parent_manifest
            parent_parts: tuple[PartRef, ...] = ()
            if parent:
                parent_parts = self._load_manifest_unlocked(str(parent)).parts

            new_parts = self._write_parts(batch)
            manifest = StoreManifest(
                parent_manifest=str(parent) if parent else None,
                created_at=self.clock.now(),
                parts=tuple(sorted(parent_parts + new_parts, key=lambda p: (p.table, p.blob_hash))),
            ).with_hash()
            self._publish_manifest(manifest)

            receipt = CommitReceipt(
                idempotency_key=idempotency_key,
                manifest_hash=manifest.manifest_hash,
                parent_manifest=manifest.parent_manifest,
                committed_at=self.clock.now(),
                rows=len(batch),
                tables={part.table: part.rows for part in new_parts},
                payload_digest=payload_digest,
            )
            catalogue.setdefault("receipts", {})[idempotency_key] = receipt.model_dump(mode="json")
            catalogue["head"] = manifest.manifest_hash
            manifests = list(catalogue.get("manifests", []))
            if manifest.manifest_hash not in manifests:
                manifests.append(manifest.manifest_hash)
            catalogue["manifests"] = manifests
            self._save_catalogue(catalogue)

        log.info(
            "store.commit",
            manifest=short_hash(manifest.manifest_hash),
            rows=len(batch),
            tables=sorted(receipt.tables),
        )
        return receipt

    def _write_parts(self, batch: Sequence[Revision]) -> tuple[PartRef, ...]:
        """One verified, content-addressed parquet part per table in the batch."""
        by_table: dict[str, list[Revision]] = {}
        for revision in batch:
            by_table.setdefault(revision.table, []).append(revision)

        self.tmp.mkdir(parents=True, exist_ok=True)
        parts: list[PartRef] = []
        for table, rows in sorted(by_table.items()):
            frame = pl.DataFrame([item.to_row() for item in rows], schema=REVISION_SCHEMA).select(
                REVISION_COLUMNS
            )
            tmp = self.tmp / f"part-{os.getpid()}-{table}-{len(parts)}.parquet.tmp"
            frame.write_parquet(tmp, compression="zstd", statistics=False)
            blob_hash = hash_file(tmp)
            # Verify before the rename, not after: a part that does not read
            # back is litter in tmp, never a blob a manifest can name.
            if pl.read_parquet(tmp).height != frame.height:
                raise StoreCorruptionError("written part did not read back", table=table)
            target = self._blob_path(blob_hash)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                tmp.unlink()
            else:
                tmp.replace(target)
            available = frame["available_time"]
            parts.append(
                PartRef(
                    blob_hash=blob_hash,
                    path=target.relative_to(self.root).as_posix(),
                    table=table,
                    rows=frame.height,
                    min_available_time=available.min(),  # type: ignore[arg-type]
                    max_available_time=available.max(),  # type: ignore[arg-type]
                )
            )
        return tuple(parts)

    def _publish_manifest(self, manifest: StoreManifest) -> None:
        for part in manifest.parts:
            path = self.root / part.path
            if not path.exists():
                raise StoreCorruptionError(
                    "manifest names a blob that does not exist", blob=part.blob_hash
                )
        self.manifests.mkdir(parents=True, exist_ok=True)
        target = self._manifest_path(manifest.manifest_hash)
        if target.exists():
            return
        tmp = self.tmp / f"{target.name}.tmp"
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(canonical_json(manifest.model_dump(mode="json")))
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(target)

    # -- manifests -------------------------------------------------------
    def load_manifest(self, manifest_hash: str) -> StoreManifest:
        return self._load_manifest_unlocked(manifest_hash)

    def _load_manifest_unlocked(self, manifest_hash: str) -> StoreManifest:
        path = self._manifest_path(manifest_hash)
        if not path.exists():
            raise ContractViolationError("no such manifest", manifest_hash=manifest_hash)
        manifest = StoreManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if manifest.manifest_hash != manifest_hash:
            raise StoreCorruptionError(
                "manifest content does not match its name",
                expected=manifest_hash,
                found=manifest.manifest_hash,
            )
        return manifest

    def _verify_parts(self, parts: Sequence[PartRef]) -> None:
        missing: list[str] = []
        corrupt: list[str] = []
        for part in parts:
            if part.blob_hash in self._verified:
                continue
            path = self.root / part.path
            if not path.exists():
                missing.append(part.blob_hash)
                continue
            if hash_file(path) != part.blob_hash:
                corrupt.append(part.blob_hash)
                continue
            self._verified.add(part.blob_hash)
        if missing:
            raise RedactedArtifactError(
                "manifest names blobs that are no longer on disk; replay of this "
                "snapshot cannot be exact",
                blobs=sorted(missing),
            )
        if corrupt:
            raise StoreCorruptionError("blob bytes changed under a manifest", blobs=sorted(corrupt))

    # -- read ------------------------------------------------------------
    def read(
        self,
        table: str,
        *,
        ctx: AnyContext,
        columns: tuple[str, ...] | None = None,
    ) -> EligibleTable:
        """The one read path. See the module docstring for why the order is fixed."""
        return self._read(table, ctx=ctx, cutoff=ctx.cutoff_at, columns=columns)

    def read_mature(
        self,
        table: str,
        *,
        ctx: FitContext,
        columns: tuple[str, ...] | None = None,
    ) -> EligibleTable:
        """Training labels: eligible at the *fit* cutoff, not the origin cutoff.

        Features for a training row were built at that row's own origin. Its
        label matured later, and the fit is allowed to see it, which is exactly
        why these are two boundaries and two methods (S33.1).
        """
        return self._read(table, ctx=ctx, cutoff=ctx.fit_cutoff, columns=columns)

    def read_reference(
        self,
        table: str,
        *,
        ctx: ScoreContext,
        columns: tuple[str, ...] | None = None,
    ) -> EligibleTable:
        """Matured outcomes for scoring an already frozen forecast.

        Reachable only with a :class:`ScoreContext`, which names the forecast
        it may score. A forecaster is never handed one.
        """
        return self._read(
            table,
            ctx=ctx,
            cutoff=ctx.issue_time,
            columns=columns,
            manifest_hash=ctx.reference_manifest,
        )

    def _read(
        self,
        table: str,
        *,
        ctx: AnyContext,
        cutoff: datetime,
        columns: tuple[str, ...] | None,
        manifest_hash: str | None = None,
    ) -> EligibleTable:
        # Step 1: resolve the pinned manifest. Never a glob over the store.
        pinned = manifest_hash or ctx.input_manifest
        manifest = self.load_manifest(pinned)
        parts = manifest.parts_for(table)

        # Step 2: verify the bytes still match what was published.
        if self.verify_on_read:
            self._verify_parts(parts)

        if not parts:
            empty = pl.DataFrame(schema=REVISION_SCHEMA)
            result = EligibleTable(table, empty, pinned, ctx.identity())
            self._log_read(table, ctx, result)
            return result

        frame = pl.read_parquet([self.root / part.path for part in parts])
        total = frame.height

        # Step 3: eligibility under this run's information profile.
        eligible = self._eligible(frame, ctx=ctx, cutoff=cutoff)
        ineligible = total - eligible.height

        # Step 4: the latest eligible revision of each source entity.
        latest = self._latest_per_entity(eligible)

        # Step 5: tombstones first, then source gates.
        alive = latest.filter(pl.col("operation") == "upsert")
        tombstoned = latest.height - alive.height
        admitted, denied = self._apply_policy(alive)

        # Step 6: order and project.
        admitted = admitted.sort(["source_id", "entity_id"])
        if columns is not None:
            admitted = admitted.select(columns)

        result = EligibleTable(
            table=table,
            frame=admitted,
            manifest_hash=pinned,
            context_identity=ctx.identity(),
            denied_sources=denied,
            tombstoned=tombstoned,
            ineligible=ineligible,
        )
        self._log_read(table, ctx, result)
        return result

    def _eligible(self, frame: pl.DataFrame, *, ctx: AnyContext, cutoff: datetime) -> pl.DataFrame:
        """Step 3. The profile decides which instant eligibility is judged on."""
        boundary = cutoff.astimezone(UTC)
        if ctx.profile is InformationProfile.PROSPECTIVE_OBSERVED:
            instant = pl.max_horizontal("available_time", "retrieved_time")
        else:
            instant = pl.col("available_time")
        working = frame.with_columns(instant.alias("eligible_at"))

        if ctx.profile is InformationProfile.STRICT_HISTORICAL:
            # A page that currently says "2019" is not evidence of its 2019
            # bytes. Strict runs need a basis that can be checked (S29.1).
            unresolved = working.filter(
                pl.col("availability_basis") == str(AvailabilityBasis.UNRESOLVED)
            )
            if unresolved.height:
                raise EligibilityError(
                    "strict historical read reached revisions with unresolved "
                    "availability; record the evidence or run this as an "
                    "engineering replay",
                    rows=unresolved.height,
                    entity_ids=sorted(set(unresolved["entity_id"].to_list()))[:5],
                )
        return working.filter(pl.col("eligible_at") <= boundary)

    def _latest_per_entity(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Step 4, with ties refused rather than broken.

        A tie means two revisions claim the same place in one source's history.
        Any tie-break here -- hash order, file order -- would be the store
        silently choosing which correction won.
        """
        if frame.is_empty():
            return frame
        ranked = frame.with_columns(
            pl.col("source_revision_order").max().over(["source_id", "entity_id"]).alias("_top")
        ).filter(pl.col("source_revision_order") == pl.col("_top"))
        collisions = (
            ranked.group_by(["source_id", "entity_id"])
            .agg(pl.col("revision_id").n_unique().alias("n"))
            .filter(pl.col("n") > 1)
        )
        if collisions.height:
            raise ContractViolationError(
                "two revisions claim the same source_revision_order for one entity",
                entity_ids=sorted(collisions["entity_id"].to_list())[:5],
            )
        return ranked.drop("_top")

    def _apply_policy(self, frame: pl.DataFrame) -> tuple[pl.DataFrame, tuple[str, ...]]:
        """Step 5's gate. Applied after ranking, so a block cannot promote."""
        if frame.is_empty():
            return frame, ()
        denied = {
            source
            for source in frame["source_id"].unique().to_list()
            if self.policy.deny_reason(source) is not None
        }
        if not denied:
            return frame, ()
        return frame.filter(~pl.col("source_id").is_in(list(denied))), tuple(sorted(denied))

    def _log_read(self, table: str, ctx: AnyContext, result: EligibleTable) -> None:
        """Append the access log line. Capabilities stop accidents; this records them."""
        entry = {
            "at": utc_isoformat(self.clock.now()),
            "table": table,
            "context": type(ctx).__name__,
            "profile": str(ctx.profile),
            "role": str(ctx.role),
            "cutoff_at": utc_isoformat(ctx.cutoff_at),
            **result.to_dict(),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        with self.read_log_path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(entry) + "\n")

    # -- replay and recovery ---------------------------------------------
    def replay(self, manifest_hash: str) -> dict[str, pl.DataFrame]:
        """The exact stored state a manifest names, table by table."""
        manifest = self.load_manifest(manifest_hash)
        self._verify_parts(manifest.parts)
        out: dict[str, pl.DataFrame] = {}
        for table in sorted(manifest.tables()):
            paths = [self.root / part.path for part in manifest.parts_for(table)]
            out[table] = pl.read_parquet(paths).sort(["source_id", "entity_id", "revision_id"])
        return out

    def recover(self, *, dry_run: bool = True, grace_seconds: float = 3600.0) -> RecoveryReport:
        """Classify what a crash left behind. Deletes only litter, never data.

        Reachability is computed over *every* manifest the catalogue knows, not
        just the head, because an earlier snapshot is exactly what a replay
        needs and exactly what a naive "keep the latest" sweep would destroy.
        """
        catalogue = self._load_catalogue()
        known = {str(item) for item in catalogue.get("manifests", [])}
        head = catalogue.get("head")
        if head:
            known.add(str(head))

        reachable: set[str] = set()
        missing: list[str] = []
        corrupt: list[str] = []
        for manifest_hash in sorted(known):
            manifest = self._load_manifest_unlocked(manifest_hash)
            for part in manifest.parts:
                reachable.add(part.blob_hash)
                path = self.root / part.path
                if not path.exists():
                    missing.append(part.blob_hash)
                elif hash_file(path) != part.blob_hash:
                    corrupt.append(part.blob_hash)

        now = time.time()
        temp_files = sorted(p.relative_to(self.root).as_posix() for p in self.tmp.glob("*.tmp"))
        orphan_blobs = sorted(
            path.relative_to(self.root).as_posix()
            for path in self.blobs.rglob("*.parquet")
            if hash_file(path) not in reachable and now - path.stat().st_mtime > grace_seconds
        )
        orphan_manifests = sorted(
            path.name
            for path in self.manifests.glob("*.json")
            if path.stem not in {short_hash(item, 64) for item in known}
        )

        removed: list[str] = []
        if not dry_run:
            for relative in temp_files + orphan_blobs:
                (self.root / relative).unlink(missing_ok=True)
                removed.append(relative)

        return RecoveryReport(
            temp_files=tuple(temp_files),
            orphan_blobs=tuple(orphan_blobs),
            orphan_manifests=tuple(orphan_manifests),
            missing_blobs=tuple(sorted(set(missing))),
            corrupt_blobs=tuple(sorted(set(corrupt))),
            removed=tuple(removed),
            dry_run=dry_run,
        )
