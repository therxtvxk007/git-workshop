"""Paired resampling statistics.

The tests that matter here are the ones where the statistic must *refuse* to
find an effect: a difference that is real on average but swamped by noise, and a
block bootstrap that widens an interval an i.i.d. bootstrap would have reported
as significant. A statistics module is only useful if it says no.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from fixtures.benchmarks.harness import paired_unit_scores
from pramaanx.benchmarks.statistics import (
    StatisticsError,
    block_bootstrap_ci,
    derive_seed,
    paired_bootstrap_ci,
    paired_effect_size,
    paired_permutation_test,
    summarise,
)


class TestDeriveSeed:
    def test_is_deterministic(self) -> None:
        assert derive_seed("a", 1) == derive_seed("a", 1)

    def test_differs_by_content(self) -> None:
        assert derive_seed("a", 1) != derive_seed("a", 2)

    def test_is_order_sensitive_but_stable(self) -> None:
        assert derive_seed("a", "b") != derive_seed("b", "a")
        assert derive_seed("a", "b") == derive_seed("a", "b")

    def test_fits_in_32_bits(self) -> None:
        assert 0 <= derive_seed("anything") < 2**32


class TestSummarise:
    def test_reports_mean_median_and_sample_std(self) -> None:
        summary = summarise([1.0, 2.0, 3.0, 4.0])
        assert summary.mean == pytest.approx(2.5)
        assert summary.median == pytest.approx(2.5)
        # ddof=1: a sample, not a population.
        assert summary.std == pytest.approx(np.std([1.0, 2.0, 3.0, 4.0], ddof=1))
        assert summary.size == 4

    def test_single_value_has_zero_spread_rather_than_nan(self) -> None:
        assert summarise([2.0]).std == 0.0

    def test_empty_sample_is_refused(self) -> None:
        with pytest.raises(StatisticsError, match="empty"):
            summarise([])


class TestPairedBootstrap:
    def test_is_reproducible_from_the_seed(self) -> None:
        control, challenger = paired_unit_scores()
        first = paired_bootstrap_ci(control, challenger, seed="fixed", resamples=500)
        second = paired_bootstrap_ci(control, challenger, seed="fixed", resamples=500)
        assert first == second

    def test_a_consistent_lift_excludes_no_improvement(self) -> None:
        control, challenger = paired_unit_scores(lift=0.02)
        interval = paired_bootstrap_ci(control, challenger, seed="s", resamples=2000)
        assert interval.excludes_no_improvement
        assert interval.point == pytest.approx(0.02)

    def test_noise_around_zero_does_not_exclude_no_improvement(self) -> None:
        rng = np.random.default_rng(0)
        control = list(rng.normal(0.4, 0.1, size=60))
        challenger = [value + rng.normal(0.0, 0.1) for value in control]
        interval = paired_bootstrap_ci(control, challenger, seed="s", resamples=2000)
        assert not interval.excludes_no_improvement

    def test_direction_is_respected_for_a_lower_is_better_metric(self) -> None:
        # A control of 0.5 and a challenger of 0.4 is an improvement when lower
        # is better, so the improvement must come out positive.
        control = [0.5] * 10
        challenger = [0.4 + 0.001 * index for index in range(10)]
        interval = paired_bootstrap_ci(
            control, challenger, seed="s", resamples=1000, higher_is_better=False
        )
        assert interval.point > 0
        assert interval.excludes_no_improvement

    def test_mismatched_lengths_are_refused(self) -> None:
        with pytest.raises(StatisticsError, match="aligned"):
            paired_bootstrap_ci([1.0, 2.0], [1.0], seed="s")

    def test_empty_input_is_refused(self) -> None:
        with pytest.raises(StatisticsError, match="at least one unit"):
            paired_bootstrap_ci([], [], seed="s")

    def test_excludes_zero_covers_both_directions(self) -> None:
        control = [0.5] * 12
        challenger = [0.4] * 12
        interval = paired_bootstrap_ci(control, challenger, seed="s", resamples=500)
        # Challenger is worse on a higher-is-better metric: the interval is
        # entirely below zero, so it excludes zero but not "no improvement".
        assert interval.excludes_zero
        assert not interval.excludes_no_improvement


class TestBlockBootstrap:
    def test_is_reproducible(self) -> None:
        control, challenger = paired_unit_scores(count=40)
        args = {"seed": "s", "block_length": 4, "resamples": 500}
        assert block_bootstrap_ci(control, challenger, **args) == block_bootstrap_ci(
            control, challenger, **args
        )

    def test_records_its_block_length_in_the_method(self) -> None:
        control, challenger = paired_unit_scores(count=40)
        interval = block_bootstrap_ci(control, challenger, seed="s", block_length=5, resamples=200)
        assert "block_length=5" in interval.method

    def test_widens_the_interval_on_temporally_dependent_units(self) -> None:
        # An autocorrelated difference series: the i.i.d. bootstrap resamples the
        # dependence away and reports an interval that is too narrow. This is the
        # reason the block bootstrap exists, so it is worth asserting.
        rng = np.random.default_rng(7)
        noise = rng.normal(0.0, 0.05, size=200)
        walk = np.cumsum(noise)
        control = list(0.4 + walk)
        challenger = [value + 0.001 for value in control]
        iid = paired_bootstrap_ci(control, challenger, seed="s", resamples=2000)
        blocked = block_bootstrap_ci(control, challenger, seed="s", block_length=20, resamples=2000)
        assert (blocked.upper - blocked.lower) > (iid.upper - iid.lower)

    def test_block_length_beyond_the_sample_is_refused(self) -> None:
        with pytest.raises(StatisticsError, match="exceeds"):
            block_bootstrap_ci([1.0, 2.0], [1.0, 2.0], seed="s", block_length=5)

    def test_block_length_must_be_positive(self) -> None:
        with pytest.raises(StatisticsError, match="at least 1"):
            block_bootstrap_ci([1.0], [1.0], seed="s", block_length=0)


class TestPermutationTest:
    def test_is_reproducible(self) -> None:
        control, challenger = paired_unit_scores()
        first = paired_permutation_test(control, challenger, seed="s", resamples=500)
        second = paired_permutation_test(control, challenger, seed="s", resamples=500)
        assert first.p_value == second.p_value

    def test_p_value_is_never_exactly_zero(self) -> None:
        # (hits + 1) / (resamples + 1): a finite number of draws cannot establish
        # a p-value of zero, and reporting one overstates the resolution.
        control, challenger = paired_unit_scores(lift=10.0)
        result = paired_permutation_test(control, challenger, seed="s", resamples=200)
        assert result.p_value > 0.0
        assert result.p_value == pytest.approx(1 / 201)

    def test_a_large_consistent_lift_is_significant(self) -> None:
        control, challenger = paired_unit_scores(count=40, lift=0.05)
        result = paired_permutation_test(control, challenger, seed="s", resamples=2000)
        assert result.p_value < 0.01

    def test_no_difference_is_not_significant(self) -> None:
        control, _ = paired_unit_scores()
        result = paired_permutation_test(control, control, seed="s", resamples=1000)
        assert result.p_value > 0.05

    def test_unknown_alternative_is_refused(self) -> None:
        with pytest.raises(StatisticsError, match="alternative"):
            paired_permutation_test([1.0], [2.0], seed="s", alternative="sideways")

    def test_two_sided_and_less_alternatives_are_supported(self) -> None:
        control, challenger = paired_unit_scores(count=30, lift=0.05)
        two_sided = paired_permutation_test(
            control, challenger, seed="s", resamples=1000, alternative="two-sided"
        )
        worse = paired_permutation_test(
            control, challenger, seed="s", resamples=1000, alternative="less"
        )
        assert two_sided.p_value < 0.05
        assert worse.p_value > 0.5


class TestEffectSize:
    def test_scales_with_the_consistency_of_the_difference(self) -> None:
        rng = np.random.default_rng(3)
        control = list(rng.normal(0.4, 0.05, size=50))
        noisy = [value + rng.normal(0.02, 0.05) for value in control]
        clean = [value + rng.normal(0.02, 0.005) for value in control]
        noisy_effect = paired_effect_size(control, noisy)
        clean_effect = paired_effect_size(control, clean)
        assert noisy_effect is not None and clean_effect is not None
        assert clean_effect > noisy_effect

    def test_a_constant_difference_is_undefined_rather_than_huge(self) -> None:
        # Zero spread makes Cohen's d unbounded. Floating point turns that into a
        # meaningless number near 1e15, which would then be reported as an
        # enormous effect. None is the honest answer.
        assert paired_effect_size([0.1, 0.2, 0.3], [0.15, 0.25, 0.35]) is None

    def test_a_single_pair_is_undefined(self) -> None:
        assert paired_effect_size([0.1], [0.2]) is None

    def test_is_json_safe(self) -> None:
        # canonical_json forbids NaN and infinity, so an undefined effect must
        # never come back as one.
        value = paired_effect_size([0.1, 0.2], [0.1, 0.2])
        assert value is None or math.isfinite(value)
