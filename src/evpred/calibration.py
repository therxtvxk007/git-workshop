"""Probability calibration and distribution-free conformal abstention.

The survey's stated requirement is that a forecast be "logically accurate and
close to infallible", and that it come with support. Infallible is not on
offer, but two things are, and neither appears in the surveyed systems:

1. **Calibration.** A raw MIL score is a ranking, not a probability. Isotonic or
   Platt scaling on a *held-out, strictly later* window turns it into one, so
   "0.7" means roughly 70% of such days see the event. Reported via Brier score
   and expected calibration error rather than accuracy alone.

2. **Conformal abstention.** Split conformal prediction gives a marginal
   coverage guarantee -- at level ``alpha``, the returned label set contains the
   truth at least ``1 - alpha`` of the time -- under exchangeability alone, with
   no assumption about the model being correct. When the model cannot commit,
   the set is ``{0, 1}`` and the system says so instead of guessing.

The exchangeability caveat is real and is documented in ``docs/04-limitations.md``:
news streams drift, so empirical coverage is measured in the backtest rather
than assumed from the theory.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


@dataclass(slots=True)
class CalibratedScores:
    probabilities: np.ndarray
    method: str


class Calibrator:
    """Isotonic (default) or Platt calibration fitted on held-out scores.

    Isotonic is non-parametric and monotone; it needs more data than Platt but
    does not assume the score-to-probability map is sigmoidal. Below
    ``min_isotonic`` calibration points the constructor silently prefers Platt,
    because isotonic on tiny samples is a step function that overfits badly.
    """

    def __init__(self, method: str = "isotonic", min_isotonic: int = 50) -> None:
        if method not in {"isotonic", "platt", "none"}:
            raise ValueError(f"unknown calibration method: {method!r}")
        self.method = method
        self.min_isotonic = min_isotonic
        self._model = None
        self._fitted_method = "none"

    def fit(self, scores: np.ndarray, labels: np.ndarray) -> "Calibrator":
        scores = np.asarray(scores, dtype=np.float64).ravel()
        labels = np.asarray(labels, dtype=np.int64).ravel()
        method = self.method

        # Degenerate cases: a single class, or too few points, cannot support a
        # meaningful map. Fall through to identity rather than fabricate one.
        if method == "none" or scores.size == 0 or len(np.unique(labels)) < 2:
            self._fitted_method = "none"
            return self
        if method == "isotonic" and scores.size < self.min_isotonic:
            method = "platt"

        if method == "isotonic":
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(scores, labels)
            self._model = iso
        else:
            lr = LogisticRegression(C=1e6, solver="lbfgs")
            lr.fit(scores.reshape(-1, 1), labels)
            self._model = lr
        self._fitted_method = method
        return self

    def transform(self, scores: np.ndarray) -> np.ndarray:
        scores = np.asarray(scores, dtype=np.float64).ravel()
        if self._fitted_method == "none" or self._model is None:
            # Identity on an already-probabilistic input; squash a raw logit.
            if scores.size and (scores.min() < 0.0 or scores.max() > 1.0):
                return 1.0 / (1.0 + np.exp(-scores))
            return scores
        if self._fitted_method == "isotonic":
            return np.clip(self._model.predict(scores), 0.0, 1.0)
        return self._model.predict_proba(scores.reshape(-1, 1))[:, 1]

    @property
    def fitted_method(self) -> str:
        return self._fitted_method


class SplitConformal:
    """Split-conformal label sets for binary forecasting.

    Nonconformity is ``1 - p(true label)``. The threshold is the
    ``ceil((n+1)(1-alpha))/n`` empirical quantile of calibration scores, which
    is the finite-sample correction that makes the coverage guarantee exact
    rather than asymptotic.

    Class-conditional mode (``mondrian=True``) computes a separate threshold per
    class. That matters for event forecasting because the positive class is
    rare: a single marginal threshold can hit 90% overall coverage while
    covering almost no positives.
    """

    def __init__(self, alpha: float = 0.1, mondrian: bool = True) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        self.alpha = alpha
        self.mondrian = mondrian
        self._q_global: float = 1.0
        self._q_class: dict[int, float] = {}

    @staticmethod
    def _quantile(scores: np.ndarray, alpha: float) -> float:
        n = scores.size
        if n == 0:
            return 1.0
        k = int(np.ceil((n + 1) * (1.0 - alpha)))
        if k > n:  # too few calibration points to guarantee this level
            return 1.0
        return float(np.sort(scores)[k - 1])

    def fit(self, probabilities: np.ndarray, labels: np.ndarray) -> "SplitConformal":
        p = np.clip(np.asarray(probabilities, dtype=np.float64).ravel(), 0.0, 1.0)
        y = np.asarray(labels, dtype=np.int64).ravel()
        nonconf = np.where(y == 1, 1.0 - p, p)
        self._q_global = self._quantile(nonconf, self.alpha)
        if self.mondrian:
            for cls in (0, 1):
                mask = y == cls
                self._q_class[cls] = (
                    self._quantile(nonconf[mask], self.alpha)
                    if mask.any()
                    else self._q_global
                )
        return self

    def predict_set(self, probabilities: np.ndarray) -> list[tuple[int, ...]]:
        p = np.clip(np.asarray(probabilities, dtype=np.float64).ravel(), 0.0, 1.0)
        q1 = self._q_class.get(1, self._q_global) if self.mondrian else self._q_global
        q0 = self._q_class.get(0, self._q_global) if self.mondrian else self._q_global
        sets: list[tuple[int, ...]] = []
        for prob in p:
            members = []
            if prob <= q0:          # nonconformity of label 0 is p
                members.append(0)
            if (1.0 - prob) <= q1:  # nonconformity of label 1 is 1-p
                members.append(1)
            sets.append(tuple(members))
        return sets

    @property
    def thresholds(self) -> dict[str, float]:
        return {"global": self._q_global, **{f"class_{k}": v for k, v in self._q_class.items()}}


def coverage_report(
    sets: list[tuple[int, ...]], labels: np.ndarray
) -> dict[str, float]:
    """Empirical coverage, abstention rate and average set size.

    ``coverage`` should land near ``1 - alpha`` if exchangeability roughly holds.
    A large gap is evidence of temporal drift, not a bug in the conformal maths.
    """
    y = np.asarray(labels, dtype=np.int64).ravel()
    if not sets:
        return {"coverage": float("nan"), "abstention": float("nan"), "avg_set_size": float("nan")}
    covered = np.array([int(t in s) for s, t in zip(sets, y)], dtype=np.float64)
    sizes = np.array([len(s) for s in sets], dtype=np.float64)
    return {
        "coverage": float(covered.mean()),
        "abstention": float((sizes != 1).mean()),
        "avg_set_size": float(sizes.mean()),
        "empty_set_rate": float((sizes == 0).mean()),
    }
