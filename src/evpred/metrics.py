"""Forecast evaluation metrics.

Accuracy is deliberately not the headline. Societal-event forecasting is
class-imbalanced: with a 15% base rate, always predicting "no" scores 85%
accuracy and is worthless. The survey reports accuracy and F1 for several of the
systems it covers without stating base rates, which makes those numbers hard to
interpret. This module reports:

* **ROC-AUC** -- ranking quality, insensitive to threshold and base rate.
* **PR-AUC with lift over base rate** -- the honest imbalanced-data metric.
* **Brier score and skill** vs. the climatological base rate -- does the
  probability beat "just say the historical rate every time"?
* **Expected calibration error** -- are the probabilities meaningful?
* **Precision@k** -- the operationally relevant quantity when an analyst can
  only review the top few alerts per week.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    roc_auc_score,
)


def expected_calibration_error(
    probabilities: np.ndarray, labels: np.ndarray, n_bins: int = 10
) -> float:
    """Equal-width binned |confidence - accuracy|, weighted by bin population."""
    p = np.asarray(probabilities, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.float64).ravel()
    if p.size == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        mask = idx == b
        if not mask.any():
            continue
        ece += (mask.mean()) * abs(p[mask].mean() - y[mask].mean())
    return float(ece)


def precision_at_k(probabilities: np.ndarray, labels: np.ndarray, k: int) -> float:
    """Fraction of true positives among the ``k`` highest-probability forecasts."""
    p = np.asarray(probabilities, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.int64).ravel()
    if p.size == 0 or k <= 0:
        return float("nan")
    k = min(k, p.size)
    top = np.argsort(-p)[:k]
    return float(y[top].mean())


def brier_skill_score(probabilities: np.ndarray, labels: np.ndarray) -> float:
    """Brier skill relative to always predicting the base rate.

    ``> 0`` means the model beats climatology; ``<= 0`` means it does not, no
    matter how good the AUC looks.
    """
    p = np.asarray(probabilities, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.float64).ravel()
    if p.size == 0:
        return float("nan")
    base = float(y.mean())
    bs = float(np.mean((p - y) ** 2))
    bs_ref = float(np.mean((base - y) ** 2))
    return float(1.0 - bs / bs_ref) if bs_ref > 0 else float("nan")


def evaluate(
    probabilities: np.ndarray,
    labels: np.ndarray,
    threshold: float = 0.5,
    k: int = 20,
) -> dict[str, float]:
    p = np.asarray(probabilities, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.int64).ravel()
    out: dict[str, float] = {
        "n": float(p.size),
        "base_rate": float(y.mean()) if y.size else float("nan"),
    }
    if p.size == 0 or len(np.unique(y)) < 2:
        # Single-class evaluation windows are common in rare-event backtests;
        # report what is defined rather than raising.
        out.update({m: float("nan") for m in
                    ("roc_auc", "pr_auc", "pr_auc_lift", "f1", "brier",
                     "brier_skill", "ece", f"precision_at_{k}")})
        if p.size:
            out["brier"] = float(np.mean((p - y) ** 2))
        return out

    out["roc_auc"] = float(roc_auc_score(y, p))
    pr = float(average_precision_score(y, p))
    out["pr_auc"] = pr
    out["pr_auc_lift"] = float(pr / out["base_rate"]) if out["base_rate"] > 0 else float("nan")
    out["f1"] = float(f1_score(y, (p >= threshold).astype(int), zero_division=0))
    out["brier"] = float(brier_score_loss(y, p))
    out["brier_skill"] = brier_skill_score(p, y)
    out["ece"] = expected_calibration_error(p, y)
    out[f"precision_at_{k}"] = precision_at_k(p, y, k)
    return out


def format_metrics(metrics: dict[str, float], title: str = "") -> str:
    head = f"{title}\n" if title else ""
    order = ["n", "base_rate", "roc_auc", "pr_auc", "pr_auc_lift", "f1",
             "brier", "brier_skill", "ece"]
    rows = []
    for key in order:
        if key in metrics:
            rows.append(f"  {key:<14} {metrics[key]:.4f}")
    for key, val in metrics.items():
        if key.startswith("precision_at_"):
            rows.append(f"  {key:<14} {val:.4f}")
    return head + "\n".join(rows)
