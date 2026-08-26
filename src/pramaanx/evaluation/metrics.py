"""Scoring primitives.

Only the metrics M0 can honestly compute are here: discovery recall, recall at
a fixed alert budget, precision and false-alert load, Brier score, log loss,
calibration slope/intercept, reliability bins and lead time.

Deliberately absent: time-window coverage and width, severity calibration,
selective risk under abstention, and subgroup breakdowns by language and source
availability. Those need the calibration and risk stages (Phases 8) and the
multilingual evidence (Phase 9), and reporting them now would mean reporting
numbers that no component actually produces.

Every function returns plain, rounded values so two runs over identical inputs
produce byte-identical reports.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

EPSILON = 1e-9
PROBABILITY_CLIP = 1e-6


def _clip(values: Sequence[float]) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), PROBABILITY_CLIP, 1.0 - PROBABILITY_CLIP)


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float | None:
    """Mean squared error of probabilistic forecasts. Lower is better."""
    if not probabilities:
        return None
    probs = np.asarray(probabilities, dtype=float)
    truth = np.asarray(outcomes, dtype=float)
    return round(float(np.mean((probs - truth) ** 2)), 9)


def log_loss(probabilities: Sequence[float], outcomes: Sequence[int]) -> float | None:
    """Negative log likelihood, clipped to keep a single confident miss finite."""
    if not probabilities:
        return None
    probs = _clip(probabilities)
    truth = np.asarray(outcomes, dtype=float)
    losses = -(truth * np.log(probs) + (1.0 - truth) * np.log(1.0 - probs))
    return round(float(np.mean(losses)), 9)


def base_rate(outcomes: Sequence[int]) -> float | None:
    if not outcomes:
        return None
    return round(float(np.mean(np.asarray(outcomes, dtype=float))), 9)


def brier_skill_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float | None:
    """Brier score relative to always predicting the sample base rate.

    Reported because an impressive-looking Brier score on rare events is
    usually just the base rate wearing a hat.
    """
    if not probabilities:
        return None
    reference = base_rate(outcomes)
    if reference is None:
        return None
    model = brier_score(probabilities, outcomes)
    baseline = brier_score([reference] * len(outcomes), outcomes)
    if model is None or baseline is None or baseline < EPSILON:
        return None
    return round(1.0 - model / baseline, 9)


def roc_auc(probabilities: Sequence[float], outcomes: Sequence[int]) -> float | None:
    """Ranking quality, independent of calibration.

    Reported alongside Brier because the two fail differently: a generator can
    rank well and be wildly over-confident, or be perfectly calibrated and rank
    no better than a coin. Discovery cares about the first.
    """
    if len(probabilities) < 2:
        return None
    truth = np.asarray(outcomes, dtype=int)
    if truth.min() == truth.max():
        return None
    from sklearn.metrics import roc_auc_score

    return round(float(roc_auc_score(truth, np.asarray(probabilities, dtype=float))), 9)


def calibration_curve(
    probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10
) -> list[dict[str, float]]:
    """Equal-width reliability bins."""
    if not probabilities:
        return []
    probs = np.asarray(probabilities, dtype=float)
    truth = np.asarray(outcomes, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    curve: list[dict[str, float]] = []
    for index in range(bins):
        low, high = edges[index], edges[index + 1]
        mask = (probs >= low) & (probs < high if index < bins - 1 else probs <= high)
        count = int(mask.sum())
        if count == 0:
            continue
        curve.append(
            {
                "bin_lower": round(float(low), 6),
                "bin_upper": round(float(high), 6),
                "count": count,
                "mean_predicted": round(float(probs[mask].mean()), 9),
                "observed_frequency": round(float(truth[mask].mean()), 9),
            }
        )
    return curve


def expected_calibration_error(
    probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10
) -> float | None:
    curve = calibration_curve(probabilities, outcomes, bins)
    if not curve:
        return None
    total = sum(entry["count"] for entry in curve)
    error = sum(
        entry["count"] * abs(entry["mean_predicted"] - entry["observed_frequency"])
        for entry in curve
    )
    return round(error / total, 9)


def calibration_slope_intercept(
    probabilities: Sequence[float], outcomes: Sequence[int]
) -> tuple[float | None, float | None]:
    """Logistic recalibration coefficients.

    Slope 1 and intercept 0 mean perfectly calibrated. Slope below 1 means
    over-confident. Returns ``(None, None)`` when one class is missing, which
    happens constantly with rare events and must not be papered over.
    """
    if len(probabilities) < 10:
        return (None, None)
    truth = np.asarray(outcomes, dtype=float)
    if truth.min() == truth.max():
        return (None, None)
    from sklearn.linear_model import LogisticRegression

    probs = _clip(probabilities)
    logits = np.log(probs / (1.0 - probs)).reshape(-1, 1)
    # A very large C is effectively unpenalised and, unlike penalty=None, means
    # the same thing across every supported scikit-learn version.
    model = LogisticRegression(C=1e12, solver="lbfgs", max_iter=1000)
    model.fit(logits, truth.astype(int))
    return (round(float(model.coef_[0][0]), 9), round(float(model.intercept_[0]), 9))


@dataclass(frozen=True)
class BudgetResult:
    budget: int
    selected: int
    hits: int
    positives: int
    recall: float | None
    precision: float | None

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "budget": self.budget,
            "selected": self.selected,
            "hits": self.hits,
            "positives": self.positives,
            "recall": self.recall,
            "precision": self.precision,
        }


def recall_at_budget(scores: Sequence[float], outcomes: Sequence[int], budget: int) -> BudgetResult:
    """Recall when only the top ``budget`` items may be shown to an analyst.

    Ties are broken by position, so the caller controls determinism by passing
    a deterministically ordered sequence.
    """
    positives = int(sum(outcomes))
    if not scores or budget <= 0:
        return BudgetResult(budget, 0, 0, positives, 0.0 if positives else None, None)
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    chosen = order[:budget]
    hits = int(sum(outcomes[index] for index in chosen))
    return BudgetResult(
        budget=budget,
        selected=len(chosen),
        hits=hits,
        positives=positives,
        recall=round(hits / positives, 9) if positives else None,
        precision=round(hits / len(chosen), 9) if chosen else None,
    )


def candidate_recall(
    matched_outcome_ids: Sequence[str], all_outcome_ids: Sequence[str]
) -> float | None:
    """Share of resolvable outcomes that any candidate covered at all.

    This is the discovery-stage ceiling: no amount of scoring can recover an
    outcome that never entered the pool.
    """
    total = len(set(all_outcome_ids))
    if total == 0:
        return None
    return round(len(set(matched_outcome_ids) & set(all_outcome_ids)) / total, 9)


def lead_time_stats(lead_times: Sequence[float]) -> dict[str, float | int | None]:
    """Distribution of warning time on hits, in days."""
    if not lead_times:
        return {"count": 0, "mean": None, "median": None, "p10": None, "p90": None}
    values = np.asarray(lead_times, dtype=float)
    return {
        "count": int(values.size),
        "mean": round(float(values.mean()), 6),
        "median": round(float(np.median(values)), 6),
        "p10": round(float(np.percentile(values, 10)), 6),
        "p90": round(float(np.percentile(values, 90)), 6),
    }


def alerts_per_region_day(alert_count: int, regions: int, days: float) -> float | None:
    """Analyst load, the denominator that makes precision claims comparable."""
    exposure = regions * days
    if exposure <= 0:
        return None
    return round(alert_count / exposure, 9)


def confusion(predicted_positive: Sequence[int], outcomes: Sequence[int]) -> dict[str, int]:
    tp = sum(1 for p, y in zip(predicted_positive, outcomes, strict=True) if p and y)
    fp = sum(1 for p, y in zip(predicted_positive, outcomes, strict=True) if p and not y)
    fn = sum(1 for p, y in zip(predicted_positive, outcomes, strict=True) if not p and y)
    tn = sum(1 for p, y in zip(predicted_positive, outcomes, strict=True) if not p and not y)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def precision_recall_f1(counts: Mapping[str, int]) -> dict[str, float | None]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = round(tp / (tp + fp), 9) if (tp + fp) else None
    recall = round(tp / (tp + fn), 9) if (tp + fn) else None
    # F1 is undefined only when precision or recall is itself undefined -- that
    # is, when nothing was predicted positive or nothing was positive. A model
    # that predicted and was wrong every time has precision 0.0 and F1 0.0; an
    # earlier version reported None there, because 0.0 is falsy, which quietly
    # turned the worst possible score into a missing one.
    if precision is None or recall is None:
        f1: float | None = None
    elif precision + recall == 0.0:
        f1 = 0.0
    else:
        f1 = round(2 * precision * recall / (precision + recall), 9)
    return {"precision": precision, "recall": recall, "f1": f1}


def wilson_interval(successes: int, trials: int, z: float = 1.959963985) -> tuple[float, float]:
    """Wilson score interval, for reporting a rate with an honest range."""
    if trials <= 0:
        return (0.0, 1.0)
    phat = successes / trials
    denominator = 1 + z**2 / trials
    centre = (phat + z**2 / (2 * trials)) / denominator
    margin = (z * math.sqrt(phat * (1 - phat) / trials + z**2 / (4 * trials**2))) / denominator
    return (round(max(centre - margin, 0.0), 9), round(min(centre + margin, 1.0), 9))
