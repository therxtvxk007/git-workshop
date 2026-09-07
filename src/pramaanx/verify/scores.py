"""Proper scores that keep their endpoints.

The repository already has a scoring module (:mod:`pramaanx.evaluation.metrics`)
whose log loss clips probabilities to 1e-6 so a single confident miss stays
finite. That is a reasonable choice for a dashboard and the wrong one here. The
plan is explicit (S32.2): ``p = 0`` with ``y = 1`` has infinite log loss, and
that infinity is the result. Clipping it replaces a model's claim of
impossibility with a claim of near-impossibility and then reports the second as
though the model had made it.

So these scores keep the infinity, count it, and let the caller decide. A mean
over an infinite term is infinite; a run that wants a finite headline number has
to say which rows it excluded and why, which is the point.

Everything returns a :class:`ScoreResult` carrying the denominator. A Brier
score over 60% of the panel is a different claim from one over all of it, and
the only way a reader can tell is if the count travels with the number
(S33.3).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from pramaanx.core.errors import ContractViolationError


class Orientation(StrEnum):
    """Which direction is better. Stated, because half of these go each way."""

    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"


class ScoreState(StrEnum):
    """Why a score is not a number, when it is not one.

    Four distinct states, kept apart because collapsing them into ``None`` or
    ``0.0`` is how an empty subgroup becomes a perfect score (S33.3).
    """

    OK = "ok"
    #: No eligible rows: an empty subgroup, or every row unobserved.
    NOT_SCORABLE = "not_scorable"
    #: The model does not produce what this metric needs.
    UNSUPPORTED = "unsupported"
    #: The computation ran and produced a non-finite value.
    NON_FINITE = "non_finite"


@dataclass(frozen=True)
class ScoreResult:
    """A score, its denominator, and what it could not compute."""

    metric: str
    value: float | None
    orientation: Orientation
    n: int
    #: Rows that contributed an infinite term. Reported rather than dropped:
    #: two confident misses and none are different results.
    non_finite: int = 0
    state: ScoreState = ScoreState.OK
    detail: str = ""

    @property
    def finite(self) -> bool:
        return self.value is not None and math.isfinite(self.value)

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "value": self.value,
            "orientation": str(self.orientation),
            "n": self.n,
            "non_finite": self.non_finite,
            "state": str(self.state),
            "detail": self.detail,
        }


def _validate(
    probabilities: Sequence[float], outcomes: Sequence[int]
) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.shape != y.shape:
        raise ContractViolationError(
            "probabilities and outcomes must be paired row for row",
            probabilities=int(p.size),
            outcomes=int(y.size),
        )
    if p.size and (p.min() < 0.0 or p.max() > 1.0):
        raise ContractViolationError("probabilities must lie in [0, 1]")
    if y.size and not np.isin(y, (0.0, 1.0)).all():
        raise ContractViolationError("binary outcomes must be 0 or 1")
    return p, y


def _empty(metric: str, orientation: Orientation, detail: str) -> ScoreResult:
    return ScoreResult(
        metric=metric,
        value=None,
        orientation=orientation,
        n=0,
        state=ScoreState.NOT_SCORABLE,
        detail=detail,
    )


def brier(probabilities: Sequence[float], outcomes: Sequence[int]) -> ScoreResult:
    """Mean squared error of a probability forecast. Always finite."""
    p, y = _validate(probabilities, outcomes)
    if p.size == 0:
        return _empty("brier", Orientation.LOWER_IS_BETTER, "no eligible rows")
    return ScoreResult(
        metric="brier",
        value=float(np.mean((p - y) ** 2)),
        orientation=Orientation.LOWER_IS_BETTER,
        n=int(p.size),
    )


def log_loss(probabilities: Sequence[float], outcomes: Sequence[int]) -> ScoreResult:
    """Negative log likelihood, unclipped.

    A model that said zero and was wrong scores infinitely badly, and that is
    the honest report. The count of such rows is returned so a caller can
    describe them rather than quietly cap them.
    """
    p, y = _validate(probabilities, outcomes)
    if p.size == 0:
        return _empty("log_loss", Orientation.LOWER_IS_BETTER, "no eligible rows")

    with np.errstate(divide="ignore", invalid="ignore"):
        # Branch per row rather than ``y*log(p) + (1-y)*log(1-p)``. That
        # expression evaluates 0 * log(0) when a confident forecast is right,
        # which is NaN in floating point and 0 by the convention every proper
        # scoring rule uses -- so the algebraic form turns a perfect prediction
        # into a missing value. ``log1p`` also keeps the y=0 branch accurate as
        # p approaches zero, which is most of a rare-event panel.
        terms = np.where(y == 1.0, -np.log(p), -np.log1p(-p))
    non_finite = int(np.count_nonzero(~np.isfinite(terms)))
    value = float(np.mean(terms))
    return ScoreResult(
        metric="log_loss",
        value=value,
        orientation=Orientation.LOWER_IS_BETTER,
        n=int(p.size),
        non_finite=non_finite,
        state=ScoreState.NON_FINITE if not math.isfinite(value) else ScoreState.OK,
        detail=(f"{non_finite} row(s) assigned zero mass to what happened" if non_finite else ""),
    )


def count_crps(
    pmfs: Sequence[Sequence[float]],
    outcomes: Sequence[int],
    *,
    tail_mass: Sequence[float] | None = None,
) -> ScoreResult:
    """CRPS for count forecasts, as the integrated Brier score over thresholds.

    For an integer-valued forecast this is the sum over ``k`` of
    ``(F(k) - 1[y <= k])**2``, which is the discrete form of the continuous
    ranked probability score and reduces to the Brier score when the support is
    ``{0, 1}``.

    An observation beyond the PMF's support cannot be scored exactly: the tail
    is one bucket, and one bucket does not say where in the tail the mass sits.
    Those rows are reported as unsupported rather than scored against an
    assumed shape (S32.2).
    """
    if len(pmfs) != len(outcomes):
        raise ContractViolationError("pmfs and outcomes must be paired row for row")
    if not pmfs:
        return _empty("count_crps", Orientation.LOWER_IS_BETTER, "no eligible rows")

    tails = list(tail_mass) if tail_mass is not None else [0.0] * len(pmfs)
    scores: list[float] = []
    unsupported = 0
    for pmf, observed, tail in zip(pmfs, outcomes, tails, strict=True):
        support = len(pmf) - 1
        if observed > support:
            unsupported += 1
            continue
        cumulative = np.cumsum(np.asarray(pmf, dtype=float))
        indicator = (np.arange(len(pmf)) >= observed).astype(float)
        scores.append(float(np.sum((cumulative - indicator) ** 2)))
        # The tail contributes at every threshold above the support, where the
        # indicator is already 1; ignoring it would flatter a model that put
        # mass beyond K.
        if tail > 0.0:
            scores[-1] += float(tail**2)

    if not scores:
        return ScoreResult(
            metric="count_crps",
            value=None,
            orientation=Orientation.LOWER_IS_BETTER,
            n=0,
            state=ScoreState.UNSUPPORTED,
            detail=f"every observation fell beyond the forecast support ({unsupported} rows)",
        )
    return ScoreResult(
        metric="count_crps",
        value=float(np.mean(scores)),
        orientation=Orientation.LOWER_IS_BETTER,
        n=len(scores),
        state=ScoreState.OK,
        detail=(
            f"{unsupported} row(s) beyond the PMF support were not scored" if unsupported else ""
        ),
    )


def skill(model: ScoreResult, reference: ScoreResult) -> ScoreResult:
    """``1 - model/reference``. Undefined where the plan says it is undefined.

    A reference loss of zero has no skill defined against it, and neither does
    a non-finite one. Both are reported as states rather than as zero, because
    zero skill and undefined skill are different findings (S33.3).
    """
    orientation = Orientation.HIGHER_IS_BETTER
    if model.value is None or reference.value is None:
        return ScoreResult(
            metric=f"{model.metric}_skill",
            value=None,
            orientation=orientation,
            n=min(model.n, reference.n),
            state=ScoreState.NOT_SCORABLE,
            detail="model or reference score is not available",
        )
    if not math.isfinite(model.value) or not math.isfinite(reference.value):
        return ScoreResult(
            metric=f"{model.metric}_skill",
            value=None,
            orientation=orientation,
            n=min(model.n, reference.n),
            non_finite=model.non_finite + reference.non_finite,
            state=ScoreState.NON_FINITE,
            detail="a non-finite loss has no skill ratio",
        )
    if reference.value == 0.0:
        return ScoreResult(
            metric=f"{model.metric}_skill",
            value=None,
            orientation=orientation,
            n=min(model.n, reference.n),
            state=ScoreState.NOT_SCORABLE,
            detail="the reference achieved a perfect score; skill is undefined",
        )
    if model.n != reference.n:
        raise ContractViolationError(
            "skill compares two scores over different row sets; pair them on common support first",
            model_rows=model.n,
            reference_rows=reference.n,
        )
    return ScoreResult(
        metric=f"{model.metric}_skill",
        value=1.0 - (model.value / reference.value),
        orientation=orientation,
        n=model.n,
    )
