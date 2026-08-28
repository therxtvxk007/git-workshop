"""Feature declarations, and what changing one does to the hashes."""

from __future__ import annotations

import pytest

from pramaanx.models.spatial.feature_registry import (
    AggregationLevel,
    Availability,
    FeatureRegistry,
    FeatureSpec,
    MissingValueRule,
    Monotonicity,
    default_feature_registry,
)


def spec(name: str = "district_count_7d", **overrides: object) -> FeatureSpec:
    payload: dict[str, object] = {
        "name": name,
        "definition": "Resolvable incidents in the trailing week.",
        "availability": Availability.AS_OF_CUTOFF,
        "lookback_days": 7,
        "aggregation_level": AggregationLevel.DISTRICT,
        "missing_value_rule": MissingValueRule.EXPLICIT_INDICATOR,
        "version": "v1",
    }
    payload.update(overrides)
    return FeatureSpec(**payload)  # type: ignore[arg-type]


def test_every_feature_declares_the_required_metadata() -> None:
    for item in default_feature_registry().specs:
        assert item.definition.strip()
        assert item.dtype.strip()
        assert item.version.strip()
        assert item.transformation.strip()
        assert isinstance(item.availability, Availability)
        assert isinstance(item.aggregation_level, AggregationLevel)
        assert isinstance(item.missing_value_rule, MissingValueRule)
        assert isinstance(item.monotonicity, Monotonicity)


def test_the_required_initial_features_are_declared() -> None:
    names = set(default_feature_registry().names)
    required = {
        *(f"district_count_{w}d" for w in (7, 30, 90, 365)),
        *(f"state_count_{w}d" for w in (7, 30, 90, 365)),
        *(f"neighbour_count_{w}d" for w in (7, 30, 90, 365)),
        "district_days_since_last_event",
        "district_decayed_count",
        "district_attempted_count_365d",
        "district_completed_count_365d",
        "district_attempted_completed_ratio",
        "state_event_rate_365d",
        "state_trend_90d_over_365d",
        "neighbour_active_count_365d",
        "neighbour_weighted_count_365d",
        "neighbour_trend_90d_over_365d",
        "calendar_month",
        "calendar_season",
        "horizon_days",
        "district_previous_cutoff_rate",
        "coverage_document_volume",
        "coverage_independent_lineage_volume",
        "coverage_evidence_acceleration",
        "coverage_contradiction_rate",
        "coverage_completeness",
        "coverage_source_outage",
        "coverage_unresolved_location_rate",
    }
    assert required <= names, f"missing declarations: {sorted(required - names)}"


def test_changing_a_definition_changes_the_registry_hash() -> None:
    baseline = FeatureRegistry([spec()], version="test@v1")
    changed = FeatureRegistry([spec(definition="Something else entirely.")], version="test@v1")
    assert baseline.registry_hash() != changed.registry_hash()


def test_changing_a_lookback_window_changes_the_registry_hash() -> None:
    baseline = FeatureRegistry([spec()], version="test@v1")
    changed = FeatureRegistry([spec(lookback_days=30)], version="test@v1")
    assert baseline.registry_hash() != changed.registry_hash()


def test_the_registry_hash_is_stable_across_declaration_order() -> None:
    first = FeatureRegistry([spec("a"), spec("b")], version="test@v1")
    second = FeatureRegistry([spec("b"), spec("a")], version="test@v1")
    assert first.registry_hash() == second.registry_hash()


def test_duplicate_declarations_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate feature declarations"):
        FeatureRegistry([spec("a"), spec("a")], version="test@v1")


def test_an_undeclared_column_is_refused() -> None:
    registry = FeatureRegistry([spec()], version="test@v1")
    with pytest.raises(KeyError, match="undeclared features present"):
        registry.validate_matrix({"district_count_7d": 1.0, "smuggled_in": 2.0})


def test_a_training_only_feature_is_refused() -> None:
    # A feature available when fitting but not when serving produces a model
    # that cannot be deployed; that is a design error, not a warning.
    with pytest.raises(ValueError, match="must also be safe for inference"):
        spec(safe_for_training=True, safe_for_inference=False)


def test_coverage_features_default_to_an_explicit_indicator() -> None:
    registry = default_feature_registry()
    for name in registry.names:
        if name.startswith("coverage_"):
            assert registry.get(name).missing_value_rule is MissingValueRule.EXPLICIT_INDICATOR
            assert registry.get(name).availability is Availability.INJECTED


def test_history_counts_declare_an_increasing_expectation() -> None:
    registry = default_feature_registry()
    assert registry.get("district_count_365d").monotonicity is Monotonicity.INCREASING
    assert registry.get("district_days_since_last_event").monotonicity is Monotonicity.DECREASING


def test_an_empty_registry_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        FeatureRegistry([], version="test@v1")
