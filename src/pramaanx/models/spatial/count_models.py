"""Maximum-likelihood count regressions: Poisson, NB2, hurdle and ZINB.

These are the count arm of the WP5 baseline ladder. They are deliberately
written against NumPy and SciPy only -- no LightGBM, CatBoost or XGBoost is
introduced by this package. Boosted count challengers are recorded as future
candidates in docs/integration/wp05_spatial.md instead.

Three things matter more here than raw likelihood:

* **Every fit reports how it ended.** `FitStatus` distinguishes convergence
  from hitting the iteration guard from a numerical failure from degenerate
  data. A silent optimiser failure that returns its starting point looks
  exactly like a fitted model that predicts the global mean, and the two must
  never be confused when the ensemble later weighs these baselines.
* **Failure has an explicit fallback, not a zero.** A district with no history
  is not a district with no risk. When a fit fails, the model falls back to a
  stated global rate and records that it did.
* **Fitting is deterministic.** Fixed initialisation, no random restarts, no
  stochastic solver. Re-running on identical input reproduces identical
  coefficients bit for bit, which is what makes the artefact hash meaningful.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]
from scipy.special import gammaln, logsumexp  # type: ignore[import-untyped]

from pramaanx.models.spatial.distributions import (
    CountDistribution,
    degenerate_distribution,
    hurdle_distribution,
    negative_binomial_distribution,
    poisson_distribution,
    zero_inflated_negative_binomial_distribution,
)

__all__ = [
    "FitResult",
    "FitStatus",
    "HurdleRegression",
    "NegativeBinomialRegression",
    "PoissonRegression",
    "ZeroInflatedNegativeBinomialRegression",
]

#: The linear predictor is clipped before exponentiation. Without this an
#: early optimiser step on a sparse design overflows to inf, the likelihood
#: becomes nan, and the solver reports a "converged" fit at the starting point.
_ETA_CLIP: Final[float] = 30.0

#: Iteration guard. Reaching it is reported, never treated as convergence.
_MAX_ITER: Final[int] = 500

_LOG_ALPHA_BOUNDS: Final[tuple[float, float]] = (-9.0, 6.0)


class FitStatus(StrEnum):
    """How a fit ended. Reported on every prediction."""

    CONVERGED = "converged"
    #: The optimiser ran out of iterations. The coefficients may still be
    #: usable, but the caller is told they were not certified.
    MAX_ITERATIONS = "max_iterations"
    #: The likelihood went non-finite, or the solver raised.
    NUMERICAL_FAILURE = "numerical_failure"
    #: Not enough signal to identify the model -- e.g. an all-zero target, or
    #: fewer positive observations than parameters.
    DEGENERATE_DATA = "degenerate_data"
    #: The fit failed and the declared global fallback is being served.
    GLOBAL_FALLBACK = "global_fallback"


@dataclass(frozen=True)
class FitResult:
    """Everything a downstream consumer needs to judge a fitted count model."""

    status: FitStatus
    coefficients: np.ndarray
    dispersion: float | None
    log_likelihood: float
    iterations: int
    #: Set when the model fell back; names the rate that was served instead.
    fallback_reason: str | None = None

    @property
    def converged(self) -> bool:
        return self.status is FitStatus.CONVERGED


def _linear_predictor(x: np.ndarray, beta: np.ndarray) -> np.ndarray:
    return np.clip(x @ beta, -_ETA_CLIP, _ETA_CLIP)


def _design(x: np.ndarray) -> np.ndarray:
    """Prepend an intercept column. Kept explicit so the coefficient vector's
    layout is the same across all four families."""
    return np.hstack([np.ones((x.shape[0], 1), dtype=float), np.asarray(x, dtype=float)])


def _initial_beta(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Deterministic start: zero slopes, intercept at the log of the mean.

    Starting from the intercept-only MLE rather than from all zeros keeps the
    optimiser away from the flat region where mu is 1 for every row.
    """
    beta = np.zeros(x.shape[1], dtype=float)
    mean = float(np.mean(y)) if y.size else 0.0
    beta[0] = math.log(max(mean, 1e-6))
    return beta


class _BaseCountRegression:
    """Shared fitting machinery. Subclasses supply the negative log-likelihood."""

    family_name = "base"

    def __init__(self, *, max_iter: int = _MAX_ITER) -> None:
        self.max_iter = max_iter
        self.result: FitResult | None = None
        self._global_rate: float = 0.0

    # -- to be provided by subclasses ------------------------------------
    def _negative_log_likelihood(self, params: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
        raise NotImplementedError

    def _initial_params(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def _bounds(self, n_features: int) -> list[tuple[float | None, float | None]] | None:
        # Unconstrained by default; families with a dispersion or inflation
        # parameter override this to keep those parameters in their domain.
        del n_features
        return None

    def _unpack(self, params: np.ndarray) -> tuple[np.ndarray, float | None]:
        raise NotImplementedError

    # -- fitting ----------------------------------------------------------
    def fit(self, x: np.ndarray, y: np.ndarray) -> FitResult:
        design = _design(x)
        y = np.asarray(y, dtype=float)
        # The global rate is computed before any fitting, so the fallback is
        # available even when the optimiser never produces a usable point.
        self._global_rate = float(np.mean(y)) if y.size else 0.0

        degenerate = self._degeneracy_reason(design, y)
        if degenerate is not None:
            self.result = FitResult(
                status=FitStatus.DEGENERATE_DATA,
                coefficients=_initial_beta(design, y),
                dispersion=None,
                log_likelihood=float("nan"),
                iterations=0,
                fallback_reason=degenerate,
            )
            return self.result

        start = self._initial_params(design, y)
        try:
            optimised = minimize(
                self._negative_log_likelihood,
                start,
                args=(design, y),
                method="L-BFGS-B",
                bounds=self._bounds(design.shape[1]),
                options={"maxiter": self.max_iter, "ftol": 1e-10, "gtol": 1e-8},
            )
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as exc:
            self.result = FitResult(
                status=FitStatus.NUMERICAL_FAILURE,
                coefficients=_initial_beta(design, y),
                dispersion=None,
                log_likelihood=float("nan"),
                iterations=0,
                fallback_reason=f"solver raised {type(exc).__name__}: {exc}",
            )
            return self.result

        value = float(optimised.fun)
        if not math.isfinite(value) or not np.all(np.isfinite(optimised.x)):
            self.result = FitResult(
                status=FitStatus.NUMERICAL_FAILURE,
                coefficients=_initial_beta(design, y),
                dispersion=None,
                log_likelihood=float("nan"),
                iterations=int(optimised.nit),
                fallback_reason="non-finite objective or parameters at the optimum",
            )
            return self.result

        beta, dispersion = self._unpack(optimised.x)
        # `success` false with nit at the cap is the iteration guard; anything
        # else false is a genuine numerical problem, and they are reported
        # differently because only one of them is worth re-running longer.
        if optimised.success:
            status = FitStatus.CONVERGED
        elif int(optimised.nit) >= self.max_iter:
            status = FitStatus.MAX_ITERATIONS
        else:
            status = FitStatus.NUMERICAL_FAILURE

        self.result = FitResult(
            status=status,
            coefficients=beta,
            dispersion=dispersion,
            log_likelihood=-value,
            iterations=int(optimised.nit),
            fallback_reason=None,
        )
        return self.result

    def _degeneracy_reason(self, design: np.ndarray, y: np.ndarray) -> str | None:
        if y.size == 0:
            return "no training rows"
        if not np.any(y > 0):
            # Every target is zero. A fitted rate here would be exactly zero,
            # which this package refuses to assert: absence of observed events
            # is not evidence that the rate is zero.
            return "no positive counts in the training window"
        if y.size < design.shape[1] + 1:
            return f"fewer rows ({y.size}) than parameters ({design.shape[1] + 1})"
        return None

    # -- prediction -------------------------------------------------------
    def predict_distribution(self, x: np.ndarray) -> list[CountDistribution]:
        raise NotImplementedError

    def _fallback_distributions(self, n_rows: int) -> list[CountDistribution]:
        """Serve the global rate, or a point mass at zero if even that is
        unavailable. Never silently returns a fitted-looking answer."""
        if self._global_rate > 0.0:
            return [poisson_distribution(self._global_rate) for _ in range(n_rows)]
        return [degenerate_distribution(0) for _ in range(n_rows)]

    def _should_fall_back(self) -> bool:
        return self.result is None or self.result.status in {
            FitStatus.DEGENERATE_DATA,
            FitStatus.NUMERICAL_FAILURE,
        }


class PoissonRegression(_BaseCountRegression):
    family_name = "poisson"

    def _initial_params(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return _initial_beta(x, y)

    def _unpack(self, params: np.ndarray) -> tuple[np.ndarray, float | None]:
        return params, None

    def _negative_log_likelihood(self, params: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
        eta = _linear_predictor(x, params)
        mu = np.exp(eta)
        # Written as y*eta - mu rather than y*log(mu) - mu: identical in exact
        # arithmetic, but avoids log(0) when a row's rate underflows.
        return float(-np.sum(y * eta - mu - gammaln(y + 1.0)))

    def predict_distribution(self, x: np.ndarray) -> list[CountDistribution]:
        rows = np.asarray(x, dtype=float).shape[0]
        if self._should_fall_back():
            return self._fallback_distributions(rows)
        assert self.result is not None
        mu = np.exp(_linear_predictor(_design(x), self.result.coefficients))
        return [poisson_distribution(float(value)) for value in mu]


class NegativeBinomialRegression(_BaseCountRegression):
    """NB2: Var(Y) = mu + alpha * mu^2, alpha > 0."""

    family_name = "negative_binomial"

    def _initial_params(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        # Dispersion is optimised on the log scale, which enforces alpha > 0
        # structurally rather than by a penalty the optimiser can walk through.
        return np.append(_initial_beta(x, y), 0.0)

    def _bounds(self, n_features: int) -> list[tuple[float | None, float | None]]:
        return [(None, None)] * n_features + [_LOG_ALPHA_BOUNDS]

    def _unpack(self, params: np.ndarray) -> tuple[np.ndarray, float | None]:
        return params[:-1], float(math.exp(params[-1]))

    def _negative_log_likelihood(self, params: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
        beta, log_alpha = params[:-1], params[-1]
        alpha = math.exp(min(max(log_alpha, _LOG_ALPHA_BOUNDS[0]), _LOG_ALPHA_BOUNDS[1]))
        r = 1.0 / alpha
        mu = np.exp(_linear_predictor(x, beta))
        log_r_mu = np.log(r + mu)
        total = np.sum(
            gammaln(y + r)
            - gammaln(r)
            - gammaln(y + 1.0)
            + r * (math.log(r) - log_r_mu)
            + y * (np.log(mu) - log_r_mu)
        )
        return float(-total) if math.isfinite(total) else float("inf")

    def predict_distribution(self, x: np.ndarray) -> list[CountDistribution]:
        rows = np.asarray(x, dtype=float).shape[0]
        if self._should_fall_back():
            return self._fallback_distributions(rows)
        assert self.result is not None and self.result.dispersion is not None
        mu = np.exp(_linear_predictor(_design(x), self.result.coefficients))
        alpha = self.result.dispersion
        return [negative_binomial_distribution(float(value), alpha) for value in mu]


class HurdleRegression(_BaseCountRegression):
    """Two independent components: a logistic hurdle and a zero-truncated NB.

    They are fitted separately because the hurdle likelihood factorises
    exactly: the binary part uses every row, the count part uses only the rows
    that crossed the hurdle. Fitting them jointly would give identical
    estimates at more cost and with worse conditioning.
    """

    family_name = "hurdle_negative_binomial"

    def __init__(self, *, max_iter: int = _MAX_ITER) -> None:
        super().__init__(max_iter=max_iter)
        self.zero_result: FitResult | None = None
        self.count_result: FitResult | None = None
        self._positive_rate: float = 0.0

    def fit(self, x: np.ndarray, y: np.ndarray) -> FitResult:
        design = _design(x)
        y = np.asarray(y, dtype=float)
        self._global_rate = float(np.mean(y)) if y.size else 0.0
        positive = y > 0
        self._positive_rate = float(np.mean(positive)) if y.size else 0.0

        if y.size == 0 or not np.any(positive):
            self.result = FitResult(
                status=FitStatus.DEGENERATE_DATA,
                coefficients=np.zeros(design.shape[1]),
                dispersion=None,
                log_likelihood=float("nan"),
                iterations=0,
                fallback_reason="no positive counts, so the hurdle is never crossed in training",
            )
            return self.result

        self.zero_result = self._fit_hurdle(design, positive.astype(float))
        # The count component sees ONLY the crossed rows. Feeding it the zeros
        # as well is the mistake that turns a hurdle into a badly-fitted NB.
        self.count_result = self._fit_truncated(design[positive], y[positive])

        statuses = {self.zero_result.status, self.count_result.status}
        if statuses & {FitStatus.NUMERICAL_FAILURE, FitStatus.DEGENERATE_DATA}:
            status = FitStatus.NUMERICAL_FAILURE
        elif FitStatus.MAX_ITERATIONS in statuses:
            status = FitStatus.MAX_ITERATIONS
        else:
            status = FitStatus.CONVERGED

        self.result = FitResult(
            status=status,
            coefficients=self.zero_result.coefficients,
            dispersion=self.count_result.dispersion,
            log_likelihood=self.zero_result.log_likelihood + self.count_result.log_likelihood,
            iterations=self.zero_result.iterations + self.count_result.iterations,
        )
        return self.result

    def _fit_hurdle(self, design: np.ndarray, crossed: np.ndarray) -> FitResult:
        def nll(beta: np.ndarray, x: np.ndarray, target: np.ndarray) -> float:
            eta = np.clip(x @ beta, -_ETA_CLIP, _ETA_CLIP)
            # log(1 + exp(eta)) via logaddexp: stable in both tails.
            return float(-np.sum(target * eta - np.logaddexp(0.0, eta)))

        start = np.zeros(design.shape[1])
        rate = float(np.mean(crossed))
        start[0] = math.log(max(rate, 1e-6) / max(1.0 - rate, 1e-6))
        optimised = minimize(
            nll,
            start,
            args=(design, crossed),
            method="L-BFGS-B",
            options={"maxiter": self.max_iter, "ftol": 1e-10},
        )
        status = (
            FitStatus.CONVERGED
            if optimised.success
            else FitStatus.MAX_ITERATIONS
            if int(optimised.nit) >= self.max_iter
            else FitStatus.NUMERICAL_FAILURE
        )
        return FitResult(status, optimised.x, None, -float(optimised.fun), int(optimised.nit))

    def _fit_truncated(self, design: np.ndarray, y: np.ndarray) -> FitResult:
        def nll(params: np.ndarray, x: np.ndarray, target: np.ndarray) -> float:
            beta, log_alpha = params[:-1], params[-1]
            alpha = math.exp(min(max(log_alpha, _LOG_ALPHA_BOUNDS[0]), _LOG_ALPHA_BOUNDS[1]))
            r = 1.0 / alpha
            mu = np.exp(_linear_predictor(x, beta))
            log_r_mu = np.log(r + mu)
            log_pmf = (
                gammaln(target + r)
                - gammaln(r)
                - gammaln(target + 1.0)
                + r * (math.log(r) - log_r_mu)
                + target * (np.log(mu) - log_r_mu)
            )
            log_zero = r * (math.log(r) - log_r_mu)
            # Subtracting log(1 - f(0)) is what makes this zero-TRUNCATED. Its
            # absence is exactly the double-counted zero mass the brief warns
            # about, and it is computed via log1p(-exp(.)) to stay stable when
            # f(0) approaches one.
            log_survive = np.log1p(-np.exp(np.minimum(log_zero, -1e-12)))
            total = np.sum(log_pmf - log_survive)
            return float(-total) if math.isfinite(total) else float("inf")

        start = np.append(_initial_beta(design, y), 0.0)
        bounds = [(None, None)] * design.shape[1] + [_LOG_ALPHA_BOUNDS]
        if y.size < design.shape[1] + 1:
            return FitResult(
                FitStatus.DEGENERATE_DATA,
                start[:-1],
                None,
                float("nan"),
                0,
                "fewer positive rows than count-component parameters",
            )
        optimised = minimize(
            nll,
            start,
            args=(design, y),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": self.max_iter, "ftol": 1e-10},
        )
        if not math.isfinite(float(optimised.fun)):
            return FitResult(
                FitStatus.NUMERICAL_FAILURE,
                start[:-1],
                None,
                float("nan"),
                int(optimised.nit),
                "non-finite truncated likelihood",
            )
        status = (
            FitStatus.CONVERGED
            if optimised.success
            else FitStatus.MAX_ITERATIONS
            if int(optimised.nit) >= self.max_iter
            else FitStatus.NUMERICAL_FAILURE
        )
        return FitResult(
            status,
            optimised.x[:-1],
            float(math.exp(optimised.x[-1])),
            -float(optimised.fun),
            int(optimised.nit),
        )

    def predict_distribution(self, x: np.ndarray) -> list[CountDistribution]:
        rows = np.asarray(x, dtype=float).shape[0]
        if self._should_fall_back() or self.zero_result is None or self.count_result is None:
            return self._fallback_distributions(rows)
        design = _design(x)
        eta = np.clip(design @ self.zero_result.coefficients, -_ETA_CLIP, _ETA_CLIP)
        cross_probability = 1.0 / (1.0 + np.exp(-eta))
        mu = np.exp(_linear_predictor(design, self.count_result.coefficients))
        alpha = self.count_result.dispersion or 1e-6
        return [
            hurdle_distribution(float(1.0 - p), float(m), alpha)
            for p, m in zip(cross_probability, mu, strict=True)
        ]


class ZeroInflatedNegativeBinomialRegression(_BaseCountRegression):
    """ZINB with a constant structural-zero probability.

    The inflation probability is a single parameter rather than a second
    regression: with district histories this sparse, an inflation model with
    its own covariates is not identified, and an unidentified component that
    still reports a number is worse than a simpler one that is honest.
    Covariate-dependent inflation is recorded as a future challenger.
    """

    family_name = "zero_inflated_negative_binomial"

    def _initial_params(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        # Start the inflation at the excess zeros a Poisson would not explain.
        mean = max(float(np.mean(y)), 1e-6)
        observed_zero = float(np.mean(y == 0))
        excess = max(observed_zero - math.exp(-mean), 1e-3)
        logit_pi = math.log(excess / max(1.0 - excess, 1e-6))
        return np.concatenate([_initial_beta(x, y), [0.0], [logit_pi]])

    def _bounds(self, n_features: int) -> list[tuple[float | None, float | None]]:
        return [(None, None)] * n_features + [_LOG_ALPHA_BOUNDS, (-12.0, 12.0)]

    def _unpack(self, params: np.ndarray) -> tuple[np.ndarray, float | None]:
        # pi is this family's own parameter and is not carried by FitResult,
        # so it is captured here, on the one code path that sees the full
        # optimiser vector.
        self._fitted_pi = self._pi(float(params[-1]))
        return params[:-2], float(math.exp(params[-2]))

    @staticmethod
    def _pi(logit_pi: float) -> float:
        return 1.0 / (1.0 + math.exp(-min(max(logit_pi, -12.0), 12.0)))

    def _negative_log_likelihood(self, params: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
        beta, log_alpha, logit_pi = params[:-2], params[-2], params[-1]
        alpha = math.exp(min(max(log_alpha, _LOG_ALPHA_BOUNDS[0]), _LOG_ALPHA_BOUNDS[1]))
        pi = self._pi(float(logit_pi))
        r = 1.0 / alpha
        mu = np.exp(_linear_predictor(x, beta))
        log_r_mu = np.log(r + mu)
        log_nb = (
            gammaln(y + r)
            - gammaln(r)
            - gammaln(y + 1.0)
            + r * (math.log(r) - log_r_mu)
            + y * (np.log(mu) - log_r_mu)
        )
        log_nb_zero = r * (math.log(r) - log_r_mu)

        is_zero = y == 0
        # The zero rows mix two sources, so their contribution goes through
        # logsumexp rather than through log(pi + (1-pi)*exp(.)), which loses
        # every digit once the NB zero mass underflows.
        zero_terms = logsumexp(
            np.vstack(
                [
                    np.full(int(np.sum(is_zero)), math.log(max(pi, 1e-300))),
                    math.log(max(1.0 - pi, 1e-300)) + log_nb_zero[is_zero],
                ]
            ),
            axis=0,
        )
        positive_terms = math.log(max(1.0 - pi, 1e-300)) + log_nb[~is_zero]
        total = float(np.sum(zero_terms) + np.sum(positive_terms))
        return -total if math.isfinite(total) else float("inf")

    def predict_distribution(self, x: np.ndarray) -> list[CountDistribution]:
        rows = np.asarray(x, dtype=float).shape[0]
        if self._should_fall_back() or self._last_params is None:
            return self._fallback_distributions(rows)
        beta, alpha, pi = self._last_params
        mu = np.exp(_linear_predictor(_design(x), beta))
        return [
            zero_inflated_negative_binomial_distribution(pi, float(value), alpha) for value in mu
        ]

    _last_params: tuple[np.ndarray, float, float] | None = None

    def fit(self, x: np.ndarray, y: np.ndarray) -> FitResult:
        result = super().fit(x, y)
        if result.status in {FitStatus.CONVERGED, FitStatus.MAX_ITERATIONS}:
            # _unpack captured pi during super().fit().
            self._last_params = (
                result.coefficients,
                result.dispersion or 1e-6,
                self._fitted_pi,
            )
        else:
            self._last_params = None
        return result

    _fitted_pi: float = 0.0
