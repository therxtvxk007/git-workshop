"""Analytical storage: Polars in memory, Parquet on disk, DuckDB for temporal
queries.

The reason this is not Pandas + CSV is not fashion. Every leakage audit and
every temporal fold in this system is a range query over the availability
timestamps; DuckDB does those over Parquet without loading the corpus, and
Polars' typed schema turns a silently-coerced timestamp into an error instead
of a wrong answer.

`retrieved_at` is nullable and is never back-filled from `published_at`. See
`pramaan_x.eval.availability` for the rule that consumes it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

import polars as pl

from ..timestamps import TimestampPolicy, TimestampPolicyError
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
            # Never substituted: a missing acquisition time is a fact about
            # the document, and filling it with `published_at` would assert
            # zero crawl latency on a document we know nothing about.
            "retrieved_at": d.retrieved_at,
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
    """Parquet-backed corpus with temporal views.

    `available_at` is the only supported way to read for a backtest: it applies
    both halves of the availability rule. `as_of` applies the publication
    cutoff alone and is deliberately weaker -- it is kept so the contaminated
    legacy diagnostic can be run and its cost quantified, not because it is
    safe. Reading the raw frame and filtering by hand is how leakage gets
    reintroduced, so the convenient paths are the audited ones.
    """

    def __init__(self, frame: pl.DataFrame | None = None, path: str | Path | None = None,
                 *, timestamp_policy: str | TimestampPolicy = TimestampPolicy.STRICT):
        if frame is None and path is None:
            raise ValueError("DocumentStore needs a frame or a path")
        self.path = Path(path) if path else None
        self.timestamp_policy = TimestampPolicy.parse(timestamp_policy)
        self._frame = frame if frame is not None else pl.read_parquet(self.path)
        if self._frame.height and self._frame["published_at"].dtype.time_zone is None:
            # A tz-naive column reaching the store is the same invention Stage 0
            # is forbidden from making, one layer down. Under the strict policy
            # it is refused rather than stamped.
            if self.timestamp_policy is not TimestampPolicy.ASSUME_UTC:
                raise TimestampPolicyError(
                    "the corpus frame has a timezone-naive `published_at` column; "
                    "the strict timestamp policy will not assume a zone for it. "
                    "Re-ingest under a policy that says what the zone is."
                )
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
        """Publication cutoff only. **Not sufficient for a backtest.**

        This filters on `published_at` alone, which answers "did the
        information exist" and not "had we acquired it". A document published
        before the cutoff but crawled after it is returned here and must not
        be: use `available_at()` for anything whose result is reported as a
        measurement. This view is retained for corpus inspection and for the
        `historical_legacy_reproduction_unpaired` arm, whose entire purpose is
        to reproduce what this weaker rule used to do.
        """
        f = self._frame.filter(pl.col("published_at") < cutoff)
        if canonical_only:
            f = f.filter(pl.col("is_canonical"))
        return f

    def available_at(self, origin: datetime, *, canonical_only: bool = True,
                     trusted_snapshot: bool = False) -> pl.DataFrame:
        """The corpus as it stood at `origin`: the backtest read path.

        Applies `available_at = max(published_at, retrieved_at)` with strict
        inequality on both sides. Rows with a null `retrieved_at` are dropped
        unless `trusted_snapshot` is set, which is the caller asserting that
        this frame came from a historical archive whose acquisition time is
        known not to postdate publication.
        """
        f = self._frame.filter(pl.col("published_at") < origin)
        if trusted_snapshot:
            f = f.filter(
                pl.col("retrieved_at").is_null() | (pl.col("retrieved_at") < origin)
            )
        else:
            f = f.filter(pl.col("retrieved_at").is_not_null()
                         & (pl.col("retrieved_at") < origin))
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
