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

ARTEFACT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class GitState:
    commit: str | None
    dirty: bool
    dirty_files: tuple[str, ...] = ()
    branch: str | None = None

    @classmethod
    def read(cls, cwd: str | Path = ".") -> GitState:
        commit = _git(["rev-parse", "HEAD"], cwd)
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        status = _git(["status", "--porcelain"], cwd)
        files = tuple(sorted(line[3:] for line in (status or "").splitlines() if line.strip()))
        return cls(commit=commit, dirty=bool(files), dirty_files=files, branch=branch)


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
    """Which implementations actually ran. Named concretely, because "dense
    retrieval" is not an identity and cannot be reproduced."""

    embedder: str
    reranker: str
    vector_engine: str
    fusion_backend: str
    sparse: str = "in-process Okapi BM25 (pramaan_x.stage1_scan.bm25)"
    late_interaction: str = (
        "MaxSim over hashed token vectors (pramaan_x.stage2_retrieve.late_interaction)"
    )


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
    return {
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


def artefact_path(payload: dict[str, Any], root: str | Path = BENCHMARK_RESULTS_DIR) -> Path:
    """Deterministic location: method / seed / (protocol+config+dataset) digest.

    The digest covers everything that changes what the numbers mean, so two
    runs that should be identical write to the same path and a run that should
    not be compared with them writes somewhere else.
    """
    key = "|".join(
        [
            str(payload["method"]),
            str(payload["seed"]),
            str(payload["protocol_fingerprint"]),
            str(payload["config_fingerprint"]),
            str(payload["dataset"]["logical_hash"]),
        ]
    )
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    return Path(root) / str(payload["method"]) / f"seed-{payload['seed']}" / f"{digest}.json"


def write_artefact(payload: dict[str, Any], root: str | Path = BENCHMARK_RESULTS_DIR) -> Path:
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
