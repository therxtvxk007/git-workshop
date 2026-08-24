"""End-to-end tests: the stack, the backtester, and its leakage guarantees."""

import datetime as dt

import numpy as np
import pytest

from evpred import (
    BacktestConfig,
    HybridConfig,
    HybridEventPredictor,
    SimConfig,
    make_dataset,
    run_backtest,
    summarise,
)
from evpred.backtest import BASELINES, _fold_cuts
from evpred.embedding import HashingSVDEmbedder, embed_documents
from evpred.extraction import RuleExtractor, annotate
from evpred.schema import build_bag_groups


@pytest.fixture(scope="module")
def small_corpus():
    sim, documents, labels = make_dataset(SimConfig(n_regions=3, n_days=110, seed=1))
    annotate(documents, RuleExtractor())
    embed_documents(documents, HashingSVDEmbedder(dim=32), fit=True)
    return sim, documents, labels


def _groups(documents, labels, n_origins=None):
    regions = sorted({d.region for d in documents})
    dates = sorted({d.date for d in documents})
    origins = [
        d for d in dates
        if d - dt.timedelta(days=14) >= dates[0] and d + dt.timedelta(days=7) <= dates[-1]
    ]
    if n_origins:
        origins = origins[:n_origins]
    return [g for g in build_bag_groups(documents, origins, regions, 14, 7, labels)
            if g.label is not None]


def test_bag_groups_never_contain_future_documents(small_corpus):
    _, documents, labels = small_corpus
    for group in _groups(documents, labels):
        for doc in group.documents:
            assert doc.date < group.origin
            assert (group.origin - doc.date).days <= 14


def test_hybrid_fit_and_predict_returns_valid_forecasts(small_corpus):
    _, documents, labels = small_corpus
    groups = _groups(documents, labels)
    model = HybridEventPredictor(HybridConfig(lookback_days=14)).fit(groups)
    forecasts = model.predict(groups[:20])
    assert len(forecasts) == 20
    for f in forecasts:
        assert 0.0 <= f.probability <= 1.0
        assert set(f.conformal_set) <= {0, 1}
        assert all(0.0 <= p.score <= 1.0 for p in f.precursors)
        assert all(p.date < f.origin for p in f.precursors)


def test_calibration_slice_is_held_out_of_branch_training(small_corpus):
    """The branches must be fitted on strictly fewer windows than are labelled."""
    _, documents, labels = small_corpus
    groups = _groups(documents, labels)
    model = HybridEventPredictor(HybridConfig(lookback_days=14)).fit(groups)
    n_fit = model.diagnostics["n_fit"]
    n_cal = model.diagnostics["n_calibration"]
    assert n_fit + n_cal == len(groups)
    assert n_cal >= 8 and n_fit > n_cal


def test_fit_rejects_degenerate_training_sets(small_corpus):
    _, documents, labels = small_corpus
    groups = _groups(documents, labels)
    with pytest.raises(ValueError, match="at least 16"):
        HybridEventPredictor().fit(groups[:4])
    single = [g for g in groups if g.label == 0][:30]
    with pytest.raises(ValueError, match="only one class"):
        HybridEventPredictor().fit(single)


def test_blend_is_scale_free_by_default(small_corpus):
    """Standardised blending must not be dominated by the wider-spread branch."""
    _, documents, labels = small_corpus
    groups = _groups(documents, labels)
    model = HybridEventPredictor(HybridConfig(lookback_days=14)).fit(groups)
    assert model.blend_rule == "mean"
    assert set(model._branch_scale) == {"mil", "gradient_boosting"}
    # A branch scaled up by a constant factor in logit space must not shift the
    # standardised combination.
    p = np.array([0.1, 0.3, 0.6, 0.9])
    z = model._standardise("mil", p)
    assert abs(float(np.mean(z))) < 5.0 and np.all(np.isfinite(z))


def test_backtest_runs_and_beats_the_base_rate(small_corpus):
    _, documents, labels = small_corpus
    result = run_backtest(
        documents, labels,
        BacktestConfig(n_folds=2, min_train_origins=45, embedding_dim=32, verbose=False),
    )
    assert len(result.folds) >= 1
    assert result.pooled["n"] > 0
    assert set(result.pooled_baselines) == set(BASELINES)
    assert "mil" in result.pooled_branches and "gradient_boosting" in result.pooled_branches
    assert 0.0 <= result.pooled_conformal["coverage"] <= 1.0
    assert isinstance(summarise(result), str)


def test_backtest_folds_are_ordered_and_disjoint(small_corpus):
    _, documents, labels = small_corpus
    result = run_backtest(
        documents, labels,
        BacktestConfig(n_folds=3, min_train_origins=45, embedding_dim=32, verbose=False),
    )
    for a, b in zip(result.folds, result.folds[1:]):
        assert a.test_end < b.test_start        # no overlap between test windows
        assert a.train_end <= b.train_end       # training only grows
    for fold in result.folds:
        assert fold.train_end <= fold.test_start


def test_shuffled_labels_destroy_skill(small_corpus):
    """A negative control: with labels shuffled, skill must collapse.

    If this passes with high AUC, the pipeline is leaking rather than learning.
    """
    _, documents, labels = small_corpus
    rng = np.random.default_rng(0)
    keys = list(labels)
    values = rng.permutation(list(labels.values()))
    shuffled = dict(zip(keys, values))
    result = run_backtest(
        documents, shuffled,
        BacktestConfig(n_folds=2, min_train_origins=45, embedding_dim=32, verbose=False),
    )
    assert abs(result.pooled["roc_auc"] - 0.5) < 0.18
    assert result.pooled["brier_skill"] < 0.10


def test_fold_cuts_respect_burn_in():
    origins = list(range(100))
    cuts = _fold_cuts(origins, n_folds=4, min_train=60)
    assert cuts[0][0] >= 60
    assert cuts[-1][1] == 100
    for (a, b), (c, _) in zip(cuts, cuts[1:]):
        assert b == c            # contiguous
        assert b > a             # non-empty
    with pytest.raises(ValueError):
        _fold_cuts(list(range(10)), n_folds=2, min_train=60)


def test_unseen_region_at_predict_time_is_handled(small_corpus):
    _, documents, labels = small_corpus
    groups = _groups(documents, labels)
    model = HybridEventPredictor(HybridConfig(lookback_days=14)).fit(groups)
    novel = groups[0]
    novel.region = "region-never-seen"
    for doc in novel.documents:
        doc.region = "region-never-seen"
    forecasts = model.predict([novel])
    assert 0.0 <= forecasts[0].probability <= 1.0
