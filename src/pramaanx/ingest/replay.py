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

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from pramaanx.clock import Clock, SystemClock
from pramaanx.config import Settings
from pramaanx.hashing import hash_bytes, hash_file, hash_object, merkle_root, stable_id
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


class ReplayFinding(PramaanModel):
    """One defect, attributed to the record it was found in."""

    defect: ReplayDefect
    observation_id: str
    source_id: str
    detail: str

    def __str__(self) -> str:
        return f"{self.defect.value}: {self.observation_id} ({self.source_id}) -- {self.detail}"


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
        )

    def _findings_for(
        self, observations: Sequence[Observation], known_sources: set[str]
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

        return sorted(findings, key=lambda f: (f.observation_id, f.defect.value))

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
