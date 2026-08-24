"""Feature construction for both branches of the hybrid model.

Two feature families, deliberately kept separate because they carry different
information and the stacking layer benefits from decorrelated branches:

*Instance features* (per document) feed the nested-MIL semantic branch:
    dense embedding  ++  event-tuple summary  ++  recency encoding

*Group features* (per region-window) feed the classical tabular branch:
    time-decayed event counts, lag structure, burst/acceleration statistics,
    source diversity, and actor-mix entropy.

The recency encoding and the decay kernel are the direct answer to survey gap
G3 -- the Pundit-style causal rules the survey criticises treat "A causes B" as
timeless, so an article from 30 days ago counts exactly as much as one from
yesterday. Here every text signal is weighted by an explicit exponential decay
with a tunable half-life, so *when* a precursor appeared changes the forecast.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .schema import BagGroup, Document, Event

# Event-tuple summary block appended to every instance vector.
EVENT_FEATURE_NAMES: tuple[str, ...] = (
    "n_events",
    "mean_polarity",
    "min_polarity",
    "max_polarity",
    "neg_event_frac",
    "mean_confidence",
    "has_time_ref",
    "n_distinct_actions",
    "conflict_intensity",
    "log_text_len",
)

GROUP_FEATURE_NAMES: tuple[str, ...] = (
    "doc_volume",
    "doc_volume_decayed",
    "event_volume_decayed",
    "neg_intensity_decayed",
    "pos_intensity_decayed",
    "polarity_balance",
    "burst_ratio_3_14",
    "acceleration",
    "max_daily_neg",
    "active_day_frac",
    "source_diversity",
    "actor_entropy",
    "action_entropy",
    "time_ref_rate",
    "lag1_neg",
    "lag3_neg",
    "lag7_neg",
    "trend_slope",
)


@dataclass(frozen=True, slots=True)
class DecayConfig:
    """Exponential recency weighting: ``w = 0.5 ** (age_days / half_life_days)``."""

    half_life_days: float = 5.0

    def weight(self, age_days: float) -> float:
        if self.half_life_days <= 0:
            return 1.0
        return 0.5 ** (age_days / self.half_life_days)


def assert_no_lookahead(group: BagGroup) -> None:
    """Fail loudly if any document is dated at or after the forecast origin.

    Called by the backtester on every group. Cheap, and it turns the most
    damaging silent bug in text forecasting into a hard error.
    """
    for doc in group.documents:
        if doc.date >= group.origin:
            raise ValueError(
                f"lookahead: document {doc.doc_id} dated {doc.date} is not before "
                f"forecast origin {group.origin} for region {group.region}"
            )


# --------------------------------------------------------------------------
# Instance-level features
# --------------------------------------------------------------------------

def event_features(doc: Document) -> np.ndarray:
    """Fixed-width summary of a document's extracted event tuples."""
    events: list[Event] = doc.events
    n = len(events)
    if n == 0:
        return np.array(
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
             math.log1p(len(doc.text))],
            dtype=np.float64,
        )
    pol = np.array([e.polarity for e in events], dtype=np.float64)
    conf = np.array([e.confidence for e in events], dtype=np.float64)
    neg = pol < 0
    return np.array(
        [
            math.log1p(n),
            float(pol.mean()),
            float(pol.min()),
            float(pol.max()),
            float(neg.mean()),
            float(conf.mean()),
            float(any(e.time_ref for e in events)),
            math.log1p(len({e.key() for e in events})),
            # Confidence-weighted negative mass: the core conflict signal.
            float(-(pol[neg] * conf[neg]).sum()) if neg.any() else 0.0,
            math.log1p(len(doc.text)),
        ],
        dtype=np.float64,
    )


def instance_matrix(group: BagGroup, decay: DecayConfig) -> tuple[np.ndarray, list[Document]]:
    """Build the per-document design matrix for one forecasting unit.

    Layout: ``[embedding | event_features | recency_weight | log_age]``.
    """
    docs = sorted(group.documents, key=lambda d: (d.date, d.doc_id))
    if not docs:
        return np.zeros((0, 0), dtype=np.float64), []
    rows = []
    for doc in docs:
        age = float((group.origin - doc.date).days)
        emb = doc.embedding
        emb = np.zeros(0) if emb is None else np.asarray(emb, dtype=np.float64).ravel()
        rows.append(
            np.concatenate(
                [
                    emb,
                    event_features(doc),
                    np.array([decay.weight(age), math.log1p(age)], dtype=np.float64),
                ]
            )
        )
    return np.vstack(rows), docs


# --------------------------------------------------------------------------
# Group-level (tabular / classical branch) features
# --------------------------------------------------------------------------

def _entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    ps = [c / total for c in counts if c > 0]
    return -sum(p * math.log(p) for p in ps)


def _window_negative_mass(group: BagGroup, lo: int, hi: int) -> float:
    """Summed confidence-weighted negative polarity for ages in ``[lo, hi)``."""
    total = 0.0
    for doc in group.documents:
        age = (group.origin - doc.date).days
        if lo <= age < hi:
            total += sum(-e.polarity * e.confidence for e in doc.events if e.polarity < 0)
    return total


def group_features(group: BagGroup, decay: DecayConfig, lookback_days: int) -> np.ndarray:
    """Time-aware tabular summary of one region-window."""
    docs = group.documents
    if not docs:
        return np.zeros(len(GROUP_FEATURE_NAMES), dtype=np.float64)

    doc_w = 0.0
    ev_w = 0.0
    neg_w = 0.0
    pos_w = 0.0
    time_ref_hits = 0
    per_day_neg: Counter[int] = Counter()
    sources: Counter[str] = Counter()
    actors: Counter[str] = Counter()
    actions: Counter[str] = Counter()

    for doc in docs:
        age = (group.origin - doc.date).days
        w = decay.weight(float(age))
        doc_w += w
        sources[doc.source] += 1
        for e in doc.events:
            ev_w += w
            signed = e.polarity * e.confidence
            if signed < 0:
                neg_w += -signed * w
                per_day_neg[age] += 1
            else:
                pos_w += signed * w
            if e.time_ref:
                time_ref_hits += 1
            if e.actor:
                actors[e.actor] += 1
            actions[e.key()] += 1

    n_events = sum(d.n_events for d in docs)
    recent = _window_negative_mass(group, 0, 3)
    baseline = _window_negative_mass(group, 0, 14)
    # Burst: how concentrated recent negativity is relative to the fortnight.
    burst = (recent / baseline) if baseline > 0 else 0.0

    lag1 = _window_negative_mass(group, 0, 1)
    lag3 = _window_negative_mass(group, 1, 3)
    lag7 = _window_negative_mass(group, 3, 7)
    accel = lag1 - lag3 / 2.0

    days = {(group.origin - d.date).days for d in docs}
    active_frac = len(days) / max(1, lookback_days)

    # Least-squares slope of daily negative mass over the lookback window.
    xs = np.arange(lookback_days, dtype=np.float64)
    ys = np.array(
        [float(per_day_neg.get(int(a), 0)) for a in xs], dtype=np.float64
    )[::-1]  # oldest -> newest
    slope = float(np.polyfit(xs, ys, 1)[0]) if ys.any() else 0.0

    return np.array(
        [
            math.log1p(len(docs)),
            math.log1p(doc_w),
            math.log1p(ev_w),
            neg_w,
            pos_w,
            (neg_w - pos_w) / (neg_w + pos_w + 1e-9),
            burst,
            accel,
            float(max(per_day_neg.values())) if per_day_neg else 0.0,
            active_frac,
            _entropy(list(sources.values())),
            _entropy(list(actors.values())),
            _entropy(list(actions.values())),
            time_ref_hits / max(1, n_events),
            lag1,
            lag3,
            lag7,
            slope,
        ],
        dtype=np.float64,
    )


def build_group_matrix(
    groups: list[BagGroup], decay: DecayConfig, lookback_days: int
) -> np.ndarray:
    if not groups:
        return np.zeros((0, len(GROUP_FEATURE_NAMES)), dtype=np.float64)
    return np.vstack([group_features(g, decay, lookback_days) for g in groups])
