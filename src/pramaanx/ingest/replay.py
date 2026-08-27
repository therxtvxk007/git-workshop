"""Deterministic replay of stored bronze evidence.

Bronze is append-only and content-addressed, which makes replay *possible*. It
does not make it *verified*. Between an ingestion and a replay a payload can be
deleted, its bytes can change underneath a reference that still resolves, a
source record can go missing, or an acquisition can have stopped halfway and
left a partial window behind. Every one of those reads, to naive code, as a
smaller corpus -- and a smaller corpus does not raise; it quietly produces a
forecast from less evidence than the run it claims to reproduce.

So replay here is a verification pass that happens to return observations,
rather than a read that happens to check a few things. Three rules:

*Fail closed.* :meth:`BronzeReplay.replay` refuses to return a corpus it found
anything wrong with. A replay that silently drops the three observations whose
payloads vanished is worse than no replay, because its output looks exactly like
a legitimate one.

*Pin everything that could change the answer.* The manifest carries source
versions, source contracts, the config hash, the code hash and the dependency
lock hash. Replays whose pins differ are not comparable, and the manifest is
what makes that checkable rather than assumed.

*Report before deciding.* :meth:`BronzeReplay.verify` never raises. It is how
you find out what is wrong with a corpus; ``replay`` is how you refuse to use
one. Fusing them would leave no way to inspect a broken ledger without
inspecting it through an exception.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from pramaanx.clock import Clock, SystemClock
from pramaanx.config import Settings, StorageConfig
from pramaanx.hashing import (
    hash_bytes,
    hash_file,
    hash_object,
    hash_tree,
    merkle_root,
    stable_id,
    utc_isoformat,
)
from pramaanx.ingest.contracts import contract_summaries
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel
from pramaanx.schemas.observation import Observation
from pramaanx.timeguard.cutoff import CutoffGuard
from pramaanx.timeguard.snapshots import code_hash

log = get_logger(__name__)


class ReplayDefect(StrEnum):
    """What can be wrong with stored bronze evidence.

    Each is a way a corpus can shrink or shift without anything failing, which
    is why each is named rather than collapsed into one "invalid" state: the
    remedy differs. A missing payload is a storage loss; a mismatched one is a
    corruption or a tamper; an unknown source is a bookkeeping failure during
    ingestion.
    """

    #: The payload reference does not resolve. The evidence is gone.
    MISSING_PAYLOAD = "missing_payload"
    #: The payload resolves but its bytes no longer hash to what was recorded.
    PAYLOAD_HASH_MISMATCH = "payload_hash_mismatch"
    #: An observation cites a source with no record in the ledger, so its
    #: licence, tier and version -- everything provenance depends on -- is
    #: unknown.
    UNKNOWN_SOURCE = "unknown_source"
    #: Two observations share an id but not their content hash. Ids are derived
    #: from content, so this means one of them was not built the way it claims.
    ID_COLLISION = "id_collision"
    #: ``first_observed_at`` is after ``retrieved_at``: the record claims to
    #: have become available after it was fetched.
    IMPOSSIBLE_TIMELINE = "impossible_timeline"
    #: The observation id does not derive from this observation's own content.
    #: Strictly stronger than :attr:`ID_COLLISION`, which needs two records to
    #: disagree before it fires: a single hand-edited record is invisible to a
    #: collision check and caught by this one.
    NON_REPRODUCIBLE_ID = "non_reproducible_id"
    #: A stored payload no observation refers to. Bronze is written
    #: observations-last, so a payload without one is the signature of an
    #: acquisition that died between writing bytes and recording them.
    ORPHANED_PAYLOAD = "orphaned_payload"
    #: Two source records claim the same ``source_id``, so which licence, tier
    #: and version applied to an ingestion is no longer answerable.
    DUPLICATE_SOURCE_RECORD = "duplicate_source_record"


class ReplayFinding(PramaanModel):
    """One defect, attributed to the record it was found in."""

    defect: ReplayDefect
    source_id: str
    detail: str
    #: Empty for a defect that belongs to the corpus rather than to one record
    #: -- an orphaned payload has no observation to attribute it to, which is
    #: precisely what is wrong with it.
    observation_id: str = ""
    payload_ref: str | None = None

    @property
    def subject(self) -> str:
        return self.observation_id or self.payload_ref or "(corpus)"

    def __str__(self) -> str:
        return f"{self.defect.value}: {self.subject} ({self.source_id}) -- {self.detail}"


class ReplayIntegrityError(RuntimeError):
    """Raised when a strict replay finds a corpus it will not vouch for."""

    def __init__(self, findings: Sequence[ReplayFinding]) -> None:
        self.findings = list(findings)
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.defect.value] = counts.get(finding.defect.value, 0) + 1
        summary = ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
        first = "; ".join(str(finding) for finding in self.findings[:3])
        super().__init__(
            f"bronze replay refused: {len(self.findings)} defect(s) [{summary}]. {first}"
            + ("; ..." if len(self.findings) > 3 else "")
            + ". A replay that drops what it cannot verify produces a forecast from "
            "less evidence than the run it claims to reproduce, and looks identical "
            "to a legitimate one."
        )


def dependency_lock_hash(root: Path | None = None) -> str:
    """Hash of ``uv.lock``, or the literal ``"absent"``.

    Recorded as a string either way rather than as ``None``. An environment
    without the lock file genuinely has different provenance from one with it,
    and saying so is what stops two incomparable replays comparing equal.
    """
    search = root or Path(__file__).resolve().parents[3]
    lock = search / "uv.lock"
    return hash_file(lock) if lock.is_file() else "absent"


class ReplayManifest(VersionedModel):
    """Provenance for one replay, and the fingerprint that identifies it."""

    replay_id: str
    created_at: UtcDatetime
    observation_count: int = Field(ge=0)
    observation_hash_root: str
    payload_bytes: int = Field(ge=0)
    source_versions: dict[str, str] = Field(default_factory=dict)
    source_contracts: dict[str, str] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    config_hash: str
    code_hash: str
    dependency_lock_hash: str

    def content_fingerprint(self) -> dict[str, object]:
        """The fields the replay hash is computed over.

        ``created_at`` and ``replay_id`` are excluded: two replays of the same
        bronze under the same pins must agree, a week apart.

        ``source_contracts`` is excluded for the reason set out on
        ``SnapshotManifest.content_fingerprint`` -- learning that a source is
        verified changes what is known about the source, not what the corpus
        contains. The dependency lock hash is *included*, because a different
        dependency set can parse the same bytes differently, which is exactly
        the kind of difference a replay exists to detect.
        """
        return {
            "observation_count": self.observation_count,
            "observation_hash_root": self.observation_hash_root,
            "payload_bytes": self.payload_bytes,
            "source_versions": dict(sorted(self.source_versions.items())),
            "source_counts": dict(sorted(self.source_counts.items())),
            "config_hash": self.config_hash,
            "code_hash": self.code_hash,
            "dependency_lock_hash": self.dependency_lock_hash,
            "schema_version": self.schema_version,
        }

    @property
    def replay_hash(self) -> str:
        return hash_object(self.content_fingerprint())


class ReplayResult:
    """A verified corpus and the manifest that pins it."""

    def __init__(self, manifest: ReplayManifest, observations: Sequence[Observation]) -> None:
        self.manifest = manifest
        self.observations = list(observations)

    @property
    def replay_hash(self) -> str:
        return self.manifest.replay_hash

    def __len__(self) -> int:
        return len(self.observations)

    def __repr__(self) -> str:
        return (
            f"ReplayResult(replay_id={self.manifest.replay_id!r}, "
            f"observations={len(self.observations)})"
        )


class BronzeReplay:
    """Reads bronze back, checks it, and refuses to vouch for a broken corpus."""

    def __init__(
        self,
        settings: Settings,
        ledger: EvidenceLedger,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.clock = clock or SystemClock()

    def verify(self) -> list[ReplayFinding]:
        """Every defect in stored bronze, sorted. Never raises.

        Ordered by ``(observation_id, defect)`` so two runs over the same
        damaged ledger produce the same report -- a diff of two verification
        runs should show what changed in the ledger, not what changed in the
        iteration order.
        """
        return self._findings_for(
            self.ledger.read_observations(),
            {record.source_id for record in self.ledger.read_source_records()},
            source_ids=[record.source_id for record in self.ledger.read_source_records()],
            check_orphans=True,
        )

    def _findings_for(
        self,
        observations: Sequence[Observation],
        known_sources: set[str],
        *,
        source_ids: Sequence[str] | None = None,
        check_orphans: bool = False,
    ) -> list[ReplayFinding]:
        """The checks themselves, over an explicit corpus.

        Split out from :meth:`verify` so each defect can be provoked directly in
        a test. Some of them -- an impossible timeline above all -- can only
        arise from a writer that bypassed the schema, and there is no honest way
        to get such a record into a real ledger in order to check that the
        replay catches it.
        """
        payloads = self.ledger.payloads

        findings: list[ReplayFinding] = []
        seen: dict[str, str] = {}

        for observation in observations:
            oid = observation.observation_id

            if not payloads.exists(observation.payload_ref):
                findings.append(
                    ReplayFinding(
                        defect=ReplayDefect.MISSING_PAYLOAD,
                        observation_id=oid,
                        source_id=observation.source_id,
                        detail=f"payload_ref {observation.payload_ref!r} does not resolve",
                    )
                )
            elif not payloads.verify(observation.payload_ref, observation.raw_content_hash):
                actual = hash_bytes(payloads.get(observation.payload_ref))
                findings.append(
                    ReplayFinding(
                        defect=ReplayDefect.PAYLOAD_HASH_MISMATCH,
                        observation_id=oid,
                        source_id=observation.source_id,
                        detail=(
                            f"stored bytes hash to {actual}, recorded as "
                            f"{observation.raw_content_hash}"
                        ),
                    )
                )

            expected_id = Observation.build_id(
                observation.source_id,
                observation.raw_content_hash,
                utc_isoformat(observation.first_observed_at),
            )
            if oid != expected_id:
                findings.append(
                    ReplayFinding(
                        defect=ReplayDefect.NON_REPRODUCIBLE_ID,
                        observation_id=oid,
                        source_id=observation.source_id,
                        detail=(
                            f"id does not derive from this record's own content; "
                            f"expected {expected_id}"
                        ),
                    )
                )

            if observation.source_id not in known_sources:
                findings.append(
                    ReplayFinding(
                        defect=ReplayDefect.UNKNOWN_SOURCE,
                        observation_id=oid,
                        source_id=observation.source_id,
                        detail="no source record; licence, tier and version are unknown",
                    )
                )

            previous = seen.get(oid)
            if previous is not None and previous != observation.raw_content_hash:
                findings.append(
                    ReplayFinding(
                        defect=ReplayDefect.ID_COLLISION,
                        observation_id=oid,
                        source_id=observation.source_id,
                        detail=(
                            f"two contents share this id: {previous} and "
                            f"{observation.raw_content_hash}"
                        ),
                    )
                )
            seen[oid] = observation.raw_content_hash

            # Observation's own validator rejects this at construction, so it
            # can only appear in a record written by something that bypassed the
            # schema. Checked anyway: replay is the last place to catch it
            # before a cutoff filter trusts the timestamp.
            if observation.first_observed_at > observation.retrieved_at:
                findings.append(
                    ReplayFinding(
                        defect=ReplayDefect.IMPOSSIBLE_TIMELINE,
                        observation_id=oid,
                        source_id=observation.source_id,
                        detail=(
                            f"first_observed_at {observation.first_observed_at.isoformat()} "
                            f"is after retrieved_at {observation.retrieved_at.isoformat()}"
                        ),
                    )
                )

        if source_ids is not None:
            counts: dict[str, int] = {}
            for source_id in source_ids:
                counts[source_id] = counts.get(source_id, 0) + 1
            findings.extend(
                ReplayFinding(
                    defect=ReplayDefect.DUPLICATE_SOURCE_RECORD,
                    source_id=source_id,
                    detail=(
                        f"{count} source records claim this id; which licence, tier and "
                        "version applied to an ingestion is no longer answerable"
                    ),
                )
                for source_id, count in sorted(counts.items())
                if count > 1
            )

        if check_orphans:
            findings.extend(self._orphaned_payloads(observations))

        return sorted(findings, key=lambda f: (f.subject, f.defect.value))

    def _orphaned_payloads(self, observations: Sequence[Observation]) -> list[ReplayFinding]:
        """Stored payloads that no observation refers to.

        This is the direction the obvious check misses. Walking observations
        finds evidence whose bytes are gone; walking bytes finds an acquisition
        that wrote payloads and then died before recording the observations that
        referred to them. Bronze is written observations-last precisely so that
        failure leaves this signature, and a replay that ignored it would
        cheerfully reproduce a truncated corpus as though it were complete.
        """
        payload_root = self.ledger.payloads.root
        if not payload_root.is_dir():
            return []
        referenced = {observation.payload_ref for observation in observations}
        stored = {
            path.relative_to(payload_root).as_posix()
            for path in payload_root.rglob("*.bin")
            if path.is_file()
        }
        return [
            ReplayFinding(
                defect=ReplayDefect.ORPHANED_PAYLOAD,
                source_id="",
                payload_ref=payload_ref,
                detail=(
                    "stored payload no observation refers to; the acquisition that wrote "
                    "it did not survive to record the observation, so this corpus is a "
                    "partial ingestion"
                ),
            )
            for payload_ref in sorted(stored - referenced)
        ]

    def replay(self, *, strict: bool = True, persist: bool = False) -> ReplayResult:
        """Reconstruct the stored corpus, refusing a damaged one.

        ``strict=False`` returns the corpus with its defects logged rather than
        raised. It exists for triage on a ledger you already know is broken, and
        its result must not be used to support a claim -- which is why the
        manifest counts what was found either way.
        """
        findings = self.verify()
        if findings and strict:
            raise ReplayIntegrityError(findings)
        if findings:
            log.warning("replay.defects_ignored", count=len(findings), strict=False)

        observations = sorted(self.ledger.read_observations(), key=lambda item: item.observation_id)
        sources = {item.source_id for item in observations}
        source_versions = {
            record.source_id: record.source_version
            for record in self.ledger.read_source_records()
            if record.source_id in sources
        }
        source_counts: dict[str, int] = {}
        payload_bytes = 0
        for item in observations:
            source_counts[item.source_id] = source_counts.get(item.source_id, 0) + 1
            if self.ledger.payloads.exists(item.payload_ref):
                payload_bytes += len(self.ledger.payloads.get(item.payload_ref))

        manifest = ReplayManifest(
            replay_id="pending",
            created_at=self.clock.now(),
            observation_count=len(observations),
            observation_hash_root=merkle_root(item.raw_content_hash for item in observations),
            payload_bytes=payload_bytes,
            source_versions=dict(sorted(source_versions.items())),
            source_contracts=contract_summaries(sources),
            source_counts=dict(sorted(source_counts.items())),
            config_hash=self.settings.config_hash,
            code_hash=code_hash(),
            dependency_lock_hash=dependency_lock_hash(),
        )
        manifest.replay_id = stable_id("replay", manifest.replay_hash, length=20)

        if persist:
            self.write(manifest)

        log.info(
            "replay.complete",
            replay_id=manifest.replay_id,
            observations=len(observations),
            defects=len(findings),
        )
        return ReplayResult(manifest, observations)

    @property
    def root(self) -> Path:
        return self.settings.storage.data_root / "replays"

    def write(self, manifest: ReplayManifest) -> Path:
        """Persist a replay manifest, refusing to overwrite a differing one."""
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{manifest.replay_id}.json"
        if target.exists():
            existing = ReplayManifest.model_validate_json(target.read_text(encoding="utf-8"))
            if existing.replay_hash != manifest.replay_hash:
                raise ValueError(
                    f"replay {manifest.replay_id} already exists with a different content "
                    f"hash ({existing.replay_hash} on disk, {manifest.replay_hash} now). "
                    "Replay ids are derived from the hash, so this means one of the two "
                    "was not built the way it claims."
                )
            return target
        target.write_text(manifest.canonical_bytes().decode("utf-8"), encoding="utf-8")
        return target


def replayed_evidence_fingerprint(
    result: ReplayResult, cutoff_at: datetime, *, settings: Settings
) -> dict[str, object]:
    """What a replayed corpus admits at a cutoff, in snapshot terms.

    The property Stage 2.3 actually asks for is not that replay returns *some*
    corpus, but that a snapshot built from replayed bronze is identical to the
    one built from the original ingestion. This returns the evidence half of a
    :class:`~pramaanx.timeguard.snapshots.SnapshotManifest` -- the fields that
    describe what was admitted -- so a caller can compare against a real
    manifest field for field.

    Deliberately not a rebuilt ``SnapshotManifest``: constructing a second
    manifest here would duplicate the builder, and a duplicate that drifts is a
    test that passes while the thing it checks is broken.
    """
    guard = CutoffGuard(cutoff_at, settings.timeguard)
    # Select candidates by the boundary first, exactly as SnapshotBuilder does.
    # In strict mode the guard *raises* on a post-cutoff record rather than
    # dropping it -- it is the authority on whether a candidate is admissible,
    # not the mechanism for choosing candidates. Handing it the whole corpus
    # would turn "this ledger contains later evidence", which is the normal
    # state of any real ledger, into a leakage error.
    candidates = [item for item in result.observations if item.first_observed_at <= guard.boundary]
    admitted = guard.screen(candidates).admitted
    counts: dict[str, int] = {}
    for item in admitted:
        counts[item.source_id] = counts.get(item.source_id, 0) + 1
    return {
        "observation_count": len(admitted),
        "observation_hashes": sorted(
            f"{item.observation_id}:{item.raw_content_hash}" for item in admitted
        ),
        "observation_hash_root": merkle_root(item.raw_content_hash for item in admitted),
        "source_counts": dict(sorted(counts.items())),
    }


class ReplayArchiveError(RuntimeError):
    """A precondition that stops a restore before it touches the destination.

    Kept apart from :class:`ReplayIntegrityError` because the two are different
    kinds of "no". An integrity error says the evidence is damaged; this says
    the restore itself is unsafe to attempt -- the archive is not what it claims
    to be, or the destination is not somewhere we may write.
    """


def _settings_at(settings: Settings, data_root: Path) -> Settings:
    """The same settings pointed at a different data root."""
    storage = settings.storage
    return settings.model_copy(
        update={
            "storage": StorageConfig(
                data_root=data_root,
                run_root=storage.run_root,
                parquet_compression=storage.parquet_compression,
                payload_shard_depth=storage.payload_shard_depth,
            )
        }
    )


def _bronze_tree_hash(bronze: Path) -> str:
    """Hash of every byte under ``bronze``, not just its Python files."""
    return hash_tree(bronze, patterns=("**/*",))


class ArchiveRestoreReport(PramaanModel):
    """What a restore did, or would have done."""

    source_root: str
    destination_root: str
    bronze_hash: str
    expected_bronze_hash: str | None
    observation_count: int
    payload_bytes: int
    source_contracts: dict[str, str]
    dependency_lock_hash: str
    dry_run: bool
    committed: bool
    already_present: bool


def restore_archive(
    settings: Settings,
    source_root: Path,
    *,
    expected_bronze_hash: str | None = None,
    dependency_lock: Path = Path("uv.lock"),
    dry_run: bool = False,
) -> ArchiveRestoreReport:
    """Validate a bronze archive and restore it atomically, without a network.

    The other half of replay. :class:`BronzeReplay` asks whether the bronze you
    already have is intact; this asks whether an archived bronze can be put
    somewhere else and still be the same evidence. Neither subsumes the other,
    and both share one verification pass so they cannot drift into disagreeing
    about what "intact" means.

    Nothing is merged into a non-empty destination. A hybrid ledger assembled
    from two archives has provenance belonging to neither, and no manifest it
    produced afterwards would be true. Restoring the identical archive twice is
    an idempotent no-op rather than an error, because that is what makes the
    operation safe to retry.
    """
    source_root = source_root.resolve()
    destination_root = settings.storage.data_root.resolve()
    if source_root == destination_root:
        raise ReplayArchiveError(
            f"replay source and destination are the same directory: {source_root}"
        )
    if not dependency_lock.is_file():
        raise ReplayArchiveError(
            f"dependency lock file not found: {dependency_lock}. A restore that cannot "
            "pin the dependency set cannot claim the restored evidence parses the same way."
        )

    bronze = source_root / "bronze"
    if not bronze.is_dir():
        raise ReplayArchiveError(f"replay source has no bronze directory: {bronze}")

    # A symlink in an archive can point anywhere, so hashing the tree and
    # copying it are no longer the same operation on the same bytes.
    links = sorted(
        path.relative_to(bronze).as_posix() for path in bronze.rglob("*") if path.is_symlink()
    )
    if links:
        raise ReplayArchiveError(f"bronze archive contains symbolic links: {links}")

    bronze_hash = _bronze_tree_hash(bronze)
    if expected_bronze_hash is not None and bronze_hash != expected_bronze_hash:
        raise ReplayArchiveError(
            "bronze archive does not match its pinned hash: "
            f"expected {expected_bronze_hash}, observed {bronze_hash}. The archive is not "
            "the one the pin was taken from."
        )

    source_settings = _settings_at(settings, source_root)
    try:
        source_ledger = EvidenceLedger(source_settings)
        observations = source_ledger.read_observations()
        source_records = source_ledger.read_source_records()
    except Exception as exc:
        raise ReplayArchiveError(f"bronze metadata is malformed: {exc}") from exc

    # The same checks the in-place path runs, so the two can never disagree.
    findings = BronzeReplay(settings, source_ledger)._findings_for(
        observations,
        {record.source_id for record in source_records},
        source_ids=[record.source_id for record in source_records],
        check_orphans=True,
    )
    if findings:
        raise ReplayIntegrityError(findings)

    payload_root = source_ledger.payloads.root
    payload_bytes = sum(
        path.stat().st_size for path in payload_root.rglob("*.bin") if path.is_file()
    )
    contracts = contract_summaries({record.source_id for record in source_records})

    destination_bronze = destination_root / "bronze"
    already_present = (
        destination_bronze.is_dir() and _bronze_tree_hash(destination_bronze) == bronze_hash
    )
    if destination_root.exists() and not already_present:
        raise ReplayArchiveError(
            f"destination is not empty and does not contain this exact bronze archive: "
            f"{destination_root}. Merging would produce a ledger whose provenance belongs "
            "to neither archive."
        )

    report = ArchiveRestoreReport(
        source_root=source_root.as_posix(),
        destination_root=destination_root.as_posix(),
        bronze_hash=bronze_hash,
        expected_bronze_hash=expected_bronze_hash,
        observation_count=len(observations),
        payload_bytes=payload_bytes,
        source_contracts=contracts,
        dependency_lock_hash=hash_file(dependency_lock),
        dry_run=dry_run,
        committed=False,
        already_present=already_present,
    )
    if dry_run or already_present:
        return report

    destination_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination_root.name}.replay-", dir=destination_root.parent)
    )
    try:
        shutil.copytree(bronze, staging / "bronze", symlinks=False, dirs_exist_ok=True)
        staged_hash = _bronze_tree_hash(staging / "bronze")
        if staged_hash != bronze_hash:
            raise ReplayArchiveError(
                f"staged bronze changed during copy: {bronze_hash} -> {staged_hash}"
            )
        # One rename, so the destination is either the whole archive or absent.
        # A half-copied ledger that looked complete is the failure this avoids.
        staging.replace(destination_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    log.info(
        "replay.restored",
        source=source_root.as_posix(),
        destination=destination_root.as_posix(),
        observations=len(observations),
    )
    return report.model_copy(update={"committed": True})
