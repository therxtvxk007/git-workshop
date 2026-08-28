"""Immutable, content-addressed manifests for fitted spatial models.

An artefact answers one question: what exactly produced this number? So the
manifest records the feature-registry hash, the training rows, the split, the
reporting-delay policy, the hyperparameters, the seed and the software
versions -- and hashes all of it.

Two properties are load-bearing:

* **Identity does not depend on wall-clock time.** `created_at` is stored for
  humans but excluded from the hash. Two identical trainings a week apart must
  produce the same artefact id, or the hash cannot be used to detect drift.
* **Writing refuses to overwrite.** An artefact root is append-only. Silently
  replacing a manifest destroys the only record of what an earlier evaluation
  actually scored.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import sklearn
from pydantic import Field, field_validator

from pramaanx.hashing import canonical_json, hash_object
from pramaanx.schemas.base import UtcDatetime, VersionedModel

__all__ = [
    "ArtifactExistsError",
    "ArtifactRootError",
    "ModelArtifact",
    "software_versions",
    "write_artifact",
]


class ArtifactExistsError(FileExistsError):
    """An artefact with this identity is already recorded."""


class ArtifactRootError(ValueError):
    """A write was attempted outside the declared artefact root."""


def software_versions() -> dict[str, str]:
    """Versions that can change a fitted result without any code change."""
    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scikit-learn": sklearn.__version__,
        "platform": platform.machine(),
    }


class ModelArtifact(VersionedModel):
    """Everything needed to reproduce, or to refuse to trust, one fitted model."""

    model_id: str
    model_version: str
    model_family: str
    feature_registry_hash: str
    feature_set_version: str
    training_cutoffs: list[UtcDatetime]
    training_row_hash: str
    outcome_definition_version: str
    reporting_delay_policy: dict[str, object]
    hyperparameters: dict[str, object] = Field(default_factory=dict)
    seed: int = 0
    #: Fitted coefficients, or a hash of a serialized estimator when the model
    #: has no closed-form parameters worth storing inline.
    fitted_state: dict[str, object] = Field(default_factory=dict)
    convergence_status: str
    software: dict[str, str] = Field(default_factory=software_versions)
    code_version: str
    split_plan_hash: str
    #: Recorded, never hashed. Identity must not depend on when it was built.
    created_at: UtcDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("model_id", "model_version", "model_family", "code_version")
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("artefact identity fields cannot be blank")
        return value

    def identity_payload(self) -> dict[str, object]:
        """The fields that define this artefact. `created_at` is absent."""
        payload = self.model_dump(mode="json")
        payload.pop("created_at", None)
        return payload

    def artifact_hash(self) -> str:
        return hash_object(self.identity_payload())

    @property
    def filename(self) -> str:
        return f"{self.model_id}-{self.artifact_hash().split(':')[-1][:16]}.json"


def write_artifact(
    artifact: ModelArtifact,
    *,
    root: Path,
    dry_run: bool = False,
) -> Path:
    """Write one manifest under `root`, refusing to overwrite or escape it.

    `dry_run` returns the path that *would* be written and touches nothing --
    not the directory, not the file. A planning mode that creates directories
    is not a planning mode.
    """
    resolved_root = root.resolve()
    target = (resolved_root / artifact.filename).resolve()
    if not target.is_relative_to(resolved_root):
        raise ArtifactRootError(
            f"{target} escapes the artefact root {resolved_root}; training may not write outside it"
        )
    if target.exists():
        raise ArtifactExistsError(
            f"{target} already exists. Artefacts are immutable: a new fit with different "
            "inputs gets a different hash, and an identical fit needs no rewrite."
        )
    if dry_run:
        return target
    resolved_root.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(artifact.model_dump(mode="json")), encoding="utf-8")
    return target


def artifact_from_state(
    *,
    model_id: str,
    model_version: str,
    model_family: str,
    feature_registry_hash: str,
    feature_set_version: str,
    training_cutoffs: list[datetime],
    training_row_hash: str,
    reporting_delay_policy: Mapping[str, object],
    split_plan_hash: str,
    fitted_state: Mapping[str, object],
    convergence_status: str,
    hyperparameters: Mapping[str, object] | None = None,
    seed: int = 0,
    code_version: str = "pramaanx-wp05@1",
    outcome_definition_version: str = "district-outcome-row@1",
) -> ModelArtifact:
    """Assemble a manifest from a fitted rung's own reported state."""
    return ModelArtifact(
        model_id=model_id,
        model_version=model_version,
        model_family=model_family,
        feature_registry_hash=feature_registry_hash,
        feature_set_version=feature_set_version,
        training_cutoffs=sorted(training_cutoffs),
        training_row_hash=training_row_hash,
        outcome_definition_version=outcome_definition_version,
        reporting_delay_policy=dict(reporting_delay_policy),
        hyperparameters=dict(hyperparameters or {}),
        seed=seed,
        fitted_state=dict(fitted_state),
        convergence_status=convergence_status,
        code_version=code_version,
        split_plan_hash=split_plan_hash,
    )
