"""Paired resampling statistics for benchmark comparisons.

Two design choices run through this module.

*Pairing, wherever units can be paired.* Two models scored on the same district
months are not two independent samples; they are one sample scored twice. An
unpaired test on paired data throws away the pairing and answers a question
nobody asked -- typically producing a wider interval that then gets reported as
"no significant difference", or a narrower one that overstates the case. Every
function here takes ``control`` and ``challenger`` as aligned sequences and
works on their differences.

*Blocks, for temporally dependent units.* Conflict forecasts made in adjacent
months are correlated. An i.i.d. bootstrap over such units resamples away that
dependence and reports an interval far too narrow. :func:`block_bootstrap_ci`
resamples contiguous blocks instead, preserving local dependence.

Every resampling function takes a string ``seed`` and derives its generator from
the content of that string, so a reported interval can be recomputed exactly
without anyone having recorded an integer that came from a clock.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

from pramaanx.hashing import hash_object

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_RESAMPLES = 10_000
_SEED_MODULUS = 2**32
_DEGENERATE_SPREAD = 1e-12
"""Below this, relative to the data, a spread is floating-point noise, not variation."""


class StatisticsError(ValueError):
    """A comparison was asked for that the data cannot support."""


def derive_seed(*parts: object) -> int:
    """A reproducible 32-bit seed from the content that identifies a resampling.

    Deriving the seed from the run identities means the same comparison always
    draws the same resamples: a confidence interval becomes a function of its
    inputs rather than a number that shifts every time it is recomputed.
    """
    digest = hash_object(list(parts)).removeprefix("sha256:")
    return int(digest[:8], 16) % _SEED_MODULUS


def _generator(seed: int | str) -> np.random.Generator:
    return np.random.default_rng(seed if isinstance(seed, int) else derive_seed(seed))


def _paired_arrays(
    control: Sequence[float],
    challenger: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    if len(control) != len(challenger):
        raise StatisticsError(
            f"paired statistics need aligned sequences: {len(control)} control values "
            f"against {len(challenger)} challenger values"
        )
    if not control:
        raise StatisticsError("paired statistics need at least one unit")
    return np.asarray(control, dtype=float), np.asarray(challenger, dtype=float)


class Summary(NamedTuple):
    """Mean, median and standard deviation of a sample."""

    mean: float
    median: float
    std: float
    size: int
    """Named ``size`` rather than ``count``: ``tuple.count`` is already a method."""


def summarise(values: Sequence[float]) -> Summary:
    """Descriptive statistics, with the sample standard deviation.

    ``ddof=1``: these are samples over seeds or units, not populations, and the
    population form understates spread exactly when the seed count is smallest.
    """
    if not values:
        raise StatisticsError("cannot summarise an empty sample")
    array = np.asarray(values, dtype=float)
    std = float(np.std(array, ddof=1)) if array.size > 1 else 0.0
    return Summary(
        mean=float(np.mean(array)),
        median=float(np.median(array)),
        std=std,
        size=int(array.size),
    )


class Interval(NamedTuple):
    """A confidence interval on the paired difference, plus its point estimate."""

    lower: float
    upper: float
    point: float
    alpha: float
    resamples: int
    method: str

    @property
    def excludes_zero(self) -> bool:
        """Whether the interval rules out "no difference" in either direction."""
        return self.lower > 0.0 or self.upper < 0.0

    @property
    def excludes_no_improvement(self) -> bool:
        """Whether the whole interval lies strictly on the improvement side.

        The gate for "exceeded". An interval whose lower bound is zero or below
        is consistent with the challenger being no better, however large the
        point estimate looks.
        """
        return self.lower > 0.0


def paired_bootstrap_ci(
    control: Sequence[float],
    challenger: Sequence[float],
    *,
    seed: int | str,
    resamples: int = DEFAULT_RESAMPLES,
    alpha: float = 0.05,
    higher_is_better: bool = True,
) -> Interval:
    """Percentile bootstrap interval for the mean paired improvement.

    Units are resampled with replacement *as pairs*, so the correlation between a
    control and a challenger score on the same unit is preserved. The returned
    interval is on improvement -- positive is better, whichever direction the
    metric runs.
    """
    if resamples < 1:
        raise StatisticsError("resamples must be positive")
    control_array, challenger_array = _paired_arrays(control, challenger)
    differences = (
        challenger_array - control_array if higher_is_better else control_array - challenger_array
    )
    rng = _generator(seed)
    size = differences.size
    indices = rng.integers(0, size, size=(resamples, size))
    means = differences[indices].mean(axis=1)
    lower, upper = np.quantile(means, [alpha / 2.0, 1.0 - alpha / 2.0])
    return Interval(
        lower=float(lower),
        upper=float(upper),
        point=float(differences.mean()),
        alpha=alpha,
        resamples=resamples,
        method="paired_percentile_bootstrap",
    )


def block_bootstrap_ci(
    control: Sequence[float],
    challenger: Sequence[float],
    *,
    seed: int | str,
    block_length: int,
    resamples: int = DEFAULT_RESAMPLES,
    alpha: float = 0.05,
    higher_is_better: bool = True,
) -> Interval:
    """Moving-block bootstrap for units that are ordered in time.

    Blocks of ``block_length`` consecutive differences are drawn with
    replacement and concatenated. Neighbouring units stay together, so the
    interval reflects dependence the i.i.d. bootstrap would destroy.

    Callers must pass the units *in temporal order*; the function cannot detect
    that they were shuffled, and a shuffled input silently degrades to an
    ordinary bootstrap.
    """
    if block_length < 1:
        raise StatisticsError("block_length must be at least 1")
    control_array, challenger_array = _paired_arrays(control, challenger)
    differences = (
        challenger_array - control_array if higher_is_better else control_array - challenger_array
    )
    size = differences.size
    if block_length > size:
        raise StatisticsError(f"block_length {block_length} exceeds the {size} available units")
    rng = _generator(seed)
    starts_available = size - block_length + 1
    blocks_needed = math.ceil(size / block_length)
    starts = rng.integers(0, starts_available, size=(resamples, blocks_needed))
    offsets = np.arange(block_length)
    # (resamples, blocks_needed, block_length) -> flatten and clip to the sample length.
    sampled = differences[starts[:, :, None] + offsets[None, None, :]]
    means = sampled.reshape(resamples, -1)[:, :size].mean(axis=1)
    lower, upper = np.quantile(means, [alpha / 2.0, 1.0 - alpha / 2.0])
    return Interval(
        lower=float(lower),
        upper=float(upper),
        point=float(differences.mean()),
        alpha=alpha,
        resamples=resamples,
        method=f"moving_block_bootstrap(block_length={block_length})",
    )


class TestResult(NamedTuple):
    p_value: float
    observed: float
    resamples: int
    alternative: str
    method: str


def paired_permutation_test(
    control: Sequence[float],
    challenger: Sequence[float],
    *,
    seed: int | str,
    resamples: int = DEFAULT_RESAMPLES,
    alternative: str = "greater",
    higher_is_better: bool = True,
) -> TestResult:
    """Paired randomisation test on the mean improvement.

    Under the null hypothesis that the two systems are exchangeable on each unit,
    flipping the sign of any subset of the paired differences is equally likely.
    The test draws random sign flips and asks how often the resulting mean is at
    least as extreme as the observed one.

    The p-value uses the ``(hits + 1) / (resamples + 1)`` form. A permutation
    p-value of exactly zero is not attainable from a finite number of draws, and
    reporting one claims more resolution than the resampling provides.
    """
    if alternative not in {"greater", "less", "two-sided"}:
        raise StatisticsError(f"unknown alternative {alternative!r}")
    control_array, challenger_array = _paired_arrays(control, challenger)
    differences = (
        challenger_array - control_array if higher_is_better else control_array - challenger_array
    )
    observed = float(differences.mean())
    rng = _generator(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(resamples, differences.size))
    permuted = (signs * differences).mean(axis=1)
    if alternative == "greater":
        hits = int(np.sum(permuted >= observed))
    elif alternative == "less":
        hits = int(np.sum(permuted <= observed))
    else:
        hits = int(np.sum(np.abs(permuted) >= abs(observed)))
    return TestResult(
        p_value=(hits + 1) / (resamples + 1),
        observed=observed,
        resamples=resamples,
        alternative=alternative,
        method="paired_sign_permutation",
    )


def paired_effect_size(
    control: Sequence[float],
    challenger: Sequence[float],
    *,
    higher_is_better: bool = True,
) -> float | None:
    """Cohen's d for paired samples: mean difference over its standard deviation.

    Returns ``None``, not a number, when the effect size is undefined: fewer than
    two pairs, or a difference that is constant across every pair. A constant
    non-zero difference has zero spread, and d is unbounded there -- reporting
    0.0 would read as "no effect" and reporting a huge value would be an artefact
    of floating-point noise in the denominator. "Undefined" is the true answer,
    and it is also the only one that survives canonical JSON, which forbids
    infinity.

    The degenerate case is detected relative to the size of the differences
    rather than against exact zero, because a constant difference computed in
    floating point has a standard deviation near 1e-17 rather than at it.
    """
    control_array, challenger_array = _paired_arrays(control, challenger)
    differences = (
        challenger_array - control_array if higher_is_better else control_array - challenger_array
    )
    if differences.size < 2:
        return None
    spread = float(np.std(differences, ddof=1))
    scale = float(np.max(np.abs(differences))) if differences.size else 0.0
    if spread <= _DEGENERATE_SPREAD * max(scale, 1.0):
        return None
    return float(np.mean(differences)) / spread
