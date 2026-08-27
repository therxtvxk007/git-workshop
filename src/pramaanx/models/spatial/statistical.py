"""Regularized occurrence classifiers and a Poisson count model."""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

from pramaanx.models.spatial.dataset import SpatialDataset


class _TabularModel:
    feature_names: tuple[str, ...] | None = None

    def _training_data(self, dataset: SpatialDataset) -> tuple[np.ndarray, np.ndarray]:
        if dataset.y_occurrence is None:
            raise ValueError("model fitting requires occurrence labels")
        self.feature_names = dataset.feature_names
        if not self.feature_names:
            raise ValueError("model fitting requires at least one feature")
        return dataset.x, dataset.y_occurrence

    def _prediction_matrix(self, dataset: SpatialDataset) -> np.ndarray:
        if self.feature_names is None:
            raise RuntimeError("model is not fitted")
        return dataset.matrix_for(self.feature_names)


class LogisticSpatialModel(_TabularModel):
    version = "logistic-spatial@1"

    def __init__(self, *, random_seed: int = 0, regularization_c: float = 1.0) -> None:
        self.model = LogisticRegression(
            C=regularization_c,
            class_weight="balanced",
            max_iter=2_000,
            random_state=random_seed,
        )

    def fit(self, dataset: SpatialDataset) -> LogisticSpatialModel:
        x, y = self._training_data(dataset)
        if len(np.unique(y)) < 2:
            raise ValueError("logistic model requires both occurrence classes")
        self.model.fit(x, y)
        return self

    def predict_proba(self, dataset: SpatialDataset) -> np.ndarray:
        return self.model.predict_proba(self._prediction_matrix(dataset))[:, 1]


class GradientBoostedSpatialModel(_TabularModel):
    version = "hist-gradient-boosting-spatial@1"

    def __init__(self, *, random_seed: int = 0, max_iter: int = 100) -> None:
        self.model = HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=max_iter,
            l2_regularization=1.0,
            random_state=random_seed,
        )

    def fit(self, dataset: SpatialDataset) -> GradientBoostedSpatialModel:
        x, y = self._training_data(dataset)
        if len(np.unique(y)) < 2:
            raise ValueError("gradient model requires both occurrence classes")
        positives = max(int(y.sum()), 1)
        negatives = max(len(y) - positives, 1)
        sample_weight = np.where(y == 1, len(y) / (2 * positives), len(y) / (2 * negatives))
        self.model.fit(x, y, sample_weight=sample_weight)
        return self

    def predict_proba(self, dataset: SpatialDataset) -> np.ndarray:
        return self.model.predict_proba(self._prediction_matrix(dataset))[:, 1]


class PoissonCountModel(_TabularModel):
    version = "poisson-count@1"

    def __init__(self, *, random_seed: int = 0, max_iter: int = 100) -> None:
        self.model = HistGradientBoostingRegressor(
            loss="poisson",
            learning_rate=0.05,
            max_iter=max_iter,
            l2_regularization=1.0,
            random_state=random_seed,
        )

    def fit(self, dataset: SpatialDataset) -> PoissonCountModel:
        if dataset.y_count is None:
            raise ValueError("count model fitting requires count labels")
        self.feature_names = dataset.feature_names
        if not self.feature_names:
            raise ValueError("count model fitting requires at least one feature")
        self.model.fit(dataset.x, dataset.y_count)
        return self

    def predict_count(self, dataset: SpatialDataset) -> np.ndarray:
        return np.maximum(self.model.predict(self._prediction_matrix(dataset)), 0.0)
