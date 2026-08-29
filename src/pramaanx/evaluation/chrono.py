"""Strictly chronological evaluation primitives.

Four things the rolling backtest in :mod:`pramaanx.evaluation.backtest` does not
do, each of which silently inflates a result if it is left undone.

*Maturity, not merely order.* A fold that started before the forecast cutoff is
not usable for calibration. Its outcomes are only knowable once the whole
horizon has elapsed **and** the reporting delay has passed on top of it. Fitting
on a fold that is chronologically earlier but not yet resolved reads outcomes
from the forecast's own future. :func:`is_mature` is the only admission test.

*Skill against an earlier-period reference.* ``brier_skill_score`` in
:mod:`pramaanx.evaluation.metrics` scores against the base rate *of the sample
being scored*, which no forecaster could have known. That is the right
diagnostic and the wrong claim. :func:`skill_score` takes an explicit reference
forecast so the reference can be built from earlier periods only.

*Unique outcomes at a budget.* ``recall_at_budget`` counts label hits, and the
matcher is many-to-one, so five candidates pointing at one event count five
times. An analyst reviewing a list of twenty finds one event, not five.
:func:`unique_outcome_topk` counts distinct outcomes.

*Overlapping folds are not independent.* A 30-day horizon stepped every 7 days
puts the same days in five consecutive folds. A t-test over those folds treats
one event as five observations. :func:`moving_block_bootstrap` resamples blocks
long enough to carry the overlap.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

#: Blocks shorter than the overlap depth break the dependence the block
#: bootstrap exists to preserve.
MIN_BLOCK_LENGTH = 2


# --------------------------------------------------------------------- maturity
def maturity_time(fold_cutoff: datetime, horizon_days: int, delay_days: float) -> datetime:
    """When a fold's outcomes become fully knowable.

    Mirrors ``ResolutionBoundary.required_evidence_end``: the horizon has to
    close and the reporting delay has to elapse on top of it.
    """
    return fold_cutoff + timedelta(days=horizon_days + delay_days)


def is_mature(
    fold_cutoff: datetime, forecast_cutoff: datetime, horizon_days: int, delay_days: float
) -> bool:
    """Whether ``fold_cutoff`` is usable to calibrate a forecast at ``forecast_cutoff``."""
    return maturity_time(fold_cutoff, horizon_days, delay_days) <= forecast_cutoff


def overlap_depth(horizon_days: int, step_days: int) -> int:
    """How many consecutive folds share days, given a horizon and a step."""
    if step_days <= 0:
        raise ValueError("step_days must be positive")
    return max(1, math.ceil(horizon_days / step_days))


# ------------------------------------------------------------------ references
def climatology(prior_labels: Sequence[int]) -> float | None:
    """Base rate over earlier, matured folds only.

    ``None`` when no matured fold exists yet, which is a real state at the start
    of any walk and must not be filled in with the current fold's own rate.
    """
    if not prior_labels:
        return None
    return float(np.mean(np.asarray(prior_labels, dtype=float)))


def persistence(
    stream_keys: Sequence[str], prior_positive_streams: Iterable[str], fallback: float
) -> list[float]:
    """Predict a stream repeats if it fired in the previous matured window.

    The hardest naive baseline on autocorrelated event data, and the one a model
    has to beat before any of its structure counts as skill.
    """
    hot = set(prior_positive_streams)
    return [1.0 - 1e-6 if key in hot else fallback for key in stream_keys]


def skill_score(
    probabilities: Sequence[float], labels: Sequence[int], reference: Sequence[float]
) -> float | None:
    """Brier skill against an explicit reference forecast. Positive beats it."""
    if not probabilities:
        return None
    # Written out rather than chained: ``a != b != c`` is ``(a != b) and (b != c)``,
    # which is False when the first two agree and the third does not.
    if len(probabilities) != len(labels) or len(labels) != len(reference):
        return None
    probs = np.asarray(probabilities, dtype=float)
    truth = np.asarray(labels, dtype=float)
    ref = np.asarray(reference, dtype=float)
    model = float(np.mean((probs - truth) ** 2))
    baseline = float(np.mean((ref - truth) ** 2))
    if baseline <= 0.0:
        return None
    return 1.0 - model / baseline


# ------------------------------------------------------------- unique-outcome k
@dataclass(frozen=True)
class UniqueTopK:
    """Top-``k`` counted in distinct outcomes rather than in label hits."""

    budget: int
    selected: int
    label_hits: int
    unique_outcomes: int
    outcomes_available: int
    unique_recall: float | None
    unique_precision: float | None
    duplication_ratio: float | None

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "budget": self.budget,
            "selected": self.selected,
            "label_hits": self.label_hits,
            "unique_outcomes": self.unique_outcomes,
            "outcomes_available": self.outcomes_available,
            "unique_recall": self.unique_recall,
            "unique_precision": self.unique_precision,
            "duplication_ratio": self.duplication_ratio,
        }


def unique_outcome_topk(
    probabilities: Sequence[float],
    matched: Sequence[bool],
    outcome_ids: Sequence[str | None],
    budget: int,
    outcomes_available: int,
) -> UniqueTopK:
    """Distinct outcomes recovered inside a review budget.

    ``duplication_ratio`` is label hits over distinct outcomes: 1.0 means every
    hit was a different event, 3.0 means the list showed the analyst the same
    event three times.
    """
    if budget <= 0 or not probabilities:
        return UniqueTopK(budget, 0, 0, 0, outcomes_available, None, None, None)
    order = sorted(range(len(probabilities)), key=lambda i: (-probabilities[i], i))
    chosen = order[:budget]
    hits = sum(1 for i in chosen if matched[i])
    unique = {outcome_ids[i] for i in chosen if matched[i] and outcome_ids[i] is not None}
    return UniqueTopK(
        budget=budget,
        selected=len(chosen),
        label_hits=hits,
        unique_outcomes=len(unique),
        outcomes_available=outcomes_available,
        unique_recall=(len(unique) / outcomes_available if outcomes_available else None),
        unique_precision=(len(unique) / len(chosen) if chosen else None),
        duplication_ratio=(hits / len(unique) if unique else None),
    )


def one_to_one_labels(
    forecast_ids: Sequence[str],
    matched: Sequence[bool],
    outcome_ids: Sequence[str | None],
    scores: Sequence[float],
) -> list[bool]:
    """Re-label under a one-to-one constraint, greedily by match score.

    The matcher assigns each forecast its best outcome independently, so an
    outcome can be claimed many times. Under one-to-one only the strongest
    claimant keeps the credit. Ties break on ``forecast_id`` so the result does
    not depend on input order.
    """
    order = sorted(
        range(len(forecast_ids)),
        key=lambda i: (-scores[i], forecast_ids[i]),
    )
    taken: set[str] = set()
    kept = [False] * len(forecast_ids)
    for i in order:
        oid = outcome_ids[i]
        if not matched[i] or oid is None or oid in taken:
            continue
        taken.add(oid)
        kept[i] = True
    return kept


# ------------------------------------------------------------------- bootstrap
@dataclass(frozen=True)
class BootstrapCI:
    point: float
    low: float
    high: float
    reps: int
    block_length: int

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0.0 or self.high < 0.0

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "point": round(self.point, 9),
            "ci_low": round(self.low, 9),
            "ci_high": round(self.high, 9),
            "reps": self.reps,
            "block_length": self.block_length,
            "excludes_zero": self.excludes_zero,
        }


def moving_block_bootstrap(
    values: Sequence[float],
    block_length: int,
    reps: int = 4000,
    alpha: float = 0.05,
    seed: int = 20260829,
) -> BootstrapCI:
    """Percentile CI for the mean of a serially dependent fold sequence.

    Blocks of consecutive folds are resampled with replacement, so folds that
    share horizon days travel together instead of being counted as independent
    draws. This replaces the t-test that overlapping folds invalidate.
    """
    series = np.asarray(values, dtype=float)
    n = series.size
    if n == 0:
        raise ValueError("cannot bootstrap an empty series")
    block = max(MIN_BLOCK_LENGTH, min(block_length, n))
    n_blocks = math.ceil(n / block)
    starts_available = n - block + 1
    rng = np.random.default_rng(seed)
    means = np.empty(reps, dtype=float)
    for r in range(reps):
        starts = rng.integers(0, starts_available, size=n_blocks)
        drawn = np.concatenate([series[s : s + block] for s in starts])[:n]
        means[r] = drawn.mean()
    return BootstrapCI(
        point=float(series.mean()),
        low=float(np.quantile(means, alpha / 2)),
        high=float(np.quantile(means, 1 - alpha / 2)),
        reps=reps,
        block_length=block,
    )


def paired_block_bootstrap(
    left: Sequence[float],
    right: Sequence[float],
    block_length: int,
    reps: int = 4000,
    alpha: float = 0.05,
    seed: int = 20260829,
) -> BootstrapCI:
    """Block bootstrap on the paired per-fold difference ``left - right``."""
    if len(left) != len(right):
        raise ValueError("paired series must be the same length")
    diff = [a - b for a, b in zip(left, right, strict=True)]
    return moving_block_bootstrap(diff, block_length, reps=reps, alpha=alpha, seed=seed)
