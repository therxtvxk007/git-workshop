"""Out-of-fold prediction records for the later ensemble package.

The rule this module exists to enforce: **a row may be predicted only by a
model that did not train on it, or on any later row.** Both halves matter. The
first stops in-sample predictions being passed off as out-of-fold. The second
stops a fold trained on 2026 scoring a row from 2025 -- which is out-of-sample
by the letter of cross-validation and pure leakage in a temporal problem.

WP5 produces these records; it does not consume them. Stacking, weighting and
routing belong to the ensemble package.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from pydantic import Field, model_validator

from pramaanx.hashing import hash_object
from pramaanx.models.spatial.contracts import SpatialTrainingRow
from pramaanx.models.spatial.prediction import FallbackLevel, SpatialPrediction
from pramaanx.models.spatial.splits import Fold
from pramaanx.schemas.base import UtcDatetime, VersionedModel

__all__ = ["OofLeakageError", "OofRecord", "build_oof_records", "validate_oof_records"]


class OofLeakageError(ValueError):
    """An out-of-fold record was produced by a model that had seen the row."""


class OofRecord(VersionedModel):
    """One model's prediction for one validation row of one fold."""

    district_id: str
    cutoff_at: UtcDatetime
    event_family: str
    fold_id: int
    model_id: str
    model_version: str
    occurrence_score: float = Field(ge=0.0, le=1.0)
    expected_count: float = Field(ge=0.0)
    distribution_family: str
    distribution_parameters: dict[str, float] = Field(default_factory=dict)
    distribution_zero_probability: float = Field(ge=0.0, le=1.0)
    training_window_start: UtcDatetime
    training_window_end: UtcDatetime
    validation_window_start: UtcDatetime
    validation_window_end: UtcDatetime
    training_snapshot_hash: str
    feature_hash: str
    model_artifact_hash: str
    fallback_level: str = FallbackLevel.MODEL.value
    available: bool = True

    @model_validator(mode="after")
    def _check_windows(self) -> OofRecord:
        # `>=`, not `>`. A training window that ends exactly at the first
        # validation cutoff means the model trained on the very row it is
        # about to score, which is in-sample however the windows are named.
        if self.training_window_end >= self.validation_window_start:
            raise OofLeakageError(
                f"fold {self.fold_id} trains to {self.training_window_end.isoformat()} but "
                f"validates from {self.validation_window_start.isoformat()}: the training "
                "window reaches the window it is being scored on"
            )
        if (
            self.cutoff_at < self.validation_window_start
            or self.cutoff_at > self.validation_window_end
        ):
            raise OofLeakageError(
                f"row cutoff {self.cutoff_at.isoformat()} lies outside fold {self.fold_id}'s "
                "validation window"
            )
        return self

    @property
    def key(self) -> tuple[str, datetime, str, str]:
        return (self.district_id, self.cutoff_at, self.event_family, self.model_id)


def build_oof_records(
    *,
    fold: Fold,
    predictions: Sequence[SpatialPrediction],
    validation_rows: Sequence[SpatialTrainingRow],
) -> list[OofRecord]:
    """Turn one fold's validation predictions into records, checking the fold."""
    if len(predictions) != len(validation_rows):
        raise ValueError(
            f"fold {fold.fold_id}: {len(predictions)} predictions for "
            f"{len(validation_rows)} validation rows; every eligible row must be predicted"
        )
    train_cutoffs = set(fold.train_cutoffs)
    records: list[OofRecord] = []
    for prediction, row in zip(predictions, validation_rows, strict=True):
        if prediction.district_id != row.district_id or prediction.cutoff_at != row.cutoff_at:
            raise ValueError("prediction and validation row are misaligned")
        if row.cutoff_at in train_cutoffs:
            raise OofLeakageError(
                f"row at {row.cutoff_at.isoformat()} is in fold {fold.fold_id}'s training "
                "cutoffs; an in-sample prediction must never be recorded as out-of-fold"
            )
        # Checked here as well as in the record, because pydantic wraps a
        # validator's exception in a ValidationError and callers of this
        # function need to catch OofLeakageError specifically.
        if not fold.validation_start <= row.cutoff_at <= fold.validation_end:
            raise OofLeakageError(
                f"row cutoff {row.cutoff_at.isoformat()} lies outside fold {fold.fold_id}'s "
                "validation window"
            )
        records.append(
            OofRecord(
                district_id=row.district_id,
                cutoff_at=row.cutoff_at,
                event_family=row.event_family,
                fold_id=fold.fold_id,
                model_id=prediction.model_id,
                model_version=prediction.model_version,
                occurrence_score=prediction.occurrence_probability,
                expected_count=prediction.expected_count,
                distribution_family=prediction.distribution.family.value,
                distribution_parameters=dict(prediction.distribution.parameters),
                distribution_zero_probability=prediction.distribution.zero_probability,
                training_window_start=fold.train_start,
                training_window_end=fold.train_end,
                validation_window_start=fold.validation_start,
                validation_window_end=fold.validation_end,
                training_snapshot_hash=prediction.training_snapshot_hash,
                feature_hash=prediction.feature_set_hash,
                model_artifact_hash=prediction.artifact_hash,
                fallback_level=prediction.fallback_level.value,
                available=prediction.available,
            )
        )
    return records


def validate_oof_records(records: Iterable[OofRecord]) -> None:
    """Check the whole set: no duplicates, and no model predicting its own rows."""
    materialised = list(records)
    keys = [record.key for record in materialised]
    if len(keys) != len(set(keys)):
        raise OofLeakageError(
            "duplicate out-of-fold records: one row was scored twice by the same model, "
            "which lets a stacker see the same observation from two folds"
        )

    # Same-fold stacking is the failure this catches: if any model's training
    # window for a fold reaches into another model's validation window for the
    # same rows, a stacker fitted on these records is fitted on leakage.
    by_row: dict[tuple[str, datetime, str], list[OofRecord]] = {}
    for record in materialised:
        by_row.setdefault((record.district_id, record.cutoff_at, record.event_family), []).append(
            record
        )
    for (_district, cutoff, _family), group in sorted(by_row.items()):
        for record in group:
            if record.training_window_end >= cutoff:
                raise OofLeakageError(
                    f"model {record.model_id} trained to "
                    f"{record.training_window_end.isoformat()} yet scored a row at "
                    f"{cutoff.isoformat()}"
                )


def records_hash(records: Iterable[OofRecord]) -> str:
    """Deterministic digest over a record set, for artefact linkage."""
    return hash_object(
        [record.model_dump(mode="json") for record in sorted(records, key=lambda r: r.key)]
    )
