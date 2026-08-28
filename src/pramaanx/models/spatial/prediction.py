"""The B0-B12 ladder behind one prediction interface, with an explicit cold start.

Every rung answers the same three questions -- probability of at least one
qualifying event, expected count, and the count distribution behind that mean
-- and carries the provenance needed to reproduce it. That uniformity is the
whole point of a ladder: a comparison between B3 and B10 is only meaningful if
both were asked for the same thing about the same rows.

Two rules are enforced here rather than left to each model:

* **Nobody silently drops a row.** If a rung cannot predict a district, it
  either uses its declared fallback or marks the prediction unavailable. It may
  not quietly shrink its own evaluation set, because a model scored on the
  easy districts alone will beat one scored on all of them.
* **Missing history is never zero.** The cold-start chain runs district ->
  state -> national -> uniform prior, and the level actually used is recorded
  on every prediction. A district with no observed events is a district we know
  nothing about, not a safe one.

Calibration is deliberately absent. These probabilities are raw model output.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

import numpy as np

from pramaanx.hashing import hash_object
from pramaanx.models.spatial.baselines import (
    DistrictHistoricalRateModel,
    UniformBaseRateModel,
)
from pramaanx.models.spatial.contracts import SpatialTrainingRow
from pramaanx.models.spatial.count_models import (
    FitStatus,
    HurdleRegression,
    NegativeBinomialRegression,
    PoissonRegression,
    ZeroInflatedNegativeBinomialRegression,
)
from pramaanx.models.spatial.dataset import SpatialDataset, SpatialFeatureRow
from pramaanx.models.spatial.distributions import (
    CountDistribution,
    poisson_distribution,
)
from pramaanx.models.spatial.statistical import (
    GradientBoostedSpatialModel,
    LogisticSpatialModel,
)

__all__ = [
    "BASELINE_LADDER",
    "FallbackLevel",
    "LadderModel",
    "RateHierarchy",
    "SpatialPrediction",
    "build_ladder",
]

#: The uninformed prior at the bottom of the cold-start chain. Deliberately a
#: declared constant rather than something derived from data: it is the answer
#: for a district about which nothing at all is known.
UNIFORM_PRIOR = 0.5

_PROBABILITY_EPSILON = 1e-6


class FallbackLevel(StrEnum):
    """Which rung of the cold-start chain actually produced a prediction."""

    MODEL = "model"
    DISTRICT = "district"
    STATE = "state"
    NATIONAL = "national"
    UNIFORM = "uniform"


def probability_to_rate(probability: float) -> float:
    """Invert P(at least one) = 1 - exp(-lambda) for a Poisson horizon.

    Occurrence-only rungs still owe an expected count. Inverting the Poisson
    relation keeps that count consistent with the probability the same model
    reported, instead of inventing a second, disagreeing number.
    """
    clipped = min(max(probability, 0.0), 1.0 - _PROBABILITY_EPSILON)
    return -math.log1p(-clipped)


def rate_to_probability(rate: float) -> float:
    """P(at least one event) under a Poisson with the given mean."""
    return -math.expm1(-max(rate, 0.0))


@dataclass(frozen=True)
class SpatialPrediction:
    """One model's answer for one district x cutoff x event family."""

    district_id: str
    cutoff_at: datetime
    event_family: str
    occurrence_probability: float
    expected_count: float
    distribution: CountDistribution
    model_id: str
    model_version: str
    training_cutoff: datetime | None
    training_snapshot_hash: str
    feature_set_hash: str
    artifact_hash: str
    fallback_level: FallbackLevel = FallbackLevel.MODEL
    #: False when the rung declared itself unable to answer. The row stays in
    #: the table so no model quietly gets an easier evaluation set.
    available: bool = True

    def as_record(self) -> dict[str, object]:
        return {
            "district_id": self.district_id,
            "cutoff_at": self.cutoff_at,
            "event_family": self.event_family,
            "occurrence_probability": self.occurrence_probability,
            "expected_count": self.expected_count,
            "distribution_family": self.distribution.family.value,
            "distribution_parameters": dict(self.distribution.parameters),
            "distribution_zero_probability": self.distribution.zero_probability,
            "distribution_variance": self.distribution.variance,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "training_cutoff": self.training_cutoff,
            "training_snapshot_hash": self.training_snapshot_hash,
            "feature_set_hash": self.feature_set_hash,
            "artifact_hash": self.artifact_hash,
            "fallback_level": self.fallback_level.value,
            "available": self.available,
        }


@dataclass
class RateHierarchy:
    """district -> state -> national -> uniform, with the level recorded.

    Rates are shrunk toward the level above using a fixed pseudo-count. A
    district with one observation in one cutoff should not be handed a rate of
    1.0; shrinkage is what keeps the sparse tail of the panel from dominating.
    """

    national: float = UNIFORM_PRIOR
    state: dict[tuple[str, str], float] = field(default_factory=dict)
    district: dict[tuple[str, str], float] = field(default_factory=dict)
    national_count_mean: float = 0.0
    state_count_mean: dict[tuple[str, str], float] = field(default_factory=dict)
    district_count_mean: dict[tuple[str, str], float] = field(default_factory=dict)
    #: District/state keys that were observed at all. Presence here is what
    #: separates "measured zero" from "never seen".
    observed_districts: set[tuple[str, str]] = field(default_factory=set)
    observed_states: set[tuple[str, str]] = field(default_factory=set)
    smoothing: float = 5.0

    @classmethod
    def fit(cls, rows: Sequence[SpatialTrainingRow], *, smoothing: float = 5.0) -> RateHierarchy:
        if not rows:
            return cls(smoothing=smoothing)
        occurrence = np.asarray([row.occurrence_target for row in rows], dtype=float)
        counts = np.asarray([row.count_target for row in rows], dtype=float)
        national = float(occurrence.mean())
        national_count = float(counts.mean())

        by_state: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        by_district: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        for row in rows:
            by_state[(row.state_id, row.event_family)].append(
                (float(row.occurrence_target), float(row.count_target))
            )
            by_district[(row.district_id, row.event_family)].append(
                (float(row.occurrence_target), float(row.count_target))
            )

        def shrink(
            group: list[tuple[float, float]], parent_rate: float, parent_count: float
        ) -> tuple[float, float]:
            n = len(group)
            occ = sum(item[0] for item in group)
            cnt = sum(item[1] for item in group)
            rate = (occ + smoothing * parent_rate) / (n + smoothing)
            mean_count = (cnt + smoothing * parent_count) / (n + smoothing)
            return rate, mean_count

        state_rates: dict[tuple[str, str], float] = {}
        state_counts: dict[tuple[str, str], float] = {}
        for key, group in by_state.items():
            state_rates[key], state_counts[key] = shrink(group, national, national_count)

        district_rates: dict[tuple[str, str], float] = {}
        district_counts: dict[tuple[str, str], float] = {}
        state_of = {
            (row.district_id, row.event_family): (row.state_id, row.event_family) for row in rows
        }
        for key, group in by_district.items():
            parent = state_of[key]
            district_rates[key], district_counts[key] = shrink(
                group, state_rates.get(parent, national), state_counts.get(parent, national_count)
            )

        return cls(
            national=national,
            state=state_rates,
            district=district_rates,
            national_count_mean=national_count,
            state_count_mean=state_counts,
            district_count_mean=district_counts,
            observed_districts=set(by_district),
            observed_states=set(by_state),
            smoothing=smoothing,
        )

    def lookup(
        self, *, district_id: str, state_id: str, event_family: str, level: FallbackLevel
    ) -> tuple[float, float, FallbackLevel]:
        """Resolve (rate, mean count, level actually used) at or below `level`."""
        district_key = (district_id, event_family)
        state_key = (state_id, event_family)

        if level is FallbackLevel.DISTRICT and district_key in self.observed_districts:
            return self.district[district_key], self.district_count_mean[district_key], level
        if (
            level in {FallbackLevel.DISTRICT, FallbackLevel.STATE}
            and state_key in self.observed_states
        ):
            return self.state[state_key], self.state_count_mean[state_key], FallbackLevel.STATE
        if level is not FallbackLevel.UNIFORM and self.observed_states:
            return self.national, self.national_count_mean, FallbackLevel.NATIONAL
        return UNIFORM_PRIOR, probability_to_rate(UNIFORM_PRIOR), FallbackLevel.UNIFORM


class LadderModel(Protocol):
    """The uniform interface every rung implements."""

    model_id: str
    version: str

    def fit(self, rows: Sequence[SpatialTrainingRow]) -> None: ...

    def predict(self, rows: Sequence[SpatialTrainingRow]) -> list[SpatialPrediction]: ...


class _BaseRung:
    """Shared provenance plumbing and the row-by-row prediction loop."""

    model_id = "B?"
    version = "unset"
    #: The deepest cold-start level this rung starts from.
    start_level = FallbackLevel.DISTRICT

    def __init__(self) -> None:
        self.hierarchy = RateHierarchy()
        self.training_cutoff: datetime | None = None
        self.training_snapshot_hash = ""
        self.feature_set_hash = ""
        self._fitted = False

    def fit(self, rows: Sequence[SpatialTrainingRow]) -> None:
        self.hierarchy = RateHierarchy.fit(rows)
        self.training_cutoff = max((row.cutoff_at for row in rows), default=None)
        self.training_snapshot_hash = rows[0].snapshot_hash if rows else ""
        self.feature_set_hash = rows[0].feature_set_version if rows else ""
        self._fit_model(rows)
        self._fitted = True

    def _fit_model(self, rows: Sequence[SpatialTrainingRow]) -> None:
        """Rungs with a fitted component override this."""

    def artifact_hash(self) -> str:
        return hash_object(
            {
                "model_id": self.model_id,
                "version": self.version,
                "state": self.artifact_state(),
                "training_cutoff": self.training_cutoff,
                "training_snapshot_hash": self.training_snapshot_hash,
                "feature_set_hash": self.feature_set_hash,
            }
        )

    def artifact_state(self) -> dict[str, object]:
        """The rung's own fitted parameters, as they appear in its manifest."""
        return {}

    def predict(self, rows: Sequence[SpatialTrainingRow]) -> list[SpatialPrediction]:
        if not self._fitted:
            raise RuntimeError(f"{self.model_id} must be fitted before predicting")
        artifact = self.artifact_hash()
        return [self._predict_row(row, artifact) for row in rows]

    def _predict_row(self, row: SpatialTrainingRow, artifact: str) -> SpatialPrediction:
        probability, distribution, level = self._answer(row)
        probability = min(max(probability, 0.0), 1.0)
        return SpatialPrediction(
            district_id=row.district_id,
            cutoff_at=row.cutoff_at,
            event_family=row.event_family,
            occurrence_probability=probability,
            expected_count=distribution.mean,
            distribution=distribution,
            model_id=self.model_id,
            model_version=self.version,
            training_cutoff=self.training_cutoff,
            training_snapshot_hash=self.training_snapshot_hash,
            feature_set_hash=self.feature_set_hash,
            artifact_hash=artifact,
            fallback_level=level,
        )

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        raise NotImplementedError

    def _from_hierarchy(
        self, row: SpatialTrainingRow, level: FallbackLevel
    ) -> tuple[float, CountDistribution, FallbackLevel]:
        rate, mean_count, used = self.hierarchy.lookup(
            district_id=row.district_id,
            state_id=row.state_id,
            event_family=row.event_family,
            level=level,
        )
        # The distribution mean is the historical mean count; the occurrence
        # probability is the historical occurrence rate. They are separate
        # estimates of separate quantities and are not forced to agree.
        return rate, poisson_distribution(max(mean_count, 1e-9)), used


class B0UniformPrior(_BaseRung):
    """The uninformed control. Never looks at the data."""

    model_id = "B0"
    version = "uniform-prior@1"
    start_level = FallbackLevel.UNIFORM

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        del row
        return (
            UNIFORM_PRIOR,
            poisson_distribution(probability_to_rate(UNIFORM_PRIOR)),
            FallbackLevel.UNIFORM,
        )


class B1NationalRate(_BaseRung):
    """The empirical national occurrence rate. The real no-skill floor."""

    model_id = "B1"
    version = "national-historical-rate@1"
    start_level = FallbackLevel.NATIONAL

    def __init__(self) -> None:
        super().__init__()
        self.inner = UniformBaseRateModel()

    def artifact_state(self) -> dict[str, object]:
        return {"national_rate": self.hierarchy.national}

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        return self._from_hierarchy(row, FallbackLevel.NATIONAL)


class B2StateRate(_BaseRung):
    model_id = "B2"
    version = "state-historical-rate@1"
    start_level = FallbackLevel.STATE

    def artifact_state(self) -> dict[str, object]:
        return {
            "state_rates": {f"{k[0]}|{k[1]}": v for k, v in sorted(self.hierarchy.state.items())}
        }

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        return self._from_hierarchy(row, FallbackLevel.STATE)


class B3DistrictRate(_BaseRung):
    """Shrunk district rate. Wraps the foundation's model for the rate itself."""

    model_id = "B3"
    version = "district-historical-rate@1"

    def __init__(self) -> None:
        super().__init__()
        self.inner = DistrictHistoricalRateModel()

    def artifact_state(self) -> dict[str, object]:
        return {
            "district_rates": {
                f"{k[0]}|{k[1]}": v for k, v in sorted(self.hierarchy.district.items())
            }
        }

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        return self._from_hierarchy(row, FallbackLevel.DISTRICT)


class B4Persistence(_BaseRung):
    """No-change: repeat the district's most recent observed count.

    Deliberately crude. It is the control that catches a model whose apparent
    skill is really just autocorrelation, and it is expected to be hard to beat
    where events cluster.
    """

    model_id = "B4"
    version = "persistence-no-change@1"

    def __init__(self) -> None:
        super().__init__()
        self.last_count: dict[tuple[str, str], float] = {}

    def _fit_model(self, rows: Sequence[SpatialTrainingRow]) -> None:
        latest: dict[tuple[str, str], tuple[datetime, float]] = {}
        for row in rows:
            key = (row.district_id, row.event_family)
            seen = latest.get(key)
            if seen is None or row.cutoff_at > seen[0]:
                latest[key] = (row.cutoff_at, float(row.count_target))
        self.last_count = {key: value for key, (_, value) in latest.items()}

    def artifact_state(self) -> dict[str, object]:
        return {"last_count": {f"{k[0]}|{k[1]}": v for k, v in sorted(self.last_count.items())}}

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        key = (row.district_id, row.event_family)
        if key not in self.last_count:
            return self._from_hierarchy(row, FallbackLevel.STATE)
        rate = max(self.last_count[key], _PROBABILITY_EPSILON)
        return rate_to_probability(rate), poisson_distribution(rate), FallbackLevel.MODEL


class B5RecencyWeighted(_BaseRung):
    """Exponentially decayed history, read from the declared decay feature."""

    model_id = "B5"
    version = "recency-weighted-count@1"
    feature_name = "district_decayed_count"

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        if self.feature_name not in row.features:
            # The feature is missing, not zero. Falling back states that.
            return self._from_hierarchy(row, FallbackLevel.DISTRICT)
        rate = max(float(row.features[self.feature_name]), 1e-9)
        return rate_to_probability(rate), poisson_distribution(rate), FallbackLevel.MODEL


class B6BaseRateControl(_BaseRung):
    """Gamma-Poisson district rate, matching the engine's G0 formulation.

    Mirrors `pramaanx.generators.base_rate.RateEstimate`: a Gamma posterior over
    the daily rate, then P(at least one) = -expm1(-rate * horizon). Keeping the
    same functional form is what makes this a *control* for the existing engine
    rather than a fourth historical-rate variant.
    """

    model_id = "B6"
    version = "base-rate-poisson-control@1"
    prior_alpha = 0.5
    prior_beta = 90.0

    def __init__(self, *, horizon_days: float = 30.0, lookback_days: float = 365.0) -> None:
        super().__init__()
        self.horizon_days = horizon_days
        self.lookback_days = lookback_days

    def artifact_state(self) -> dict[str, object]:
        return {
            "prior_alpha": self.prior_alpha,
            "prior_beta": self.prior_beta,
            "horizon_days": self.horizon_days,
            "lookback_days": self.lookback_days,
        }

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        observed = row.features.get("district_count_365d")
        if observed is None:
            return self._from_hierarchy(row, FallbackLevel.DISTRICT)
        alpha = self.prior_alpha + float(observed)
        beta = self.prior_beta + self.lookback_days
        daily_rate = alpha / beta
        horizon_rate = max(daily_rate * self.horizon_days, 1e-9)
        return (
            rate_to_probability(horizon_rate),
            poisson_distribution(horizon_rate),
            FallbackLevel.MODEL,
        )


class _SklearnRung(_BaseRung):
    """Shared adapter for the foundation's sklearn occurrence models."""

    def __init__(self) -> None:
        super().__init__()
        self.feature_names: tuple[str, ...] = ()
        self.model: LogisticSpatialModel | GradientBoostedSpatialModel | None = None
        self.fit_failure: str | None = None
        self.standardizer = Standardizer()

    def _build_model(self) -> LogisticSpatialModel | GradientBoostedSpatialModel:
        raise NotImplementedError

    def _fit_model(self, rows: Sequence[SpatialTrainingRow]) -> None:
        self.feature_names = tuple(sorted({name for row in rows for name in row.features}))
        self.standardizer = Standardizer.fit(_matrix(rows, self.feature_names), self.feature_names)
        dataset = _dataset_from_rows(rows, self.feature_names, self.standardizer)
        labels = np.asarray([row.occurrence_target for row in rows], dtype=int)
        if len(np.unique(labels)) < 2 or not self.feature_names:
            # One class, or no features: the model is not identified. It says
            # so and falls back rather than reporting a constant as a fit.
            self.model = None
            self.fit_failure = (
                "only one occurrence class present" if self.feature_names else "no features"
            )
            return
        model = self._build_model()
        model.fit(dataset)
        self.model = model
        self.fit_failure = None

    def artifact_state(self) -> dict[str, object]:
        state: dict[str, object] = {
            "features": list(self.feature_names),
            "fit_failure": self.fit_failure,
        }
        state.update(self.standardizer.as_state())
        return state

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        if self.model is None:
            return self._from_hierarchy(row, FallbackLevel.DISTRICT)
        dataset = _dataset_from_rows([row], self.feature_names, self.standardizer)
        probability = float(self.model.predict_proba(dataset)[0])
        rate = probability_to_rate(probability)
        return probability, poisson_distribution(max(rate, 1e-9)), FallbackLevel.MODEL


class B7Logistic(_SklearnRung):
    model_id = "B7"
    version = "regularized-logistic@1"

    def __init__(self, *, regularization_c: float = 1.0, random_seed: int = 0) -> None:
        super().__init__()
        self.regularization_c = regularization_c
        self.random_seed = random_seed

    def _build_model(self) -> LogisticSpatialModel:
        return LogisticSpatialModel(
            random_seed=self.random_seed, regularization_c=self.regularization_c
        )

    def artifact_state(self) -> dict[str, object]:
        state = super().artifact_state()
        state.update({"regularization_c": self.regularization_c, "seed": self.random_seed})
        return state


class B8GradientBoosting(_SklearnRung):
    model_id = "B8"
    version = "hist-gradient-boosting@1"

    def __init__(self, *, max_iter: int = 100, random_seed: int = 0) -> None:
        super().__init__()
        self.max_iter = max_iter
        self.random_seed = random_seed

    def _build_model(self) -> GradientBoostedSpatialModel:
        return GradientBoostedSpatialModel(random_seed=self.random_seed, max_iter=self.max_iter)

    def artifact_state(self) -> dict[str, object]:
        state = super().artifact_state()
        state.update({"max_iter": self.max_iter, "seed": self.random_seed})
        return state


#: The design matrix the count regressions use.
#:
#: Deliberately small and declared rather than "every available column". A
#: district panel has tens of rows per fold and the history windows are highly
#: collinear -- 7d, 30d, 90d and 365d counts are nested sums of each other.
#: Handing a Poisson or NB2 GLM all of them produces either a rank-deficient
#: design or coefficients that swing wildly between folds, and the resulting
#: instability would be read as a property of the count family rather than of
#: the design. The boosted rung (B8) keeps the full matrix, where collinearity
#: is harmless.
COUNT_DESIGN_FEATURES: tuple[str, ...] = (
    "district_count_30d",
    "district_count_365d",
    "district_decayed_count",
    "neighbour_count_365d",
    "state_count_365d",
)


class _CountRung(_BaseRung):
    """Shared adapter for the maximum-likelihood count regressions."""

    design_features: tuple[str, ...] = COUNT_DESIGN_FEATURES

    def __init__(self) -> None:
        super().__init__()
        self.feature_names: tuple[str, ...] = ()
        self.estimator: object | None = None
        self.status: FitStatus | None = None
        self.standardizer = Standardizer()

    def _build_estimator(self) -> object:
        raise NotImplementedError

    def _fit_model(self, rows: Sequence[SpatialTrainingRow]) -> None:
        available = {name for row in rows for name in row.features}
        self.feature_names = tuple(name for name in self.design_features if name in available)
        raw = _matrix(rows, self.feature_names)
        self.standardizer = Standardizer.fit(raw, self.feature_names)
        counts = np.asarray([row.count_target for row in rows], dtype=float)
        estimator = self._build_estimator()
        result = estimator.fit(self.standardizer.transform(raw), counts)  # type: ignore[attr-defined]
        self.status = result.status
        self.estimator = estimator

    def artifact_state(self) -> dict[str, object]:
        state: dict[str, object] = {
            "features": list(self.feature_names),
            "status": self.status.value if self.status else None,
        }
        state.update(self.standardizer.as_state())
        return state

    def _answer(self, row: SpatialTrainingRow) -> tuple[float, CountDistribution, FallbackLevel]:
        if self.estimator is None or self.status in {
            FitStatus.DEGENERATE_DATA,
            FitStatus.NUMERICAL_FAILURE,
        }:
            return self._from_hierarchy(row, FallbackLevel.DISTRICT)
        matrix = self.standardizer.transform(_matrix([row], self.feature_names))
        distribution = self.estimator.predict_distribution(matrix)[0]  # type: ignore[attr-defined]
        # Occurrence probability comes from the distribution's own zero mass,
        # so the two outputs of a count rung cannot contradict each other.
        return 1.0 - distribution.zero_probability, distribution, FallbackLevel.MODEL


class B9Poisson(_CountRung):
    model_id = "B9"
    version = "poisson-glm@1"

    def _build_estimator(self) -> PoissonRegression:
        return PoissonRegression()


class B10NegativeBinomial(_CountRung):
    model_id = "B10"
    version = "negative-binomial-nb2@1"

    def _build_estimator(self) -> NegativeBinomialRegression:
        return NegativeBinomialRegression()


class B11Hurdle(_CountRung):
    model_id = "B11"
    version = "hurdle-negative-binomial@1"

    def _build_estimator(self) -> HurdleRegression:
        return HurdleRegression()


class B12ZeroInflated(_CountRung):
    model_id = "B12"
    version = "zero-inflated-negative-binomial@1"

    def _build_estimator(self) -> ZeroInflatedNegativeBinomialRegression:
        return ZeroInflatedNegativeBinomialRegression()


#: The preregistered ladder, in order.
BASELINE_LADDER: tuple[type[_BaseRung], ...] = (
    B0UniformPrior,
    B1NationalRate,
    B2StateRate,
    B3DistrictRate,
    B4Persistence,
    B5RecencyWeighted,
    B6BaseRateControl,
    B7Logistic,
    B8GradientBoosting,
    B9Poisson,
    B10NegativeBinomial,
    B11Hurdle,
    B12ZeroInflated,
)


def build_ladder() -> list[_BaseRung]:
    """One fresh instance of every rung, in preregistered order."""
    return [rung() for rung in BASELINE_LADDER]


@dataclass
class Standardizer:
    """Zero-mean, unit-scale preprocessing fitted on training rows only.

    Required rather than cosmetic. The raw design mixes 365-day incident counts
    (hundreds) with a month code (1-12); on that scale an L-BFGS logistic fit
    hits its iteration cap without converging, and a Poisson GLM's linear
    predictor saturates the overflow clip before the optimiser has moved. Both
    then report a "fit" that is really a failure to move.

    It is fitted on the training fold and reused unchanged at prediction time.
    Re-fitting on the rows being predicted would leak their distribution into
    the transform, which is exactly the kind of leakage that looks harmless.
    """

    names: tuple[str, ...] = ()
    mean: tuple[float, ...] = ()
    scale: tuple[float, ...] = ()

    @classmethod
    def fit(cls, matrix: np.ndarray, names: Sequence[str]) -> Standardizer:
        if matrix.size == 0:
            return cls(names=tuple(names))
        mean = matrix.mean(axis=0)
        spread = matrix.std(axis=0)
        # A constant column has zero spread; dividing by one leaves it at zero
        # rather than producing an infinity.
        spread = np.where(spread < 1e-12, 1.0, spread)
        return cls(names=tuple(names), mean=tuple(mean.tolist()), scale=tuple(spread.tolist()))

    def transform(self, matrix: np.ndarray) -> np.ndarray:
        if not self.mean:
            return matrix
        return (matrix - np.asarray(self.mean)) / np.asarray(self.scale)

    def as_state(self) -> dict[str, object]:
        return {
            "standardizer_mean": {
                name: round(value, 12) for name, value in zip(self.names, self.mean, strict=False)
            },
            "standardizer_scale": {
                name: round(value, 12) for name, value in zip(self.names, self.scale, strict=False)
            },
        }


def _matrix(rows: Sequence[SpatialTrainingRow], names: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [[row.features.get(name, 0.0) for name in names] for row in rows], dtype=float
    )


def _dataset_from_rows(
    rows: Sequence[SpatialTrainingRow],
    names: Sequence[str],
    standardizer: Standardizer,
) -> SpatialDataset:
    """Adapt training rows to the foundation's SpatialDataset.

    Built by hand rather than through the outcome join, because the labels have
    already been validated by the training-row contract and re-deriving them
    here would create a second, divergent definition of a trainable row.
    """
    scaled = standardizer.transform(_matrix(rows, names))
    feature_rows = [
        SpatialFeatureRow(
            district_id=row.district_id,
            cutoff_at=row.cutoff_at,
            event_family=row.event_family,
            boundary_version=row.boundary_version,
            features=dict(zip(names, (float(value) for value in scaled[index]), strict=True)),
        )
        for index, row in enumerate(rows)
    ]
    dataset = SpatialDataset(feature_rows)
    dataset.y_occurrence = np.asarray([row.occurrence_target for row in rows], dtype=int)
    dataset.y_count = np.asarray([row.count_target for row in rows], dtype=float)
    return dataset
