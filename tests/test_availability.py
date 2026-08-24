"""The availability rule: when a document could first have been used.

Every case in this file is one a `published_at`-only filter gets wrong. That is
the point: a test that only exercises the happy path would pass against the
rule this module exists to replace.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from pramaan_x.eval.availability import (
    TRUSTED_SNAPSHOT_FLAG,
    AvailabilityFilter,
    NaiveTimestampError,
    Rejection,
    audit_returned,
    available_at,
    available_documents,
    classify,
    is_available,
    to_utc,
)
from pramaan_x.types import Document

T = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)


def doc(doc_id="d", published=None, retrieved=None, **meta) -> Document:
    return Document(
        doc_id=doc_id,
        source_id="s",
        text="body",
        title="t",
        published_at=published if published is not None else T - timedelta(days=1),
        retrieved_at=retrieved,
        meta=dict(meta),
    )


# ----------------------------------------------------------- the rule ---


def test_available_at_is_the_later_of_the_two():
    pub = T - timedelta(days=5)
    ret = T - timedelta(days=2)
    assert available_at(doc(published=pub, retrieved=ret)) == ret
    # ...and it does not go backwards when retrieval precedes publication.
    assert available_at(doc(published=ret, retrieved=pub)) == ret


def test_published_before_but_retrieved_after_origin_is_unavailable():
    """The case the old filter got wrong: the document existed on Monday and
    was crawled on Friday, so a Wednesday forecast could not have used it."""
    d = doc(published=T - timedelta(days=3), retrieved=T + timedelta(days=2))
    assert classify(d, T) is Rejection.RETRIEVED_AFTER_ORIGIN
    assert not is_available(d, T)
    assert available_at(d) > T


def test_retrieved_before_but_published_after_origin_is_unavailable():
    """The inverse, which happens with embargoed or scheduled publication: we
    hold the bytes but the information is not published yet."""
    d = doc(published=T + timedelta(days=1), retrieved=T - timedelta(days=1))
    assert classify(d, T) is Rejection.PUBLISHED_AFTER_ORIGIN
    assert not is_available(d, T)


def test_both_before_origin_is_available():
    d = doc(published=T - timedelta(days=3), retrieved=T - timedelta(days=1))
    assert classify(d, T) is None
    assert is_available(d, T)


@pytest.mark.parametrize("field", ["published", "retrieved"])
def test_document_exactly_at_the_origin_is_not_available(field):
    """Strict inequality on both sides. A document stamped at the instant the
    forecast is made was not in hand when it was made."""
    kwargs = {"published": T - timedelta(days=2), "retrieved": T - timedelta(days=2)}
    kwargs[field] = T
    d = doc(**kwargs)
    assert not is_available(d, T)
    expected = (
        Rejection.PUBLISHED_AFTER_ORIGIN
        if field == "published"
        else Rejection.RETRIEVED_AFTER_ORIGIN
    )
    assert classify(d, T) is expected


def test_one_microsecond_before_the_origin_is_available():
    tick = timedelta(microseconds=1)
    d = doc(published=T - tick, retrieved=T - tick)
    assert is_available(d, T)


# ------------------------------------------------------- missing time ---


def test_missing_acquisition_time_is_rejected_not_guessed():
    """The rule that must not be softened: no substitution of `published_at`."""
    d = doc(published=T - timedelta(days=10), retrieved=None)
    assert classify(d, T) is Rejection.MISSING_ACQUISITION_TIME
    assert available_at(d) is None
    assert not is_available(d, T)


def test_trusted_historical_snapshot_flag_admits_a_missing_acquisition_time():
    d = doc(published=T - timedelta(days=10), retrieved=None, **{TRUSTED_SNAPSHOT_FLAG: True})
    assert classify(d, T) is None
    assert available_at(d) == T - timedelta(days=10)


def test_trusted_snapshot_still_obeys_the_publication_cutoff():
    """The flag asserts something about acquisition, not about publication."""
    d = doc(published=T + timedelta(days=1), retrieved=None, **{TRUSTED_SNAPSHOT_FLAG: True})
    assert classify(d, T) is Rejection.PUBLISHED_AFTER_ORIGIN


# --------------------------------------------------------- timezones ---


def test_timezone_conversion_decides_availability_correctly():
    """+05:30 midnight is the previous evening in UTC. Comparing the wall
    clocks instead of the instants flips the answer."""
    kolkata = timezone(timedelta(hours=5, minutes=30))
    origin = datetime(2025, 6, 1, 0, 0, tzinfo=UTC)
    # 04:00 in Kolkata on 1 June is 22:30 on 31 May UTC -- before the origin.
    early = datetime(2025, 6, 1, 4, 0, tzinfo=kolkata)
    d = doc(published=early, retrieved=early)
    assert to_utc(early) < origin
    assert is_available(d, origin)
    # 07:00 in Kolkata is 01:30 UTC -- after it.
    late = datetime(2025, 6, 1, 7, 0, tzinfo=kolkata)
    assert not is_available(doc(published=late, retrieved=late), origin)


def test_naive_timestamps_are_rejected_rather_than_assumed_utc():
    naive = datetime(2025, 5, 1, 12, 0)
    with pytest.raises(NaiveTimestampError):
        to_utc(naive)
    assert classify(doc(published=naive, retrieved=naive), T) is Rejection.NAIVE_TIMESTAMP
    d = doc(published=T - timedelta(days=2), retrieved=naive)
    assert classify(d, T) is Rejection.NAIVE_TIMESTAMP


def test_origin_in_another_zone_is_normalised():
    kolkata = timezone(timedelta(hours=5, minutes=30))
    d = doc(published=T - timedelta(hours=1), retrieved=T - timedelta(hours=1))
    assert is_available(d, T.astimezone(kolkata))


# ------------------------------------------------- updated documents ---


def test_republished_document_is_available_from_its_new_stamps():
    """A wire item reissued with a later publication date is, for availability
    purposes, a document that appeared later -- even though the same text was
    in the world earlier. The rule reads the stamps it is given and does not
    try to reason about the text's history."""
    original = doc(
        "orig",
        published=T - timedelta(days=10),
        retrieved=T - timedelta(days=10) + timedelta(hours=1),
    )
    republished = doc(
        "orig-r2", published=T + timedelta(days=1), retrieved=T + timedelta(days=1, hours=1)
    )
    assert is_available(original, T)
    assert not is_available(republished, T)


def test_updated_document_crawled_late_is_unavailable_despite_old_publication():
    """The dangerous update: the publication date stays at the original, the
    body is revised, and the revision is crawled after the origin. Publication
    date alone says 'use it'; the rule says no."""
    d = doc(
        "updated", published=T - timedelta(days=30), retrieved=T + timedelta(hours=1), revision=2
    )
    assert not is_available(d, T)
    assert classify(d, T) is Rejection.RETRIEVED_AFTER_ORIGIN


# ------------------------------------------------------------ filter ---


def test_filter_keeps_the_usable_and_records_every_rejection():
    docs = [
        doc("ok", published=T - timedelta(days=2), retrieved=T - timedelta(days=1)),
        doc("late-crawl", published=T - timedelta(days=2), retrieved=T + timedelta(days=1)),
        doc("future", published=T + timedelta(days=1), retrieved=T + timedelta(days=1)),
        doc("no-crawl-time", published=T - timedelta(days=2), retrieved=None),
    ]
    f = AvailabilityFilter(T)
    kept = f.split(docs)
    assert [d.doc_id for d in kept] == ["ok"]
    assert f.n_rejected == 3
    assert f.counts == {
        str(Rejection.RETRIEVED_AFTER_ORIGIN): 1,
        str(Rejection.PUBLISHED_AFTER_ORIGIN): 1,
        str(Rejection.MISSING_ACQUISITION_TIME): 1,
    }
    assert {v.doc_id for v in f.violations} == {"late-crawl", "future", "no-crawl-time"}
    assert all(v.origin == T.isoformat() for v in f.violations)


def test_available_documents_is_monotone_in_the_origin():
    docs = [
        doc(
            f"d{i}",
            published=T - timedelta(days=i),
            retrieved=T - timedelta(days=i) + timedelta(hours=1),
        )
        for i in range(1, 20)
    ]
    early = available_documents(docs, T - timedelta(days=10))
    late = available_documents(docs, T)
    assert {d.doc_id for d in early} <= {d.doc_id for d in late}


def test_audit_catches_a_leak_downstream_of_the_filter():
    """The filter is a promise; the audit is the verification. A ranker that
    reintroduces a document the filter dropped is invisible to the filter."""
    leaked = doc("leaked", published=T - timedelta(days=1), retrieved=T + timedelta(days=3))
    clean = doc("clean", published=T - timedelta(days=1), retrieved=T - timedelta(days=1))
    by_id = {d.doc_id: d for d in (leaked, clean)}
    violations = audit_returned(by_id, ["clean", "leaked"], T)
    assert [v.doc_id for v in violations] == ["leaked"]
    assert violations[0].reason is Rejection.RETRIEVED_AFTER_ORIGIN
    assert audit_returned(by_id, ["clean"], T) == []


def test_audit_ignores_ids_it_has_never_seen():
    by_id = {"a": doc("a", published=T - timedelta(days=1), retrieved=T - timedelta(days=1))}
    assert audit_returned(by_id, ["a", "unknown"], T) == []
