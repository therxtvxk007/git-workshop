"""Information availability: when a document could first have been *used*.

`published_at` is not the constraint a backtest is subject to. A document that
appeared in the world on Monday and was not crawled until Friday could not have
informed a forecast made on Wednesday, and a benchmark that pretends otherwise
reports a retrieval quality no live system could reproduce.

The rule is therefore::

    available_at = max(published_at, retrieved_at)

and a document may be used at forecast origin ``T`` only when *both*

  * ``published_at < T``  -- the information existed; and
  * ``retrieved_at  < T`` -- we had actually acquired it.

Missing acquisition time is not filled in. Substituting `published_at` for a
missing `retrieved_at` is the exact assumption the rule exists to forbid: it
silently asserts zero crawl latency, which is the most optimistic possible
answer to the question being asked. A document with no `retrieved_at` is
rejected from a backtest unless it carries an explicit
``trusted_historical_snapshot`` flag, which is a human assertion that the
acquisition time is known to be no later than publication (a bulk archive
delivery, a licensed historical dump).

All comparisons happen in UTC. Timestamps carrying a non-UTC offset are
converted, never truncated; a naive timestamp has no defined instant and is
rejected rather than guessed at.

**Clusters.** After deduplication a document stands for its whole
near-duplicate cluster, and the cluster's availability is the availability of
its *earliest-available member* -- not of its canonical. The canonical is the
earliest-*published* member, which is a different thing: if it was crawled late
or never, but a syndicated copy was in hand at the origin, then the story was
in hand at the origin. Deciding otherwise would let a deduplication step, whose
only job is to stop double-counting evidence, silently delete evidence instead.

"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..types import Document

#: Meta key carrying a cluster's members and their own timestamps, written by
#: `stage0_ingest.dedup.apply_dedup`.
CLUSTER_MEMBERS_KEY = "cluster_members"

#: Meta key asserting that a document with no `retrieved_at` came from a
#: historical snapshot whose acquisition time is known not to postdate
#: publication. This is an operator assertion about provenance, not an
#: inference the code may make on its own.
TRUSTED_SNAPSHOT_FLAG = "trusted_historical_snapshot"


class Rejection(enum.StrEnum):
    """Why a document may not be used at a given origin."""

    PUBLISHED_AFTER_ORIGIN = "published_after_origin"
    RETRIEVED_AFTER_ORIGIN = "retrieved_after_origin"
    MISSING_ACQUISITION_TIME = "missing_acquisition_time"
    NAIVE_TIMESTAMP = "naive_timestamp"


@dataclass(frozen=True)
class AvailabilityViolation:
    """One document that was used, or offered, when it should not have been."""

    doc_id: str
    reason: Rejection
    origin: str
    published_at: str | None = None
    retrieved_at: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "doc_id": self.doc_id,
            "reason": str(self.reason),
            "origin": self.origin,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
        }


class NaiveTimestampError(ValueError):
    """Raised when a timestamp has no timezone and therefore no instant."""


def to_utc(ts: datetime) -> datetime:
    """Normalise an aware timestamp to UTC.

    A naive timestamp is an error, not a UTC timestamp. Two feeds writing
    ``2025-06-01T00:00:00`` in Kolkata and in London do not describe the same
    instant, and the difference is larger than most of the lead times this
    system reasons about.
    """
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise NaiveTimestampError(
            f"timestamp {ts!r} has no timezone; availability cannot be decided"
        )
    return ts.astimezone(UTC)


def is_trusted_snapshot(doc: Document) -> bool:
    """Exactly the boolean `True`, nothing else.

    `bool(meta.get(flag))` accepted the string "false" as trust, which is what
    a YAML or JSON round trip of a boolean produces often enough to matter, and
    also accepted 1, "yes" and any non-empty container. The flag admits a
    document with no acquisition time at all, so it is the one place in this
    package where a near-miss must not be read generously.
    """
    return getattr(doc, "meta", {}).get(TRUSTED_SNAPSHOT_FLAG, False) is True


@dataclass(frozen=True)
class Member:
    """One member of a near-duplicate cluster, with its own timestamps."""

    doc_id: str
    published_at: datetime | None
    retrieved_at: datetime | None
    trusted: bool = False


def cluster_members(doc: Document) -> list[Member]:
    """The cluster this document stands for.

    A document that never went through deduplication, or one whose cluster has
    a single member, stands only for itself -- so the single-member case is the
    same code path rather than a special case.
    """
    raw = getattr(doc, "meta", {}).get(CLUSTER_MEMBERS_KEY)
    if not raw:
        return [Member(doc.doc_id, doc.published_at, doc.retrieved_at, is_trusted_snapshot(doc))]
    out: list[Member] = []
    for m in raw:
        out.append(
            Member(
                doc_id=str(m.get("doc_id", "")),
                published_at=_parse(m.get("published_at")),
                retrieved_at=_parse(m.get("retrieved_at")),
                trusted=m.get(TRUSTED_SNAPSHOT_FLAG, False) is True,
            )
        )
    return out or [Member(doc.doc_id, doc.published_at, doc.retrieved_at, is_trusted_snapshot(doc))]


def _parse(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def cluster_members_at(doc: Document, origin: datetime) -> list[Member]:
    """The cluster's members that were usable at `origin`.

    Deduplication is monotone in publication order: a later document may join
    an existing cluster but never re-canonicalises it and never removes a
    member. So the *stored* member list grows as the corpus grows, while the
    list restricted to an origin does not -- and it is the restricted list that
    any decision at that origin is entitled to use.
    """
    return [m for m in cluster_members(doc) if classify_member(m, origin) is None]


def member_available_at(member: Member) -> datetime | None:
    """`max(published_at, retrieved_at)` for one member, or None if undecidable."""
    if member.published_at is None:
        return None
    try:
        pub = to_utc(member.published_at)
    except NaiveTimestampError:
        return None
    if member.retrieved_at is None:
        return pub if member.trusted else None
    try:
        return max(pub, to_utc(member.retrieved_at))
    except NaiveTimestampError:
        return None


def available_at(doc: Document) -> datetime | None:
    """The instant this document -- or any copy of it -- first became usable.

    For a single document this is ``max(published_at, retrieved_at)``, with a
    missing `retrieved_at` giving None unless the trusted-snapshot flag is set.
    For a deduplicated cluster it is the *earliest* such instant across the
    members, because the story was in hand as soon as any copy of it was.
    """
    instants = [a for a in (member_available_at(m) for m in cluster_members(doc)) if a is not None]
    return min(instants) if instants else None


#: When no member of a cluster is usable, the reported reason is the one from
#: the member that came closest to being usable. Ordered most-nearly-available
#: first, so "we had it but crawled it late" outranks "we never crawled it",
#: which outranks "it had not been published yet".
_REASON_PRIORITY = (
    Rejection.RETRIEVED_AFTER_ORIGIN,
    Rejection.MISSING_ACQUISITION_TIME,
    Rejection.NAIVE_TIMESTAMP,
    Rejection.PUBLISHED_AFTER_ORIGIN,
)


def classify_member(member: Member, origin: datetime) -> Rejection | None:
    """None when this individual member is usable at `origin`, else why not."""
    origin = to_utc(origin)
    if member.published_at is None:
        return Rejection.PUBLISHED_AFTER_ORIGIN
    try:
        pub = to_utc(member.published_at)
    except NaiveTimestampError:
        return Rejection.NAIVE_TIMESTAMP
    if pub >= origin:
        return Rejection.PUBLISHED_AFTER_ORIGIN
    if member.retrieved_at is None:
        return None if member.trusted else Rejection.MISSING_ACQUISITION_TIME
    try:
        ret = to_utc(member.retrieved_at)
    except NaiveTimestampError:
        return Rejection.NAIVE_TIMESTAMP
    return Rejection.RETRIEVED_AFTER_ORIGIN if ret >= origin else None


def classify(doc: Document, origin: datetime) -> Rejection | None:
    """None when the document's cluster is usable at `origin`, else why not.

    Usable means *some* member was usable. A cluster is rejected only when
    every copy of the story was out of reach.
    """
    reasons: list[Rejection] = []
    for member in cluster_members(doc):
        reason = classify_member(member, origin)
        if reason is None:
            return None
        reasons.append(reason)
    for candidate in _REASON_PRIORITY:
        if candidate in reasons:
            return candidate
    return Rejection.PUBLISHED_AFTER_ORIGIN


def is_available(doc: Document, origin: datetime) -> bool:
    """Strict inequality on both sides: a document stamped exactly at the
    origin is not available. The origin is the instant the forecast is made,
    and anything simultaneous with it was not in hand when it was made."""
    return classify(doc, origin) is None


@dataclass
class AvailabilityFilter:
    """Applies the rule to a corpus and keeps the audit trail.

    The rejections are not a diagnostic side effect; they are reported in the
    run artefact, because "how much of the corpus was unusable at this origin"
    is part of what the measurement means.
    """

    origin: datetime
    violations: list[AvailabilityViolation] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def split(self, docs: Iterable[Document]) -> list[Document]:
        """Returns the usable documents; records every rejection."""
        keep: list[Document] = []
        iso = to_utc(self.origin).isoformat()
        for d in docs:
            reason = classify(d, self.origin)
            if reason is None:
                keep.append(d)
                continue
            self.counts[str(reason)] = self.counts.get(str(reason), 0) + 1
            self.violations.append(
                AvailabilityViolation(
                    doc_id=d.doc_id,
                    reason=reason,
                    origin=iso,
                    published_at=_iso_or_none(d.published_at),
                    retrieved_at=_iso_or_none(d.retrieved_at),
                )
            )
        return keep

    @property
    def n_rejected(self) -> int:
        return len(self.violations)


def available_documents(docs: Iterable[Document], origin: datetime) -> list[Document]:
    """The corpus as it stood at `origin`. The only supported input to any
    index, statistic or ranker fitted for that origin."""
    return AvailabilityFilter(origin).split(docs)


def audit_returned(
    docs_by_id: dict[str, Document], returned_ids: Sequence[str], origin: datetime
) -> list[AvailabilityViolation]:
    """Post-hoc check on what a retriever actually handed back.

    Filtering the input is a promise; this is the verification. They are kept
    separate on purpose -- a bug that reintroduces a future document downstream
    of the filter is invisible to the filter itself.
    """
    out: list[AvailabilityViolation] = []
    iso = to_utc(origin).isoformat()
    for doc_id in returned_ids:
        doc = docs_by_id.get(doc_id)
        if doc is None:
            continue
        reason = classify(doc, origin)
        if reason is not None:
            out.append(
                AvailabilityViolation(
                    doc_id=doc_id,
                    reason=reason,
                    origin=iso,
                    published_at=_iso_or_none(doc.published_at),
                    retrieved_at=_iso_or_none(doc.retrieved_at),
                )
            )
    return out


def _iso_or_none(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts is not None else None
