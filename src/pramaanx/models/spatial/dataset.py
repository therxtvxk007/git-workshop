"""Training matrices for one district x cutoff x event family."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

import numpy as np
from pydantic import Field, field_validator

from pramaanx.outcomes.models import DistrictOutcomeRow, LabelStatus
from pramaanx.schemas.base import UtcDatetime, VersionedModel


class SpatialFeatureRow(VersionedModel):
    district_id: str
    cutoff_at: UtcDatetime
    event_family: str
    boundary_version: str
    features: dict[str, float] = Field(default_factory=dict)

    @field_validator("features")
    @classmethod
    def _finite_features(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not np.isfinite(feature_value) for feature_value in value.values()):
            raise ValueError("spatial features must be finite")
        return dict(sorted(value.items()))

    @property
    def key(self) -> tuple[str, datetime, str]:
        return (self.district_id, self.cutoff_at, self.event_family)


class SpatialDataset:
    """A fixed-column matrix joined to complete outcome rows."""

    def __init__(
        self,
        feature_rows: Sequence[SpatialFeatureRow],
        outcome_rows: Sequence[DistrictOutcomeRow] | None = None,
    ) -> None:
        self.rows = tuple(feature_rows)
        feature_names = sorted({name for row in self.rows for name in row.features})
        self.feature_names = tuple(feature_names)
        self.x = np.asarray(
            [[row.features.get(name, 0.0) for name in self.feature_names] for row in self.rows],
            dtype=float,
        )
        self.y_occurrence: np.ndarray | None = None
        self.y_count: np.ndarray | None = None
        if outcome_rows is not None:
            outcomes = {
                (row.district_id, row.cutoff_at, row.event_family): row
                for row in outcome_rows
                if row.label_status in {LabelStatus.OBSERVED, LabelStatus.ZERO}
            }
            missing = [row.key for row in self.rows if row.key not in outcomes]
            if missing:
                raise ValueError(f"features lack complete outcomes for {len(missing)} rows")
            joined = [outcomes[row.key] for row in self.rows]
            self.y_occurrence = np.asarray(
                [int(outcome.incident_occurred) for outcome in joined], dtype=int
            )
            self.y_count = np.asarray([outcome.incident_count for outcome in joined], dtype=float)

    def matrix_for(self, feature_names: Iterable[str]) -> np.ndarray:
        names = tuple(feature_names)
        return np.asarray(
            [[row.features.get(name, 0.0) for name in names] for row in self.rows], dtype=float
        )
