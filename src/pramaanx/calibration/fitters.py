"""Fitted calibrators.

Three methods, chosen because they fail in different directions and the choice
between them is a real one:

*Platt scaling* is a two-parameter logistic on the log-odds. It is the right
default on small calibration samples because two parameters cannot chase noise
very far. It cannot fix a non-monotone miscalibration.

*Isotonic regression* is non-parametric and monotone. It fixes shapes Platt
cannot, and it overfits enthusiastically on small samples -- it will happily map
a whole score range onto a single training outcome.

*Beta calibration* sits between them: three parameters on ``log p`` and
``log(1 - p)``, so it handles the asymmetric miscalibration that rare-event
scores usually have, without isotonic's step functions.

Two rules apply to all of them.

*A degenerate sample is an error, not a fallback.* A calibration set with one
outcome class, or with fewer points than parameters, raises. Quietly returning
the identity would produce a forecast labelled "calibrated" whose probabilities
were never touched, which is the single most misleading thing this package
could do.

*Fitting is separate from applying.* A calibrator is fitted on outcomes that
were resolvable before the cutoff and applied to forecasts made at it. The
sample carries its own availability bounds so that a leak shows up as a date
comparison rather than as a suspiciously good Brier score.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from pydantic import Field, model_validator

from pramaanx.calibration.base import (
    BaseCalibrator,
    CalibrationReport,
    register_calibrator,
)
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel, UtcDatetime

log = get_logger(__name__)

#: Probabilities are squeezed away from the open interval endpoints before any
#: log-odds transform. Without this a single p=0 or p=1 makes the fit infinite.
EPSILON = 1e-6

#: Smallest calibration sample any fitter will accept.
MIN_SAMPLE_SIZE = 20


class CalibrationSample(PramaanModel):
    """Scores paired with resolved outcomes, plus the window they came from."""

    probabilities: list[float] = Field(default_factory=list)
    outcomes: list[int] = Field(default_factory=list)
    #: Availability bounds of the outcomes, not of the forecasts. An outcome
    #: that was not resolvable until after the cutoff cannot be in a sample used
    #: to calibrate forecasts made at it.
    sample_start: UtcDatetime
    sample_end: UtcDatetime

    @model_validator(mode="after")
    def _check_pairs(self) -> CalibrationSample:
        if len(self.probabilities) != len(self.outcomes):
            raise ValueError(
                f"probabilities and outcomes differ in length: "
                f"{len(self.probabilities)} vs {len(self.outcomes)}"
            )
        for value in self.probabilities:
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"probability outside [0, 1]: {value}")
        for value in self.outcomes:
            if value not in (0, 1):
                raise ValueError(f"outcome must be 0 or 1, got {value}")
        if self.sample_end < self.sample_start:
            raise ValueError("sample_end precedes sample_start")
        return self

    def __len__(self) -> int:
        return len(self.outcomes)

    @property
    def positives(self) -> int:
        return sum(self.outcomes)

    @property
    def negatives(self) -> int:
        return len(self.outcomes) - self.positives

    @property
    def base_rate(self) -> float:
        return self.positives / len(self.outcomes) if self.outcomes else 0.0

    def validate_fittable(self, *, minimum: int = MIN_SAMPLE_SIZE) -> None:
        """Raise unless this sample can support a fit.

        Both checks matter and they catch different things. Too few points is a
        power problem. One outcome class is an identifiability problem: there is
        no decision boundary to find, and every fitter would return something
        confident and meaningless.
        """
        if len(self) < minimum:
            raise ValueError(f"calibration sample has {len(self)} points, need at least {minimum}")
        if self.positives == 0 or self.negatives == 0:
            raise ValueError(
                f"calibration sample has one outcome class only "
                f"({self.positives} positive, {self.negatives} negative); "
                "a calibrator cannot be fitted on it"
            )


def _squeeze(values: Sequence[float]) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), EPSILON, 1.0 - EPSILON)


class PlattCalibrator(BaseCalibrator):
    """Two-parameter logistic scaling on the log-odds."""

    name = "platt"
    VERSION = "0.1.0"

    def __init__(self) -> None:
        super().__init__()
        self.slope: float = 1.0
        self.intercept: float = 0.0

    def fit(self, sample: CalibrationSample, *, minimum: int = MIN_SAMPLE_SIZE) -> PlattCalibrator:
        """Fit on ``sample``, with Platt's own target smoothing.

        The smoothed targets -- ``(N+ + 1)/(N+ + 2)`` and ``1/(N- + 2)`` rather
        than 1 and 0 -- are the correction from the original paper. They stop
        the fit running the slope to infinity on a separable sample, which is
        common when the score already ranks well.
        """
        from sklearn.linear_model import LogisticRegression

        sample.validate_fittable(minimum=minimum)
        probabilities = _squeeze(sample.probabilities)
        features = np.log(probabilities / (1.0 - probabilities)).reshape(-1, 1)
        outcomes = np.asarray(sample.outcomes, dtype=float)

        positive_target = (sample.positives + 1.0) / (sample.positives + 2.0)
        negative_target = 1.0 / (sample.negatives + 2.0)
        targets = np.where(outcomes > 0.5, positive_target, negative_target)

        # Weighted two-class fit reproducing the smoothed targets: each point
        # contributes to both classes in proportion to its smoothed target.
        stacked = np.vstack([features, features])
        labels = np.concatenate([np.ones_like(targets), np.zeros_like(targets)])
        weights = np.concatenate([targets, 1.0 - targets])

        model = LogisticRegression(solver="lbfgs", C=1e6, max_iter=1000)
        model.fit(stacked, labels, sample_weight=weights)
        self.slope = float(model.coef_[0][0])
        self.intercept = float(model.intercept_[0])

        self._report = CalibrationReport(
            method=self.name,
            fitted=True,
            sample_size=len(sample),
            sample_start=sample.sample_start,
            sample_end=sample.sample_end,
            base_rate=sample.base_rate,
            notes=[
                f"slope={self.slope:.6f}",
                f"intercept={self.intercept:.6f}",
                "targets smoothed per Platt (1999)",
            ],
        )
        log.info("calibration.fitted", method=self.name, n=len(sample))
        return self

    def apply(self, probability: float) -> float:
        squeezed = min(max(probability, EPSILON), 1.0 - EPSILON)
        logit = math.log(squeezed / (1.0 - squeezed))
        return self._clamp(1.0 / (1.0 + math.exp(-(self.slope * logit + self.intercept))))


class IsotonicCalibrator(BaseCalibrator):
    """Non-parametric monotone calibration."""

    name = "isotonic"
    VERSION = "0.1.0"

    #: Isotonic has effectively one parameter per distinct score, so it needs a
    #: much larger sample than Platt before it is anything but memorisation.
    MIN_ISOTONIC_SAMPLE = 200

    def __init__(self) -> None:
        super().__init__()
        self._model: object | None = None

    def fit(self, sample: CalibrationSample, *, minimum: int | None = None) -> IsotonicCalibrator:
        from sklearn.isotonic import IsotonicRegression

        threshold = self.MIN_ISOTONIC_SAMPLE if minimum is None else minimum
        sample.validate_fittable(minimum=threshold)
        model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        model.fit(
            np.asarray(sample.probabilities, dtype=float),
            np.asarray(sample.outcomes, dtype=float),
        )
        self._model = model
        self._report = CalibrationReport(
            method=self.name,
            fitted=True,
            sample_size=len(sample),
            sample_start=sample.sample_start,
            sample_end=sample.sample_end,
            base_rate=sample.base_rate,
            notes=[
                "monotone step function; extrapolation clipped at the training range",
                f"minimum sample enforced: {threshold}",
            ],
        )
        log.info("calibration.fitted", method=self.name, n=len(sample))
        return self

    def apply(self, probability: float) -> float:
        if self._model is None:
            raise RuntimeError("isotonic calibrator used before fit()")
        predicted = self._model.predict(np.asarray([probability], dtype=float))  # type: ignore[attr-defined]
        return self._clamp(float(predicted[0]))


class BetaCalibrator(BaseCalibrator):
    """Three-parameter beta calibration.

    Fits a logistic on ``[log p, -log(1 - p)]``, which is the beta-family
    parameterisation. It can represent the asymmetric miscalibration typical of
    rare-event scores -- confident at the low end, badly overconfident at the
    high end -- that Platt's single slope cannot bend.
    """

    name = "beta"
    VERSION = "0.1.0"

    def __init__(self) -> None:
        super().__init__()
        self.coefficients: tuple[float, float] = (1.0, 1.0)
        self.intercept: float = 0.0

    def fit(self, sample: CalibrationSample, *, minimum: int = MIN_SAMPLE_SIZE) -> BetaCalibrator:
        from sklearn.linear_model import LogisticRegression

        sample.validate_fittable(minimum=minimum)
        probabilities = _squeeze(sample.probabilities)
        features = np.column_stack([np.log(probabilities), -np.log(1.0 - probabilities)])
        model = LogisticRegression(solver="lbfgs", C=1e6, max_iter=1000)
        model.fit(features, np.asarray(sample.outcomes, dtype=int))
        self.coefficients = (float(model.coef_[0][0]), float(model.coef_[0][1]))
        self.intercept = float(model.intercept_[0])
        self._report = CalibrationReport(
            method=self.name,
            fitted=True,
            sample_size=len(sample),
            sample_start=sample.sample_start,
            sample_end=sample.sample_end,
            base_rate=sample.base_rate,
            notes=[
                f"a={self.coefficients[0]:.6f}",
                f"b={self.coefficients[1]:.6f}",
                f"c={self.intercept:.6f}",
            ],
        )
        log.info("calibration.fitted", method=self.name, n=len(sample))
        return self

    def apply(self, probability: float) -> float:
        squeezed = min(max(probability, EPSILON), 1.0 - EPSILON)
        first, second = self.coefficients
        linear = first * math.log(squeezed) - second * math.log(1.0 - squeezed) + self.intercept
        return self._clamp(1.0 / (1.0 + math.exp(-linear)))


register_calibrator(PlattCalibrator)
register_calibrator(IsotonicCalibrator)
register_calibrator(BetaCalibrator)
