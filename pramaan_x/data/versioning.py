"""Dataset versioning by content hash.

What this module does: pin a corpus's content, the cutoff it was read at, and
the config fingerprint together, so a metric can always be traced to the exact
inputs that produced it. A backtest whose corpus cannot be reconstructed is an
anecdote.

**What this module is not: DVC.** An earlier version of this file wrote a file
named `<corpus>.dvc` containing a field labelled `md5` whose value was the first
32 hex characters of a SHA-256 digest of the frame's *logical* content. That is
not an MD5, not a hash of the bytes DVC would hash, and not a pointer `dvc
checkout` could ever resolve -- three separate ways of being wrong, presented as
DVC compatibility. It has been replaced by `write_content_pointer`, which writes
a `.pointer.json` and names its hashes honestly.

DVC is not configured in this repository and this module does not pretend it is.
Wiring it up means `dvc init`, a remote, and `dvc add` producing its own `.dvc`
files with its own hashes; until somebody does that, nothing here should carry
the extension.
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


def write_content_pointer(path: str | Path, manifest: DatasetManifest) -> Path:
    """Write `<file>.pointer.json` next to a data file.

    Every hash is labelled with the algorithm that produced it and the thing it
    was computed over, because that is the entire job of a pointer file:

      `file_sha256`     SHA-256 of the bytes on disk -- "the same artefact"
      `logical_sha256`  order-independent digest of the rows -- "the same corpus"

    This is not a DVC pointer and does not claim to be one. It is not consumed
    by `dvc checkout`; it is consumed by a human or a script asking whether two
    files are the same data.
    """
    path = Path(path)
    pointer = path.with_suffix(path.suffix + ".pointer.json")
    payload = {
        "format": "pramaan-x/content-pointer/1",
        "not_dvc": "this file is not a DVC pointer and dvc cannot resolve it",
        "path": path.name,
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "file_sha256": hash_parquet(path) if path.exists() else None,
        "logical_sha256": manifest.content_hash,
        "manifest_id": manifest.id,
        "name": manifest.name,
        "created_at": manifest.created_at,
        "git_commit": manifest.git_commit,
        "config_fingerprint": manifest.config_fingerprint,
        "cutoff": manifest.cutoff,
    }
    pointer.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return pointer


class LeakageAudit:
    """Publication-cutoff audit: nothing *published* at or after the origin.

    This is one half of the availability rule and is deliberately named for the
    half it checks. It does not look at `retrieved_at`, so a document published
    before the origin and crawled after it passes here and is still unusable.
    `pramaan_x.eval.availability` implements the full rule and is what an
    evaluation must use; this remains for corpus-level publication audits.
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
