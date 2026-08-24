"""Tests for calibration and conformal abstention."""

import numpy as np
import pytest

from evpred.calibration import Calibrator, SplitConformal, coverage_report
from evpred.metrics import brier_skill_score, expected_calibration_error, evaluate


@pytest.fixture
def scored():
    rng = np.random.default_rng(0)
    y = rng.binomial(1, 0.25, 1200)
    s = rng.normal(loc=1.8 * y, scale=1.0)
    return s, y


def test_calibration_improves_brier_on_held_out_data(scored):
    s, y = scored
    cal = Calibrator("isotonic").fit(s[:600], y[:600])
    p = cal.transform(s[600:])
    naive = 1.0 / (1.0 + np.exp(-s[600:]))  # raw logit squashed, uncalibrated
    assert np.mean((p - y[600:]) ** 2) < np.mean((naive - y[600:]) ** 2)


def test_calibrated_probabilities_beat_climatology(scored):
    s, y = scored
    cal = Calibrator("isotonic").fit(s[:600], y[:600])
    assert brier_skill_score(cal.transform(s[600:]), y[600:]) > 0.1


def test_isotonic_falls_back_to_platt_on_small_samples(scored):
    s, y = scored
    assert Calibrator("isotonic", min_isotonic=50).fit(s[:20], y[:20]).fitted_method == "platt"
    assert Calibrator("isotonic", min_isotonic=50).fit(s, y).fitted_method == "isotonic"


def test_single_class_calibration_degrades_gracefully():
    cal = Calibrator("isotonic").fit(np.linspace(-2, 2, 40), np.zeros(40, dtype=int))
    assert cal.fitted_method == "none"
    out = cal.transform(np.array([-3.0, 0.0, 3.0]))
    assert np.all((out >= 0) & (out <= 1))  # logits squashed, not passed through


def test_conformal_coverage_meets_the_target(scored):
    s, y = scored
    cal = Calibrator("isotonic").fit(s[:400], y[:400])
    p = cal.transform(s[400:])
    conf = SplitConformal(alpha=0.1, mondrian=False).fit(p[:400], y[400:800])
    report = coverage_report(conf.predict_set(p[400:]), y[800:])
    assert report["coverage"] >= 0.85  # target 0.90, finite-sample slack


def test_mondrian_conformal_protects_the_minority_class(scored):
    """Class-conditional thresholds trade marginal coverage for minority coverage.

    This is the reason mondrian is the default: with a rare positive class a
    single marginal threshold can look fine overall while covering few true
    positives, which is exactly the case a forecasting system must not fail.
    """
    s, y = scored
    cal = Calibrator("isotonic").fit(s[:400], y[:400])
    p = cal.transform(s[400:])
    y_cal, y_test = y[400:800], y[800:]
    marginal = SplitConformal(alpha=0.1, mondrian=False).fit(p[:400], y_cal)
    classwise = SplitConformal(alpha=0.1, mondrian=True).fit(p[:400], y_cal)

    def positive_coverage(model):
        sets = model.predict_set(p[400:])
        pos = [s_ for s_, t in zip(sets, y_test) if t == 1]
        return float(np.mean([1 in s_ for s_ in pos]))

    assert positive_coverage(classwise) >= positive_coverage(marginal) - 1e-9
    assert positive_coverage(classwise) >= 0.85


def test_tighter_alpha_widens_the_prediction_sets(scored):
    s, y = scored
    cal = Calibrator("isotonic").fit(s[:400], y[:400])
    p = cal.transform(s[400:])
    strict = SplitConformal(alpha=0.01).fit(p[:400], y[400:800])
    loose = SplitConformal(alpha=0.3).fit(p[:400], y[400:800])
    s_strict = coverage_report(strict.predict_set(p[400:]), y[800:])
    s_loose = coverage_report(loose.predict_set(p[400:]), y[800:])
    assert s_strict["avg_set_size"] >= s_loose["avg_set_size"]


def test_conformal_rejects_invalid_alpha():
    for bad in (0.0, 1.0, -0.5, 2.0):
        with pytest.raises(ValueError):
            SplitConformal(alpha=bad)


def test_ece_is_zero_for_perfectly_calibrated_predictions():
    rng = np.random.default_rng(3)
    p = rng.uniform(0, 1, 40000)
    y = rng.binomial(1, p)
    assert expected_calibration_error(p, y) < 0.02


def test_metrics_survive_a_single_class_window():
    out = evaluate(np.array([0.2, 0.3, 0.4]), np.array([0, 0, 0]))
    assert out["n"] == 3.0
    assert np.isnan(out["roc_auc"])
    assert not np.isnan(out["brier"])  # still defined
