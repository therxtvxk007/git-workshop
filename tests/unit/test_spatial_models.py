from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from pramaanx.models.ensemble import FittedLogisticStacker
from pramaanx.models.spatial import (
    DistrictHistoricalRateModel,
    GradientBoostedSpatialModel,
    LogisticSpatialModel,
    PoissonCountModel,
    SpatialDataset,
    SpatialFeatureRow,
    UniformBaseRateModel,
)
from pramaanx.outcomes import DistrictOutcomeRow, LabelStatus

START = datetime(2020, 1, 1, tzinfo=UTC)


def training_dataset() -> SpatialDataset:
    features: list[SpatialFeatureRow] = []
    outcomes: list[DistrictOutcomeRow] = []
    for index in range(80):
        positive = index % 4 == 0
        cutoff = START + timedelta(days=index * 30)
        district_id = f"IND-D-{index % 4}"
        features.append(
            SpatialFeatureRow(
                district_id=district_id,
                cutoff_at=cutoff,
                event_family="insurgency",
                boundary_version="v1",
                features={
                    "district_count_30d": 4.0 if positive else 0.0,
                    "neighbour_count_30d": 2.0 if positive else 0.0,
                },
            )
        )
        outcomes.append(
            DistrictOutcomeRow(
                district_id=district_id,
                cutoff_at=cutoff,
                horizon_end=cutoff + timedelta(days=30),
                event_family="insurgency",
                incident_occurred=positive,
                incident_count=2 if positive else 0,
                first_incident_at=cutoff + timedelta(days=1) if positive else None,
                first_resolvable_at=cutoff + timedelta(days=2) if positive else None,
                label_status=LabelStatus.OBSERVED if positive else LabelStatus.ZERO,
                boundary_version="v1",
                incident_ids=[f"a-{index}", f"b-{index}"] if positive else [],
            )
        )
    return SpatialDataset(features, outcomes)


def test_baselines_and_models_produce_bounded_predictions() -> None:
    dataset = training_dataset()
    occurrence_models = [
        UniformBaseRateModel().fit(dataset),
        DistrictHistoricalRateModel().fit(dataset),
        LogisticSpatialModel(random_seed=7).fit(dataset),
        GradientBoostedSpatialModel(random_seed=7, max_iter=30).fit(dataset),
    ]
    for model in occurrence_models:
        predictions = model.predict_proba(dataset)
        assert predictions.shape == (80,)
        assert np.all((predictions >= 0.0) & (predictions <= 1.0))

    counts = PoissonCountModel(random_seed=7, max_iter=30).fit(dataset).predict_count(dataset)
    assert counts.shape == (80,)
    assert np.all(counts >= 0.0)


def test_logistic_model_learns_the_signal_direction() -> None:
    dataset = training_dataset()
    predictions = LogisticSpatialModel(random_seed=7).fit(dataset).predict_proba(dataset)
    assert predictions[0] > predictions[1]


def test_stacker_must_be_fitted_on_oof_predictions() -> None:
    stacker = FittedLogisticStacker(random_seed=7)
    spatial = np.asarray([0.1, 0.8, 0.2, 0.9])
    semantic = np.asarray([0.2, 0.7, 0.1, 0.8])
    labels = np.asarray([0, 1, 0, 1])
    with pytest.raises(RuntimeError, match="not fitted"):
        stacker.predict(spatial, semantic)
    predictions = stacker.fit(spatial, semantic, labels).predict(spatial, semantic)
    assert stacker.fitted
    assert np.all((predictions >= 0.0) & (predictions <= 1.0))
