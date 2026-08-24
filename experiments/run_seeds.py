"""Multi-seed evaluation.

A single walk-forward run of this system has four folds of a few hundred windows
each at a ~20% base rate. That is not enough to rank models: two runs of the
same configuration on different simulator seeds moved the stacked ROC-AUC from
0.623 to 0.572 and flipped whether it beat the volume-only baseline. Reporting
one seed would be exactly the validation weakness the survey criticises (gaps G6
and G10), so this script runs several and reports the spread.

    python experiments/run_seeds.py --seeds 8

Prints, for every model and baseline, mean +/- standard deviation across seeds,
and how often each beats the strongest baseline.
"""

from __future__ import annotations

import argparse
import time

import numpy as np

from evpred import BacktestConfig, HybridConfig, SimConfig, make_dataset, run_backtest
from evpred.backtest import _mean_metrics


def run_one(seed: int, args) -> dict[str, dict[str, float]]:
    _, documents, labels = make_dataset(
        SimConfig(n_regions=args.regions, n_days=args.days, seed=seed)
    )
    result = run_backtest(
        documents,
        labels,
        BacktestConfig(
            n_folds=args.folds, min_train_origins=args.min_train,
            lookback_days=14, horizon_days=7, verbose=False,
        ),
        model_config=HybridConfig(lookback_days=14),
    )
    rows = {"STACKED": _mean_metrics([fr.metrics for fr in result.folds])}
    rows.update({f"branch:{k}": v for k, v in result.pooled_branches.items()
                 if k != "stacked"})
    rows.update({f"baseline:{k}": v for k, v in result.pooled_baselines.items()})
    rows["_conformal"] = result.pooled_conformal
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--regions", type=int, default=6)
    ap.add_argument("--days", type=int, default=300)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--min-train", type=int, default=90)
    args = ap.parse_args()

    t0 = time.time()
    runs = []
    for seed in range(args.seeds):
        runs.append(run_one(seed, args))
        print(f"  seed {seed} done ({time.time() - t0:.0f}s)", flush=True)

    names = [k for k in runs[0] if not k.startswith("_")]
    metrics = ("roc_auc", "pr_auc", "brier", "brier_skill", "ece")

    print(f"\n{args.seeds} seeds x {args.folds} folds, "
          f"{args.regions} regions, {args.days} days\n")
    header = f"{'model':<30}" + "".join(f"{m:>18}" for m in metrics)
    print(header)
    print("-" * len(header))
    table = {}
    for name in names:
        row = f"{name:<30}"
        table[name] = {}
        for m in metrics:
            vals = np.array([r[name].get(m, np.nan) for r in runs], dtype=float)
            vals = vals[np.isfinite(vals)]
            table[name][m] = vals
            row += f"{vals.mean():>11.3f}+-{vals.std():<5.3f}" if vals.size else f"{'n/a':>18}"
        print(row)

    # Is the system actually better than the best baseline, seed by seed?
    baselines = [n for n in names if n.startswith("baseline:")]
    best_base = max(baselines, key=lambda n: table[n]["roc_auc"].mean())
    stacked = table["STACKED"]["roc_auc"]
    base = table[best_base]["roc_auc"]
    wins = int(np.sum(stacked > base))
    diff = stacked - base
    print("\n" + "-" * len(header))
    print(f"strongest baseline: {best_base}  (mean ROC-AUC {base.mean():.3f})")
    print(f"STACKED beats it on {wins}/{len(stacked)} seeds; "
          f"mean difference {diff.mean():+.3f} +- {diff.std():.3f}")
    # Paired across seeds, so the seed-to-seed variance cancels.
    if diff.size > 1 and diff.std() > 0:
        t = diff.mean() / (diff.std(ddof=1) / np.sqrt(diff.size))
        print(f"paired t across seeds: t = {t:+.2f} (|t| > 2.4 is suggestive at n=8)")

    cov = np.array([r["_conformal"]["coverage"] for r in runs])
    abst = np.array([r["_conformal"]["abstention"] for r in runs])
    print(f"conformal coverage {cov.mean():.3f} +- {cov.std():.3f} "
          f"(target 0.900), abstention {abst.mean():.3f} +- {abst.std():.3f}")
    print(f"\ntotal {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
