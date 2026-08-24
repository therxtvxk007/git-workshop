"""Dataset versioning by content hash.

DVC handles the storage; what DVC cannot do for us is prove that a *result* was
produced from a particular corpus under a particular cutoff. That is what the
manifest here is for: it pins the corpus content, the cutoff, and the config
fingerprint together, so a metric can always be traced to the exact inputs that
produced it. A backtest whose corpus cannot be reconstructed is an anecdote.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetManifest:
    name: str
    content_hash: str
    n_records: int
    earliest: str
    latest: str
    cutoff: str | None
    config_fingerprint: str
    created_at: str
    git_commit: str | None = None
    parent: str | None = None          # hash of the manifest this derives from
    extra: dict[str, Any] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @property
    def id(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def hash_parquet(path: str | Path, chunk: int = 1 << 20) -> str:
    """Hash the bytes on disk. Deliberately not a hash of the logical content:
    if the encoding changed, the artefact changed, and a reader is entitled to
    know that even when the rows are identical."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def hash_frame(frame) -> str:
    """Order-independent hash of logical content, for comparing two frames that
    may have been written by different code paths."""
    import polars as pl

    if not isinstance(frame, pl.DataFrame):
        raise TypeError("hash_frame expects a polars DataFrame")
    cols = sorted(frame.columns)
    h = hashlib.sha256()
    h.update(",".join(f"{c}:{frame[c].dtype}" for c in cols).encode())
    row_hashes = sorted(
        hashlib.blake2b(
            "\x1f".join(str(r[c]) for c in cols).encode("utf-8", "replace"),
            digest_size=16,
        ).hexdigest()
        for r in frame.iter_rows(named=True)
    )
    for rh in row_hashes:
        h.update(rh.encode())
    return h.hexdigest()


def git_commit(cwd: str | Path = ".") -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(cwd),
            capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def build_manifest(
    name: str,
    frame,
    *,
    config_fingerprint: str,
    cutoff: datetime | None = None,
    parent: str | None = None,
    extra: dict[str, Any] | None = None,
) -> DatasetManifest:

    if frame.height:
        earliest = str(frame["published_at"].min())
        latest = str(frame["published_at"].max())
    else:
        earliest = latest = ""
    return DatasetManifest(
        name=name,
        content_hash=hash_frame(frame),
        n_records=frame.height,
        earliest=earliest,
        latest=latest,
        cutoff=cutoff.isoformat() if cutoff else None,
        config_fingerprint=config_fingerprint,
        created_at=datetime.now(UTC).isoformat(),
        git_commit=git_commit(),
        parent=parent,
        extra=extra or {},
    )


def write_dvc_stub(path: str | Path, manifest: DatasetManifest) -> Path:
    """Emit a `.dvc` pointer alongside the manifest so `dvc checkout` works in
    a deployment that has DVC configured, without making DVC a hard dependency
    of the library."""
    path = Path(path)
    stub = path.with_suffix(path.suffix + ".dvc")
    stub.write_text(
        "outs:\n"
        f"- md5: {manifest.content_hash[:32]}\n"
        f"  size: {path.stat().st_size if path.exists() else 0}\n"
        f"  path: {path.name}\n"
        f"  desc: {manifest.name} @ {manifest.created_at}\n"
    )
    return stub


class LeakageAudit:
    """Assert that nothing dated at or after the forecast origin was visible.

    Run this on every evaluation fold. The cost is one comparison per document;
    the alternative is publishing a lead-time number that is an artefact of
    post-event reporting.
    """

    def __init__(self, cutoff: datetime) -> None:
        self.cutoff = cutoff
        self.violations: list[tuple[str, str]] = []

    def check_frame(self, frame) -> LeakageAudit:
        import polars as pl

        bad = frame.filter(pl.col("published_at") >= self.cutoff)
        for r in bad.iter_rows(named=True):
            self.violations.append((r["doc_id"], str(r["published_at"])))
        return self

    def check_documents(self, docs) -> LeakageAudit:
        for d in docs:
            if d.published_at >= self.cutoff:
                self.violations.append((d.doc_id, d.published_at.isoformat()))
        return self

    @property
    def clean(self) -> bool:
        return not self.violations

    def raise_if_dirty(self) -> None:
        if self.violations:
            head = ", ".join(f"{d}@{t}" for d, t in self.violations[:5])
            raise AssertionError(
                f"publication-cutoff leakage: {len(self.violations)} documents at or "
                f"after {self.cutoff.isoformat()} reached the forecast [{head}]"
            )
