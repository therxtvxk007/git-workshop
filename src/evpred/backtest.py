"""Rolling-origin (walk-forward) backtesting.

Gap G6/G10 in the survey is that the reviewed systems are not validated against
events that actually occurred, partly because doing it properly is expensive.
Doing it *improperly* is the more common failure: a random train/test split over
a time series lets the model train on the future and test on the past, and
inflates every metric reported afterwards.

This harness enforces the discipline:

* folds are contiguous blocks of forecast **origins**, in order;
* the model trains only on origins strictly before the fold's cut date;
* the **embedder is refit per fold on training documents only**, so no corpus
  statistic crosses the cut;
* every group is checked for lookahead documents before it is scored;
* baselines run through the identical split, so comparisons are apples to apples.

An expanding window (default) mimics a system retrained periodically on all
history. A sliding window (``window_days``) mimics one that deliberately forgets,
which is often better under regime change.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from .calibration import coverage_report
from .embedding import Embedder, HashingSVDEmbedder, embed_documents
from .extraction import EventExtractor, RuleExtractor, annotate
from .features import assert_no_lookahead
from .metrics import evaluate
from .schema import BagGroup, Date, Document, Forecast, build_bag_groups
from .stacking import HybridConfig, HybridEventPredictor


@dataclass(slots=True)
class BacktestConfig:
    lookback_days: int = 14
    horizon_days: int = 7
    n_folds: int = 5
    min_train_origins: int = 60
    window_days: int | None = None
    """Sliding-window training length in days; ``None`` = expanding window."""
    embedding_dim: int = 96
    top_k_evidence: int = 5
    verbose: bool = True


@dataclass(slots=True)
class FoldResult:
    fold: int
    train_end: Date
    test_start: Date
    test_end: Date
    n_train: int
    n_test: int
    metrics: dict[str, float]
    branch_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    baseline_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    conformal: dict[str, float] = field(default_factory=dict)
    forecasts: list[Forecast] = field(default_factory=list)


@dataclass(slots=True)
class BacktestResult:
    folds: list[FoldResult]
    pooled: dict[str, float]
    pooled_branches: dict[str, dict[str, float]]
    pooled_baselines: dict[str, dict[str, float]]
    pooled_conformal: dict[str, float]
    forecasts: list[Forecast]
    diagnostics: dict[str, object] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Baselines. Every one of these is cheap; a text model that cannot beat them is
# not earning its complexity, and the survey's summary table has no such floor.
# --------------------------------------------------------------------------

def baseline_base_rate(train: list[BagGroup], test: list[BagGroup]) -> np.ndarray:
    rate = float(np.mean([g.label for g in train])) if train else 0.5
    return np.full(len(test), rate, dtype=np.float64)


def baseline_persistence(train: list[BagGroup], test: list[BagGroup]) -> np.ndarray:
    """Per-region historical rate: the climatology a domain expert would use."""
    per_region: dict[str, list[int]] = {}
    for g in train:
        per_region.setdefault(g.region, []).append(int(g.label))
    overall = float(np.mean([g.label for g in train])) if train else 0.5
    return np.array(
        [float(np.mean(per_region.get(g.region, [overall]))) for g in test],
        dtype=np.float64,
    )


def baseline_volume(train: list[BagGroup], test: list[BagGroup]) -> np.ndarray:
    """Document volume alone, logistic-scaled. Tests whether text *content*
    adds anything over merely counting how much was written."""
    from sklearn.linear_model import LogisticRegression

    def feat(groups: list[BagGroup]) -> np.ndarray:
        return np.array(
            [[np.log1p(g.n_documents), np.log1p(sum(d.n_events for d in g.documents))]
             for g in groups],
            dtype=np.float64,
        )

    y = np.array([g.label for g in train], dtype=np.int64)
    if len(np.unique(y)) < 2:
        return np.full(len(test), float(y.mean()) if y.size else 0.5)
    model = LogisticRegression(max_iter=1000).fit(feat(train), y)
    return model.predict_proba(feat(test))[:, 1]


BASELINES: dict[str, Callable[[list[BagGroup], list[BagGroup]], np.ndarray]] = {
    "base_rate": baseline_base_rate,
    "region_climatology": baseline_persistence,
    "volume_only": baseline_volume,
}


# --------------------------------------------------------------------------

def _fold_cuts(origins: list[Date], n_folds: int, min_train: int) -> list[tuple[int, int]]:
    """Contiguous test blocks after an initial training burn-in."""
    n = len(origins)
    if n <= min_train:
        raise ValueError(
            f"need more than min_train_origins={min_train} distinct origins, got {n}"
        )
    remaining = n - min_train
    n_folds = max(1, min(n_folds, remaining))
    edges = np.linspace(min_train, n, n_folds + 1).astype(int)
    return [(int(edges[i]), int(edges[i + 1])) for i in range(n_folds)
            if edges[i + 1] > edges[i]]


def run_backtest(
    documents: Sequence[Document],
    labels: dict[tuple[str, Date], int],
    config: BacktestConfig | None = None,
    model_config: HybridConfig | None = None,
    extractor: EventExtractor | None = None,
    embedder_factory: Callable[[], Embedder] | None = None,
) -> BacktestResult:
    """Walk-forward evaluation of the hybrid model against baselines."""
    cfg = config or BacktestConfig()
    mcfg = model_config or HybridConfig(
        lookback_days=cfg.lookback_days, half_life_days=5.0
    )
    mcfg.lookback_days = cfg.lookback_days
    extractor = extractor or RuleExtractor()
    embedder_factory = embedder_factory or (
        lambda: HashingSVDEmbedder(dim=cfg.embedding_dim)
    )

    documents = list(documents)
    if cfg.verbose:
        print(f"[backtest] {len(documents)} documents; extracting events...")
    annotate(documents, extractor)

    regions = sorted({d.region for d in documents})
    all_dates = sorted({d.date for d in documents})
    # Valid origins need a full lookback behind and a full horizon ahead.
    origins = [
        d for d in all_dates
        if d - _dt.timedelta(days=cfg.lookback_days) >= all_dates[0]
        and d + _dt.timedelta(days=cfg.horizon_days) <= all_dates[-1]
    ]
    if cfg.verbose:
        print(f"[backtest] {len(regions)} regions, {len(origins)} usable origins")

    cuts = _fold_cuts(origins, cfg.n_folds, cfg.min_train_origins)
    fold_results: list[FoldResult] = []
    all_forecasts: list[Forecast] = []

    for fold_i, (lo, hi) in enumerate(cuts):
        test_origins = origins[lo:hi]
        train_origins = origins[:lo]
        if cfg.window_days is not None:
            floor = test_origins[0] - _dt.timedelta(days=cfg.window_days)
            train_origins = [o for o in train_origins if o >= floor]
        if not train_origins or not test_origins:
            continue

        cut = test_origins[0]
        # Documents usable for TRAINING artefacts: strictly before the first
        # test origin minus the horizon, so no training label peeks past the cut.
        train_doc_cut = cut - _dt.timedelta(days=cfg.horizon_days)
        train_docs = [d for d in documents if d.date < train_doc_cut]
        if len(train_docs) < 20:
            continue

        # Refit the embedder on training text only, then apply to everything.
        embedder = embedder_factory()
        embed_documents(train_docs, embedder, fit=True)
        embed_documents(documents, embedder, fit=False)

        train_groups = [
            g for g in build_bag_groups(documents, train_origins, regions,
                                        cfg.lookback_days, cfg.horizon_days, labels)
            if g.label is not None and g.origin < train_doc_cut
        ]
        test_groups = [
            g for g in build_bag_groups(documents, test_origins, regions,
                                        cfg.lookback_days, cfg.horizon_days, labels)
            if g.label is not None
        ]
        if not train_groups or not test_groups:
            continue
        for g in train_groups + test_groups:
            assert_no_lookahead(g)

        y_test = np.array([g.label for g in test_groups], dtype=np.int64)
        y_train = np.array([g.label for g in train_groups], dtype=np.int64)
        if len(np.unique(y_train)) < 2:
            continue

        if cfg.verbose:
            print(f"[fold {fold_i}] train={len(train_groups)} (<= {train_doc_cut}) "
                  f"test={len(test_groups)} ({test_origins[0]}..{test_origins[-1]}) "
                  f"base_rate={y_test.mean():.3f}")

        model = HybridEventPredictor(mcfg).fit(train_groups)
        forecasts = model.predict(test_groups, top_k_evidence=cfg.top_k_evidence)
        probs = np.array([f.probability for f in forecasts], dtype=np.float64)

        branches = model.branch_probabilities(test_groups)
        branch_metrics = {
            name: evaluate(vals, y_test) for name, vals in branches.items()
        }
        baseline_metrics = {
            name: evaluate(fn(train_groups, test_groups), y_test)
            for name, fn in BASELINES.items()
        }
        conformal = coverage_report([f.conformal_set for f in forecasts], y_test)

        fold_results.append(
            FoldResult(
                fold=fold_i,
                train_end=train_doc_cut,
                test_start=test_origins[0],
                test_end=test_origins[-1],
                n_train=len(train_groups),
                n_test=len(test_groups),
                metrics=evaluate(probs, y_test),
                branch_metrics=branch_metrics,
                baseline_metrics=baseline_metrics,
                conformal=conformal,
                forecasts=forecasts,
            )
        )
        all_forecasts.extend(forecasts)

    if not fold_results:
        raise RuntimeError(
            "no usable folds; try more days, fewer folds, or a lower min_train_origins"
        )

    # Pool across folds on the raw forecasts rather than averaging per-fold
    # metrics: fold-averaged AUC is not the AUC of the pooled predictions, and
    # rare-event folds can be single-class.
    y_all = np.array([f.label for f in all_forecasts], dtype=np.int64)
    p_all = np.array([f.probability for f in all_forecasts], dtype=np.float64)

    def pool(getter: Callable[[FoldResult], dict[str, dict[str, float]]]) -> dict[str, dict[str, float]]:
        names = {k for fr in fold_results for k in getter(fr)}
        return {
            n: _mean_metrics([getter(fr)[n] for fr in fold_results if n in getter(fr)])
            for n in names
        }

    return BacktestResult(
        folds=fold_results,
        pooled=evaluate(p_all, y_all),
        pooled_branches=pool(lambda fr: fr.branch_metrics),
        pooled_baselines=pool(lambda fr: fr.baseline_metrics),
        pooled_conformal=_mean_metrics([fr.conformal for fr in fold_results]),
        forecasts=all_forecasts,
        diagnostics={"n_folds": len(fold_results), "regions": regions},
    )


def _mean_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    keys = {k for r in rows for k in r}
    out: dict[str, float] = {}
    for k in keys:
        vals = [r[k] for r in rows if k in r and not np.isnan(r[k])]
        out[k] = float(np.mean(vals)) if vals else float("nan")
    return out


def summarise(result: BacktestResult) -> str:
    """Comparison table: the stacked model, each branch, and every baseline."""
    rows: list[tuple[str, dict[str, float]]] = [("STACKED (pooled)", result.pooled)]
    rows += [(f"  branch: {k}", v) for k, v in sorted(result.pooled_branches.items())]
    rows += [(f"  baseline: {k}", v) for k, v in sorted(result.pooled_baselines.items())]

    header = f"{'model':<28}{'ROC-AUC':>9}{'PR-AUC':>9}{'lift':>8}{'Brier':>9}{'BSS':>9}{'ECE':>8}"
    lines = [header, "-" * len(header)]
    for name, m in rows:
        lines.append(
            f"{name:<28}{m.get('roc_auc', float('nan')):>9.3f}"
            f"{m.get('pr_auc', float('nan')):>9.3f}"
            f"{m.get('pr_auc_lift', float('nan')):>8.2f}"
            f"{m.get('brier', float('nan')):>9.4f}"
            f"{m.get('brier_skill', float('nan')):>9.3f}"
            f"{m.get('ece', float('nan')):>8.3f}"
        )
    c = result.pooled_conformal
    lines += [
        "-" * len(header),
        f"base rate {result.pooled.get('base_rate', float('nan')):.3f}"
        f"   folds {result.diagnostics.get('n_folds')}"
        f"   forecasts {len(result.forecasts)}",
        f"conformal: coverage {c.get('coverage', float('nan')):.3f}"
        f"  abstention {c.get('abstention', float('nan')):.3f}"
        f"  avg set size {c.get('avg_set_size', float('nan')):.2f}",
    ]
    return "\n".join(lines)
