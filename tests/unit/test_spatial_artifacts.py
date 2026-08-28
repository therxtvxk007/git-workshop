"""Artefact identity, immutability and dry-run behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pramaanx.models.spatial.artifacts import (
    ArtifactExistsError,
    ArtifactRootError,
    artifact_from_state,
    write_artifact,
)
from pramaanx.models.spatial.feature_registry import default_feature_registry

CUTOFF = datetime(2026, 2, 1, tzinfo=UTC)


def artifact(**overrides: object):
    payload: dict[str, object] = {
        "model_id": "B9",
        "model_version": "poisson-glm@1",
        "model_family": "B9",
        "feature_registry_hash": default_feature_registry().registry_hash(),
        "feature_set_version": "spatial-features@v1",
        "training_cutoffs": [CUTOFF],
        "training_row_hash": "sha256:rows",
        "reporting_delay_policy": {"reporting_delay_days": 3, "horizon_days": 30},
        "split_plan_hash": "sha256:plan",
        "fitted_state": {"coefficients": [0.1, -0.2]},
        "convergence_status": "converged",
    }
    payload.update(overrides)
    return artifact_from_state(**payload)  # type: ignore[arg-type]


def test_identity_does_not_depend_on_wall_clock_time() -> None:
    first = artifact()
    second = artifact()
    object.__setattr__(second, "created_at", CUTOFF + timedelta(days=400))
    # Two identical trainings a week apart must be the same artefact, or the
    # hash cannot be used to detect drift.
    assert first.artifact_hash() == second.artifact_hash()
    assert "created_at" not in first.identity_payload()


def test_changing_a_feature_definition_changes_the_artifact_hash() -> None:
    baseline = artifact()
    changed = artifact(feature_registry_hash="sha256:a-different-registry")
    assert baseline.artifact_hash() != changed.artifact_hash()


def test_changing_the_reporting_delay_policy_changes_the_artifact_hash() -> None:
    baseline = artifact()
    changed = artifact(reporting_delay_policy={"reporting_delay_days": 21, "horizon_days": 30})
    assert baseline.artifact_hash() != changed.artifact_hash()


def test_changing_hyperparameters_changes_the_artifact_hash() -> None:
    assert artifact().artifact_hash() != artifact(hyperparameters={"C": 0.25}).artifact_hash()


def test_artifacts_cannot_be_overwritten(tmp_path: Path) -> None:
    item = artifact()
    write_artifact(item, root=tmp_path)
    with pytest.raises(ArtifactExistsError, match="immutable"):
        write_artifact(item, root=tmp_path)


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    planned = write_artifact(artifact(), root=root, dry_run=True)
    assert planned.name.startswith("B9-")
    # Not the file, and not even the directory: a planning mode that creates
    # directories is not a planning mode.
    assert not planned.exists()
    assert not root.exists()


def test_writing_outside_the_root_is_refused(tmp_path: Path) -> None:
    escaping = artifact(model_id="../escape")
    with pytest.raises(ArtifactRootError, match="escapes the artefact root"):
        write_artifact(escaping, root=tmp_path / "artifacts")


def test_identical_inputs_produce_identical_hashes() -> None:
    assert artifact().artifact_hash() == artifact().artifact_hash()


def test_software_versions_are_recorded() -> None:
    item = artifact()
    assert "python" in item.software
    assert "numpy" in item.software
    assert "scikit-learn" in item.software


def test_blank_identity_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be blank"):
        artifact(model_id="   ")
