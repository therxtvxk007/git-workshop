"""Censored, pending and unresolved labels must never reach a model."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures.spatial.synthetic import (
    FAMILY,
    build_adjacency,
    build_panel,
    observation_end,
)
from pramaanx.models.spatial.contracts import (
    ContractViolationError,
    ReportingDelayPolicy,
    build_training_rows,
)
from pramaanx.models.spatial.features import build_extended_spatial_features
from pramaanx.outcomes.models import LabelStatus
from pramaanx.outcomes.panel import build_district_outcome_panel

HORIZON = 30
DELAY = 3


def _panel(*, observation_offset_days: int | None = None):
    panel = build_panel(district_count=6, cutoff_count=5)
    end = (
        observation_end(panel.cutoffs, horizon_days=HORIZON, delay_days=DELAY)
        if observation_offset_days is None
        else max(panel.cutoffs) + timedelta(days=observation_offset_days)
    )
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
        adjacency=build_adjacency(6),
        horizon_days=HORIZON,
    )
    delay = ReportingDelayPolicy(
        reporting_delay_days=DELAY, observation_end=end, horizon_days=HORIZON
    )
    return panel, outcomes, features, delay


def test_censored_rows_are_excluded_rather_than_labelled_zero() -> None:
    """An observation window that stops early censors the last cutoffs."""
    panel, outcomes, features, delay = _panel(observation_offset_days=5)
    censored = {
        (row.district_id, row.cutoff_at, row.event_family)
        for row in outcomes
        if row.label_status is LabelStatus.RIGHT_CENSORED
    }
    assert censored, "fixture did not produce censored rows"

    rows = build_training_rows(
        feature_rows=[row for row in features if row.key not in censored],
        outcome_rows=outcomes,
        registry=panel.registry,
        feature_set_version="spatial-features@v1",
        snapshot_hash="sha256:synthetic",
        reporting_delay=delay,
    )
    # Not one censored row survived, and none was quietly turned into a zero.
    assert all(row.label_status in {LabelStatus.OBSERVED, LabelStatus.ZERO} for row in rows.rows)
    assert not {row.key for row in rows.rows} & censored


def test_a_feature_row_with_no_label_is_pending_not_negative() -> None:
    panel, outcomes, features, delay = _panel()
    with pytest.raises(ContractViolationError, match="no resolved label"):
        build_training_rows(
            feature_rows=features,
            outcome_rows=outcomes[:-5],  # drop labels, keep the feature rows
            registry=panel.registry,
            feature_set_version="spatial-features@v1",
            snapshot_hash="sha256:synthetic",
            reporting_delay=delay,
        )


def test_every_surviving_feature_is_available_at_its_cutoff() -> None:
    panel, outcomes, features, delay = _panel()
    rows = build_training_rows(
        feature_rows=features,
        outcome_rows=outcomes,
        registry=panel.registry,
        feature_set_version="spatial-features@v1",
        snapshot_hash="sha256:synthetic",
        reporting_delay=delay,
    )
    for row in rows.rows:
        for name, seen in row.feature_available_at.items():
            assert seen <= row.cutoff_at, f"{name} would have been unavailable at the cutoff"


def test_the_row_hash_moves_when_a_feature_value_moves() -> None:
    panel, outcomes, features, delay = _panel()
    kwargs = {
        "outcome_rows": outcomes,
        "registry": panel.registry,
        "feature_set_version": "spatial-features@v1",
        "snapshot_hash": "sha256:synthetic",
        "reporting_delay": delay,
    }
    baseline = build_training_rows(feature_rows=features, **kwargs)
    mutated = [
        row.model_copy(update={"features": {**row.features, "district_count_30d": 99.0}})
        if index == 0
        else row
        for index, row in enumerate(features)
    ]
    assert build_training_rows(feature_rows=mutated, **kwargs).rows_hash() != baseline.rows_hash()


def test_registry_supplies_the_state_identity() -> None:
    panel, outcomes, features, delay = _panel()
    rows = build_training_rows(
        feature_rows=features,
        outcome_rows=outcomes,
        registry=panel.registry,
        feature_set_version="spatial-features@v1",
        snapshot_hash="sha256:synthetic",
        reporting_delay=delay,
    )
    # State comes from the effective-dated registry, never from the feature row.
    assert all(row.state_id.startswith("IND-S-") for row in rows.rows)
    assert len({row.state_id for row in rows.rows}) > 1
