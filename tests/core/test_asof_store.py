"""The as-of store's correctness argument, one row of the plan's matrix each.

These are the tests the revision plan calls P0 (S27.1, S38). Each one names the
specific reordering or shortcut it exists to forbid; a green suite here is the
claim that a forecast could not have seen what it must not have seen.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest
from _builders import ORIGIN

from pramaanx.clock import FixedClock
from pramaanx.core.asof import RevisionStore, WithheldSources
from pramaanx.core.contexts import (
    AvailabilityBasis,
    ForecastContext,
    InformationProfile,
    OriginRole,
)
from pramaanx.core.errors import (
    ContractViolationError,
    EligibilityError,
    IdempotencyConflictError,
    RedactedArtifactError,
    StoreCorruptionError,
    WriterLockError,
)
from pramaanx.core.revisions import Revision, RevisionOperation

MakeRevision = Callable[..., Revision]
MakeContext = Callable[..., ForecastContext]


def _values(store: RevisionStore, ctx: ForecastContext, table: str = "events") -> list[object]:
    return [record["revision"] for record in store.read(table, ctx=ctx).records()]


# -- availability boundary -------------------------------------------------
def test_availability_boundary_is_inclusive_at_the_cutoff(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """One unit before, exactly at, and one unit after. The rule is ``<=``."""
    receipt = store.commit([make_revision("e1", 0, days=2.0)], idempotency_key="k")
    micro = timedelta(microseconds=1) / timedelta(days=1)

    before = store.read("events", ctx=make_context(receipt.manifest_hash, days=2.0 - micro))
    at = store.read("events", ctx=make_context(receipt.manifest_hash, days=2.0))
    after = store.read("events", ctx=make_context(receipt.manifest_hash, days=2.0 + micro))

    assert before.rows == 0
    assert at.rows == 1
    assert after.rows == 1


def test_prospective_profile_waits_for_retrieval(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """Published in January, fetched in March: not ours in February.

    A strict historical replay judges the same row on availability alone, so
    the two profiles disagree here on purpose.
    """
    receipt = store.commit(
        [
            make_revision(
                "e1",
                0,
                days=0.0,
                retrieved_days=10.0,
                basis=AvailabilityBasis.VERSIONED_RELEASE,
                evidence="sha256:release",
            )
        ],
        idempotency_key="k",
    )
    at_five = make_context(receipt.manifest_hash, days=5.0)
    assert store.read("events", ctx=at_five).rows == 0

    historical = make_context(
        receipt.manifest_hash, days=5.0, profile=InformationProfile.STRICT_HISTORICAL
    )
    assert store.read("events", ctx=historical).rows == 1


# -- revision history ------------------------------------------------------
def test_each_cutoff_reconstructs_its_own_state(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """Report, correction, deletion, then a legitimate new revision."""
    receipt = store.commit(
        [
            make_revision("e1", 0, days=0.0, payload={"revision": "first"}),
            make_revision("e1", 1, days=3.0, payload={"revision": "corrected"}),
            make_revision("e1", 2, days=5.0, operation=RevisionOperation.DELETE),
            make_revision("e1", 3, days=8.0, payload={"revision": "reinstated"}),
        ],
        idempotency_key="k",
    )
    manifest = receipt.manifest_hash
    assert _values(store, make_context(manifest, days=1.0)) == ["first"]
    assert _values(store, make_context(manifest, days=4.0)) == ["corrected"]
    assert _values(store, make_context(manifest, days=6.0)) == []
    assert _values(store, make_context(manifest, days=9.0)) == ["reinstated"]


def test_a_tombstone_does_not_resurrect_the_row_it_deleted(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """Tombstones are dropped after ranking, never before.

    Dropping them first would leave the earlier upsert as the newest surviving
    revision, and the deleted row would come back.
    """
    receipt = store.commit(
        [
            make_revision("e1", 0, days=0.0),
            make_revision("e1", 1, days=2.0, operation=RevisionOperation.DELETE),
        ],
        idempotency_key="k",
    )
    result = store.read("events", ctx=make_context(receipt.manifest_hash, days=9.0))
    assert result.rows == 0
    assert result.tombstoned == 1


def test_a_blocked_source_does_not_promote_its_own_superseded_row(
    tmp_path: Path, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """Source gates run after ranking, so blocking cannot resurrect.

    If the gate ran first it would remove the newest revision and the ranking
    would then promote the older one -- a withheld source leaking through its
    own history.
    """
    store = RevisionStore(
        tmp_path / "store",
        clock=FixedClock(ORIGIN),
        policy=WithheldSources(frozenset({"shadow"})),
    )
    receipt = store.commit(
        [
            make_revision("e1", 0, days=0.0, source_id="shadow", payload={"revision": "old"}),
            make_revision("e1", 1, days=1.0, source_id="shadow", payload={"revision": "new"}),
            make_revision("e2", 0, days=0.0, source_id="acled", payload={"revision": "kept"}),
        ],
        idempotency_key="k",
    )
    result = store.read("events", ctx=make_context(receipt.manifest_hash, days=9.0))
    assert [record["revision"] for record in result.records()] == ["kept"]
    assert result.denied_sources == ("shadow",)


def test_ambiguous_revision_order_is_refused_not_broken(
    store: RevisionStore, make_revision: MakeRevision
) -> None:
    """Two revisions in one slot have no defensible winner."""
    with pytest.raises(ContractViolationError, match="same source_revision_order"):
        store.commit(
            [
                make_revision("e1", 1, days=0.0, payload={"revision": "a"}),
                make_revision("e1", 1, days=1.0, payload={"revision": "b"}),
            ],
            idempotency_key="k",
        )


# -- archive evidence ------------------------------------------------------
def test_strict_history_refuses_unresolved_availability(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """A live page that currently says 2019 is not proof of its 2019 bytes."""
    receipt = store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k")
    ctx = make_context(
        receipt.manifest_hash, days=5.0, profile=InformationProfile.STRICT_HISTORICAL
    )
    with pytest.raises(EligibilityError, match="unresolved availability"):
        store.read("events", ctx=ctx)


def test_an_evidence_claim_without_a_reference_is_rejected(
    make_revision: MakeRevision,
) -> None:
    with pytest.raises(ContractViolationError, match="no reference"):
        make_revision("e1", 0, basis=AvailabilityBasis.VERIFIED_ARCHIVE_CAPTURE)


# -- snapshot isolation and future invariance ------------------------------
def test_a_later_commit_cannot_change_a_sealed_manifest(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """Adding a release after sealing leaves the sealed replay identical."""
    first = store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k1")
    sealed = store.replay(first.manifest_hash)

    store.commit([make_revision("e2", 0, days=0.0)], idempotency_key="k2")

    assert store.replay(first.manifest_hash)["events"].equals(sealed["events"])
    ctx = make_context(first.manifest_hash, days=9.0)
    assert store.read("events", ctx=ctx).rows == 1


def test_future_information_does_not_change_an_earlier_read(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """The plan's replacement for 'shift every timestamp and expect a change'.

    Appending records that were not available at the cutoff must leave the
    earlier read byte-identical. This is the invariance half; the boundary-
    crossing test below is the other half, and neither alone is sufficient.
    """
    first = store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k1")
    ctx = make_context(first.manifest_hash, days=5.0)
    before = store.read("events", ctx=ctx).frame

    later = store.commit(
        [make_revision("e2", 0, days=30.0), make_revision("e3", 0, days=40.0)],
        idempotency_key="k2",
    )
    assert store.read("events", ctx=ctx).frame.equals(before)

    # And the same cutoff over the *newer* manifest still refuses the future.
    widened = make_context(later.manifest_hash, days=5.0)
    assert store.read("events", ctx=widened).frame.equals(before)


def test_moving_one_row_across_the_cutoff_removes_its_contribution(
    tmp_path: Path, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """The boundary-crossing half: a controlled move must change the result.

    Two otherwise identical stores differing only in when one row became
    available. Invariance alone would pass even if the cutoff were ignored, so
    this is the test that proves the filter is load-bearing.
    """
    stores = []
    for index, days in enumerate((1.0, 9.0)):
        store = RevisionStore(tmp_path / f"store-{index}", clock=FixedClock(ORIGIN))
        receipt = store.commit([make_revision("e1", 0, days=days)], idempotency_key="k")
        stores.append((store, receipt.manifest_hash))

    (early_store, early), (late_store, late) = stores
    assert early_store.read("events", ctx=make_context(early, days=5.0)).rows == 1
    assert late_store.read("events", ctx=make_context(late, days=5.0)).rows == 0


def test_a_fresh_chain_starts_from_no_parent(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """``parent_manifest=None`` means no parent, not "use the head"."""
    store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k1")
    fresh = store.commit(
        [make_revision("e2", 0, days=0.0)], idempotency_key="k2", parent_manifest=None
    )
    result = store.read("events", ctx=make_context(fresh.manifest_hash, days=5.0))
    assert result.frame["entity_id"].to_list() == ["e2"]


# -- durability ------------------------------------------------------------
def test_a_retry_returns_the_original_receipt(
    store: RevisionStore, make_revision: MakeRevision
) -> None:
    batch = [make_revision("e1", 0, days=0.0)]
    first = store.commit(batch, idempotency_key="k")
    second = store.commit(batch, idempotency_key="k")
    assert second.manifest_hash == first.manifest_hash
    assert second.replayed is True
    assert first.replayed is False


def test_the_same_key_with_a_different_payload_is_a_conflict(
    store: RevisionStore, make_revision: MakeRevision
) -> None:
    store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k")
    with pytest.raises(IdempotencyConflictError):
        store.commit([make_revision("e2", 0, days=0.0)], idempotency_key="k")


def test_a_second_writer_fails_within_a_bounded_wait(
    store: RevisionStore, make_revision: MakeRevision
) -> None:
    """Two processes cannot both own the catalogue. The wait is bounded."""
    store.lock_path.parent.mkdir(parents=True, exist_ok=True)
    store.lock_path.write_text("held by another process", encoding="utf-8")
    store.lock_timeout_seconds = 0.1
    with pytest.raises(WriterLockError):
        store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k")
    store.lock_path.unlink()


def test_a_crash_before_the_receipt_leaves_no_visible_commit(
    store: RevisionStore, make_revision: MakeRevision
) -> None:
    """Blobs and a manifest without a receipt are litter, not a snapshot.

    Simulated by publishing parts and a manifest and never writing the
    catalogue -- exactly what a kill between steps 3 and 4 leaves behind.
    """
    from pramaanx.core.asof import StoreManifest

    parts = store._write_parts([make_revision("e1", 0, days=0.0)])
    manifest = StoreManifest(created_at=ORIGIN, parts=parts).with_hash()
    store._publish_manifest(manifest)

    assert store.head is None
    assert store.receipts() == []

    report = store.recover(grace_seconds=-1.0)
    assert report.healthy
    assert report.orphan_blobs
    assert manifest.manifest_hash not in {r.manifest_hash for r in store.receipts()}


def test_recovery_never_deletes_a_reachable_blob(
    store: RevisionStore, make_revision: MakeRevision
) -> None:
    """An older snapshot's parts are reachable, and a sweep must keep them."""
    first = store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k1")
    store.commit([make_revision("e2", 0, days=0.0)], idempotency_key="k2")

    report = store.recover(dry_run=False, grace_seconds=-1.0)
    assert report.healthy
    assert store.replay(first.manifest_hash)["events"].height == 1


def test_corrupt_bytes_are_reported_not_served(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    receipt = store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k")
    part = store.load_manifest(receipt.manifest_hash).parts[0]
    (store.root / part.path).write_bytes(b"not a parquet file")
    store._verified.clear()

    with pytest.raises(StoreCorruptionError):
        store.read("events", ctx=make_context(receipt.manifest_hash, days=5.0))
    assert store.recover().corrupt_blobs == (part.blob_hash,)


def test_a_physically_removed_blob_fails_replay_loudly(
    store: RevisionStore, make_revision: MakeRevision
) -> None:
    """Deletion obligations break exact replay. Say so rather than shorten it."""
    receipt = store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k")
    part = store.load_manifest(receipt.manifest_hash).parts[0]
    (store.root / part.path).unlink()
    store._verified.clear()

    with pytest.raises(RedactedArtifactError):
        store.replay(receipt.manifest_hash)


# -- reads are recorded ----------------------------------------------------
def test_every_read_is_logged_with_its_context(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    """Capabilities stop accidents; the log is what a reviewer can audit."""
    receipt = store.commit([make_revision("e1", 0, days=0.0)], idempotency_key="k")
    ctx = make_context(receipt.manifest_hash, days=5.0)
    store.read("events", ctx=ctx)

    lines = store.read_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = pl.read_json(store.read_log_path).row(0, named=True)
    assert entry["context"] == "ForecastContext"
    assert entry["context_identity"] == ctx.identity()
    assert entry["role"] == str(OriginRole.RETRO_TEST)


def test_payloads_decode_to_columns(
    store: RevisionStore, make_revision: MakeRevision, make_context: MakeContext
) -> None:
    receipt = store.commit(
        [
            make_revision("e1", 0, days=0.0, payload={"district": "d1", "count": 2}),
            make_revision("e2", 0, days=0.0, payload={"district": "d2", "count": 0}),
        ],
        idempotency_key="k",
    )
    frame = store.read("events", ctx=make_context(receipt.manifest_hash, days=5.0)).payloads()
    assert frame.sort("entity_id")["count"].to_list() == [2, 0]
