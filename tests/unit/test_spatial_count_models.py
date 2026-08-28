"""Count-regression fitting: recovery, determinism and explicit failure.

Parameter recovery here is a statement about the estimators on data whose
generating process is known. It is not, and must not be read as, evidence of
real-world forecasting skill.
"""

from __future__ import annotations

import numpy as np
import pytest

from pramaanx.models.spatial.count_models import (
    FitStatus,
    HurdleRegression,
    NegativeBinomialRegression,
    PoissonRegression,
    ZeroInflatedNegativeBinomialRegression,
)
from pramaanx.models.spatial.distributions import CountFamily

TRUE_INTERCEPT = -1.2
TRUE_SLOPES = (0.8, -0.4)


def _design(n: int = 4000, seed: int = 20260115) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = np.column_stack([rng.normal(size=n), rng.normal(size=n)])
    mu = np.exp(TRUE_INTERCEPT + TRUE_SLOPES[0] * x[:, 0] + TRUE_SLOPES[1] * x[:, 1])
    return x, mu


def test_poisson_recovers_a_known_log_linear_rate() -> None:
    x, mu = _design()
    y = np.random.default_rng(7).poisson(mu)
    result = PoissonRegression().fit(x, y)
    assert result.status is FitStatus.CONVERGED
    assert result.coefficients[0] == pytest.approx(TRUE_INTERCEPT, abs=0.1)
    assert result.coefficients[1] == pytest.approx(TRUE_SLOPES[0], abs=0.1)
    assert result.coefficients[2] == pytest.approx(TRUE_SLOPES[1], abs=0.1)


def test_negative_binomial_keeps_dispersion_positive() -> None:
    x, mu = _design()
    rng = np.random.default_rng(11)
    alpha = 0.6
    shape = 1.0 / alpha
    y = rng.negative_binomial(shape, shape / (shape + mu))
    result = NegativeBinomialRegression().fit(x, y)
    assert result.status is FitStatus.CONVERGED
    assert result.dispersion is not None
    assert result.dispersion > 0.0
    assert result.dispersion == pytest.approx(alpha, rel=0.35)


def test_poisson_expected_counts_are_finite_and_non_negative() -> None:
    x, mu = _design(n=500)
    y = np.random.default_rng(3).poisson(mu)
    model = PoissonRegression()
    model.fit(x, y)
    for distribution in model.predict_distribution(x):
        assert np.isfinite(distribution.mean)
        assert distribution.mean >= 0.0


def test_hurdle_and_zero_inflated_produce_valid_distributions() -> None:
    x, mu = _design(n=2500)
    rng = np.random.default_rng(19)
    shape = 1.0 / 0.6
    structural = rng.random(x.shape[0]) < 0.35
    y = np.where(structural, 0, rng.negative_binomial(shape, shape / (shape + mu)))

    hurdle = HurdleRegression()
    hurdle.fit(x, y)
    zinb = ZeroInflatedNegativeBinomialRegression()
    zinb.fit(x, y)

    for model, family in (
        (hurdle, CountFamily.HURDLE_NEGATIVE_BINOMIAL),
        (zinb, CountFamily.ZERO_INFLATED_NEGATIVE_BINOMIAL),
    ):
        distributions = model.predict_distribution(x[:20])
        assert all(item.family is family for item in distributions)
        for item in distributions:
            assert sum(item.pmf(k) for k in range(0, 2000)) == pytest.approx(1.0, abs=1e-8)


def test_all_zero_targets_are_a_declared_failure_not_a_zero_rate() -> None:
    x, _ = _design(n=300)
    y = np.zeros(x.shape[0])
    model = PoissonRegression()
    result = model.fit(x, y)
    # Absence of observed events is not evidence that the rate is zero, and the
    # model must say which of the two it is looking at.
    assert result.status is FitStatus.DEGENERATE_DATA
    assert result.fallback_reason is not None
    assert "no positive counts" in result.fallback_reason


def test_more_parameters_than_rows_is_refused() -> None:
    rng = np.random.default_rng(5)
    x = rng.normal(size=(4, 10))
    y = np.asarray([0.0, 1.0, 0.0, 2.0])
    result = NegativeBinomialRegression().fit(x, y)
    assert result.status is FitStatus.DEGENERATE_DATA


def test_failed_fits_fall_back_rather_than_predicting_nothing() -> None:
    x, _ = _design(n=200)
    model = PoissonRegression()
    model.fit(x, np.zeros(x.shape[0]))
    distributions = model.predict_distribution(x[:5])
    assert len(distributions) == 5
    assert all(item.family is CountFamily.DEGENERATE for item in distributions)


@pytest.mark.parametrize(
    "factory",
    [
        PoissonRegression,
        NegativeBinomialRegression,
        HurdleRegression,
        ZeroInflatedNegativeBinomialRegression,
    ],
    ids=lambda f: f.__name__,
)
def test_fitting_is_deterministic(factory: type) -> None:
    x, mu = _design(n=800)
    y = np.random.default_rng(23).poisson(mu)
    first = factory().fit(x, y)
    second = factory().fit(x, y)
    assert np.array_equal(first.coefficients, second.coefficients)
    assert first.dispersion == second.dispersion
    assert first.status is second.status


def test_iteration_guard_is_reported_separately_from_convergence() -> None:
    x, mu = _design(n=1500)
    y = np.random.default_rng(29).poisson(mu)
    result = NegativeBinomialRegression(max_iter=1).fit(x, y)
    # One iteration cannot converge; the model must not claim that it did.
    assert result.status is not FitStatus.CONVERGED
    assert result.status in {FitStatus.MAX_ITERATIONS, FitStatus.NUMERICAL_FAILURE}
