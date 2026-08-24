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
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..types import Document

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
    return bool(getattr(doc, "meta", {}).get(TRUSTED_SNAPSHOT_FLAG, False))


def available_at(doc: Document) -> datetime | None:
    """The instant this document first became usable, or None if undecidable.

    Returns ``max(published_at, retrieved_at)``. When `retrieved_at` is absent,
    the answer is `published_at` **only** for a trusted historical snapshot;
    otherwise it is None, and callers must treat the document as unusable
    rather than assume a value.
    """
    pub = to_utc(doc.published_at)
    ret = doc.retrieved_at
    if ret is None:
        return pub if is_trusted_snapshot(doc) else None
    return max(pub, to_utc(ret))


def classify(doc: Document, origin: datetime) -> Rejection | None:
    """None when the document is usable at `origin`, else why it is not."""
    origin = to_utc(origin)
    try:
        pub = to_utc(doc.published_at)
    except NaiveTimestampError:
        return Rejection.NAIVE_TIMESTAMP
    if pub >= origin:
        return Rejection.PUBLISHED_AFTER_ORIGIN
    ret = doc.retrieved_at
    if ret is None:
        if is_trusted_snapshot(doc):
            return None
        return Rejection.MISSING_ACQUISITION_TIME
    try:
        ret_utc = to_utc(ret)
    except NaiveTimestampError:
        return Rejection.NAIVE_TIMESTAMP
    if ret_utc >= origin:
        return Rejection.RETRIEVED_AFTER_ORIGIN
    return None


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
