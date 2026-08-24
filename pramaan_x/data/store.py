"""Analytical storage: Polars in memory, Parquet on disk, DuckDB for temporal
queries.

The reason this is not Pandas + CSV is not fashion. Every leakage audit and
every temporal fold in this system is a range query over `published_at`; DuckDB
does those over Parquet without loading the corpus, and Polars' typed schema
turns a silently-coerced timestamp into an error instead of a wrong answer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

import polars as pl

from ..types import Document, Modality

DOC_SCHEMA: dict[str, pl.DataType] = {
    "doc_id": pl.Utf8,
    "source_id": pl.Utf8,
    "source_family": pl.Utf8,
    "title": pl.Utf8,
    "text": pl.Utf8,
    "published_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "language": pl.Utf8,
    "modality": pl.Utf8,
    "content_hash": pl.Utf8,
    "cluster_id": pl.Utf8,
    "is_canonical": pl.Boolean,
    "n_tokens": pl.UInt32,
}


def documents_to_frame(docs: Iterable[Document]) -> pl.DataFrame:
    rows = [
        {
            "doc_id": d.doc_id,
            "source_id": d.source_id,
            "source_family": d.meta.get("source_family", ""),
            "title": d.title,
            "text": d.text,
            "published_at": d.published_at,
            "retrieved_at": d.retrieved_at or d.published_at,
            "language": d.language,
            "modality": d.modality.value if isinstance(d.modality, Modality) else str(d.modality),
            "content_hash": d.content_hash,
            "cluster_id": d.cluster_id or d.doc_id,
            "is_canonical": d.is_canonical,
            "n_tokens": len(d.full_text.split()),
        }
        for d in docs
    ]
    if not rows:
        return pl.DataFrame(schema=DOC_SCHEMA)
    return pl.DataFrame(rows, schema_overrides=DOC_SCHEMA)


class DocumentStore:
    """Parquet-backed corpus with an as-of view.

    `as_of` is the only supported way to read for a forecast. Reading the raw
    frame and filtering by hand is exactly how publication-cutoff leakage gets
    reintroduced, so the convenient path is the safe one.
    """

    def __init__(self, frame: pl.DataFrame | None = None, path: str | Path | None = None):
        if frame is None and path is None:
            raise ValueError("DocumentStore needs a frame or a path")
        self.path = Path(path) if path else None
        self._frame = frame if frame is not None else pl.read_parquet(self.path)
        if self._frame.height and self._frame["published_at"].dtype.time_zone is None:
            self._frame = self._frame.with_columns(
                pl.col("published_at").dt.replace_time_zone("UTC"),
                pl.col("retrieved_at").dt.replace_time_zone("UTC"),
            )

    # ------------------------------------------------------------ io ---

    @classmethod
    def from_documents(cls, docs: Iterable[Document]) -> DocumentStore:
        return cls(frame=documents_to_frame(docs))

    def write(self, path: str | Path, compression: str = "zstd") -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._frame.write_parquet(path, compression=compression)
        self.path = path
        return path

    @property
    def frame(self) -> pl.DataFrame:
        return self._frame

    def __len__(self) -> int:
        return self._frame.height

    # --------------------------------------------------------- views ---

    def as_of(self, cutoff: datetime, *, canonical_only: bool = True) -> pl.DataFrame:
        """Everything publishable knowledge could contain at `cutoff`.

        Filters on `published_at`, not `retrieved_at`: a document that existed
        in the world but had not been crawled yet is still legitimately usable
        by a retrospective backtest, whereas one published after the cutoff is
        never usable regardless of when we happened to fetch it.
        """
        f = self._frame.filter(pl.col("published_at") < cutoff)
        if canonical_only:
            f = f.filter(pl.col("is_canonical"))
        return f

    def window(self, start: datetime, end: datetime, *, canonical_only: bool = True) -> pl.DataFrame:
        f = self._frame.filter(
            (pl.col("published_at") >= start) & (pl.col("published_at") < end)
        )
        if canonical_only:
            f = f.filter(pl.col("is_canonical"))
        return f

    def daily_counts(self, *, canonical_only: bool = True) -> pl.DataFrame:
        f = self._frame.filter(pl.col("is_canonical")) if canonical_only else self._frame
        return (
            f.with_columns(pl.col("published_at").dt.date().alias("day"))
            .group_by("day")
            .agg(pl.len().alias("n"))
            .sort("day")
        )

    def apply_clusters(self, cluster_of: dict[str, str], canonical: set[str]) -> DocumentStore:
        """Fold stage-0 dedup decisions back into the store."""
        self._frame = self._frame.with_columns(
            pl.col("doc_id").replace_strict(cluster_of, default=None)
              .fill_null(pl.col("doc_id")).alias("cluster_id"),
            pl.col("doc_id").is_in(list(canonical)).alias("is_canonical"),
        )
        return self

    def documents(self, doc_ids: Sequence[str] | None = None) -> list[Document]:
        f = self._frame
        if doc_ids is not None:
            f = f.filter(pl.col("doc_id").is_in(list(doc_ids)))
        out = []
        for r in f.iter_rows(named=True):
            out.append(Document(
                doc_id=r["doc_id"], source_id=r["source_id"], title=r["title"],
                text=r["text"], published_at=r["published_at"],
                retrieved_at=r["retrieved_at"], language=r["language"],
                modality=Modality(r["modality"]), content_hash=r["content_hash"],
                cluster_id=r["cluster_id"], is_canonical=r["is_canonical"],
                meta={"source_family": r["source_family"]},
            ))
        return out

    # -------------------------------------------------------- duckdb ---

    def sql(self, query: str) -> pl.DataFrame:
        """Run DuckDB SQL against the corpus. `docs` is the registered view."""
        import duckdb

        con = duckdb.connect()
        try:
            con.register("docs", self._frame.to_arrow())
            return pl.from_arrow(con.execute(query).arrow())
        finally:
            con.close()

    def source_independence(self, doc_ids: Sequence[str]) -> float:
        """Distinct syndication families over distinct documents.

        This is the number that stops thirty copies of one wire story reading
        as thirty corroborating sources. It is a feature, not a diagnostic.
        """
        if not doc_ids:
            return 0.0
        f = self._frame.filter(pl.col("doc_id").is_in(list(doc_ids)))
        if not f.height:
            return 0.0
        fams = f["source_family"].n_unique()
        return float(fams) / float(f.height)
