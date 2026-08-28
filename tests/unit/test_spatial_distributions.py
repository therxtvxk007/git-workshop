"""Count-distribution invariants.

Synthetic only. Nothing here is a claim about real predictive performance.
"""

from __future__ import annotations

import math

import pytest

from pramaanx.models.spatial.distributions import (
    CountDistribution,
    CountFamily,
    DistributionValidationError,
    degenerate_distribution,
    hurdle_distribution,
    negative_binomial_distribution,
    poisson_distribution,
    zero_inflated_negative_binomial_distribution,
)

SUPPORT = range(0, 4000)


def _families() -> list[CountDistribution]:
    return [
        poisson_distribution(0.4),
        negative_binomial_distribution(0.4, 1.5),
        hurdle_distribution(0.9, 1.2, 0.8),
        zero_inflated_negative_binomial_distribution(0.6, 1.1, 0.9),
        degenerate_distribution(0),
    ]


@pytest.mark.parametrize("distribution", _families(), ids=lambda d: d.family.value)
def test_probability_mass_sums_to_one(distribution: CountDistribution) -> None:
    total = sum(distribution.pmf(k) for k in SUPPORT)
    assert total == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("distribution", _families(), ids=lambda d: d.family.value)
def test_reported_mean_matches_the_distribution(distribution: CountDistribution) -> None:
    empirical = sum(k * distribution.pmf(k) for k in SUPPORT)
    assert empirical == pytest.approx(distribution.mean, abs=1e-6)


@pytest.mark.parametrize("distribution", _families(), ids=lambda d: d.family.value)
def test_invariants_hold(distribution: CountDistribution) -> None:
    assert distribution.variance >= 0.0
    assert 0.0 <= distribution.zero_probability <= 1.0
    assert distribution.pmf(0) == pytest.approx(distribution.zero_probability, abs=1e-12)
    quantiles = [distribution.quantiles[f"q{level:g}"] for level in distribution.quantile_levels]
    assert quantiles == sorted(quantiles)


def test_hurdle_zero_probability_comes_only_from_the_hurdle() -> None:
    distribution = hurdle_distribution(0.9, 1.2, 0.8)
    assert distribution.zero_probability == pytest.approx(0.9)
    # The positive part is zero-truncated, so the mean is larger than the naive
    # (1 - p_zero) * mu. Getting this wrong is the double-counted-zero bug.
    assert distribution.mean > (1.0 - 0.9) * 1.2
    assert sum(distribution.pmf(k) for k in range(1, 4000)) == pytest.approx(0.1, abs=1e-9)


def test_zero_inflated_includes_sampling_zeros() -> None:
    distribution = zero_inflated_negative_binomial_distribution(0.6, 1.1, 0.9)
    # Reporting pi alone would understate how often the model predicts nothing.
    assert distribution.zero_probability > 0.6
    assert distribution.mean == pytest.approx(0.4 * 1.1)


def test_negative_binomial_is_overdispersed_relative_to_poisson() -> None:
    poisson = poisson_distribution(0.4)
    nb = negative_binomial_distribution(0.4, 1.5)
    assert nb.variance > poisson.variance
    assert nb.zero_probability > poisson.zero_probability


def test_dispersion_must_be_positive() -> None:
    with pytest.raises(DistributionValidationError):
        CountDistribution(
            family=CountFamily.NEGATIVE_BINOMIAL,
            mean=1.0,
            variance=2.0,
            zero_probability=0.3,
            dispersion=-1.0,
            parameters={"mu": 1.0, "alpha": 1.0},
        ).validate()


def test_a_mean_that_disagrees_with_the_pmf_is_refused() -> None:
    with pytest.raises(DistributionValidationError, match="disagrees with the distribution mean"):
        CountDistribution(
            family=CountFamily.POISSON,
            mean=99.0,
            variance=1.0,
            zero_probability=math.exp(-1.0),
            dispersion=None,
            parameters={"mu": 1.0},
        ).validate()


def test_zero_probability_outside_the_unit_interval_is_refused() -> None:
    with pytest.raises(DistributionValidationError, match="zero probability outside"):
        CountDistribution(
            family=CountFamily.POISSON,
            mean=1.0,
            variance=1.0,
            zero_probability=1.7,
            dispersion=None,
            parameters={"mu": 1.0},
        ).validate()
