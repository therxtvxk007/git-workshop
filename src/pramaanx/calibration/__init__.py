"""Calibration and conformal risk control.

Replaces what M0 records as ``identity@uncalibrated`` and
``fixed_threshold@placeholder`` -- but replaces them by *injection*, not by
deletion. Both M0 behaviours survive here as real implementations
(:class:`~pramaanx.calibration.base.IdentityCalibrator`,
:class:`~pramaanx.calibration.base.FixedThresholdController`) that reproduce
the original strings exactly, so a pipeline switched to injection produces
byte-identical output until something fitted is supplied.

That property is what makes the change safe to land: the M0 acceptance hashes
do not move, and the diff that introduces calibration is separable from the
diff that turns it on.

Two separate concerns, two protocols:

*Calibration* maps scores to probabilities and is judged by a Brier score.
*Risk control* maps probabilities to statuses and encodes a policy about how
many misses are worth how many false alerts. The second is not a modelling
question, and fusing it into the first hides it from the people who should be
arguing about it.
"""

from __future__ import annotations

from pramaanx.calibration.base import (
    IDENTITY_CALIBRATION,
    PLACEHOLDER_POLICY,
    BaseCalibrator,
    BaseRiskController,
    CalibrationReport,
    Calibrator,
    FixedThresholdController,
    IdentityCalibrator,
    RiskController,
    available_calibrators,
    get_calibrator_class,
    register_calibrator,
)
from pramaanx.calibration.conformal import (
    DEFAULT_ALPHA,
    DEFAULT_DELTA,
    EXCHANGEABILITY_CAVEAT,
    ConformalReport,
    RecallFirstController,
    empirical_miss_rate,
    hoeffding_slack,
    required_positives,
)
from pramaanx.calibration.fitters import (
    EPSILON,
    MIN_SAMPLE_SIZE,
    BetaCalibrator,
    CalibrationSample,
    IsotonicCalibrator,
    PlattCalibrator,
)

__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_DELTA",
    "EPSILON",
    "EXCHANGEABILITY_CAVEAT",
    "IDENTITY_CALIBRATION",
    "MIN_SAMPLE_SIZE",
    "PLACEHOLDER_POLICY",
    "BaseCalibrator",
    "BaseRiskController",
    "BetaCalibrator",
    "CalibrationReport",
    "CalibrationSample",
    "Calibrator",
    "ConformalReport",
    "FixedThresholdController",
    "IdentityCalibrator",
    "IsotonicCalibrator",
    "PlattCalibrator",
    "RecallFirstController",
    "RiskController",
    "available_calibrators",
    "empirical_miss_rate",
    "get_calibrator_class",
    "hoeffding_slack",
    "register_calibrator",
    "required_positives",
]
