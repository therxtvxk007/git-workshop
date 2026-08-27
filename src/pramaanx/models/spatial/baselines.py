"""Transparent baseline ladder for district occurrence and counts."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from pramaanx.models.spatial.dataset import SpatialDataset


def _labels(dataset: SpatialDataset) -> np.ndarray:
    if dataset.y_occurrence is None:
        raise ValueError("baseline fitting requires occurrence labels")
    return dataset.y_occurrence


class UniformBaseRateModel:
    version = "uniform-base-rate@1"

    def __init__(self) -> None:
        self.rate: float | None = None

    def fit(self, dataset: SpatialDataset) -> UniformBaseRateModel:
        labels = _labels(dataset)
        self.rate = float(labels.mean()) if len(labels) else 0.0
        return self

    def predict_proba(self, dataset: SpatialDataset) -> np.ndarray:
        if self.rate is None:
            raise RuntimeError("model is not fitted")
        return np.full(len(dataset.rows), self.rate, dtype=float)


class DistrictHistoricalRateModel:
    version = "district-historical-rate@1"

    def __init__(self, *, smoothing_strength: float = 5.0) -> None:
        if smoothing_strength < 0:
            raise ValueError("smoothing_strength cannot be negative")
        self.smoothing_strength = smoothing_strength
        self.global_rate: float | None = None
        self.rates: dict[tuple[str, str], float] = {}

    def fit(self, dataset: SpatialDataset) -> DistrictHistoricalRateModel:
        labels = _labels(dataset)
        self.global_rate = float(labels.mean()) if len(labels) else 0.0
        values: dict[tuple[str, str], list[int]] = defaultdict(list)
        for row, label in zip(dataset.rows, labels, strict=True):
            values[(row.district_id, row.event_family)].append(int(label))
        self.rates = {
            key: (sum(group) + self.smoothing_strength * self.global_rate)
            / (len(group) + self.smoothing_strength)
            for key, group in values.items()
        }
        return self

    def predict_proba(self, dataset: SpatialDataset) -> np.ndarray:
        if self.global_rate is None:
            raise RuntimeError("model is not fitted")
        return np.asarray(
            [
                self.rates.get((row.district_id, row.event_family), self.global_rate)
                for row in dataset.rows
            ],
            dtype=float,
        )


class RecencyCountBaseline:
    version = "recency-count@1"

    def __init__(self, *, window_days: int = 30) -> None:
        if window_days <= 0:
            raise ValueError("window_days must be positive")
        self.window_days = window_days

    def predict_count(self, dataset: SpatialDataset) -> np.ndarray:
        feature = f"district_count_{self.window_days}d"
        return np.asarray([row.features.get(feature, 0.0) for row in dataset.rows], dtype=float)

    def predict_proba(self, dataset: SpatialDataset) -> np.ndarray:
        # Poisson probability of one or more incidents from the recency count.
        return np.asarray(
            [1.0 - math.exp(-value) for value in self.predict_count(dataset)], dtype=float
        )
