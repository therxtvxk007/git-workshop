from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from pramaanx.config import Settings
from pramaanx.district_pipeline import SemanticSignal, run_district_cutoff
from pramaanx.models.spatial import SpatialFeatureRow
from pramaanx.schemas import DistrictRef

CUTOFF = datetime(2026, 8, 1, tzinfo=UTC)


class Occurrence:
    version = "occurrence@1"

    def predict_proba(self, dataset: object) -> np.ndarray:
        del dataset
        return np.asarray([0.2, 0.8])


class Counts:
    version = "count@1"

    def predict_count(self, dataset: object) -> np.ndarray:
        del dataset
        return np.asarray([0.1, 1.2])


class FittedEnsemble:
    version = "fitted-test-ensemble@1"
    fitted = True

    def predict(
        self, spatial_probabilities: np.ndarray, semantic_probabilities: np.ndarray | None = None
    ) -> np.ndarray:
        assert semantic_probabilities is not None
        return (spatial_probabilities + semantic_probabilities) / 2.0


def districts() -> list[DistrictRef]:
    return [
        DistrictRef(
            district_id=f"IND-D-{index}",
            district_name=f"District {index}",
            state_id="IND-S-1",
            state_name="State",
            boundary_version="v1",
        )
        for index in [1, 2]
    ]


def features() -> list[SpatialFeatureRow]:
    return [
        SpatialFeatureRow(
            district_id=district.district_id,
            cutoff_at=CUTOFF,
            event_family="insurgency",
            boundary_version="v1",
            features={"district_count_30d": float(index)},
        )
        for index, district in enumerate(districts())
    ]


def semantics() -> list[SemanticSignal]:
    return [
        SemanticSignal(
            district_id=district.district_id,
            cutoff_at=CUTOFF,
            event_family="insurgency",
            probability=probability,
            model_version="semantic-oof@1",
            evidence_ids=[f"obs-{index}"],
        )
        for index, (district, probability) in enumerate(zip(districts(), [0.4, 0.9], strict=True))
    ]


def test_spatial_only_pipeline_emits_auditable_district_forecasts() -> None:
    result = run_district_cutoff(
        Settings(),
        cutoff_at=CUTOFF,
        snapshot_hash="sha256:snapshot",
        districts=districts(),
        feature_rows=features(),
        spatial_model=Occurrence(),
        count_model=Counts(),
    )
    assert len(result.forecasts) == 2
    assert {forecast.spatial_model_version for forecast in result.forecasts} == {"occurrence@1"}
    assert {forecast.ensemble_version for forecast in result.forecasts} == {"spatial-only@1"}
    assert all(forecast.target.horizon_end.day == 31 for forecast in result.forecasts)


def test_semantic_arm_requires_an_explicit_fitted_ensemble() -> None:
    with pytest.raises(ValueError, match="fitted ensemble"):
        run_district_cutoff(
            Settings(),
            cutoff_at=CUTOFF,
            snapshot_hash="sha256:snapshot",
            districts=districts(),
            feature_rows=features(),
            spatial_model=Occurrence(),
            count_model=Counts(),
            semantic_signals=semantics(),
        )

    result = run_district_cutoff(
        Settings(),
        cutoff_at=CUTOFF,
        snapshot_hash="sha256:snapshot",
        districts=districts(),
        feature_rows=features(),
        spatial_model=Occurrence(),
        count_model=Counts(),
        semantic_signals=semantics(),
        ensemble=FittedEnsemble(),
    )
    assert {forecast.semantic_model_version for forecast in result.forecasts} == {"semantic-oof@1"}
