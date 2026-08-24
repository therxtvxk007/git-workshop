"""Metrics verified against hand-computable cases.

A metric implementation that is only ever checked against its own output is
worthless; each test here fixes an expected value that can be derived by hand.
"""

from __future__ import annotations

import numpy as np
import pytest

from pramaan_x.eval.metrics import (
    brier,
    coverage,
    evaluate_retrieval,
    expected_calibration_error,
    far_at_recall,
    lead_time_days,
    log_loss,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    set_size,
)


def test_recall_at_k_hand_computed():
    assert recall_at_k(["a", "b", "c", "d"], {"c", "d", "z"}, 4) == pytest.approx(2 / 3)
    assert recall_at_k(["a", "b", "c", "d"], {"c", "d", "z"}, 2) == 0.0


def test_recall_of_empty_relevant_is_nan():
    assert np.isnan(recall_at_k(["a"], set(), 1))


def test_precision_at_k():
    assert precision_at_k(["a", "b", "c"], {"a", "c"}, 3) == pytest.approx(2 / 3)
    assert precision_at_k([], {"a"}, 3) == 0.0


def test_ndcg_is_one_for_perfect_ranking():
    rel = {"a": 3.0, "b": 2.0, "c": 1.0}
    assert ndcg_at_k(["a", "b", "c"], rel, 3) == pytest.approx(1.0)


def test_ndcg_penalises_inversion():
    rel = {"a": 3.0, "b": 2.0, "c": 1.0}
    assert ndcg_at_k(["c", "b", "a"], rel, 3) < ndcg_at_k(["a", "b", "c"], rel, 3)


def test_mrr():
    assert mrr(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)
    assert mrr(["x"], {"a"}) == 0.0


def test_evaluate_retrieval_skips_empty_queries():
    rep = evaluate_retrieval([(["a"], {"a"}), (["b"], set())], ks=(1,))
    assert rep.n_queries == 1 and rep.n_empty == 1
    assert rep.recall[1] == 1.0


def test_brier_and_log_loss_bounds():
    y = np.array([1, 0, 1, 0])
    assert brier(y.astype(float), y) == 0.0
    assert brier(np.full(4, 0.5), y) == pytest.approx(0.25)
    assert log_loss(np.full(4, 0.5), y) == pytest.approx(np.log(2), rel=1e-6)


def test_ece_zero_for_calibrated_predictions():
    rng = np.random.default_rng(0)
    p = rng.random(20000)
    y = (rng.random(20000) < p).astype(int)
    assert expected_calibration_error(p, y) < 0.02


def test_ece_detects_miscalibration():
    rng = np.random.default_rng(0)
    p = rng.random(20000)
    y = (rng.random(20000) < p).astype(int)
    assert expected_calibration_error(np.clip(p * 0.4, 0, 1), y) > 0.15


def test_far_at_full_recall_uses_lowest_positive():
    """At 100% required recall the threshold must sit at or below the weakest
    true positive -- otherwise the recall constraint is not actually met."""
    p = np.array([0.9, 0.8, 0.2, 0.75, 0.1, 0.05])
    y = np.array([1, 1, 1, 0, 0, 0])
    far, thr = far_at_recall(p, y, 1.0)
    assert thr <= 0.2
    assert far == pytest.approx(1 / 3)


def test_far_decreases_as_required_recall_falls():
    rng = np.random.default_rng(1)
    p = rng.random(4000)
    y = (rng.random(4000) < p).astype(int)
    assert far_at_recall(p, y, 0.8)[0] < far_at_recall(p, y, 1.0)[0]


def test_lead_time_ignores_alerts_after_the_event():
    out = lead_time_days([0, 5, 10], [7, 3, 20])
    assert out["n"] == 2
    assert out["mean"] == pytest.approx(8.5)


def test_coverage_and_set_size():
    preds = [{"a", "b"}, {"c"}]
    truths = [{"a"}, {"c", "d"}]
    assert coverage(preds, truths) == pytest.approx((1.0 + 0.5) / 2)
    assert set_size(preds)["mean"] == pytest.approx(1.5)
