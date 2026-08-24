"""Tests for the nested MIL core.

The pooling gradient is both the training signal and the evidence the system
shows a user, so it is verified numerically rather than assumed.
"""

import numpy as np
import pytest

from evpred.nmil import NestedMIL, NestedMILConfig, PooledGroup, check_gradient


def make_groups(n=40, d=6, n_bags=3, seed=0, regions=("a", "b")):
    rng = np.random.default_rng(seed)
    groups = []
    for i in range(n):
        k = int(rng.integers(3, 9))
        X = rng.normal(size=(k, d))
        bag_index = rng.integers(0, n_bags, size=k)
        label = int(X[:, 0].max() > 0.8)
        groups.append(
            PooledGroup(X=X, bag_index=bag_index, n_bags=n_bags,
                        region=regions[i % len(regions)], label=label)
        )
    return groups


def test_analytic_gradient_matches_finite_differences():
    model = NestedMIL(NestedMILConfig(lambda_global=0.1, lambda_task=0.5))
    assert check_gradient(model, make_groups()) < 1e-6


def test_gradient_correct_with_many_regions():
    model = NestedMIL(NestedMILConfig(lambda_global=0.3, lambda_task=2.0))
    groups = make_groups(n=30, regions=("a", "b", "c", "d"))
    assert check_gradient(model, groups) < 1e-6


def test_attributions_form_a_distribution():
    model = NestedMIL().fit(make_groups())
    for group in make_groups(n=5, seed=7):
        attribution = model.attributions(group)
        assert attribution.shape[0] == group.X.shape[0]
        assert np.all(attribution >= 0)
        assert attribution.sum() == pytest.approx(1.0, abs=1e-9)


def test_pooling_between_mean_and_max():
    """Smooth-max must sit between the mean and the max of instance scores."""
    model = NestedMIL(NestedMILConfig(tau_instance=0.5, tau_bag=0.5))
    scores = np.array([-1.0, 0.0, 2.0, 0.5])
    members = [np.array([0, 1]), np.array([2, 3])]
    pooled, attribution = model._pool(scores, members)
    assert scores.mean() <= pooled <= scores.max()
    assert attribution.sum() == pytest.approx(1.0)


def test_low_temperature_approaches_max():
    hot = NestedMIL(NestedMILConfig(tau_instance=5.0, tau_bag=5.0))
    cold = NestedMIL(NestedMILConfig(tau_instance=0.02, tau_bag=0.02))
    scores = np.array([-1.0, 0.0, 3.0, 0.5])
    members = [np.array([0, 1, 2, 3])]
    assert cold._pool(scores, members)[0] > hot._pool(scores, members)[0]
    assert cold._pool(scores, members)[0] == pytest.approx(scores.max(), abs=0.1)


def test_multitask_shrinkage_is_monotone():
    """Larger lambda_task must pull region heads closer to the shared trunk."""
    groups = make_groups(n=60, seed=3)
    loose = NestedMIL(NestedMILConfig(lambda_task=0.01)).fit(groups)
    tight = NestedMIL(NestedMILConfig(lambda_task=100.0)).fit(groups)
    assert max(tight.region_divergence().values()) < max(loose.region_divergence().values())


def test_unseen_region_falls_back_to_shared_trunk():
    model = NestedMIL().fit(make_groups(regions=("a", "b")))
    unseen = make_groups(n=3, seed=11, regions=("brand-new-region",))
    probs = model.predict_proba(unseen)
    assert probs.shape == (3,)
    assert np.all(np.isfinite(probs))
    assert np.all((probs >= 0) & (probs <= 1))


def test_empty_group_uses_region_bias_only():
    groups = make_groups()
    model = NestedMIL().fit(groups)
    empty = PooledGroup(X=np.zeros((0, 6)), bag_index=np.zeros(0, dtype=int),
                        n_bags=0, region="a", label=None)
    p = model.predict_proba([empty])
    assert p.shape == (1,) and 0.0 <= p[0] <= 1.0
    assert model.attributions(empty).size == 0


def test_fit_rejects_unlabelled_and_inconsistent_input():
    with pytest.raises(ValueError):
        NestedMIL().fit([])
    mixed = make_groups(n=4)
    mixed[1].X = np.zeros((3, 99))
    with pytest.raises(ValueError, match="inconsistent"):
        NestedMIL().fit(mixed)


def test_predict_before_fit_raises():
    with pytest.raises(RuntimeError):
        NestedMIL().predict_proba(make_groups(n=2))


def test_separable_problem_is_learned():
    """A clean signal in feature 0 should be learnable to high AUC."""
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(5)
    groups = []
    for i in range(120):
        k = int(rng.integers(4, 10))
        X = rng.normal(scale=0.3, size=(k, 4))
        label = int(i % 2 == 0)
        if label:  # plant one strongly positive instance -- classic MIL setup
            X[rng.integers(0, k), 0] += 4.0
        groups.append(PooledGroup(X=X, bag_index=rng.integers(0, 3, size=k),
                                  n_bags=3, region="a", label=label))
    model = NestedMIL(NestedMILConfig(lambda_global=0.01, lambda_task=0.01)).fit(groups)
    auc = roc_auc_score([g.label for g in groups], model.predict_proba(groups))
    assert auc > 0.95


def test_attribution_finds_the_planted_instance():
    """The witness instance should carry most of the attribution mass."""
    rng = np.random.default_rng(9)
    groups = []
    for i in range(120):
        k = 6
        X = rng.normal(scale=0.3, size=(k, 4))
        label = int(i % 2 == 0)
        if label:
            X[2, 0] += 4.0
        groups.append(PooledGroup(X=X, bag_index=np.array([0, 0, 1, 1, 2, 2]),
                                  n_bags=3, region="a", label=label))
    model = NestedMIL(NestedMILConfig(lambda_global=0.01, lambda_task=0.01)).fit(groups)
    positives = [g for g in groups if g.label == 1][:10]
    top_is_planted = [int(np.argmax(model.attributions(g)) == 2) for g in positives]
    assert sum(top_is_planted) >= 8
