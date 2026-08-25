"""The timestamp policy. One rule, applied wherever a document enters.

This module exists because there were two rules. `eval.availability` refused a
naive timestamp as undecidable -- correctly, since a wall-clock reading with no
offset does not name an instant. `stage0_ingest.validate` repaired the same
value with `replace(tzinfo=UTC)`. Stage 0 runs first, so the repair always won:
by the time the availability rule looked at a document, the naive stamp had
been invented away and the documented contract was decorative.

Two rules that disagree are not two rules, they are one rule and a bug. So the
decision is made here, once, and Stage 0, the document store and the benchmark
all call the same function.

Two modes, and the strict one is the default:

``strict``
    A naive `published_at` or `retrieved_at` is rejected, with the reason
    preserved so it reaches the run artefact. No timezone is ever inferred. An
    aware timestamp in any zone is *converted* to UTC, which is arithmetic on a
    known instant and not the same thing at all.

``assume_utc``
    A naive stamp is read as UTC and counted. This is a real need -- plenty of
    feeds emit local wall clocks with no offset and an operator may know which
    zone they meant -- but it is an assertion by that operator, not an
    inference the code is entitled to make. It must be configured explicitly
    and `require_strict` keeps it out of anything whose numbers get reported.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import UTC, datetime


class TimestampPolicyError(RuntimeError):
    """Raised when a policy is used somewhere it is not permitted."""


class TimestampPolicy(enum.StrEnum):
    STRICT = "strict"
    ASSUME_UTC = "assume_utc"

    @classmethod
    def parse(cls, value: str | TimestampPolicy) -> TimestampPolicy:
        try:
            return cls(str(value))
        except ValueError:
            raise TimestampPolicyError(
                f"unknown timestamp policy {value!r}; expected one of {[p.value for p in cls]}"
            ) from None


#: Reason strings. Stable, because they are recorded in artefacts and asserted
#: on in tests -- a reason that gets reworded silently breaks both.
NAIVE_PUBLISHED = "naive published_at: no timezone, so it names no instant"
NAIVE_RETRIEVED = "naive retrieved_at: no timezone, so it names no instant"


@dataclass(frozen=True)
class Resolved:
    """The outcome of applying the policy to one timestamp."""

    value: datetime | None
    assumed_utc: bool = False
    reason: str | None = None

    @property
    def rejected(self) -> bool:
        return self.reason is not None


def resolve(ts: datetime | None, policy: str | TimestampPolicy, *, field: str) -> Resolved:
    """Apply the policy to one timestamp.

    `None` is passed through untouched: a missing acquisition time is a
    separate question, answered by `eval.availability`, and conflating "absent"
    with "unusable" would lose the distinction the availability rule needs.
    """
    policy = TimestampPolicy.parse(policy)
    if ts is None:
        return Resolved(None)
    if ts.tzinfo is not None and ts.utcoffset() is not None:
        # Aware. Convert to UTC -- this preserves the instant.
        return Resolved(ts.astimezone(UTC))
    if policy is TimestampPolicy.ASSUME_UTC:
        return Resolved(ts.replace(tzinfo=UTC), assumed_utc=True)
    reason = NAIVE_PUBLISHED if field == "published_at" else NAIVE_RETRIEVED
    return Resolved(None, reason=reason)


def require_strict(policy: str | TimestampPolicy, context: str) -> TimestampPolicy:
    """Refuse to continue unless the policy is `strict`.

    Called by the benchmark ingestion path. The escape hatch has legitimate
    uses; producing a reported measurement is not one of them, and the only way
    to keep that true is to make the reported path check.
    """
    parsed = TimestampPolicy.parse(policy)
    if parsed is not TimestampPolicy.STRICT:
        raise TimestampPolicyError(
            f"{context} requires the strict timestamp policy, but the "
            f"configuration asks for {parsed.value!r}. A corpus whose naive "
            f"timestamps were assumed to be UTC cannot produce a strict "
            f"backtest result: the assumption is an operator's assertion, not "
            f"a measured fact, and it is unavailable to the availability rule."
        )
    return parsed
