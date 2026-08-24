"""Parquet / DuckDB / Polars pipeline: data-integrity tests.

These are the tests the risk table demands for the data plane. They target
integrity properties rather than API surface, because the failures that matter
here are silent: a timezone dropped on a Parquet round trip, an `as_of` view
that leaks a future document, a schema coerced to string.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl
import pytest

from pramaan_x.data.store import DOC_SCHEMA, DocumentStore, documents_to_frame
from pramaan_x.data.versioning import (
    LeakageAudit,
    build_manifest,
    hash_frame,
    hash_parquet,
    write_content_pointer,
)


def test_schema_is_enforced(documents):
    f = documents_to_frame(documents[:50])
    for col, dtype in DOC_SCHEMA.items():
        assert col in f.columns, f"missing column {col}"
        assert f[col].dtype == dtype, f"{col} is {f[col].dtype}, expected {dtype}"


def test_no_rows_lost_in_conversion(documents):
    assert documents_to_frame(documents).height == len(documents)


def test_parquet_roundtrip_preserves_content(documents, tmp_path):
    """The failure guarded against: a Parquet round trip that silently changes
    timestamps or ordering, making a re-run non-reproducible."""
    store = DocumentStore.from_documents(documents)
    before = hash_frame(store.frame)
    path = store.write(tmp_path / "corpus.parquet")
    reloaded = DocumentStore(path=path)
    assert hash_frame(reloaded.frame) == before
    assert reloaded.frame.height == store.frame.height


def test_timezones_survive_roundtrip(documents, tmp_path):
    store = DocumentStore.from_documents(documents)
    path = store.write(tmp_path / "tz.parquet")
    reloaded = DocumentStore(path=path)
    assert reloaded.frame["published_at"].dtype.time_zone == "UTC"
    assert reloaded.frame["published_at"].min() == store.frame["published_at"].min()


def test_as_of_never_returns_future_documents(documents):
    """The single most important property in the package. If this fails, every
    lead-time and recall figure the system reports is inflated."""
    store = DocumentStore.from_documents(documents)
    span = store.frame["published_at"]
    for frac in (0.1, 0.5, 0.9):
        cutoff = span.min() + (span.max() - span.min()) * frac
        view = store.as_of(cutoff, canonical_only=False)
        assert view.height > 0
        assert view["published_at"].max() < cutoff


def test_as_of_is_monotone(documents):
    store = DocumentStore.from_documents(documents)
    span = store.frame["published_at"]
    early = span.min() + (span.max() - span.min()) * 0.3
    late = span.min() + (span.max() - span.min()) * 0.7
    assert store.as_of(early).height <= store.as_of(late).height


def test_window_is_half_open(documents):
    """[start, end) -- so consecutive windows tile the corpus exactly once and
    a document on a boundary is never counted twice."""
    store = DocumentStore.from_documents(documents)
    lo = store.frame["published_at"].min()
    mid = lo + timedelta(days=40)
    hi = lo + timedelta(days=80)
    a = store.window(lo, mid, canonical_only=False)
    b = store.window(mid, hi, canonical_only=False)
    assert set(a["doc_id"]) & set(b["doc_id"]) == set()
    total = store.window(lo, hi, canonical_only=False).height
    assert a.height + b.height == total


def test_duckdb_agrees_with_polars(documents):
    """Two engines over the same Arrow buffer must not disagree. When they do,
    it is usually a null-handling difference that would quietly change counts."""
    store = DocumentStore.from_documents(documents)
    sql = store.sql("select count(*) as n from docs").item()
    assert sql == store.frame.height
    by_family_sql = dict(
        store.sql("select source_family, count(*) n from docs group by 1")
             .iter_rows()
    )
    by_family_pl = dict(
        store.frame.group_by("source_family").agg(pl.len().alias("n")).iter_rows()
    )
    assert by_family_sql == by_family_pl


def test_source_independence_counts_families_not_ids(documents):
    """Thirty copies of one wire story must not read as thirty sources."""
    store = DocumentStore.from_documents(documents)
    frame = store.frame
    one_family = frame.filter(pl.col("source_family") == frame["source_family"][0])
    ids = one_family["doc_id"].to_list()[:20]
    assert len(ids) > 1
    score = store.source_independence(ids)
    assert score == pytest.approx(1.0 / len(ids), rel=1e-6)


def test_source_independence_of_empty_set_is_zero(documents):
    assert DocumentStore.from_documents(documents).source_independence([]) == 0.0


def test_apply_clusters_marks_canonical(documents):
    from pramaan_x.stage0_ingest.dedup import Deduplicator

    docs = list(documents)
    rep = Deduplicator().run(docs)
    store = DocumentStore.from_documents(docs).apply_clusters(rep.cluster_of, rep.canonical)
    assert store.frame["is_canonical"].sum() == rep.n_clusters
    assert store.as_of(store.frame["published_at"].max()).height <= rep.n_clusters


def test_manifest_is_reproducible(documents):
    store = DocumentStore.from_documents(documents)
    a = build_manifest("c", store.frame, config_fingerprint="abc")
    b = build_manifest("c", store.frame, config_fingerprint="abc")
    assert a.content_hash == b.content_hash


def test_manifest_detects_content_change(documents):
    store = DocumentStore.from_documents(documents)
    a = build_manifest("c", store.frame, config_fingerprint="abc")
    mutated = store.frame.with_columns(pl.col("text") + " appended")
    b = build_manifest("c", mutated, config_fingerprint="abc")
    assert a.content_hash != b.content_hash


def test_hash_frame_is_row_order_independent(documents):
    store = DocumentStore.from_documents(documents)
    shuffled = store.frame.sample(fraction=1.0, shuffle=True, seed=7)
    assert hash_frame(store.frame) == hash_frame(shuffled)


def test_leakage_audit_fires_on_future_documents(documents):
    store = DocumentStore.from_documents(documents)
    span = store.frame["published_at"]
    cutoff = span.min() + (span.max() - span.min()) * 0.5
    assert LeakageAudit(cutoff).check_frame(store.as_of(cutoff, canonical_only=False)).clean
    dirty = LeakageAudit(cutoff).check_frame(store.frame)
    assert not dirty.clean
    with pytest.raises(AssertionError, match="publication-cutoff leakage"):
        dirty.raise_if_dirty()


def test_content_pointer_hashes_are_real_and_correctly_labelled(documents, tmp_path):
    """The bug this replaces: a field labelled `md5` holding 32 characters of a
    SHA-256 over the *logical* rows, in a file named `.dvc`. Every hash here is
    named for the algorithm and the bytes it was actually computed over."""
    import json

    store = DocumentStore.from_documents(documents)
    path = store.write(tmp_path / "c.parquet")
    manifest = build_manifest("c", store.frame, config_fingerprint="abc")
    pointer = write_content_pointer(path, manifest)

    assert pointer.name == "c.parquet.pointer.json"
    assert not pointer.name.endswith(".dvc")
    body = json.loads(pointer.read_text())
    assert body["file_sha256"] == hash_parquet(path)
    assert body["logical_sha256"] == hash_frame(store.frame)
    assert body["size_bytes"] == path.stat().st_size
    assert "md5" not in body
    assert "not a DVC pointer" in body["not_dvc"]


def test_no_dvc_pointer_is_written_anywhere(documents, tmp_path):
    """DVC is not configured in this repository, so nothing may emit a file
    that claims it is."""
    store = DocumentStore.from_documents(documents)
    path = store.write(tmp_path / "c.parquet")
    write_content_pointer(path, build_manifest("c", store.frame,
                                               config_fingerprint="abc"))
    assert list(tmp_path.rglob("*.dvc")) == []


# ------------------------------------------------ the availability view ---


def test_available_at_drops_documents_crawled_after_the_origin(documents):
    """`as_of` keeps them because they were published in time. `available_at`
    does not, because we did not have them."""
    from pramaan_x.eval.availability import is_available

    store = DocumentStore.from_documents(documents)
    span = store.frame["published_at"]
    origin = span.min() + (span.max() - span.min()) * 0.5
    published_view = store.as_of(origin, canonical_only=False)
    available_view = store.available_at(origin, canonical_only=False)
    assert available_view.height < published_view.height
    assert available_view["retrieved_at"].max() < origin
    assert available_view["published_at"].max() < origin
    by_id = {d.doc_id: d for d in documents}
    for doc_id in available_view["doc_id"].to_list()[:200]:
        assert is_available(by_id[doc_id], origin)


def test_available_at_rejects_missing_acquisition_time_by_default(documents):
    store = DocumentStore.from_documents(documents)
    origin = store.frame["published_at"].max()
    strict = store.available_at(origin, canonical_only=False)
    assert strict["retrieved_at"].null_count() == 0
    trusting = store.available_at(origin, canonical_only=False, trusted_snapshot=True)
    assert trusting.height > strict.height


def test_retrieved_at_is_not_backfilled_from_published_at(documents):
    """The silent substitution that made the acquisition rule a no-op."""
    store = DocumentStore.from_documents(documents)
    assert store.frame["retrieved_at"].null_count() > 0, (
        "the corpus must contain documents with no acquisition time, or the "
        "rule is never exercised"
    )
