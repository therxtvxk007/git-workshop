"""Content-addressed payload storage and deterministic Parquet tables.

The evidence lake follows the bronze/silver/gold discipline:

* **bronze** -- exact acquired bytes plus source metadata and a content hash,
  append-only;
* **silver** -- normalised documents, translations, extracted mentions;
* **gold** -- canonical entities, resolved events, labelled outcomes.

Writes here are deterministic and idempotent: the same records written twice
produce the same files and no duplicate rows. That is what lets a leakage test
assert *byte-identical* outputs rather than merely similar ones.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

import polars as pl

from pramaanx.hashing import canonical_json, hash_bytes, hash_object, short_hash
from pramaanx.logging import get_logger
from pramaanx.schemas.base import VersionedModel

log = get_logger(__name__)

M = TypeVar("M", bound=VersionedModel)

RECORD_COLUMN = "record_json"
HASH_COLUMN = "record_hash"

ParquetCompression = Literal["lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"]
VALID_COMPRESSIONS: frozenset[str] = frozenset(
    ("lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd")
)


class PayloadStore:
    """Append-only, content-addressed blob store for raw source bytes.

    Writing the same bytes twice is a no-op, so re-running a connector never
    mutates bronze. Re-writing *different* bytes under an existing hash is
    impossible by construction, which is the point.
    """

    def __init__(self, root: Path, shard_depth: int = 2) -> None:
        self.root = Path(root)
        self.shard_depth = max(1, min(shard_depth, 4))

    def _relative_path(self, digest_hex: str) -> Path:
        shards = [digest_hex[i * 2 : i * 2 + 2] for i in range(self.shard_depth)]
        return Path(*shards) / f"{digest_hex}.bin"

    def path_for(self, content_hash: str) -> Path:
        return self.root / self._relative_path(content_hash.removeprefix("sha256:"))

    def put(self, data: bytes) -> tuple[str, str]:
        """Store bytes; return ``(content_hash, payload_ref)``."""
        content_hash = hash_bytes(data)
        relative = self._relative_path(content_hash.removeprefix("sha256:"))
        target = self.root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".bin.tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        return content_hash, relative.as_posix()

    def get(self, payload_ref: str) -> bytes:
        target = self.root / payload_ref
        if not target.exists():
            raise FileNotFoundError(f"payload not found: {payload_ref}")
        return target.read_bytes()

    def exists(self, payload_ref: str) -> bool:
        return (self.root / payload_ref).exists()

    def verify(self, payload_ref: str, expected_hash: str) -> bool:
        """Detect bytes that changed underneath a stored reference."""
        if not self.exists(payload_ref):
            return False
        return hash_bytes(self.get(payload_ref)) == expected_hash


@dataclass(frozen=True)
class TableSpec:
    """How a record type is indexed and partitioned on disk."""

    name: str
    key_field: str
    index_builder: Callable[[Any], dict[str, Any]]
    partition_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class WriteResult:
    table: str
    written: int
    skipped: int
    files: tuple[str, ...]

    @property
    def total(self) -> int:
        return self.written + self.skipped


class RecordTable:
    """A deterministic Parquet dataset of versioned records.

    Records are stored as canonical JSON in one column, alongside flat index
    columns used for filtering (crucially ``first_observed_at``, which cutoff
    filtering depends on). Keeping the full record as canonical JSON means a
    schema addition never silently reshapes historical files.
    """

    def __init__(self, root: Path, spec: TableSpec, compression: str = "zstd") -> None:
        if compression not in VALID_COMPRESSIONS:
            raise ValueError(
                f"unsupported parquet compression {compression!r}; "
                f"choose one of {sorted(VALID_COMPRESSIONS)}"
            )
        self.root = Path(root) / spec.name
        self.spec = spec
        self.compression = cast(ParquetCompression, compression)

    # -- writing ---------------------------------------------------------
    def _rows(self, records: Iterable[M]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in records:
            index = self.spec.index_builder(record)
            payload = record.model_dump(mode="json")
            rows.append(
                {
                    **index,
                    RECORD_COLUMN: canonical_json(payload),
                    HASH_COLUMN: hash_object(payload),
                }
            )
        return rows

    def _partition_dir(self, row: dict[str, Any]) -> Path:
        parts = [f"{field}={row[field]}" for field in self.spec.partition_fields]
        return self.root.joinpath(*parts) if parts else self.root

    def append(self, records: Iterable[M]) -> WriteResult:
        """Append records, skipping keys already present in their partitions."""
        rows = self._rows(records)
        if not rows:
            return WriteResult(self.spec.name, 0, 0, ())

        grouped: dict[Path, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(self._partition_dir(row), []).append(row)

        written = 0
        skipped = 0
        files: list[str] = []
        key = self.spec.key_field
        for directory, group in sorted(grouped.items(), key=lambda kv: kv[0].as_posix()):
            existing = self._existing_keys(directory)
            fresh: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in sorted(group, key=lambda item: str(item[key])):
                identifier = str(row[key])
                if identifier in existing or identifier in seen:
                    skipped += 1
                    continue
                seen.add(identifier)
                fresh.append(row)
            if not fresh:
                continue
            # Deterministic file name: identical batches land in identical files.
            batch_hash = short_hash(hash_object([row[HASH_COLUMN] for row in fresh]))
            target = directory / f"part-{batch_hash}.parquet"
            directory.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                pl.DataFrame(fresh).write_parquet(target, compression=self.compression)
            written += len(fresh)
            files.append(target.relative_to(self.root).as_posix())

        log.debug("table.append", table=self.spec.name, written=written, skipped=skipped)
        return WriteResult(self.spec.name, written, skipped, tuple(sorted(files)))

    def _existing_keys(self, directory: Path) -> set[str]:
        parts = sorted(directory.glob("part-*.parquet"))
        if not parts:
            return set()
        frame = pl.read_parquet(parts, columns=[self.spec.key_field])
        return set(frame[self.spec.key_field].cast(pl.Utf8).to_list())

    # -- reading ---------------------------------------------------------
    @property
    def files(self) -> list[Path]:
        return sorted(self.root.rglob("part-*.parquet"))

    def is_empty(self) -> bool:
        return not self.files

    def scan(self) -> pl.LazyFrame:
        files = self.files
        if not files:
            return pl.LazyFrame()
        return pl.scan_parquet(files)

    def read_frame(self) -> pl.DataFrame:
        files = self.files
        if not files:
            return pl.DataFrame()
        return pl.read_parquet(files)

    def read_models(
        self,
        model_cls: type[M],
        *,
        predicate: pl.Expr | None = None,
        columns: Sequence[str] | None = None,
    ) -> list[M]:
        """Materialise records, sorted by key for deterministic downstream order."""
        files = self.files
        if not files:
            return []
        lazy = pl.scan_parquet(files)
        if predicate is not None:
            lazy = lazy.filter(predicate)
        frame = lazy.sort(self.spec.key_field).collect()
        if columns is not None:
            frame = frame.select(columns)
        return [model_cls.model_validate_json(payload) for payload in frame[RECORD_COLUMN]]

    def count(self) -> int:
        files = self.files
        if not files:
            return 0
        return int(pl.scan_parquet(files).select(pl.len()).collect().item())
