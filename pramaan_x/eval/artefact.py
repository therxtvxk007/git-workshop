"""The machine-verifiable run artefact.

A metric printed to a terminal is an anecdote. The artefact is the claim: it
pins the number to the commit that produced it, the corpus it was computed on
(by both logical and byte hash), the configuration, the temporal protocol, the
forecast origins, the seed, and the count of availability violations that the
run itself detected.

Two rules about this file:

  * it is written by the benchmark, never typed by hand. A metrics JSON that a
    human edited is a claim about a run that did not happen.
  * its path is a deterministic function of what it describes, so re-running
    the same protocol on the same commit overwrites the same file instead of
    quietly accumulating a directory of near-identical results to pick from.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..data.versioning import hash_frame, hash_parquet
from .availability import AvailabilityViolation
from .metrics import RetrievalReport
from .protocol import TemporalProtocol

#: Where every benchmark artefact lands, relative to the repository root.
BENCHMARK_RESULTS_DIR = "benchmark_results"

ARTEFACT_SCHEMA_VERSION = 3

#: Paths whose contents change what a result *means*. Everything here is
#: hashed into the scientific identity, and a run refuses to publish while any
#: of it is dirty.
SOURCE_ROOTS = ("pramaan_x", "configs", "pyproject.toml", "uv.lock")

#: Directories excluded from the source-dirty calculation, because a benchmark
#: writing its own output must not be able to make itself un-publishable. The
#: exclusion is explicit and tested rather than implied by a path prefix that
#: happens to be skipped.
GENERATED_PATHS = ("benchmark_results/", "artifacts/", ".venv/", "__pycache__/")


class DirtyWorktreeError(RuntimeError):
    """Raised when a result artefact would be attributed to a commit that does
    not contain the code that produced it."""


@dataclass(frozen=True)
class GitState:
    """Where the code came from, and whether the commit describes it.

    `dirty` is every uncommitted path. `source_dirty` is the subset that
    changes what a result means -- see `SOURCE_ROOTS` and `GENERATED_PATHS`.
    The distinction matters: a run that writes its own artefact makes the
    worktree dirty by definition, and refusing to publish on that basis would
    make publishing impossible.
    """

    commit: str | None
    dirty: bool
    dirty_files: tuple[str, ...] = ()
    branch: str | None = None
    source_dirty: bool = False
    source_dirty_files: tuple[str, ...] = ()
    source_tree_hash: str | None = None

    @classmethod
    def read(cls, cwd: str | Path = ".") -> GitState:
        commit = _git(["rev-parse", "HEAD"], cwd)
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        status = _git(["status", "--porcelain"], cwd)
        files = tuple(
            sorted(
                line[3:].strip().strip('"') for line in (status or "").splitlines() if line.strip()
            )
        )
        source_files = tuple(f for f in files if is_source_path(f))
        return cls(
            commit=commit,
            dirty=bool(files),
            dirty_files=files,
            branch=branch,
            source_dirty=bool(source_files),
            source_dirty_files=source_files,
            source_tree_hash=source_tree_hash(cwd),
        )


def is_source_path(path: str) -> bool:
    """True when a path's contents change what a result means."""
    if any(path.startswith(g) or f"/{g}" in path for g in GENERATED_PATHS):
        return False
    return any(path == root or path.startswith(f"{root}/") for root in SOURCE_ROOTS)


def source_tree_hash(cwd: str | Path = ".") -> str | None:
    """A digest of the tracked source as it exists on disk right now.

    Not the commit: the commit says which revision was checked out, this says
    what the files actually contained. They agree only when the source is
    clean, and an artefact carrying both lets a reader tell the difference
    without trusting either alone.
    """
    listing = _git(["ls-files", "-z", *SOURCE_ROOTS], cwd)
    if listing is None:
        return None
    root = Path(cwd)
    digest = hashlib.sha256()
    for name in sorted(p for p in listing.split("\0") if p):
        if not is_source_path(name):
            continue
        digest.update(name.encode())
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256((root / name).read_bytes()).digest())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _git(args: Sequence[str], cwd: str | Path = ".") -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=10, check=True
        )
        return out.stdout.strip()
    except Exception:
        # A run outside a git checkout is still a run; it is just less
        # traceable, and the artefact says so with a null commit.
        return None


@dataclass(frozen=True)
class DatasetIdentity:
    """Both hashes, because they answer different questions.

    `logical_hash` is order-independent over the rows: it says "the same corpus".
    `file_hash` is over the bytes on disk: it says "the same artefact". They
    diverge whenever the encoding changes without the content changing, and a
    reader is entitled to know which kind of difference they are looking at.
    """

    name: str
    n_documents: int
    logical_hash: str
    file_hash: str | None
    file_bytes: int | None
    earliest: str | None
    latest: str | None
    generator: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_frame(
        cls, name: str, frame, *, generator: dict[str, Any], parquet_path: str | Path | None = None
    ) -> DatasetIdentity:
        path = Path(parquet_path) if parquet_path else None
        return cls(
            name=name,
            n_documents=frame.height,
            logical_hash=hash_frame(frame),
            file_hash=hash_parquet(path) if path and path.exists() else None,
            file_bytes=path.stat().st_size if path and path.exists() else None,
            earliest=str(frame["published_at"].min()) if frame.height else None,
            latest=str(frame["published_at"].max()) if frame.height else None,
            generator=dict(generator),
        )


@dataclass(frozen=True)
class BackendIdentity:
    """Which implementations actually ran, and at which versions.

    Named concretely because "dense retrieval" is not an identity and cannot be
    reproduced -- and versioned because "lightgbm" is not one either. A ranker
    fitted by two LightGBM releases is two rankers.
    """

    embedder: str
    reranker: str
    vector_engine: str
    fusion_backend: str
    versions: dict[str, str] = field(default_factory=dict)
    sparse: str = "in-process Okapi BM25 (pramaan_x.stage1_scan.bm25)"
    late_interaction: str = (
        "MaxSim over hashed token vectors (pramaan_x.stage2_retrieve.late_interaction)"
    )


def backend_versions() -> dict[str, str]:
    """Versions of everything that can change a number in this artefact."""
    import platform as _platform
    from importlib.metadata import PackageNotFoundError, version

    out: dict[str, str] = {"python": _platform.python_version()}
    for package in (
        "numpy",
        "scipy",
        "scikit-learn",
        "polars",
        "pyarrow",
        "duckdb",
        "lightgbm",
    ):
        try:
            out[package] = version(package)
        except PackageNotFoundError:
            out[package] = "absent"
    # This package's version comes from the module being executed, not from
    # installed distribution metadata. An editable install keeps reporting the
    # version recorded when it was created, so a stale `pip install -e` makes an
    # artefact claim two different versions of itself -- which is exactly the
    # inconsistency the identity is supposed to make impossible. It happened
    # here: artefacts were published recording pramaan-x 1.0.0 while the code
    # producing them was 0.5.0.
    out["pramaan-x"] = _package_version()
    return out


def scientific_identity(payload: dict[str, Any]) -> dict[str, Any]:
    """Everything that has to match for two runs to be the same measurement.

    The previous version keyed artefacts on method, seed, protocol, config and
    dataset -- and omitted the code. Two different commits therefore resolved
    to the same path, so a later run silently overwrote an earlier one and the
    file gave no way to tell. The code revision is the most important thing in
    this dict.
    """
    git = payload.get("git", {})
    backends = payload.get("backends", {})
    return {
        "method": payload.get("method"),
        "seed": payload.get("seed"),
        "git_commit": git.get("commit"),
        "source_tree_hash": git.get("source_tree_hash"),
        "uv_lock_sha256": payload.get("environment", {}).get("uv_lock_sha256"),
        "package_version": payload.get("environment", {}).get("package_version"),
        "protocol_fingerprint": payload.get("protocol_fingerprint"),
        "dataset_logical_hash": payload.get("dataset", {}).get("logical_hash"),
        "dataset_file_hash": payload.get("dataset", {}).get("file_hash"),
        "config_fingerprint": payload.get("config_fingerprint"),
        "backends": {
            "embedder": backends.get("embedder"),
            "reranker": backends.get("reranker"),
            "vector_engine": backends.get("vector_engine"),
            "fusion_backend": backends.get("fusion_backend"),
            "versions": backends.get("versions", {}),
        },
    }


def identity_digest(payload: dict[str, Any]) -> str:
    blob = json.dumps(scientific_identity(payload), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def build_artefact(
    *,
    method: str,
    protocol: TemporalProtocol,
    dataset: DatasetIdentity,
    backends: BackendIdentity,
    config_fingerprint: str,
    seed: int,
    reports: dict[str, RetrievalReport],
    availability_violations: Sequence[AvailabilityViolation],
    n_train_queries: int,
    n_test_queries: int,
    n_index_builds: int,
    invariants: dict[str, str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the artefact payload. Pure: no IO, so it is easy to test."""
    origins = [o.isoformat() for o in protocol.origins("test")]
    by_reason: dict[str, int] = {}
    for v in availability_violations:
        by_reason[str(v.reason)] = by_reason.get(str(v.reason), 0) + 1
    payload: dict[str, Any] = {
        "schema_version": ARTEFACT_SCHEMA_VERSION,
        "benchmark": "oracle_target_retrieval",
        "measures": "precursor-evidence retrieval for a GIVEN target "
        "(location and event type supplied by an oracle)",
        "does_not_measure": "event forecasting; no metric here is a forecasting "
        "score and none may be reported as one",
        "method": method,
        "created_at": datetime.now(UTC).isoformat(),
        "git": asdict(GitState.read()),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "package_version": _package_version(),
            "uv_lock_sha256": _lock_sha256(),
        },
        "dataset": asdict(dataset),
        "config_fingerprint": config_fingerprint,
        "protocol": protocol.to_dict(),
        "protocol_fingerprint": protocol.fingerprint(),
        "forecast_origins": origins,
        "n_forecast_origins": len(origins),
        "n_index_builds": n_index_builds,
        "seed": seed,
        "backends": asdict(backends),
        "queries": {
            "train": n_train_queries,
            "test": n_test_queries,
            "evaluated": reports[next(iter(reports))].n_queries if reports else 0,
            "relevant_documents": (reports[next(iter(reports))].n_relevant if reports else 0),
        },
        "availability_violations": {
            "total": len(availability_violations),
            "by_reason": by_reason,
            "sample": [v.to_dict() for v in availability_violations[:20]],
        },
        "invariants": dict(invariants),
        "metrics": {stage: rep.summary() for stage, rep in reports.items()},
        "extra": dict(extra or {}),
    }
    payload["identity"] = scientific_identity(payload)
    payload["identity_digest"] = identity_digest(payload)
    return payload


def _package_version() -> str:
    from .. import __version__

    return __version__


def _lock_sha256() -> str | None:
    from ..service import lockfile_sha256

    return lockfile_sha256()


def artefact_path(payload: dict[str, Any], root: str | Path = BENCHMARK_RESULTS_DIR) -> Path:
    """Deterministic location, keyed on the run's full scientific identity.

    The previous key covered method, seed, protocol, config and dataset, and
    omitted the code revision -- so two commits resolved to the same file and a
    later run silently overwrote an earlier one, leaving nothing in the
    directory to say which code produced which number. Everything in
    `scientific_identity` is in the digest now, the code revision included.
    """
    digest = identity_digest(payload)[:16]
    return Path(root) / str(payload["method"]) / f"seed-{payload['seed']}" / f"{digest}.json"


def write_artefact(
    payload: dict[str, Any],
    root: str | Path = BENCHMARK_RESULTS_DIR,
    *,
    require_clean_source: bool = True,
) -> Path:
    """Write the artefact, refusing to publish one whose commit is a fiction.

    A result attributed to a commit that does not contain the code that
    produced it is worse than an unattributed one, because it invites somebody
    to check out that commit and expect the number back. Generated output
    directories are excluded from the check -- a run writing its own artefact
    necessarily dirties the worktree, and treating that as disqualifying would
    make publishing impossible. The exclusion list is `GENERATED_PATHS`, it is
    explicit, and `tests/test_artefact_identity.py` tests it.
    """
    git = payload.get("git", {})
    if require_clean_source and git.get("source_dirty"):
        raise DirtyWorktreeError(
            "refusing to publish a result artefact from a dirty source tree: "
            f"{len(git.get('source_dirty_files', []))} tracked source files differ "
            f"from {git.get('commit', 'HEAD')!r} "
            f"({', '.join(git.get('source_dirty_files', [])[:5])}). "
            "Commit the source first so the artefact's commit describes the code "
            "that produced it, or pass require_clean_source=False for a "
            "throwaway run whose artefact will not be published."
        )
    path = artefact_path(payload, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return path


def aggregate(payloads: Sequence[dict[str, Any]], stage: str = "rerank") -> dict[str, Any]:
    """Mean, standard deviation and per-seed values across repeated runs.

    Standard deviation is over seeds and is reported with n, because a spread
    computed from three runs is itself a noisy quantity and quoting it without
    n invites it to be read as a confidence interval.
    """
    import numpy as np

    per_seed: list[dict[str, Any]] = []
    keys: set[str] = set()
    for p in payloads:
        metrics = p.get("metrics", {}).get(stage, {})
        numeric = {
            k: float(v)
            for k, v in metrics.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        keys |= set(numeric)
        per_seed.append({"seed": p.get("seed"), "metrics": numeric, "artefact": p.get("_path")})
    stats: dict[str, dict[str, float]] = {}
    for k in sorted(keys):
        vals = np.array([s["metrics"][k] for s in per_seed if k in s["metrics"]], dtype=float)
        if not vals.size:
            continue
        stats[k] = {
            "mean": float(vals.mean()),
            "std": float(vals.std(ddof=1)) if vals.size > 1 else 0.0,
            "min": float(vals.min()),
            "max": float(vals.max()),
            "n": int(vals.size),
        }
    return {"stage": stage, "n_seeds": len(per_seed), "per_seed": per_seed, "statistics": stats}


def controlled_comparison(
    payloads: Sequence[dict[str, Any]], stage: str = "rerank"
) -> dict[str, Any]:
    """Split a set of artefacts into what may be compared and what may not.

    The separation is structural rather than advisory: the unpaired section has
    no `delta` key for anything to be read out of, so a downstream table cannot
    accidentally difference an arm that changed four things at once.
    """
    from .oracle_target_retrieval import CONTROLLED_METHODS, STRICT

    controlled: dict[str, Any] = {}
    unpaired: dict[str, Any] = {}
    for p in payloads:
        method = p["method"]
        entry = {
            "seed": p.get("seed"),
            "metrics": p.get("metrics", {}).get(stage, {}),
            "artefact": p.get("_path"),
        }
        if method in CONTROLLED_METHODS:
            paired = p.get("extra", {}).get("paired_vs_strict")
            if paired is not None:
                entry["delta"] = paired["per_query_delta"]
                entry["n_paired_queries"] = paired["n_paired_queries"]
            entry["query_set_fingerprint"] = (
                p.get("extra", {}).get("controlled", {}).get("query_set_fingerprint")
            )
            controlled.setdefault(method, entry)
        else:
            entry["comparability"] = p.get("extra", {}).get("comparability")
            unpaired.setdefault(method, entry)
    fingerprints = {m: e.get("query_set_fingerprint") for m, e in controlled.items()}
    distinct = {f for f in fingerprints.values() if f}
    return {
        "stage": stage,
        "reference": STRICT,
        "controlled": controlled,
        "unpaired": unpaired,
        "query_sets_identical": len(distinct) <= 1,
        "query_set_fingerprints": fingerprints,
    }
