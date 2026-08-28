"""The ladder end to end: comparability, cold start and out-of-fold integrity.

Every figure below comes from a synthetic panel with a known generating
process. Nothing here is a claim about real-world predictive performance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures.spatial.synthetic import (
    FAMILY,
    build_panel,
    observation_end,
)
from pramaanx.models.spatial import (
    BASELINE_LADDER,
    FallbackLevel,
    ReportingDelayPolicy,
    SplitPolicy,
    build_extended_spatial_features,
    build_ladder,
    build_training_rows,
    default_feature_registry,
    plan_training,
    train_ladder,
)
from pramaanx.models.spatial.oof import OofLeakageError, validate_oof_records
from pramaanx.models.spatial.prediction import RateHierarchy
from pramaanx.outcomes.panel import build_district_outcome_panel

HORIZON = 30
DELAY = 3


@pytest.fixture(scope="module")
def rows():
    panel = build_panel()
    end = observation_end(panel.cutoffs, horizon_days=HORIZON, delay_days=DELAY)
    outcomes = build_district_outcome_panel(
        registry=panel.registry,
        incidents=panel.incidents,
        cutoffs=panel.cutoffs,
        event_families=[FAMILY],
        horizon_days=HORIZON,
        observation_end=end,
        reporting_delay_days=DELAY,
    )
    features = build_extended_spatial_features(
        registry=panel.registry,
        incidents=panel.incidents,
        cutoffs=panel.cutoffs,
        event_families=[FAMILY],
        history_windows_days=[7, 30, 90, 365],
        adjacency=panel.adjacency,
        horizon_days=HORIZON,
    )
    return build_training_rows(
        feature_rows=features,
        outcome_rows=outcomes,
        registry=panel.registry,
        feature_set_version="spatial-features@v1",
        snapshot_hash="sha256:synthetic",
        reporting_delay=ReportingDelayPolicy(
            reporting_delay_days=DELAY, observation_end=end, horizon_days=HORIZON
        ),
    )


@pytest.fixture(scope="module")
def trained(rows, tmp_path_factory):
    root = tmp_path_factory.mktemp("artifacts")
    return train_ladder(
        rows,
        policy=SplitPolicy(final_test_cutoffs=2, calibration_cutoffs=1, min_train_cutoffs=2),
        artifact_root=root,
    )


def test_the_ladder_has_thirteen_preregistered_rungs() -> None:
    assert len(BASELINE_LADDER) == 13
    assert [rung().model_id for rung in BASELINE_LADDER] == [f"B{i}" for i in range(13)]


def test_the_panel_is_sparse_enough_to_be_interesting(rows) -> None:
    positives = sum(row.occurrence_target for row in rows.rows)
    share = positives / len(rows.rows)
    assert 0.05 < share < 0.6, f"synthetic occurrence share {share:.3f} is unrealistic"


def test_every_baseline_predicts_the_identical_eligible_row_set(trained) -> None:
    per_model: dict[str, set[tuple[str, object, str]]] = {}
    for record in trained.oof_records:
        per_model.setdefault(record.model_id, set()).add(
            (record.district_id, record.cutoff_at, record.event_family)
        )
    assert len(per_model) == 13
    reference = per_model["B0"]
    for model_id, keys in per_model.items():
        assert keys == reference, f"{model_id} was scored on a different row set"


def test_predictions_are_bounded_and_finite(trained) -> None:
    for record in trained.oof_records:
        assert 0.0 <= record.occurrence_score <= 1.0
        assert record.expected_count >= 0.0
        assert 0.0 <= record.distribution_zero_probability <= 1.0


def test_expected_count_matches_the_reported_distribution(trained) -> None:
    for record in trained.oof_records:
        if record.distribution_family == "poisson":
            assert record.expected_count == pytest.approx(
                record.distribution_parameters["mu"], rel=1e-9
            )


def test_out_of_fold_rows_are_never_predicted_by_their_training_model(trained) -> None:
    for record in trained.oof_records:
        assert record.training_window_end < record.validation_window_start
        assert record.cutoff_at >= record.validation_window_start
        assert record.cutoff_at <= record.validation_window_end


def test_same_fold_stacking_leakage_is_impossible(trained) -> None:
    # Passes only because every record's training window closes before the row
    # it scores; a stacker fitted on these cannot see its own answers.
    validate_oof_records(trained.oof_records)


def test_a_record_that_trained_past_its_row_is_refused(trained) -> None:
    record = trained.oof_records[0]
    forged = record.model_copy(update={"training_window_end": record.validation_window_end})
    with pytest.raises(OofLeakageError):
        validate_oof_records([forged])


def test_final_test_cutoffs_never_appear_in_any_prediction(trained) -> None:
    sealed = set(trained.plan.final_test_cutoffs)
    assert sealed
    assert not any(record.cutoff_at in sealed for record in trained.oof_records)


def test_calibration_cutoffs_are_reserved_not_trained_on(trained) -> None:
    reserved = set(trained.plan.calibration_cutoffs)
    assert reserved
    assert not any(record.cutoff_at in reserved for record in trained.oof_records)


def test_artifacts_are_written_once_per_model_and_fold(trained) -> None:
    assert len(trained.artifacts) == 13 * len(trained.plan.folds)
    hashes = [item.artifact_hash() for item in trained.artifacts]
    assert len(hashes) == len(set(hashes))
    for path in trained.written_paths:
        assert path.exists()


def test_convergence_status_is_recorded_for_every_fit(trained) -> None:
    assert len(trained.convergence) == 13 * len(trained.plan.folds)
    assert all(isinstance(status, str) and status for status in trained.convergence.values())


def test_count_rungs_actually_fit_somewhere(trained) -> None:
    # If every count rung fell back on every fold the ladder would be vacuous.
    converged = [
        key
        for key, status in trained.convergence.items()
        if status == "converged" and key.split("@")[0] in {"B9", "B10", "B11", "B12"}
    ]
    assert converged, "no count model converged on any fold"


def test_dry_run_plans_without_writing(rows, tmp_path) -> None:
    root = tmp_path / "planned"
    plan = plan_training(
        rows,
        policy=SplitPolicy(final_test_cutoffs=2, calibration_cutoffs=1, min_train_cutoffs=2),
        artifact_root=root,
    )
    assert plan.model_ids == tuple(f"B{i}" for i in range(13))
    assert plan.artifact_paths
    assert not root.exists()
    assert "folds:" in plan.describe()


def test_identical_inputs_produce_identical_predictions_and_hashes(rows, tmp_path) -> None:
    policy = SplitPolicy(final_test_cutoffs=2, calibration_cutoffs=1, min_train_cutoffs=2)
    first = train_ladder(rows, policy=policy, artifact_root=tmp_path / "a")
    second = train_ladder(rows, policy=policy, artifact_root=tmp_path / "b")
    assert [item.artifact_hash() for item in first.artifacts] == [
        item.artifact_hash() for item in second.artifacts
    ]
    assert [record.occurrence_score for record in first.oof_records] == [
        record.occurrence_score for record in second.oof_records
    ]


def test_an_unseen_district_falls_back_explicitly(rows) -> None:
    hierarchy = RateHierarchy.fit(rows.rows)
    rate, mean_count, level = hierarchy.lookup(
        district_id="IND-D-999999",
        state_id="IND-S-1",
        event_family=FAMILY,
        level=FallbackLevel.DISTRICT,
    )
    # It falls back to the state, and says so. It does not return zero.
    assert level is FallbackLevel.STATE
    assert rate > 0.0
    assert mean_count >= 0.0


def test_an_unseen_state_falls_back_to_national(rows) -> None:
    hierarchy = RateHierarchy.fit(rows.rows)
    _rate, _count, level = hierarchy.lookup(
        district_id="IND-D-999999",
        state_id="IND-S-999999",
        event_family=FAMILY,
        level=FallbackLevel.DISTRICT,
    )
    assert level is FallbackLevel.NATIONAL


def test_an_empty_history_falls_back_to_the_uniform_prior() -> None:
    hierarchy = RateHierarchy.fit([])
    rate, _count, level = hierarchy.lookup(
        district_id="IND-D-1",
        state_id="IND-S-1",
        event_family=FAMILY,
        level=FallbackLevel.DISTRICT,
    )
    assert level is FallbackLevel.UNIFORM
    # Not zero. An unobserved district is unknown, not safe.
    assert rate > 0.0


def test_missing_history_is_not_treated_as_zero(rows) -> None:
    hierarchy = RateHierarchy.fit(rows.rows)
    unseen, _c, level = hierarchy.lookup(
        district_id="IND-D-404",
        state_id="IND-S-1",
        event_family=FAMILY,
        level=FallbackLevel.DISTRICT,
    )
    assert level is not FallbackLevel.MODEL
    assert unseen > 0.0


def test_every_rung_reports_its_fallback_level(trained) -> None:
    levels = {record.fallback_level for record in trained.oof_records}
    assert levels
    assert levels <= {level.value for level in FallbackLevel}


def test_unfitted_rungs_refuse_to_predict() -> None:
    for rung in build_ladder():
        with pytest.raises(RuntimeError, match="must be fitted"):
            rung.predict([])


def test_the_feature_registry_declares_every_produced_column(rows) -> None:
    registry = default_feature_registry()
    produced = set(rows.feature_names)
    undeclared = produced - set(registry.names)
    assert not undeclared, f"columns produced but never declared: {sorted(undeclared)}"
