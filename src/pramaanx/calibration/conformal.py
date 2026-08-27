"""Recall-first conformal risk control.

The placeholder controller picks statuses from constants somebody chose. This
one picks the alert threshold from calibration data, subject to an explicit
bound on the miss rate: *of the events that actually happen, at most alpha
should fall below the alert threshold, with confidence 1 - delta.*

That is the recall-first framing, and the direction matters. Bounding false
alerts and hoping recall follows is the wrong trade for an early-warning
system: a missed massacre and a spurious alert are not symmetric errors, and a
controller that treats them symmetrically has silently made a policy decision
nobody signed off.

The method is RCPS (risk-controlling prediction sets): scan candidate
thresholds, bound the empirical risk at each with a Hoeffding upper confidence
bound, and take the largest threshold whose bound still clears alpha -- the
fewest alerts consistent with the guarantee.

**The guarantee is conditional and the condition is violated here.** Finite-
sample validity requires the calibration and test data to be exchangeable.
Forecasting is a time series: regimes shift, reporting changes, and the future
is not a random draw from the past. So the bound this controller reports is an
*approximate* guarantee under an assumption that is known to be imperfect, and
it says so in :class:`ConformalReport.caveats` on every fit. Recording that is
the whole point -- a bound presented without its assumption is worse than no
bound, because it invites reliance it cannot support.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import Field, model_validator

from pramaanx.calibration.base import BaseRiskController
from pramaanx.calibration.fitters import CalibrationSample
from pramaanx.config import AlertPolicyConfig
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel
from pramaanx.schemas.forecast import ForecastStatus

log = get_logger(__name__)

#: Default target miss rate. A tenth of true events falling below the alert
#: threshold. A default for a demo, not a policy: the number belongs to whoever
#: owns the consequences of a miss.
DEFAULT_ALPHA = 0.10

#: Default confidence level for the bound.
DEFAULT_DELTA = 0.05

#: The exchangeability caveat, attached to every fit.
EXCHANGEABILITY_CAVEAT = (
    "Finite-sample validity assumes calibration and test data are exchangeable. "
    "Temporal forecasting violates this: regimes shift and reporting practice "
    "changes. Treat the bound as approximate and re-fit per fold."
)


class ConformalReport(PramaanModel):
    """Everything needed to check a controller's claim."""

    alpha: float = Field(gt=0.0, lt=1.0)
    delta: float = Field(gt=0.0, lt=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    #: Positives in the calibration sample. The bound depends on this, not on
    #: the total sample size: a hundred thousand forecasts with four hits
    #: support a guarantee built on four observations.
    positive_count: int = Field(ge=0)
    sample_size: int = Field(ge=0)
    empirical_miss_rate: float = Field(ge=0.0, le=1.0)
    #: Bounded rather than left open. An unfitted controller reports the worst
    #: case, 1.0, instead of infinity: the report is a canonically hashable
    #: record, and ``canonical_json`` rejects non-finite numbers outright.
    upper_bound: float = Field(ge=0.0, le=1.0)
    alert_rate: float = Field(ge=0.0, le=1.0)
    fitted: bool = False
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_caveat(self) -> ConformalReport:
        # The caveat is not optional. A fitted report without it could be quoted
        # as an unconditional guarantee.
        if self.fitted and EXCHANGEABILITY_CAVEAT not in self.caveats:
            raise ValueError("a fitted conformal report must carry the exchangeability caveat")
        return self


def hoeffding_slack(count: int, delta: float) -> float:
    """Hoeffding half-width for a bounded mean at confidence ``1 - delta``."""
    if count <= 0:
        return float("inf")
    return math.sqrt(math.log(1.0 / delta) / (2.0 * count))


def required_positives(alpha: float, delta: float) -> int:
    """Smallest positive count that can support this (alpha, delta).

    Below this the Hoeffding slack alone exceeds alpha, so *no* threshold --
    not even alerting on everything -- can be certified. Reporting the number
    turns an impossible request into an actionable one.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if not 0.0 < delta < 1.0:
        raise ValueError(f"delta must be in (0, 1), got {delta}")
    return int(math.ceil(math.log(1.0 / delta) / (2.0 * alpha * alpha)))


class RecallFirstController(BaseRiskController):
    """Alert threshold fitted to bound the miss rate.

    Statuses below the alert threshold keep M0's retention discipline exactly:
    nothing is dropped, uncertain cases are held as ABSTAIN, MONITOR or
    INSUFFICIENT_EVIDENCE. The controller changes *when we alert*, not *what we
    keep*, because the recall guarantee is about the alert boundary and
    extending it to retention would be claiming a bound the fit never tested.
    """

    name = "conformal_recall_first"
    VERSION = "0.1.0"

    def __init__(self, policy: AlertPolicyConfig) -> None:
        super().__init__()
        self.policy = policy
        self.threshold: float = policy.alert_threshold
        self._report = ConformalReport(
            alpha=DEFAULT_ALPHA,
            delta=DEFAULT_DELTA,
            threshold=policy.alert_threshold,
            positive_count=0,
            sample_size=0,
            empirical_miss_rate=0.0,
            upper_bound=1.0,
            alert_rate=0.0,
            fitted=False,
            caveats=["unfitted: falling back to the configured fixed threshold"],
        )

    @property
    def version(self) -> str:
        state = "fitted" if self._report.fitted else "unfitted"
        return f"{self.name}@{self.VERSION}+{state}+alpha{self._report.alpha:g}"

    def report(self) -> ConformalReport:
        return self._report

    def fit(
        self,
        sample: CalibrationSample,
        *,
        alpha: float = DEFAULT_ALPHA,
        delta: float = DEFAULT_DELTA,
    ) -> RecallFirstController:
        """Fit the alert threshold on ``sample``.

        Raises when the sample cannot support the requested guarantee, naming
        the positive count that would. Silently loosening alpha or falling back
        to the fixed threshold would produce a controller labelled conformal
        that controls nothing.
        """
        sample.validate_fittable(minimum=2)
        positives = [
            probability
            for probability, outcome in zip(sample.probabilities, sample.outcomes, strict=True)
            if outcome == 1
        ]
        count = len(positives)
        slack = hoeffding_slack(count, delta)
        if slack > alpha:
            needed = required_positives(alpha, delta)
            raise ValueError(
                f"cannot certify a miss rate of {alpha:g} at confidence {1 - delta:g} "
                f"from {count} positive outcomes: the Hoeffding slack alone is "
                f"{slack:.4f}. At least {needed} positives are required, or alpha "
                f"must be relaxed."
            )

        candidates = sorted({0.0, *sample.probabilities, 1.0})
        chosen = 0.0
        chosen_risk = 0.0
        for threshold in candidates:
            missed = sum(1 for value in positives if value < threshold)
            empirical = missed / count
            if empirical + slack <= alpha:
                chosen = threshold
                chosen_risk = empirical
            else:
                # Risk is monotone in the threshold, so the first failure ends
                # the scan. Continuing would only find thresholds that are worse.
                break

        alerted = sum(1 for value in sample.probabilities if value >= chosen)
        self.threshold = float(chosen)
        self._report = ConformalReport(
            alpha=alpha,
            delta=delta,
            threshold=self.threshold,
            positive_count=count,
            sample_size=len(sample),
            empirical_miss_rate=chosen_risk,
            upper_bound=chosen_risk + slack,
            alert_rate=alerted / len(sample) if len(sample) else 0.0,
            fitted=True,
            caveats=[EXCHANGEABILITY_CAVEAT],
        )
        log.info(
            "calibration.conformal_fitted",
            threshold=self.threshold,
            alpha=alpha,
            positives=count,
            empirical_miss_rate=chosen_risk,
        )
        return self

    def assign(
        self,
        probability: float,
        *,
        uncertainty: float,
        evidence_count: int,
        novelty: float,
    ) -> ForecastStatus:
        policy = self.policy
        if evidence_count < policy.min_evidence_items and probability >= policy.monitor_threshold:
            return ForecastStatus.INSUFFICIENT_EVIDENCE
        if uncertainty >= 0.5 and probability >= policy.watch_threshold:
            return ForecastStatus.ABSTAIN
        if novelty >= policy.novelty_monitor_threshold:
            return ForecastStatus.MONITOR
        if probability >= self.threshold:
            return ForecastStatus.ALERT
        if probability >= policy.watch_threshold:
            return ForecastStatus.WATCH
        return ForecastStatus.MONITOR


def empirical_miss_rate(
    probabilities: Sequence[float], outcomes: Sequence[int], threshold: float
) -> float:
    """Fraction of true events falling below ``threshold``.

    Exposed separately so a test or a report can check a controller's claim
    against held-out data without reaching into its internals.
    """
    positives = [
        probability
        for probability, outcome in zip(probabilities, outcomes, strict=True)
        if outcome == 1
    ]
    if not positives:
        return 0.0
    return sum(1 for value in positives if value < threshold) / len(positives)
