"""Declared, versioned, hashable feature definitions.

A feature that exists only as a column name in a matrix cannot be audited. Six
months later nobody can say whether ``district_count_30d`` counted incidents by
occurrence date or by report date, whether it was inclusive at the cutoff, or
what it does for a district that did not exist yet -- and each of those answers
changes what the model learned.

So every feature is declared here with its availability rule, lookback window,
missing-value rule and version. The registry hashes to a stable digest that
goes into every model artefact: change a definition and the hash changes, which
makes silent redefinition impossible rather than merely discouraged.

This module declares the *contract*. The history features are computed by
``features.py`` (extended from the foundation); the evidence and coverage
features are declared here but computed by other work packages and injected --
this package does not build news or NLP features.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum

from pydantic import field_validator, model_validator

from pramaanx.hashing import hash_object
from pramaanx.schemas.base import VersionedModel

__all__ = [
    "AggregationLevel",
    "Availability",
    "FeatureRegistry",
    "FeatureSpec",
    "MissingValueRule",
    "Monotonicity",
    "default_feature_registry",
]


class Availability(StrEnum):
    """When a feature's inputs become usable.

    `AS_OF_CUTOFF` is the strict rule this package enforces: an event may
    contribute only when it both occurred at or before the cutoff AND became
    resolvable at or before the cutoff. `INJECTED` marks a feature supplied by
    another package, which must carry its own availability timestamp.
    """

    AS_OF_CUTOFF = "as_of_cutoff"
    CALENDAR = "calendar"
    INJECTED = "injected"


class AggregationLevel(StrEnum):
    DISTRICT = "district"
    STATE = "state"
    NEIGHBOURHOOD = "neighbourhood"
    NATIONAL = "national"
    CALENDAR = "calendar"


class MissingValueRule(StrEnum):
    """What a model may do when a feature has no value.

    `EXPLICIT_INDICATOR` is the default for history features on purpose. Zero
    means "measured, and it was zero"; missing means "we did not look, or could
    not". Collapsing the two teaches every model that an unobserved district is
    a safe district.
    """

    ZERO_IS_MEASURED = "zero_is_measured"
    EXPLICIT_INDICATOR = "explicit_indicator"
    NATIVE_NAN = "native_nan"
    FORBIDDEN = "forbidden"


class Monotonicity(StrEnum):
    NONE = "none"
    INCREASING = "increasing"
    DECREASING = "decreasing"


class FeatureSpec(VersionedModel):
    """One declared feature."""

    name: str
    definition: str
    dtype: str = "float64"
    availability: Availability
    #: Trailing window in days. `None` for features with no window (calendar
    #: features, injected coverage snapshots).
    lookback_days: int | None = None
    aggregation_level: AggregationLevel
    missing_value_rule: MissingValueRule
    #: e.g. "identity", "log1p", "ratio". Recorded because a transformation
    #: applied inconsistently between training and inference is invisible.
    transformation: str = "identity"
    version: str
    monotonicity: Monotonicity = Monotonicity.NONE
    safe_for_training: bool = True
    safe_for_inference: bool = True

    @field_validator("name", "definition", "version", "transformation", "dtype")
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("feature declarations cannot contain blank fields")
        return value

    @model_validator(mode="after")
    def _check_spec(self) -> FeatureSpec:
        if self.lookback_days is not None and self.lookback_days <= 0:
            raise ValueError(f"{self.name}: lookback_days must be positive when set")
        if self.safe_for_training and not self.safe_for_inference:
            # Training on something unavailable at inference produces a model
            # that cannot be served; it is a design error, not a warning.
            raise ValueError(
                f"{self.name}: a feature safe for training must also be safe for inference"
            )
        return self


class FeatureRegistry:
    """An ordered, hashable collection of feature declarations."""

    def __init__(self, specs: Iterable[FeatureSpec], *, version: str) -> None:
        ordered = sorted(specs, key=lambda spec: spec.name)
        names = [spec.name for spec in ordered]
        if len(names) != len(set(names)):
            duplicated = sorted({name for name in names if names.count(name) > 1})
            raise ValueError(f"duplicate feature declarations: {duplicated}")
        if not ordered:
            raise ValueError("feature registry cannot be empty")
        if not version.strip():
            raise ValueError("feature registry version cannot be blank")
        self._specs = tuple(ordered)
        self.version = version

    @property
    def specs(self) -> tuple[FeatureSpec, ...]:
        return self._specs

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self._specs)

    def training_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self._specs if spec.safe_for_training)

    def get(self, name: str) -> FeatureSpec:
        for spec in self._specs:
            if spec.name == name:
                return spec
        raise KeyError(f"feature {name!r} is not declared in registry {self.version!r}")

    def registry_hash(self) -> str:
        """Digest over every declaration. Any definition change moves it."""
        return hash_object(
            {
                "version": self.version,
                "specs": [spec.model_dump(mode="json") for spec in self._specs],
            }
        )

    def validate_matrix(self, feature_values: Mapping[str, float]) -> None:
        """Refuse a row carrying features nobody declared."""
        undeclared = sorted(set(feature_values) - set(self.names))
        if undeclared:
            raise KeyError(
                f"undeclared features present: {undeclared}. Every column must be declared "
                f"in registry {self.version!r} before a model may consume it."
            )


def _history(
    name: str,
    definition: str,
    level: AggregationLevel,
    window: int | None,
    *,
    missing_value_rule: MissingValueRule = MissingValueRule.EXPLICIT_INDICATOR,
    **kwargs: object,
) -> FeatureSpec:
    """Declare a history feature.

    The missing-value rule defaults to an explicit indicator rather than to
    zero, and is overridable only by naming it: a caller that wants "absent
    means measured zero" has to say so.
    """
    return FeatureSpec(
        name=name,
        definition=definition,
        availability=Availability.AS_OF_CUTOFF,
        lookback_days=window,
        aggregation_level=level,
        missing_value_rule=missing_value_rule,
        version="v1",
        **kwargs,  # type: ignore[arg-type]
    )


_WINDOWS = (7, 30, 90, 365)


def default_feature_registry(version: str = "spatial-features@v1") -> FeatureRegistry:
    """The WP5 initial feature set.

    History counts are declared monotonically increasing in risk. That is a
    stated expectation used to check fitted coefficients, not a constraint
    imposed on the fit: a baseline whose district-history coefficient comes out
    negative is telling you something about the data, and silencing it with a
    monotone constraint would hide it.
    """
    specs: list[FeatureSpec] = []

    for window in _WINDOWS:
        specs.append(
            _history(
                f"district_count_{window}d",
                f"Resolvable incidents in this district in the {window} days before the cutoff.",
                AggregationLevel.DISTRICT,
                window,
                monotonicity=Monotonicity.INCREASING,
            )
        )
        specs.append(
            _history(
                f"state_count_{window}d",
                f"Resolvable incidents across this district's state in the trailing {window} days.",
                AggregationLevel.STATE,
                window,
                monotonicity=Monotonicity.INCREASING,
            )
        )
        specs.append(
            _history(
                f"neighbour_count_{window}d",
                f"Resolvable incidents in adjacent districts in the trailing {window} days, "
                "using the adjacency graph for this row's boundary version.",
                AggregationLevel.NEIGHBOURHOOD,
                window,
                monotonicity=Monotonicity.INCREASING,
            )
        )

    specs.extend(
        [
            _history(
                "district_days_since_last_event",
                "Days from the last resolvable district incident to the cutoff. Uses the "
                "declared censoring sentinel when the district has never had one, which is "
                "not the same as zero.",
                AggregationLevel.DISTRICT,
                None,
                monotonicity=Monotonicity.DECREASING,
            ),
            _history(
                "district_decayed_count",
                "Exponentially decayed resolvable incident count with a 30-day half-life.",
                AggregationLevel.DISTRICT,
                None,
                transformation="exponential_decay_halflife_30d",
                monotonicity=Monotonicity.INCREASING,
            ),
            _history(
                "district_attempted_count_365d",
                "Attempted-but-not-completed incidents in the trailing year.",
                AggregationLevel.DISTRICT,
                365,
            ),
            _history(
                "district_completed_count_365d",
                "Completed incidents in the trailing year.",
                AggregationLevel.DISTRICT,
                365,
                monotonicity=Monotonicity.INCREASING,
            ),
            _history(
                "district_attempted_completed_ratio",
                "Attempted / (attempted + completed) over the trailing year. Declared with an "
                "explicit indicator because a district with neither is not a district with a "
                "ratio of zero.",
                AggregationLevel.DISTRICT,
                365,
                transformation="ratio",
            ),
            _history(
                "state_event_rate_365d",
                "State incidents per district per year, normalising for state size.",
                AggregationLevel.STATE,
                365,
                transformation="rate_per_district",
            ),
            _history(
                "state_trend_90d_over_365d",
                "State 90-day count over its annualised rate; above one means accelerating.",
                AggregationLevel.STATE,
                365,
                transformation="ratio",
            ),
            _history(
                "neighbour_active_count_365d",
                "How many adjacent districts had at least one resolvable incident this year.",
                AggregationLevel.NEIGHBOURHOOD,
                365,
                monotonicity=Monotonicity.INCREASING,
            ),
            _history(
                "neighbour_weighted_count_365d",
                "Adjacency-weight-weighted neighbour incident count over the trailing year.",
                AggregationLevel.NEIGHBOURHOOD,
                365,
                transformation="adjacency_weighted",
                monotonicity=Monotonicity.INCREASING,
            ),
            _history(
                "neighbour_trend_90d_over_365d",
                "Neighbour 90-day count over its annualised rate.",
                AggregationLevel.NEIGHBOURHOOD,
                365,
                transformation="ratio",
            ),
            _history(
                "district_missing_location_count",
                "Qualifying incidents in this family whose district could not be resolved. "
                "Kept as a feature because unresolved location is a property of the evidence, "
                "not of the district.",
                AggregationLevel.NATIONAL,
                None,
            ),
            _history(
                "district_history_observed",
                "1 when this district has any resolvable history at all, 0 otherwise. The "
                "indicator that keeps 'never observed' distinguishable from 'observed zero'.",
                AggregationLevel.DISTRICT,
                None,
                missing_value_rule=MissingValueRule.ZERO_IS_MEASURED,
            ),
            _history(
                "district_previous_cutoff_rate",
                "The district's occurrence rate as estimated at the previous cutoff. Available "
                "only where an earlier cutoff exists; the first cutoff carries the indicator.",
                AggregationLevel.DISTRICT,
                None,
            ),
        ]
    )

    # Calendar features carry no history and cannot leak, but they are still
    # declared: an undeclared column is an unauditable one.
    specs.extend(
        [
            FeatureSpec(
                name="calendar_month",
                definition="Month of the cutoff, 1-12, as an integer code.",
                availability=Availability.CALENDAR,
                aggregation_level=AggregationLevel.CALENDAR,
                missing_value_rule=MissingValueRule.FORBIDDEN,
                version="v1",
            ),
            FeatureSpec(
                name="calendar_season",
                definition="Meteorological season of the cutoff, 0-3.",
                availability=Availability.CALENDAR,
                aggregation_level=AggregationLevel.CALENDAR,
                missing_value_rule=MissingValueRule.FORBIDDEN,
                version="v1",
            ),
            FeatureSpec(
                name="horizon_days",
                definition="Length of the forecast window in days.",
                availability=Availability.CALENDAR,
                aggregation_level=AggregationLevel.CALENDAR,
                missing_value_rule=MissingValueRule.FORBIDDEN,
                version="v1",
            ),
        ]
    )

    # Injected features. Declared so the contract is complete and the hash
    # covers them; computed by WP1/WP2, never by this package.
    injected = [
        ("coverage_document_volume", "Documents observed for this district-family-window."),
        ("coverage_independent_lineage_volume", "Distinct independent lineages among them."),
        ("coverage_evidence_acceleration", "Short-window document volume over its trailing rate."),
        ("coverage_contradiction_rate", "Share of documents contradicting the qualifying claim."),
        ("coverage_completeness", "Estimated share of the intended sources actually observed."),
        ("coverage_source_outage", "1 when a contributing source was in a recorded outage."),
        ("coverage_unresolved_location_rate", "Share of documents with unresolved location."),
    ]
    specs.extend(
        FeatureSpec(
            name=name,
            definition=definition,
            availability=Availability.INJECTED,
            aggregation_level=AggregationLevel.DISTRICT,
            # Injected coverage is the one place where absence must never be
            # imputed: a source outage and a calm week both produce no
            # documents, and only the indicator separates them.
            missing_value_rule=MissingValueRule.EXPLICIT_INDICATOR,
            version="v1",
            safe_for_training=True,
            safe_for_inference=True,
        )
        for name, definition in injected
    )

    return FeatureRegistry(specs, version=version)
