"""Typed failures with stable machine-readable codes.

Two reasons this module exists rather than a scatter of ``ValueError``.

First, ``assert`` can be disabled with ``python -O``. The plan is explicit that
collection approvals, probability validation and chronology enforcement must not
depend on a statement the interpreter is allowed to skip (revision plan, S28).
Every gate in this package raises one of these instead.

Second, a caller that has to match on an error message matches on prose. The
``code`` here is the stable part: it goes into manifests, ledger rows and test
assertions, and it may not change once published, even when the message does.
"""

from __future__ import annotations

from typing import Any

from pramaanx.hashing import canonical_json


class PramaanError(Exception):
    """Base class for every failure this project raises deliberately."""

    code = "pramaanx.error"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = dict(sorted(context.items()))

    def __str__(self) -> str:
        if not self.context:
            return self.message
        return f"{self.message} [{canonical_json(self.context)}]"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


class ContractViolationError(PramaanError):
    """A declared contract -- schema, config, manifest -- is not satisfied."""

    code = "pramaanx.contract_violation"


class EligibilityError(PramaanError):
    """A record was asked for under an information profile it cannot satisfy.

    Distinct from :class:`CutoffLeakageError`: this is the store refusing to serve
    something, not evidence that something already escaped.
    """

    code = "pramaanx.eligibility"


class CutoffLeakageError(PramaanError):
    """Post-cutoff information reached a pre-cutoff stage."""

    code = "pramaanx.leakage"


class CapabilityUnsupportedError(PramaanError):
    """A component was asked for an output it does not claim to produce.

    The plan's rule (S32.1, S42): a binary classifier does not acquire daily
    count paths by satisfying a Python signature. Fabricating the missing
    construction would smuggle in a statistical assumption, so the honest
    answer is this exception, and the run records the gap.
    """

    code = "pramaanx.capability_unsupported"


class UnresolvedContractError(PramaanError):
    """The model contract does not define what an implementation would need.

    Raised where the plan preserves an ambiguity on purpose (S42): union
    forecasts from family marginals, partition sampling from pairwise
    probabilities, calibrated counts from an occurrence calibrator. An adapter
    may not pick the missing assumption.
    """

    code = "pramaanx.unresolved_contract"


class StoreCorruptionError(PramaanError):
    """Stored bytes do not match the identity a manifest published for them."""

    code = "pramaanx.store_corruption"


class WriterLockError(PramaanError):
    """Another process owns the catalogue writer lock."""

    code = "pramaanx.writer_lock"


class IdempotencyConflictError(PramaanError):
    """The same idempotency key was reused for a different payload.

    A retry after a crash must return the original receipt. A *different*
    payload under the same key is a bug in the caller, not a retry, and
    silently accepting it would let one key describe two commits.
    """

    code = "pramaanx.idempotency_conflict"


class RedactedArtifactError(PramaanError):
    """Replay was asked for bytes that a deletion obligation removed.

    Correction tombstones preserve history; a physical deletion cannot. The
    plan requires replay to fail loudly here rather than return a silently
    shortened table (S30.3).
    """

    code = "pramaanx.redacted"
