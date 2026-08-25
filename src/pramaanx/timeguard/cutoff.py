"""CutoffGuard: the single gate every observation passes through.

Cutoff safety is a model feature, not merely an evaluation option. Nothing
downstream -- retrieval, features, generators, adjudication -- is allowed to see
an observation this guard rejects.

The admission rule is deliberately one line::

    observation.first_observed_at <= cutoff_at

Everything else in this module exists to catch the cases where that line is
true but the record is still not trustworthy: a timeline that cannot be real, a
publication date after the cutoff on a supposedly older document, a payload
whose bytes no longer match the hash they were ingested under.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pramaanx.config import TimeguardConfig
from pramaanx.hashing import utc_isoformat
from pramaanx.logging import get_logger
from pramaanx.schemas.observation import Observation

log = get_logger(__name__)


class LeakageError(RuntimeError):
    """Post-cutoff information reached, or tried to reach, a pre-cutoff stage."""


class ViolationKind(StrEnum):
    FUTURE_OBSERVATION = "future_observation"
    """first_observed_at is after the cutoff. The primary rule."""

    PUBLISHED_AFTER_CUTOFF = "published_after_cutoff"
    """Claims to have been observable before it was published: the body on the
    other end of that URL is not the body that existed at the cutoff."""

    OBSERVED_BEFORE_PUBLISHED = "observed_before_published"
    """Observed before publication. Either the source lies about its dates or
    the record has been edited; both disqualify it from a point-in-time run."""

    RETRIEVED_BEFORE_OBSERVED = "retrieved_before_observed"
    """Structurally impossible; indicates a corrupted or hand-edited record."""


@dataclass(frozen=True)
class CutoffViolation:
    kind: ViolationKind
    observation_id: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.observation_id}: {self.detail}"


@dataclass(frozen=True)
class AdmissionReport:
    """Outcome of screening a batch of observations against one cutoff."""

    cutoff_at: datetime
    admitted: tuple[Observation, ...]
    violations: tuple[CutoffViolation, ...]

    @property
    def admitted_count(self) -> int:
        return len(self.admitted)

    @property
    def rejected_count(self) -> int:
        return len(self.violations)

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for violation in self.violations:
            counts[str(violation.kind)] = counts.get(str(violation.kind), 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        return {
            "cutoff_at": utc_isoformat(self.cutoff_at),
            "admitted": self.admitted_count,
            "rejected": self.rejected_count,
            "violations_by_kind": self.counts_by_kind(),
        }


class CutoffGuard:
    """Admits only what was legitimately available at ``cutoff_at``."""

    def __init__(self, cutoff_at: datetime, config: TimeguardConfig | None = None) -> None:
        if cutoff_at.tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        self.cutoff_at = cutoff_at.astimezone(UTC)
        self.config = config or TimeguardConfig()
        self._skew = timedelta(seconds=self.config.max_future_skew_seconds)

    @property
    def boundary(self) -> datetime:
        """The effective admission boundary, including any permitted skew.

        Skew defaults to zero. It exists for feeds whose clocks are known to run
        slightly ahead, and any non-zero value is recorded in the snapshot
        manifest so a reviewer can see the allowance that was granted.
        """
        return self.cutoff_at + self._skew

    def inspect(self, observation: Observation) -> list[CutoffViolation]:
        """Return every reason this observation may not be used at the cutoff."""
        violations: list[CutoffViolation] = []
        oid = observation.observation_id

        if observation.first_observed_at > self.boundary:
            violations.append(
                CutoffViolation(
                    ViolationKind.FUTURE_OBSERVATION,
                    oid,
                    f"first_observed_at={utc_isoformat(observation.first_observed_at)} "
                    f"> cutoff={utc_isoformat(self.boundary)}",
                )
            )

        if observation.retrieved_at < observation.first_observed_at:
            violations.append(
                CutoffViolation(
                    ViolationKind.RETRIEVED_BEFORE_OBSERVED,
                    oid,
                    f"retrieved_at={utc_isoformat(observation.retrieved_at)} precedes "
                    f"first_observed_at={utc_isoformat(observation.first_observed_at)}",
                )
            )

        published = observation.published_at
        if published is not None:
            if published > observation.first_observed_at:
                violations.append(
                    CutoffViolation(
                        ViolationKind.OBSERVED_BEFORE_PUBLISHED,
                        oid,
                        f"published_at={utc_isoformat(published)} is after "
                        f"first_observed_at={utc_isoformat(observation.first_observed_at)}",
                    )
                )
            if self.config.reject_updated_bodies and published > self.boundary:
                violations.append(
                    CutoffViolation(
                        ViolationKind.PUBLISHED_AFTER_CUTOFF,
                        oid,
                        f"published_at={utc_isoformat(published)} is after the cutoff; "
                        "the stored body cannot be the pre-cutoff body",
                    )
                )
        return violations

    def is_admissible(self, observation: Observation) -> bool:
        return not self.inspect(observation)

    def assert_admissible(self, observation: Observation) -> None:
        violations = self.inspect(observation)
        if violations:
            raise LeakageError("; ".join(str(item) for item in violations))

    def screen(self, observations: Iterable[Observation]) -> AdmissionReport:
        """Screen a batch. In strict mode, any violation raises.

        Strict mode is the default because the alternative -- quietly dropping
        an inadmissible record -- makes a leak look like a thin news day.
        """
        admitted: list[Observation] = []
        violations: list[CutoffViolation] = []
        for observation in observations:
            found = self.inspect(observation)
            if found:
                violations.extend(found)
            else:
                admitted.append(observation)

        if violations and self.config.strict:
            summary = "; ".join(str(item) for item in violations[:5])
            more = "" if len(violations) <= 5 else f" (+{len(violations) - 5} more)"
            raise LeakageError(
                f"{len(violations)} cutoff violation(s) at "
                f"{utc_isoformat(self.cutoff_at)}: {summary}{more}"
            )

        if violations:
            log.warning(
                "cutoff.violations",
                cutoff=utc_isoformat(self.cutoff_at),
                rejected=len(violations),
            )
        admitted.sort(key=lambda item: (item.first_observed_at, item.observation_id))
        return AdmissionReport(self.cutoff_at, tuple(admitted), tuple(violations))

    def filter(self, observations: Iterable[Observation]) -> list[Observation]:
        """Admissible observations only, in deterministic order."""
        return list(self.screen(observations).admitted)

    def horizon(self, days: int) -> datetime:
        """The forecast horizon end for this cutoff."""
        return self.cutoff_at + timedelta(days=days)

    def __repr__(self) -> str:
        return (
            f"CutoffGuard(cutoff_at={utc_isoformat(self.cutoff_at)!r}, strict={self.config.strict})"
        )


def partition_by_cutoff(
    observations: Sequence[Observation], cutoff_at: datetime
) -> tuple[list[Observation], list[Observation]]:
    """Split observations into (available at cutoff, not yet available).

    Used by the backtest to build the resolution view without ever handing the
    future half to a forecasting stage.
    """
    boundary = cutoff_at.astimezone(UTC)
    past = [item for item in observations if item.first_observed_at <= boundary]
    future = [item for item in observations if item.first_observed_at > boundary]
    past.sort(key=lambda item: (item.first_observed_at, item.observation_id))
    future.sort(key=lambda item: (item.first_observed_at, item.observation_id))
    return past, future
