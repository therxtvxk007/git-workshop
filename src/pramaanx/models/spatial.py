"""District baselines and trainable spatial models."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

@dataclass(frozen=True)
class DistrictHistory:
    district_id: str
    event_times: tuple[float, ...]

def historical_rate(history: DistrictHistory, cutoff: float, lookback_days: int = 365,
                    horizon_days: int = 30) -> float:
    start = cutoff - lookback_days * 86400
    count = sum(start < t <= cutoff for t in history.event_times)
    return float(min(1.0, count / max(1.0, lookback_days / horizon_days)))

def recency_score(history: DistrictHistory, cutoff: float, half_life_days: float = 30.0) -> float:
    values = [np.exp(-(cutoff - t) / (half_life_days * 86400)) for t in history.event_times if t <= cutoff]
    return float(1.0 - np.exp(-sum(values)))

class LogisticSpatialModel:
    version = "district-logistic@0.1.0"
    def __init__(self) -> None:
        self.model = LogisticRegression(max_iter=2000, class_weight="balanced")
    def fit(self, x: np.ndarray, y: np.ndarray) -> "LogisticSpatialModel":
        self.model.fit(x, y)
        return self
    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(x)[:, 1]

class GradientBoostedSpatialModel:
    version = "district-hgb@0.1.0"
    def __init__(self) -> None:
        self.model = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=150)
    def fit(self, x: np.ndarray, y: np.ndarray) -> "GradientBoostedSpatialModel":
        self.model.fit(x, y)
        return self
    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(x)[:, 1]
