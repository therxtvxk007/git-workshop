"""Chronological rolling-origin splits with an embargo that is derived, not guessed.

Random train/test splitting is impossible to express here, and that is
deliberate: there is no shuffle parameter to set wrongly. Every split is
defined by cutoff dates in order.

The embargo is the part that is easy to get wrong. A model that is fitted on
cutoff ``T`` has only seen ``T``'s label once the horizon has elapsed *and* the
reporting delay has passed. So a validation cutoff ``V`` may only be predicted
by a model whose training cutoffs all satisfy

    T + horizon_days + reporting_delay_days <= V

Using a hand-picked embargo of "a few weeks" instead lets the last training
fold's labels arrive after the validation cutoff it is being scored against,
which inflates every metric downstream. The minimum embargo is therefore
computed from the reporting-delay policy that built the rows, and a caller may
lengthen it but not shorten it.

The final-test reservation is sealed. `select_rows` refuses to return rows for
it at all, so this package cannot open those labels even by accident.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.hashing import hash_object
from pramaanx.models.spatial.contracts import ReportingDelayPolicy, SpatialTrainingRow
from pramaanx.schemas.base import VersionedModel

__all__ = [
    "Fold",
    "SealedSplitError",
    "SplitPlan",
    "SplitPolicy",
    "SplitPurpose",
    "build_rolling_origin_plan",
    "select_rows",
]


class SealedSplitError(RuntimeError):
    """Something tried to open a reservation this package must not read."""


class SplitPurpose(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    #: Reserved for the later calibration package. Cutoffs are listed so the
    #: reservation is auditable; this package does not fit on them.
    CALIBRATION = "calibration"
    #: Reserved for final evaluation. Sealed.
    FINAL_TEST = "final_test"


class SplitPolicy(VersionedModel):
    """How the rolling origin advances."""

    #: Cutoffs held out at the end, most recent first: final test, then
    #: calibration. Both are reservations, not folds.
    final_test_cutoffs: int = Field(default=3, ge=0)
    calibration_cutoffs: int = Field(default=2, ge=0)
    #: Cutoffs scored per fold.
    validation_cutoffs: int = Field(default=1, ge=1)
    #: Smallest training block before the first fold is emitted.
    min_train_cutoffs: int = Field(default=2, ge=1)
    #: Expanding (default) accumulates history; sliding keeps a fixed span.
    expanding: bool = True
    sliding_train_cutoffs: int | None = Field(default=None, ge=1)
    #: Extra embargo on top of the derived minimum. Never shortens it.
    additional_embargo_days: int = Field(default=0, ge=0)
    policy_version: str = "rolling-origin@1"

    @model_validator(mode="after")
    def _check_policy(self) -> SplitPolicy:
        if not self.expanding and self.sliding_train_cutoffs is None:
            raise ValueError("a sliding window requires sliding_train_cutoffs")
        return self

    def embargo_days(self, delay: ReportingDelayPolicy) -> int:
        """The gap a training cutoff must clear before a validation cutoff."""
        return delay.horizon_days + delay.reporting_delay_days + self.additional_embargo_days


@dataclass(frozen=True)
class Fold:
    """One rolling-origin fold. Cutoff lists are explicit, never ranges."""

    fold_id: int
    train_cutoffs: tuple[datetime, ...]
    validation_cutoffs: tuple[datetime, ...]
    embargo_days: int

    @property
    def train_start(self) -> datetime:
        return self.train_cutoffs[0]

    @property
    def train_end(self) -> datetime:
        return self.train_cutoffs[-1]

    @property
    def validation_start(self) -> datetime:
        return self.validation_cutoffs[0]

    @property
    def validation_end(self) -> datetime:
        return self.validation_cutoffs[-1]

    def fold_hash(self) -> str:
        return hash_object(
            {
                "fold_id": self.fold_id,
                "train_cutoffs": list(self.train_cutoffs),
                "validation_cutoffs": list(self.validation_cutoffs),
                "embargo_days": self.embargo_days,
            }
        )


@dataclass(frozen=True)
class SplitPlan:
    """Every fold plus the two sealed reservations."""

    folds: tuple[Fold, ...]
    calibration_cutoffs: tuple[datetime, ...]
    final_test_cutoffs: tuple[datetime, ...]
    policy: SplitPolicy
    reporting_delay: ReportingDelayPolicy

    def plan_hash(self) -> str:
        return hash_object(
            {
                "folds": [fold.fold_hash() for fold in self.folds],
                "calibration_cutoffs": list(self.calibration_cutoffs),
                "final_test_cutoffs": list(self.final_test_cutoffs),
                "policy": self.policy.model_dump(mode="json"),
                "reporting_delay": self.reporting_delay.model_dump(mode="json"),
            }
        )

    def modelling_cutoffs(self) -> tuple[datetime, ...]:
        """Cutoffs this package may touch: training and validation only."""
        seen: set[datetime] = set()
        for fold in self.folds:
            seen.update(fold.train_cutoffs)
            seen.update(fold.validation_cutoffs)
        return tuple(sorted(seen))


def build_rolling_origin_plan(
    cutoffs: Iterable[datetime],
    *,
    policy: SplitPolicy,
    reporting_delay: ReportingDelayPolicy,
) -> SplitPlan:
    """Lay out folds over ordered cutoffs, reserving the tail."""
    ordered = tuple(sorted(set(cutoffs)))
    if any(cutoff.tzinfo is None for cutoff in ordered):
        raise ValueError("split cutoffs must be timezone-aware")
    reserved = policy.final_test_cutoffs + policy.calibration_cutoffs
    if len(ordered) <= reserved + policy.min_train_cutoffs:
        raise ValueError(
            f"{len(ordered)} cutoffs cannot support {reserved} reserved plus at least "
            f"{policy.min_train_cutoffs} training and {policy.validation_cutoffs} validation"
        )

    final_test = (
        ordered[len(ordered) - policy.final_test_cutoffs :] if policy.final_test_cutoffs else ()
    )
    remaining = ordered[: len(ordered) - policy.final_test_cutoffs]
    calibration = (
        remaining[len(remaining) - policy.calibration_cutoffs :]
        if policy.calibration_cutoffs
        else ()
    )
    modelling = remaining[: len(remaining) - policy.calibration_cutoffs]

    embargo = policy.embargo_days(reporting_delay)
    folds: list[Fold] = []
    fold_id = 0
    start_index = policy.min_train_cutoffs

    while start_index + policy.validation_cutoffs <= len(modelling):
        validation = modelling[start_index : start_index + policy.validation_cutoffs]
        first_validation = validation[0]
        # Only training cutoffs whose labels were knowable before the
        # validation cutoff survive the embargo. Dropping them is the point.
        eligible = [
            cutoff
            for cutoff in modelling[:start_index]
            if cutoff + timedelta(days=embargo) <= first_validation
        ]
        if not policy.expanding and policy.sliding_train_cutoffs is not None:
            eligible = eligible[-policy.sliding_train_cutoffs :]

        if len(eligible) >= policy.min_train_cutoffs:
            folds.append(
                Fold(
                    fold_id=fold_id,
                    train_cutoffs=tuple(eligible),
                    validation_cutoffs=tuple(validation),
                    embargo_days=embargo,
                )
            )
            fold_id += 1
        start_index += policy.validation_cutoffs

    if not folds:
        raise ValueError(
            f"no fold survived the {embargo}-day embargo. The cutoff spacing is shorter than "
            "the horizon plus the reporting delay, so no training label is knowable in time."
        )
    return SplitPlan(tuple(folds), calibration, final_test, policy, reporting_delay)


def select_rows(
    rows: Sequence[SpatialTrainingRow],
    *,
    plan: SplitPlan,
    fold: Fold | None,
    purpose: SplitPurpose,
) -> tuple[SpatialTrainingRow, ...]:
    """Return the rows for one purpose, refusing the sealed reservation."""
    if purpose is SplitPurpose.FINAL_TEST:
        raise SealedSplitError(
            "the final-test reservation is sealed to this package. WP5 produces training and "
            "validation predictions only; opening these labels here would make every later "
            "evaluation a re-report of a number this package already saw."
        )
    if purpose is SplitPurpose.CALIBRATION:
        wanted = set(plan.calibration_cutoffs)
    elif fold is None:
        raise ValueError(f"{purpose.value} rows require a fold")
    elif purpose is SplitPurpose.TRAIN:
        wanted = set(fold.train_cutoffs)
    else:
        wanted = set(fold.validation_cutoffs)
    return tuple(row for row in rows if row.cutoff_at in wanted)
