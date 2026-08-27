"""Calibration and risk-control contracts.

M0 hard-codes two strings into every forecast: ``identity@uncalibrated`` and
``fixed_threshold@placeholder``. They are honest labels for what the pipeline
actually does, and the point of this package is to make them *replaceable*
rather than to make them disappear.

Two protocols, deliberately separate:

:class:`Calibrator`
    Maps a raw score to a probability. Answers "how likely is this?"

:class:`RiskController`
    Maps a probability to a status. Answers "what do we do about it?"

Keeping them apart matters because they fail differently and are audited
differently. A miscalibrated probability is a modelling error measurable with a
Brier score; a badly chosen threshold is a *policy* error, a decision about how
many misses are worth how many false alerts, and no amount of calibration data
settles it. Fusing them into one "scoring" stage hides the policy inside the
model, which is where policies go to avoid being argued with.

The default implementations here reproduce M0's behaviour exactly, bit for bit.
That is what lets the pipeline take an injected calibrator and controller
without any behaviour change until a fitted one is supplied.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from pramaanx.config import AlertPolicyConfig
from pramaanx.schemas.base import PramaanModel, UtcDatetime
from pramaanx.schemas.forecast import ForecastStatus

#: The M0 labels. Imported by the pipeline so the strings live in exactly one
#: place once the injection patch lands.
IDENTITY_CALIBRATION = "identity@uncalibrated"
PLACEHOLDER_POLICY = "fixed_threshold@placeholder"


class CalibrationReport(PramaanModel):
    """Provenance for a fitted calibrator.

    A calibrator without this is not usable in a report: "calibrated" is a claim
    about a fitting procedure on a specific sample, and a probability that
    cannot say which sample it was calibrated on cannot support the claim.
    """

    method: str
    fitted: bool = False
    sample_size: int = Field(default=0, ge=0)
    #: Availability bounds of the calibration sample. Both None when unfitted.
    sample_start: UtcDatetime | None = None
    sample_end: UtcDatetime | None = None
    #: Mean outcome in the calibration sample -- the base rate the calibrator
    #: was fitted against. A calibrator fitted on a 0.2% positive sample will
    #: not transfer to a 20% regime, and this is the number that shows it.
    base_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_fitted(self) -> CalibrationReport:
        if self.fitted and self.sample_size <= 0:
            raise ValueError("a fitted calibrator must record a non-empty sample size")
        if not self.fitted and self.sample_size:
            raise ValueError("an unfitted calibrator must not claim a sample")
        return self


@runtime_checkable
class Calibrator(Protocol):
    """Structural contract for probability calibration."""

    name: str

    @property
    def version(self) -> str: ...

    def apply(self, probability: float) -> float: ...

    def report(self) -> CalibrationReport: ...


@runtime_checkable
class RiskController(Protocol):
    """Structural contract for turning probabilities into statuses."""

    name: str

    @property
    def version(self) -> str: ...

    def assign(
        self,
        probability: float,
        *,
        uncertainty: float,
        evidence_count: int,
        novelty: float,
    ) -> ForecastStatus: ...


class BaseCalibrator(ABC):
    """Convenience base: name, version string, unfitted report by default."""

    name: str = ""
    VERSION: str = "0.1.0"

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define a name")
        self._report = CalibrationReport(method=self.name, fitted=False)

    @property
    def version(self) -> str:
        state = "fitted" if self._report.fitted else "unfitted"
        return f"{self.name}@{self.VERSION}+{state}"

    def report(self) -> CalibrationReport:
        return self._report

    @abstractmethod
    def apply(self, probability: float) -> float:
        """Map one raw probability onto a calibrated one."""

    def apply_all(self, probabilities: Sequence[float]) -> list[float]:
        return [self.apply(value) for value in probabilities]

    @staticmethod
    def _clamp(value: float) -> float:
        """Keep outputs inside [0, 1].

        Fitted calibrators can extrapolate slightly outside the unit interval on
        inputs beyond their training range. Clamping is correct here and is not
        hiding anything: the schema requires a probability, and a value of 1.03
        is not a more confident forecast, it is an out-of-range input.
        """
        return float(min(max(value, 0.0), 1.0))


class IdentityCalibrator(BaseCalibrator):
    """Passes probabilities through unchanged.

    The M0 behaviour, kept as a real implementation rather than as a ``None``
    check at the call site. A pipeline that special-cases "no calibrator" grows
    two code paths, and the uncalibrated one is the one nobody tests.
    """

    name = "identity"
    VERSION = "0.1.0"

    @property
    def version(self) -> str:
        # Reproduces the exact M0 label, so that switching the pipeline to
        # injection changes no recorded string and no report hash.
        return IDENTITY_CALIBRATION

    def apply(self, probability: float) -> float:
        return self._clamp(probability)


class BaseRiskController(ABC):
    """Convenience base for controllers."""

    name: str = ""
    VERSION: str = "0.1.0"

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define a name")

    @property
    def version(self) -> str:
        return f"{self.name}@{self.VERSION}"

    @abstractmethod
    def assign(
        self,
        probability: float,
        *,
        uncertainty: float,
        evidence_count: int,
        novelty: float,
    ) -> ForecastStatus:
        """Assign a status to one forecast."""


class FixedThresholdController(BaseRiskController):
    """The M0 placeholder policy, extracted verbatim.

    This is a byte-for-byte port of ``pipeline.assign_status`` and must stay
    that way: it is the control arm. When a conformal controller is evaluated,
    the comparison is against *this*, so any drift between the two makes the
    comparison meaningless.

    The ordering principle it encodes is the part worth keeping. Uncertain cases
    are retained as MONITOR, ABSTAIN or INSUFFICIENT_EVIDENCE. Nothing is ever
    dropped, which is what protects recall at this stage.
    """

    name = "fixed_threshold"
    VERSION = "0.1.0"

    def __init__(self, policy: AlertPolicyConfig) -> None:
        super().__init__()
        self.policy = policy

    @property
    def version(self) -> str:
        return PLACEHOLDER_POLICY

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
        if probability >= policy.alert_threshold:
            return ForecastStatus.ALERT
        if probability >= policy.watch_threshold:
            return ForecastStatus.WATCH
        return ForecastStatus.MONITOR


_CALIBRATORS: dict[str, type[BaseCalibrator]] = {}


def register_calibrator(cls: type[BaseCalibrator]) -> type[BaseCalibrator]:
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a name before registration")
    if cls.name in _CALIBRATORS and _CALIBRATORS[cls.name] is not cls:
        raise ValueError(f"duplicate calibrator name: {cls.name}")
    _CALIBRATORS[cls.name] = cls
    return cls


def get_calibrator_class(name: str) -> type[BaseCalibrator]:
    from pramaanx import calibration  # noqa: F401  (populates the registry)

    if name not in _CALIBRATORS:
        known = ", ".join(sorted(_CALIBRATORS)) or "<none>"
        raise KeyError(f"unknown calibrator {name!r}; registered: {known}")
    return _CALIBRATORS[name]


def available_calibrators() -> dict[str, type[BaseCalibrator]]:
    from pramaanx import calibration  # noqa: F401

    return dict(sorted(_CALIBRATORS.items()))


register_calibrator(IdentityCalibrator)
