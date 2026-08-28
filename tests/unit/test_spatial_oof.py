"""Out-of-fold record construction and its refusals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.models.spatial.contracts import SpatialTrainingRow
from pramaanx.models.spatial.distributions import poisson_distribution
from pramaanx.models.spatial.oof import (
    OofLeakageError,
    build_oof_records,
    records_hash,
    validate_oof_records,
)
from pramaanx.models.spatial.prediction import FallbackLevel, SpatialPrediction
from pramaanx.models.spatial.splits import Fold
from pramaanx.outcomes.models import LabelStatus

TRAIN = datetime(2026, 1, 1, tzinfo=UTC)
VALIDATE = TRAIN + timedelta(days=60)


def fold() -> Fold:
    return Fold(
        fold_id=0,
        train_cutoffs=(TRAIN,),
        validation_cutoffs=(VALIDATE,),
        embargo_days=33,
    )


def row(cutoff: datetime = VALIDATE, district: str = "IND-D-1") -> SpatialTrainingRow:
    return SpatialTrainingRow(
        district_id=district,
        state_id="IND-S-1",
        boundary_version="v1",
        cutoff_at=cutoff,
        event_family="insurgency",
        feature_set_version="spatial-features@v1",
        features={"district_count_30d": 1.0},
        feature_available_at={"district_count_30d": cutoff},
        occurrence_target=1,
        count_target=1,
        label_status=LabelStatus.OBSERVED,
        target_first_resolvable_at=cutoff + timedelta(days=5),
        snapshot_hash="sha256:demo",
    )


def prediction(cutoff: datetime = VALIDATE, district: str = "IND-D-1") -> SpatialPrediction:
    return SpatialPrediction(
        district_id=district,
        cutoff_at=cutoff,
        event_family="insurgency",
        occurrence_probability=0.3,
        expected_count=0.35,
        distribution=poisson_distribution(0.35),
        model_id="B9",
        model_version="poisson-glm@1",
        training_cutoff=TRAIN,
        training_snapshot_hash="sha256:demo",
        feature_set_hash="spatial-features@v1",
        artifact_hash="sha256:artifact",
        fallback_level=FallbackLevel.MODEL,
    )


def test_records_carry_the_full_provenance() -> None:
    [record] = build_oof_records(fold=fold(), predictions=[prediction()], validation_rows=[row()])
    assert record.fold_id == 0
    assert record.model_id == "B9"
    assert record.training_window_start == TRAIN
    assert record.validation_window_end == VALIDATE
    assert record.model_artifact_hash == "sha256:artifact"
    assert record.feature_hash == "spatial-features@v1"
    assert record.fallback_level == FallbackLevel.MODEL.value


def test_a_row_from_the_training_cutoffs_is_refused() -> None:
    leaking = Fold(
        fold_id=1, train_cutoffs=(TRAIN, VALIDATE), validation_cutoffs=(VALIDATE,), embargo_days=0
    )
    with pytest.raises(OofLeakageError, match="in-sample prediction"):
        build_oof_records(fold=leaking, predictions=[prediction()], validation_rows=[row()])


def test_a_missing_prediction_is_refused() -> None:
    with pytest.raises(ValueError, match="every eligible row must be predicted"):
        build_oof_records(fold=fold(), predictions=[], validation_rows=[row()])


def test_misaligned_predictions_are_refused() -> None:
    with pytest.raises(ValueError, match="misaligned"):
        build_oof_records(
            fold=fold(),
            predictions=[prediction(district="IND-D-9")],
            validation_rows=[row()],
        )


def test_a_row_outside_the_validation_window_is_refused() -> None:
    with pytest.raises(OofLeakageError, match="outside fold"):
        build_oof_records(
            fold=fold(),
            predictions=[prediction(cutoff=VALIDATE + timedelta(days=30))],
            validation_rows=[row(cutoff=VALIDATE + timedelta(days=30))],
        )


def test_duplicate_records_are_refused() -> None:
    [record] = build_oof_records(fold=fold(), predictions=[prediction()], validation_rows=[row()])
    with pytest.raises(OofLeakageError, match="duplicate out-of-fold records"):
        validate_oof_records([record, record])


def test_records_hash_is_order_independent() -> None:
    first = build_oof_records(
        fold=fold(),
        predictions=[prediction(), prediction(district="IND-D-2")],
        validation_rows=[row(), row(district="IND-D-2")],
    )
    assert records_hash(first) == records_hash(list(reversed(first)))
