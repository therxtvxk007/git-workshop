"""Ensembles fitted on out-of-fold predictions, never hand-weighted."""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression


class SpatialOnlyEnsemble:
    version = "spatial-only@1"
    fitted = True

    def predict(
        self, spatial_probabilities: np.ndarray, semantic_probabilities: np.ndarray | None = None
    ) -> np.ndarray:
        del semantic_probabilities
        return np.asarray(spatial_probabilities, dtype=float)


class FittedLogisticStacker:
    """Two-stream stacker whose coefficients come only from historical OOF rows."""

    version = "logistic-stacker@1"

    def __init__(self, *, random_seed: int = 0) -> None:
        self.model = LogisticRegression(C=1.0, max_iter=2_000, random_state=random_seed)
        self.fitted = False

    def fit(
        self,
        spatial_oof: np.ndarray,
        semantic_oof: np.ndarray,
        outcomes: np.ndarray,
    ) -> FittedLogisticStacker:
        if not (len(spatial_oof) == len(semantic_oof) == len(outcomes)):
            raise ValueError("stacker OOF arrays must have equal lengths")
        if len(np.unique(outcomes)) < 2:
            raise ValueError("stacker fit requires both outcome classes")
        features = np.column_stack([spatial_oof, semantic_oof])
        self.model.fit(features, outcomes)
        self.fitted = True
        return self

    def predict(
        self, spatial_probabilities: np.ndarray, semantic_probabilities: np.ndarray | None = None
    ) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("stacker is not fitted")
        if semantic_probabilities is None:
            raise ValueError("semantic probabilities are required by the fitted stacker")
        if len(spatial_probabilities) != len(semantic_probabilities):
            raise ValueError("ensemble inputs must have equal lengths")
        features = np.column_stack([spatial_probabilities, semantic_probabilities])
        return self.model.predict_proba(features)[:, 1]
