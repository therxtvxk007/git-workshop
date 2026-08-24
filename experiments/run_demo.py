"""End-to-end demonstration on simulated data.

Runs the full pipeline -- extraction, embedding, nested MIL + gradient boosting
stack, calibration, conformal abstention, evidence -- under a rolling-origin
backtest, and reports it against three baselines and an achievability ceiling.

    python experiments/run_demo.py --regions 6 --days 300 --folds 4

Everything here is simulated. Read docs/04-limitations.md before quoting any
number this prints.
"""

from __future__ import annotations

import argparse
import time

import numpy as np

from evpred import (
    BacktestConfig,
    HybridConfig,
    SimConfig,
    make_dataset,
    run_backtest,
    summarise,
)
from evpred.evidence import aggregate_precursor_actions, precursor_report
from evpred.metrics import evaluate


def precursor_recall(result, documents, top_k: int = 5) -> dict[str, float]:
    """How often recovered evidence is a genuine precursor.

    Measurable only because the simulator records which documents came from the
    escalation process. Compared against the corpus-wide precursor rate, which
    is what picking documents at random would achieve.
    """
    truth = {d.doc_id: bool(d.meta.get("is_precursor")) for d in documents}
    hits = total = 0
    for f in result.forecasts:
        if f.label != 1:
            continue  # only ask about forecasts where something did happen
        for p in f.precursors[:top_k]:
            total += 1
            hits += int(truth.get(p.doc_id, False))
    corpus_rate = float(np.mean(list(truth.values()))) if truth else float("nan")
    precision = (hits / total) if total else float("nan")
    return {
        "precursor_precision_at_k": precision,
        "corpus_precursor_rate": corpus_rate,
        "lift_over_random": (precision / corpus_rate) if total and corpus_rate else float("nan"),
        "n_evaluated": float(total),
    }


def oracle_ceiling(sim, result) -> dict[str, float]:
    """Metrics for a forecaster that can see the hidden state."""
    oracle, truth = [], []
    for f in result.forecasts:
        t = (f.origin - sim.config.start).days
        x = sim.tension[f.region]
        p_none = 1.0
        for k in range(f.horizon_days):
            if 0 <= t + k < sim.config.n_days:
                p_none *= 1.0 - min(
                    0.9, sim.config.event_floor + sim.config.event_gain * x[t + k]
                )
        oracle.append(1.0 - p_none)
        truth.append(f.label)
    return evaluate(np.array(oracle), np.array(truth))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", type=int, default=6)
    ap.add_argument("--days", type=int, default=300)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--min-train", type=int, default=90)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--half-life", type=float, default=5.0)
    args = ap.parse_args()

    t0 = time.time()
    sim, documents, labels = make_dataset(
        SimConfig(n_regions=args.regions, n_days=args.days, seed=args.seed)
    )
    print(f"simulated {len(documents)} documents / {args.regions} regions / "
          f"{args.days} days  ({time.time() - t0:.1f}s)")

    result = run_backtest(
        documents,
        labels,
        BacktestConfig(
            n_folds=args.folds,
            min_train_origins=args.min_train,
            lookback_days=14,
            horizon_days=7,
            verbose=True,
        ),
        model_config=HybridConfig(lookback_days=14, half_life_days=args.half_life),
    )

    print("\n" + "=" * 78)
    print("BACKTEST  (rolling origin, walk-forward)")
    print("=" * 78)
    print(summarise(result))

    ceiling = oracle_ceiling(sim, result)
    print(f"\nlatent-state oracle (achievability ceiling): "
          f"ROC-AUC {ceiling['roc_auc']:.3f}  PR-AUC {ceiling['pr_auc']:.3f}")
    print("  the model reads text; the oracle reads the hidden state that generated it.")

    print("\n" + "=" * 78)
    print("PRECURSOR RECOVERY")
    print("=" * 78)
    for k, v in precursor_recall(result, documents).items():
        print(f"  {k:<28} {v:.4f}")
    print("\n  attribution mass by event predicate:")
    for action, mass in aggregate_precursor_actions(result.forecasts, top_n=10):
        print(f"    {action:<16} {mass:.3f}")

    print("\n" + "=" * 78)
    print("SAMPLE FORECASTS WITH EVIDENCE")
    print("=" * 78)
    for f in sorted(result.forecasts, key=lambda f: -f.probability)[:2]:
        print(precursor_report(f))
        print()
    abstained = [f for f in result.forecasts if f.abstained]
    if abstained:
        print(f"({len(abstained)}/{len(result.forecasts)} forecasts abstained; example:)")
        print(precursor_report(abstained[0]))

    print(f"\ntotal wall time {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
