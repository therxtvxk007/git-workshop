"""Evaluation metrics.

Split by what they measure, because conflating them is how a system gets
reported as good at something it was never tested on:

  retrieval    Recall@k, nDCG@k, MRR -- ranking quality
  probability  Brier, log loss, ECE, reliability -- calibration quality
  operational  FAR at required recall, lead time -- what a desk actually feels

Accuracy is deliberately absent. At a base rate near 1% it is maximised by
predicting "no event" forever, and any system tuned against it will learn to.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

# ------------------------------------------------------------- retrieval ---


def recall_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    """Fraction of relevant items appearing in the top k.

    This is the stage-2 objective and it is measured *before* nDCG on purpose:
    an item the cascade never retrieves cannot be recovered by any amount of
    reranking, so recall is a ceiling on everything downstream.
    """
    if not relevant:
        return float("nan")
    top = set(retrieved[:k])
    return len(top & relevant) / len(relevant)


def precision_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    """Fraction of the top k that is relevant.

    Reported alongside recall rather than instead of it. On this task the
    relevant set is tiny (a handful of precursor documents), so precision@k is
    bounded above by |relevant|/k and a low value at k=50 is arithmetic, not a
    verdict. It is here because an analyst reads a fixed-length list and cares
    what fraction of it is worth reading.
    """
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(1 for d in top if d in relevant) / len(top)


def dcg(gains: Sequence[float]) -> float:
    g = np.asarray(gains, dtype=float)
    if not g.size:
        return 0.0
    discounts = 1.0 / np.log2(np.arange(2, g.size + 2))
    return float((g * discounts).sum())


def ndcg_at_k(retrieved: Sequence[str], relevance: dict[str, float], k: int) -> float:
    gains = [relevance.get(d, 0.0) for d in retrieved[:k]]
    ideal = sorted(relevance.values(), reverse=True)[:k]
    denom = dcg(ideal)
    return float(dcg(gains) / denom) if denom > 0 else float("nan")


def mrr(retrieved: Sequence[str], relevant: set[str]) -> float:
    for i, d in enumerate(retrieved, start=1):
        if d in relevant:
            return 1.0 / i
    return 0.0


@dataclass
class RetrievalReport:
    recall: dict[int, float]
    ndcg: dict[int, float]
    mrr: float
    n_queries: int
    n_empty: int = 0
    precision: dict[int, float] = field(default_factory=dict)
    n_relevant: int = 0                 # summed over evaluated queries
    latency_ms: dict[str, float] = field(default_factory=dict)

    def summary(self) -> dict[str, float | int]:
        out: dict[str, float | int] = {"queries": self.n_queries, "empty": self.n_empty,
                                       "relevant_documents": self.n_relevant}
        for k, v in sorted(self.recall.items()):
            out[f"recall@{k}"] = round(v, 4)
        for k, v in sorted(self.precision.items()):
            out[f"precision@{k}"] = round(v, 4)
        for k, v in sorted(self.ndcg.items()):
            out[f"ndcg@{k}"] = round(v, 4)
        out["mrr"] = round(self.mrr, 4)
        for k, v in sorted(self.latency_ms.items()):
            out[f"latency_ms.{k}"] = round(v, 3)
        return out


def evaluate_retrieval(
    runs: Sequence[tuple[Sequence[str], set[str]]],
    *,
    ks: Sequence[int] = (10, 20, 50, 100),
    graded: Sequence[dict[str, float]] | None = None,
    latency_ms: dict[str, float] | None = None,
) -> RetrievalReport:
    """`runs` is a sequence of (ranked doc ids, relevant doc ids) per query."""
    rec: dict[int, list[float]] = {k: [] for k in ks}
    prec: dict[int, list[float]] = {k: [] for k in ks}
    nd: dict[int, list[float]] = {k: [] for k in ks}
    rr: list[float] = []
    empty = 0
    n_relevant = 0
    for i, (ranked, relevant) in enumerate(runs):
        if not relevant:
            empty += 1
            continue
        n_relevant += len(relevant)
        for k in ks:
            rec[k].append(recall_at_k(ranked, relevant, k))
            prec[k].append(precision_at_k(ranked, relevant, k))
            rel_map = graded[i] if graded else dict.fromkeys(relevant, 1.0)
            nd[k].append(ndcg_at_k(ranked, rel_map, k))
        rr.append(mrr(ranked, relevant))
    return RetrievalReport(
        recall={k: float(np.mean(v)) if v else float("nan") for k, v in rec.items()},
        precision={k: float(np.mean(v)) if v else float("nan") for k, v in prec.items()},
        ndcg={k: float(np.mean(v)) if v else float("nan") for k, v in nd.items()},
        mrr=float(np.mean(rr)) if rr else float("nan"),
        n_queries=len(runs) - empty,
        n_empty=empty,
        n_relevant=n_relevant,
        latency_ms=dict(latency_ms or {}),
    )


# ----------------------------------------------------------- probability ---


def brier(p: np.ndarray, y: np.ndarray) -> float:
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p: np.ndarray, y: np.ndarray, eps: float = 1e-12) -> float:
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def expected_calibration_error(p: np.ndarray, y: np.ndarray, n_bins: int = 15,
                               strategy: str = "quantile") -> float:
    """ECE with quantile bins by default.

    Equal-width bins are the common choice and are misleading at low base rates:
    almost every prediction lands in the first bin, so the reported error is
    dominated by one bucket and the tail -- where the alerts are -- is invisible.
    """
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    if p.size == 0:
        return float("nan")
    if strategy == "quantile":
        edges = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
        if edges.size < 2:
            return float(abs(p.mean() - y.mean()))
    else:
        edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=True), 0, len(edges) - 2)
    total = 0.0
    for b in range(len(edges) - 1):
        m = idx == b
        if not m.any():
            continue
        total += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(total)


def reliability_curve(p: np.ndarray, y: np.ndarray, n_bins: int = 10
                      ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (mean predicted, observed frequency, bin weight)."""
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    edges = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
    if edges.size < 2:
        return np.array([p.mean()]), np.array([y.mean()]), np.array([1.0])
    idx = np.clip(np.digitize(p, edges[1:-1], right=True), 0, len(edges) - 2)
    pred, obs, w = [], [], []
    for b in range(len(edges) - 1):
        m = idx == b
        if not m.any():
            continue
        pred.append(p[m].mean())
        obs.append(y[m].mean())
        w.append(m.mean())
    return np.array(pred), np.array(obs), np.array(w)


# ----------------------------------------------------------- operational ---


def far_at_recall(p: np.ndarray, y: np.ndarray, required_recall: float = 1.0
                  ) -> tuple[float, float]:
    """False-alarm rate at the threshold that just achieves `required_recall`.

    This is the headline operating number: given that we must not miss events,
    how many false candidates does the desk have to work through? Returns
    (false alarm rate, threshold).
    """
    p = np.asarray(p, float)
    y = np.asarray(y, int)
    pos = p[y == 1]
    neg = p[y == 0]
    if pos.size == 0:
        return float("nan"), float("nan")
    # Highest threshold still capturing the required fraction of positives.
    thr = float(np.quantile(pos, max(0.0, 1.0 - required_recall)))
    far = float((neg >= thr).mean()) if neg.size else 0.0
    return far, thr


def lead_time_days(
    alert_times: Sequence[float], event_times: Sequence[float]
) -> dict[str, float]:
    """Distribution of warning time. A system with excellent recall and a mean
    lead time of one day has not warned anybody about anything."""
    leads = [e - a for a, e in zip(alert_times, event_times, strict=True) if e >= a]
    if not leads:
        return {"n": 0, "mean": float("nan"), "median": float("nan"),
                "p10": float("nan"), "p90": float("nan")}
    arr = np.asarray(leads, float)
    return {"n": int(arr.size), "mean": float(arr.mean()),
            "median": float(np.median(arr)), "p10": float(np.quantile(arr, 0.1)),
            "p90": float(np.quantile(arr, 0.9))}


def coverage(prediction_sets: Sequence[set[str]], truths: Sequence[set[str]]) -> float:
    """Fraction of true events captured by the prediction sets (macro over
    forecasts, so a single busy day cannot dominate)."""
    vals = []
    for pred, truth in zip(prediction_sets, truths, strict=True):
        if not truth:
            continue
        vals.append(len(pred & truth) / len(truth))
    return float(np.mean(vals)) if vals else float("nan")


def set_size(prediction_sets: Sequence[set[str]]) -> dict[str, float]:
    sizes = np.array([len(s) for s in prediction_sets], dtype=float)
    if not sizes.size:
        return {"mean": float("nan"), "median": float("nan"), "max": float("nan")}
    return {"mean": float(sizes.mean()), "median": float(np.median(sizes)),
            "max": float(sizes.max())}
