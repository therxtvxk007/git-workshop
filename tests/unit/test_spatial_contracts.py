"""What the training-row contract refuses.

Row-level violations surface as pydantic ``ValidationError`` because
``SpatialTrainingRow`` is a validated record; set-level violations raise
``ContractViolationError`` directly, so a caller can branch on them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from pramaanx.models.spatial.contracts import (
    ContractViolationError,
    ReportingDelayPolicy,
    SpatialTrainingRow,
    TrainingRowSet,
)
from pramaanx.outcomes.models import LabelStatus

CUTOFF = datetime(2026, 2, 1, tzinfo=UTC)
DELAY = ReportingDelayPolicy(
    reporting_delay_days=3,
    observation_end=CUTOFF + timedelta(days=40),
    horizon_days=30,
)


def row(**overrides: object) -> SpatialTrainingRow:
    payload: dict[str, object] = {
        "district_id": "IND-D-1",
        "state_id": "IND-S-1",
        "boundary_version": "v1",
        "cutoff_at": CUTOFF,
        "event_family": "insurgency",
        "feature_set_version": "spatial-features@v1",
        "features": {"district_count_30d": 2.0},
        "feature_available_at": {"district_count_30d": CUTOFF},
        "occurrence_target": 1,
        "count_target": 2,
        "label_status": LabelStatus.OBSERVED,
        "target_first_resolvable_at": CUTOFF + timedelta(days=5),
        "snapshot_hash": "sha256:demo",
    }
    payload.update(overrides)
    return SpatialTrainingRow(**payload)  # type: ignore[arg-type]


def test_a_feature_available_after_the_cutoff_is_refused() -> None:
    with pytest.raises(ValidationError, match="available only after the cutoff"):
        row(feature_available_at={"district_count_30d": CUTOFF + timedelta(hours=1)})


def test_right_censored_labels_cannot_enter_training() -> None:
    with pytest.raises(ValidationError, match="not trainable"):
        row(label_status=LabelStatus.RIGHT_CENSORED)


def test_unresolved_location_labels_cannot_enter_training() -> None:
    with pytest.raises(ValidationError, match="not trainable"):
        row(label_status=LabelStatus.UNRESOLVED_LOCATION)


def test_occurrence_must_agree_with_the_count() -> None:
    with pytest.raises(ValidationError, match="occurrence_target must equal"):
        row(occurrence_target=0, count_target=2)


def test_availability_for_an_absent_feature_is_refused() -> None:
    with pytest.raises(ValidationError, match="availability recorded for absent features"):
        row(feature_available_at={"nonexistent": CUTOFF, "district_count_30d": CUTOFF})


def test_duplicate_rows_are_rejected() -> None:
    with pytest.raises(ContractViolationError, match="duplicate district/cutoff/family"):
        TrainingRowSet(
            rows=[row(), row()],
            feature_set_version="spatial-features@v1",
            reporting_delay=DELAY,
            snapshot_hash="sha256:demo",
        )


def test_mixed_snapshot_hashes_are_rejected() -> None:
    with pytest.raises(ContractViolationError, match="snapshot hashes other than"):
        TrainingRowSet(
            rows=[row(), row(district_id="IND-D-2", snapshot_hash="sha256:other")],
            feature_set_version="spatial-features@v1",
            reporting_delay=DELAY,
            snapshot_hash="sha256:demo",
        )


def test_an_incomplete_district_universe_is_rejected() -> None:
    rows = [
        row(),
        row(district_id="IND-D-2"),
        row(event_family="flood"),  # only one district for the second family
    ]
    with pytest.raises(ContractViolationError, match="incomplete district universe"):
        TrainingRowSet(
            rows=rows,
            feature_set_version="spatial-features@v1",
            reporting_delay=DELAY,
            snapshot_hash="sha256:demo",
        )


def test_mixed_boundary_versions_in_one_cutoff_are_rejected() -> None:
    with pytest.raises(ContractViolationError, match="mixes boundary versions"):
        TrainingRowSet(
            rows=[row(), row(district_id="IND-D-2", boundary_version="v2")],
            feature_set_version="spatial-features@v1",
            reporting_delay=DELAY,
            snapshot_hash="sha256:demo",
        )


def test_a_row_set_declares_one_feature_set_version() -> None:
    with pytest.raises(ContractViolationError, match="feature_set_version"):
        TrainingRowSet(
            rows=[row(), row(district_id="IND-D-2", feature_set_version="other@v9")],
            feature_set_version="spatial-features@v1",
            reporting_delay=DELAY,
            snapshot_hash="sha256:demo",
        )


def test_naive_timestamps_are_rejected() -> None:
    # A guessed timezone is a cutoff bug waiting to happen.
    with pytest.raises(ValidationError):
        row(cutoff_at=datetime(2026, 2, 1))  # noqa: DTZ001 - the point of the test


def test_row_hash_ignores_ordering() -> None:
    first = TrainingRowSet(
        rows=[row(), row(district_id="IND-D-2")],
        feature_set_version="spatial-features@v1",
        reporting_delay=DELAY,
        snapshot_hash="sha256:demo",
    )
    second = TrainingRowSet(
        rows=[row(district_id="IND-D-2"), row()],
        feature_set_version="spatial-features@v1",
        reporting_delay=DELAY,
        snapshot_hash="sha256:demo",
    )
    assert first.rows_hash() == second.rows_hash()
