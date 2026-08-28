"""Fit the ladder across rolling-origin folds and materialise the artefacts.

One entry point, `train_ladder`, does the whole thing: for every fold it fits
every rung on that fold's training rows only, predicts the validation rows,
records out-of-fold predictions, and writes one immutable artefact per
(model, fold).

The ordering is the guarantee. A rung never sees a validation row before it is
asked to predict it, because the fit and the prediction take different row
sequences and the split plan is what decides which is which.

`dry_run=True` plans the whole run -- folds, artefact paths, row counts --
without fitting anything or writing a byte.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pramaanx.models.spatial.artifacts import ModelArtifact, artifact_from_state, write_artifact
from pramaanx.models.spatial.contracts import TrainingRowSet
from pramaanx.models.spatial.feature_registry import FeatureRegistry, default_feature_registry
from pramaanx.models.spatial.oof import OofRecord, build_oof_records, validate_oof_records
from pramaanx.models.spatial.prediction import SpatialPrediction, build_ladder
from pramaanx.models.spatial.splits import (
    SplitPlan,
    SplitPolicy,
    SplitPurpose,
    build_rolling_origin_plan,
    select_rows,
)

__all__ = ["TrainingPlan", "TrainingResult", "plan_training", "train_ladder"]


@dataclass(frozen=True)
class TrainingPlan:
    """What a run would do, computed without doing any of it."""

    plan: SplitPlan
    artifact_paths: tuple[Path, ...]
    fold_row_counts: tuple[tuple[int, int, int], ...]
    model_ids: tuple[str, ...]

    def describe(self) -> str:
        lines = [
            f"folds: {len(self.plan.folds)}",
            f"models: {len(self.model_ids)} ({', '.join(self.model_ids)})",
            f"calibration cutoffs reserved: {len(self.plan.calibration_cutoffs)}",
            f"final-test cutoffs sealed: {len(self.plan.final_test_cutoffs)}",
            f"artefacts that would be written: {len(self.artifact_paths)}",
        ]
        lines.extend(
            f"  fold {fold_id}: train={train} rows, validate={validate} rows"
            for fold_id, train, validate in self.fold_row_counts
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class TrainingResult:
    plan: SplitPlan
    oof_records: tuple[OofRecord, ...]
    artifacts: tuple[ModelArtifact, ...]
    written_paths: tuple[Path, ...]
    #: Per-model convergence, so a run that fell back everywhere is visible.
    convergence: dict[str, str]


def plan_training(
    rows: TrainingRowSet,
    *,
    policy: SplitPolicy,
    artifact_root: Path,
    registry: FeatureRegistry | None = None,
) -> TrainingPlan:
    """Compute the plan. Writes nothing, fits nothing, creates no directories."""
    del registry
    plan = build_rolling_origin_plan(
        rows.cutoffs, policy=policy, reporting_delay=rows.reporting_delay
    )
    counts: list[tuple[int, int, int]] = []
    paths: list[Path] = []
    ladder = build_ladder()
    for fold in plan.folds:
        train_rows = select_rows(rows.rows, plan=plan, fold=fold, purpose=SplitPurpose.TRAIN)
        validation_rows = select_rows(
            rows.rows, plan=plan, fold=fold, purpose=SplitPurpose.VALIDATION
        )
        counts.append((fold.fold_id, len(train_rows), len(validation_rows)))
        paths.extend(artifact_root / f"{rung.model_id}-fold{fold.fold_id}.json" for rung in ladder)
    return TrainingPlan(
        plan=plan,
        artifact_paths=tuple(paths),
        fold_row_counts=tuple(counts),
        model_ids=tuple(rung.model_id for rung in ladder),
    )


def train_ladder(
    rows: TrainingRowSet,
    *,
    policy: SplitPolicy,
    artifact_root: Path,
    registry: FeatureRegistry | None = None,
    dry_run: bool = False,
) -> TrainingResult:
    """Fit every rung on every fold and emit out-of-fold predictions."""
    feature_registry = registry or default_feature_registry()
    plan = build_rolling_origin_plan(
        rows.cutoffs, policy=policy, reporting_delay=rows.reporting_delay
    )
    row_hash = rows.rows_hash()

    all_records: list[OofRecord] = []
    artifacts: list[ModelArtifact] = []
    written: list[Path] = []
    convergence: dict[str, str] = {}

    for fold in plan.folds:
        train_rows = select_rows(rows.rows, plan=plan, fold=fold, purpose=SplitPurpose.TRAIN)
        validation_rows = select_rows(
            rows.rows, plan=plan, fold=fold, purpose=SplitPurpose.VALIDATION
        )
        if not train_rows or not validation_rows:
            continue

        for rung in build_ladder():
            rung.fit(train_rows)
            predictions: Sequence[SpatialPrediction] = rung.predict(validation_rows)
            all_records.extend(
                build_oof_records(
                    fold=fold, predictions=predictions, validation_rows=validation_rows
                )
            )
            state = rung.artifact_state()
            status = str(state.get("status") or state.get("fit_failure") or "fitted")
            convergence[f"{rung.model_id}@fold{fold.fold_id}"] = status
            artifact = artifact_from_state(
                model_id=f"{rung.model_id}-fold{fold.fold_id}",
                model_version=rung.version,
                model_family=rung.model_id,
                feature_registry_hash=feature_registry.registry_hash(),
                feature_set_version=rows.feature_set_version,
                training_cutoffs=list(fold.train_cutoffs),
                training_row_hash=row_hash,
                reporting_delay_policy=rows.reporting_delay.model_dump(mode="json"),
                split_plan_hash=plan.plan_hash(),
                fitted_state=state,
                convergence_status=status,
            )
            artifacts.append(artifact)
            written.append(write_artifact(artifact, root=artifact_root, dry_run=dry_run))

    validate_oof_records(all_records)
    return TrainingResult(
        plan=plan,
        oof_records=tuple(all_records),
        artifacts=tuple(artifacts),
        written_paths=tuple(written),
        convergence=convergence,
    )
