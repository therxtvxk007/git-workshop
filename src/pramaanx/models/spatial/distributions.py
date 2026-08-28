"""Typed count-distribution summaries.

WP5 has to report more than an expected count. A district with an expected
0.4 events behaves very differently depending on whether that 0.4 comes from a
Poisson (zero probability 0.67) or from a zero-inflated negative binomial with
a structural-zero component (zero probability 0.9 and a much heavier tail), and
a downstream consumer that only ever sees the mean cannot tell those apart.

Every distribution here is closed under `validate()`: it is checked, not
assumed, that the reported mean equals the distribution's own mean, that the
variance is non-negative, that the zero probability lies in [0, 1] and that
quantiles are ordered. A summary that fails those checks is refused rather
than returned, because an invalid distribution flowing into an ensemble is
harder to notice than a missing one.

No extreme-value tail modelling and no neural density estimation live here;
those belong to later packages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Final

import numpy as np
from scipy.special import gammaln  # type: ignore[import-untyped]

__all__ = [
    "CountDistribution",
    "CountFamily",
    "DistributionValidationError",
    "degenerate_distribution",
    "hurdle_distribution",
    "negative_binomial_distribution",
    "poisson_distribution",
    "zero_inflated_negative_binomial_distribution",
]

#: Upper bound when summing a pmf to find quantiles. Counts in this problem are
#: district-level event tallies over a bounded horizon; a cap keeps a
#: pathological dispersion estimate from spinning forever.
_QUANTILE_CAP: Final[int] = 10_000

#: Tolerance for the "reported mean equals distribution mean" check. Loose
#: enough for float summation over a truncated support, tight enough that a
#: genuine parameterisation error fails.
_MEAN_TOLERANCE: Final[float] = 1e-6


class DistributionValidationError(ValueError):
    """A distribution summary violated one of its own invariants."""


class CountFamily(StrEnum):
    """Families this package can report.

    `DEGENERATE` exists for the global-fallback path: when a fit fails, the
    model still has to answer, and it answers with an explicit point mass
    rather than with a silently-invented Poisson.
    """

    POISSON = "poisson"
    NEGATIVE_BINOMIAL = "negative_binomial"
    HURDLE_NEGATIVE_BINOMIAL = "hurdle_negative_binomial"
    ZERO_INFLATED_NEGATIVE_BINOMIAL = "zero_inflated_negative_binomial"
    DEGENERATE = "degenerate"


def _nb_log_pmf(k: np.ndarray, mu: float, alpha: float) -> np.ndarray:
    """log P(Y = k) for NB2, computed in log space throughout.

    NB2 parameterises the variance as mu + alpha * mu^2, so `r = 1 / alpha` is
    the shape. Everything goes through `gammaln`; forming Gamma(r + k)
    directly overflows for the dispersions that thin district histories
    produce.
    """
    r = 1.0 / alpha
    return (
        gammaln(k + r)
        - gammaln(r)
        - gammaln(k + 1.0)
        + r * (math.log(r) - math.log(r + mu))
        + k * (math.log(mu) - math.log(r + mu))
    )


def _poisson_log_pmf(k: np.ndarray, mu: float) -> np.ndarray:
    return k * math.log(mu) - mu - gammaln(k + 1.0)


@dataclass(frozen=True)
class CountDistribution:
    """A validated summary of a predicted count distribution."""

    family: CountFamily
    mean: float
    variance: float
    zero_probability: float
    #: NB2 dispersion. `None` for families that do not have one (Poisson,
    #: degenerate) -- reporting 0.0 there would read as "equidispersed and
    #: measured" rather than "not applicable".
    dispersion: float | None
    parameters: dict[str, float]
    #: (lower, upper). `None` upper means unbounded above.
    support: tuple[int, int | None] = (0, None)
    quantile_levels: tuple[float, ...] = (0.5, 0.9, 0.95, 0.99)
    quantiles: dict[str, int] = field(default_factory=dict)

    def pmf(self, k: int) -> float:
        """P(Y = k). Defined for every family, including the fallback."""
        if k < 0:
            return 0.0
        array = np.asarray([float(k)])
        params = self.parameters

        if self.family is CountFamily.DEGENERATE:
            return 1.0 if k == int(params["point"]) else 0.0

        if self.family is CountFamily.POISSON:
            return float(np.exp(_poisson_log_pmf(array, params["mu"]))[0])

        if self.family is CountFamily.NEGATIVE_BINOMIAL:
            return float(np.exp(_nb_log_pmf(array, params["mu"], params["alpha"]))[0])

        if self.family is CountFamily.ZERO_INFLATED_NEGATIVE_BINOMIAL:
            pi = params["pi"]
            nb = float(np.exp(_nb_log_pmf(array, params["mu"], params["alpha"]))[0])
            # The structural zero is added ONLY at k = 0. Adding it anywhere
            # else is the classic way a ZINB stops summing to one.
            return pi + (1.0 - pi) * nb if k == 0 else (1.0 - pi) * nb

        if self.family is CountFamily.HURDLE_NEGATIVE_BINOMIAL:
            p_zero = params["p_zero"]
            if k == 0:
                # The zero probability comes from the hurdle component alone.
                return p_zero
            mu, alpha = params["mu_positive"], params["alpha"]
            nb_zero = float(np.exp(_nb_log_pmf(np.asarray([0.0]), mu, alpha))[0])
            nb_k = float(np.exp(_nb_log_pmf(array, mu, alpha))[0])
            # Zero-truncated: renormalise the positive part by (1 - f(0)) and
            # scale by (1 - p_zero). The zero mass is never counted twice.
            return (1.0 - p_zero) * nb_k / max(1.0 - nb_zero, 1e-300)

        raise DistributionValidationError(f"unhandled family: {self.family}")

    def validate(self) -> CountDistribution:
        """Check every invariant. Returns self so it can be chained."""
        if not math.isfinite(self.mean) or self.mean < 0.0:
            raise DistributionValidationError(
                f"mean must be finite and non-negative, got {self.mean}"
            )
        if not math.isfinite(self.variance) or self.variance < 0.0:
            raise DistributionValidationError(
                f"variance must be finite and non-negative, got {self.variance}"
            )
        if not 0.0 <= self.zero_probability <= 1.0:
            raise DistributionValidationError(
                f"zero probability outside [0, 1]: {self.zero_probability}"
            )
        if self.dispersion is not None and self.dispersion <= 0.0:
            raise DistributionValidationError(
                f"dispersion must be strictly positive, got {self.dispersion}"
            )

        computed_zero = self.pmf(0)
        if abs(computed_zero - self.zero_probability) > 1e-9:
            raise DistributionValidationError(
                f"reported zero probability {self.zero_probability} disagrees with the pmf {computed_zero}"
            )

        # The mean the caller reports must be the mean this distribution
        # actually has. This is the check that catches a hurdle model whose
        # positive component was not truncated.
        implied = self._implied_mean()
        if abs(implied - self.mean) > max(_MEAN_TOLERANCE, _MEAN_TOLERANCE * abs(self.mean)):
            raise DistributionValidationError(
                f"reported mean {self.mean} disagrees with the distribution mean {implied}"
            )

        ordered = [
            self.quantiles[self._q_key(level)]
            for level in self.quantile_levels
            if self._q_key(level) in self.quantiles
        ]
        if any(b < a for a, b in pairwise(ordered)):
            raise DistributionValidationError(f"quantiles are not monotone: {self.quantiles}")
        return self

    def _implied_mean(self) -> float:
        params = self.parameters
        if self.family is CountFamily.DEGENERATE:
            return float(params["point"])
        if self.family is CountFamily.POISSON:
            return float(params["mu"])
        if self.family is CountFamily.NEGATIVE_BINOMIAL:
            return float(params["mu"])
        if self.family is CountFamily.ZERO_INFLATED_NEGATIVE_BINOMIAL:
            return float((1.0 - params["pi"]) * params["mu"])
        if self.family is CountFamily.HURDLE_NEGATIVE_BINOMIAL:
            mu, alpha = params["mu_positive"], params["alpha"]
            nb_zero = float(np.exp(_nb_log_pmf(np.asarray([0.0]), mu, alpha))[0])
            return float((1.0 - params["p_zero"]) * mu / max(1.0 - nb_zero, 1e-300))
        raise DistributionValidationError(f"unhandled family: {self.family}")

    @staticmethod
    def _q_key(level: float) -> str:
        return f"q{level:g}"


def _quantiles(distribution: CountDistribution) -> dict[str, int]:
    """Smallest k with cumulative mass >= level, by forward summation.

    Summation rather than a closed form because the hurdle and zero-inflated
    families have no standard inverse-cdf, and a mixed strategy across families
    would make the quantiles incomparable between baselines.
    """
    levels = sorted(distribution.quantile_levels)
    out: dict[str, int] = {}
    cumulative = 0.0
    index = 0
    for k in range(_QUANTILE_CAP + 1):
        cumulative += distribution.pmf(k)
        while index < len(levels) and cumulative >= levels[index] - 1e-12:
            out[CountDistribution._q_key(levels[index])] = k
            index += 1
        if index >= len(levels):
            break
    # A distribution whose mass did not reach the level inside the cap reports
    # the cap, flagged by the caller rather than silently reported as exact.
    for level in levels[index:]:
        out[CountDistribution._q_key(level)] = _QUANTILE_CAP
    return out


def _finalise(distribution: CountDistribution) -> CountDistribution:
    quantiles = _quantiles(distribution)
    return CountDistribution(
        family=distribution.family,
        mean=distribution.mean,
        variance=distribution.variance,
        zero_probability=distribution.zero_probability,
        dispersion=distribution.dispersion,
        parameters=distribution.parameters,
        support=distribution.support,
        quantile_levels=distribution.quantile_levels,
        quantiles=quantiles,
    ).validate()


def poisson_distribution(mu: float) -> CountDistribution:
    mu = float(max(mu, 1e-12))
    return _finalise(
        CountDistribution(
            family=CountFamily.POISSON,
            mean=mu,
            variance=mu,
            zero_probability=math.exp(-mu),
            dispersion=None,
            parameters={"mu": mu},
        )
    )


def negative_binomial_distribution(mu: float, alpha: float) -> CountDistribution:
    mu = float(max(mu, 1e-12))
    alpha = float(max(alpha, 1e-9))
    zero = float(np.exp(_nb_log_pmf(np.asarray([0.0]), mu, alpha))[0])
    return _finalise(
        CountDistribution(
            family=CountFamily.NEGATIVE_BINOMIAL,
            mean=mu,
            variance=mu + alpha * mu * mu,
            zero_probability=zero,
            dispersion=alpha,
            parameters={"mu": mu, "alpha": alpha},
        )
    )


def hurdle_distribution(p_zero: float, mu_positive: float, alpha: float) -> CountDistribution:
    """Hurdle NB.

    `p_zero` is the whole of P(Y = 0) and comes from the binary component.
    `mu_positive` is the mean of the UNtruncated NB whose zero-truncation
    supplies P(Y = k | Y > 0). The realised mean is therefore
    (1 - p_zero) * mu_positive / (1 - f(0)), not (1 - p_zero) * mu_positive.
    """
    p_zero = float(min(max(p_zero, 0.0), 1.0))
    mu_positive = float(max(mu_positive, 1e-12))
    alpha = float(max(alpha, 1e-9))

    nb_zero = float(np.exp(_nb_log_pmf(np.asarray([0.0]), mu_positive, alpha))[0])
    truncation = max(1.0 - nb_zero, 1e-300)
    mean = (1.0 - p_zero) * mu_positive / truncation
    nb_variance = mu_positive + alpha * mu_positive * mu_positive
    second_moment_positive = (nb_variance + mu_positive * mu_positive) / truncation
    variance = max((1.0 - p_zero) * second_moment_positive - mean * mean, 0.0)

    return _finalise(
        CountDistribution(
            family=CountFamily.HURDLE_NEGATIVE_BINOMIAL,
            mean=mean,
            variance=variance,
            zero_probability=p_zero,
            dispersion=alpha,
            parameters={"p_zero": p_zero, "mu_positive": mu_positive, "alpha": alpha},
        )
    )


def zero_inflated_negative_binomial_distribution(
    pi: float, mu: float, alpha: float
) -> CountDistribution:
    """ZINB.

    `pi` is the STRUCTURAL zero probability. Total P(Y = 0) is
    pi + (1 - pi) * f_NB(0): the sampling zeros the NB itself produces are
    still there, and a model that reports `pi` as the zero probability is
    understating how often it predicts nothing.
    """
    pi = float(min(max(pi, 0.0), 1.0))
    mu = float(max(mu, 1e-12))
    alpha = float(max(alpha, 1e-9))

    nb_zero = float(np.exp(_nb_log_pmf(np.asarray([0.0]), mu, alpha))[0])
    return _finalise(
        CountDistribution(
            family=CountFamily.ZERO_INFLATED_NEGATIVE_BINOMIAL,
            mean=(1.0 - pi) * mu,
            variance=(1.0 - pi) * mu * (1.0 + mu * (alpha + pi)),
            zero_probability=pi + (1.0 - pi) * nb_zero,
            dispersion=alpha,
            parameters={"pi": pi, "mu": mu, "alpha": alpha},
        )
    )


def degenerate_distribution(point: int = 0) -> CountDistribution:
    """The explicit fallback. Used only when a fit has failed and said so."""
    return _finalise(
        CountDistribution(
            family=CountFamily.DEGENERATE,
            mean=float(point),
            variance=0.0,
            zero_probability=1.0 if point == 0 else 0.0,
            dispersion=None,
            parameters={"point": float(point)},
        )
    )
