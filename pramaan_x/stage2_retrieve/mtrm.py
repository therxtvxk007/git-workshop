"""MTRM: multi-granularity trend features.

The choice the design brief refuses to make is between global cyclic regularity
and local adjacent transitions. Both are real, and which one dominates is a
property of the *event type*, not of the method: cyber incidents carry almost no
seasonal signal, floods are almost entirely seasonal, and protest sits between.

So no horizon is selected here. Features are emitted at every granularity and
the hazard model in stage 4 learns the weighting per event type. That is the
whole design: push the choice down to where there is data to make it with.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from ..types import Target
from .graph import MemoryGraph

DEFAULT_HORIZONS: tuple[int, ...] = (1, 3, 7, 30, 90, 365)


@dataclass
class MtrmFeatures:
    horizons: tuple[int, ...] = DEFAULT_HORIZONS

    def compute(self, counts: np.ndarray) -> dict[str, float]:
        """`counts` is a daily series ending at the forecast origin (exclusive)."""
        counts = np.asarray(counts, dtype=float)
        out: dict[str, float] = {}
        n = counts.size
        if n == 0:
            for h in self.horizons:
                out |= {f"mtrm_rate_{h}d": 0.0, f"mtrm_slope_{h}d": 0.0,
                        f"mtrm_ratio_{h}d": 0.0, f"mtrm_share_{h}d": 0.0}
            out["mtrm_dominant_horizon"] = 0.0
            out["mtrm_seasonal_strength"] = 0.0
            return out

        total = counts.sum()
        long_rate = total / n
        rates: dict[int, float] = {}
        for h in self.horizons:
            w = counts[-h:] if h <= n else counts
            rate = float(w.mean()) if w.size else 0.0
            rates[h] = rate
            out[f"mtrm_rate_{h}d"] = rate
            out[f"mtrm_slope_{h}d"] = _slope(w)
            # Ratio against the full-history baseline: the shift at this
            # granularity, comparable across targets of different volume.
            out[f"mtrm_ratio_{h}d"] = float(np.log((rate + 0.05) / (long_rate + 0.05)))
            out[f"mtrm_share_{h}d"] = float(w.sum() / total) if total > 0 else 0.0

        # Which granularity departs furthest from baseline. Handed to the model
        # as a feature, not used to select a horizon here.
        dev = {h: abs(out[f"mtrm_ratio_{h}d"]) for h in self.horizons}
        out["mtrm_dominant_horizon"] = float(max(dev, key=dev.get)) if dev else 0.0
        out["mtrm_seasonal_strength"] = _seasonal_strength(counts)
        out["mtrm_acf1"] = _acf(counts, 1)
        out["mtrm_acf7"] = _acf(counts, 7)
        return out

    def for_target(self, graph: MemoryGraph, target: Target, as_of: datetime,
                   history_days: int = 540) -> dict[str, float]:
        start = as_of - timedelta(days=history_days)
        counts = np.asarray(graph.counts_by_day(target, start, as_of), dtype=float)
        return self.compute(counts)


def _slope(x: np.ndarray) -> float:
    """Ordinary least squares slope, normalised by the window mean so that a
    doubling registers the same whatever the absolute volume."""
    if x.size < 3:
        return 0.0
    t = np.arange(x.size, dtype=float)
    t = t - t.mean()
    denom = float((t * t).sum())
    if denom == 0:
        return 0.0
    slope = float((t * (x - x.mean())).sum() / denom)
    return slope / max(x.mean(), 1e-9)


def _seasonal_strength(x: np.ndarray, period: int = 7) -> float:
    """Fraction of variance explained by the periodic component.

    Computed by averaging over phase rather than fitting a full decomposition:
    at these series lengths a proper STL is over-parameterised and the extra
    machinery buys nothing.
    """
    if x.size < period * 3:
        return 0.0
    n = (x.size // period) * period
    folded = x[-n:].reshape(-1, period)
    phase_means = folded.mean(axis=0)
    total_var = float(x[-n:].var())
    if total_var <= 0:
        return 0.0
    seasonal_var = float(np.repeat(phase_means[None, :], folded.shape[0], axis=0).var())
    return float(min(seasonal_var / total_var, 1.0))


def _acf(x: np.ndarray, lag: int) -> float:
    if x.size <= lag + 2:
        return 0.0
    a = x[:-lag] - x[:-lag].mean()
    b = x[lag:] - x[lag:].mean()
    denom = np.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum() / denom) if denom > 0 else 0.0
