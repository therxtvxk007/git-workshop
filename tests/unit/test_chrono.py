"""Tests for the strictly chronological evaluation primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.evaluation.chrono import (
    BootstrapCI,
    climatology,
    is_mature,
    maturity_time,
    moving_block_bootstrap,
    one_to_one_labels,
    overlap_depth,
    paired_block_bootstrap,
    persistence,
    skill_score,
    unique_outcome_topk,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class TestMaturity:
    def test_maturity_adds_horizon_and_delay(self) -> None:
        assert maturity_time(T0, 30, 3.0) == T0 + timedelta(days=33)

    def test_fold_is_immature_until_delay_elapses(self) -> None:
        # One second short of the boundary is still immature.
        assert not is_mature(T0, T0 + timedelta(days=33) - timedelta(seconds=1), 30, 3.0)
        assert is_mature(T0, T0 + timedelta(days=33), 30, 3.0)

    def test_a_merely_earlier_fold_is_not_mature(self) -> None:
        """The whole point: chronological order is not sufficient."""
        earlier = T0
        forecast_at = T0 + timedelta(days=7)
        assert earlier < forecast_at
        assert not is_mature(earlier, forecast_at, 30, 3.0)

    @pytest.mark.parametrize(
        ("horizon", "step", "expected"), [(30, 7, 5), (30, 30, 1), (30, 1, 30), (7, 30, 1)]
    )
    def test_overlap_depth(self, horizon: int, step: int, expected: int) -> None:
        assert overlap_depth(horizon, step) == expected

    def test_overlap_depth_rejects_zero_step(self) -> None:
        with pytest.raises(ValueError, match="step_days must be positive"):
            overlap_depth(30, 0)


class TestReferences:
    def test_climatology_is_none_without_prior_folds(self) -> None:
        assert climatology([]) is None

    def test_climatology_is_the_prior_mean(self) -> None:
        assert climatology([1, 0, 0, 0]) == pytest.approx(0.25)

    def test_persistence_marks_previously_hot_streams(self) -> None:
        out = persistence(["a", "b", "c"], ["a", "c"], fallback=0.1)
        assert out[0] > 0.9
        assert out[1] == pytest.approx(0.1)
        assert out[2] > 0.9

    def test_skill_score_positive_when_model_beats_reference(self) -> None:
        labels = [1, 0, 1, 0]
        good = [0.9, 0.1, 0.9, 0.1]
        ref = [0.5] * 4
        value = skill_score(good, labels, ref)
        assert value is not None and value > 0.5

    def test_skill_score_negative_when_model_loses(self) -> None:
        labels = [1, 0, 1, 0]
        bad = [0.1, 0.9, 0.1, 0.9]
        value = skill_score(bad, labels, [0.5] * 4)
        assert value is not None and value < 0

    def test_skill_score_rejects_length_mismatch(self) -> None:
        # Regression: a chained ``!=`` let this case through.
        assert skill_score([0.5, 0.5], [1, 0], [0.5]) is None

    def test_skill_score_none_on_empty(self) -> None:
        assert skill_score([], [], []) is None

    def test_skill_score_none_when_reference_is_perfect(self) -> None:
        assert skill_score([0.5, 0.5], [1, 0], [1.0, 0.0]) is None


class TestUniqueTopK:
    def test_duplicate_matches_count_once(self) -> None:
        probs = [0.9, 0.8, 0.7, 0.1]
        matched = [True, True, True, False]
        ids = ["o1", "o1", "o1", None]
        result = unique_outcome_topk(probs, matched, ids, budget=3, outcomes_available=4)
        assert result.label_hits == 3
        assert result.unique_outcomes == 1
        assert result.duplication_ratio == pytest.approx(3.0)
        assert result.unique_recall == pytest.approx(0.25)

    def test_distinct_matches_have_no_duplication(self) -> None:
        result = unique_outcome_topk(
            [0.9, 0.8], [True, True], ["o1", "o2"], budget=2, outcomes_available=2
        )
        assert result.unique_outcomes == 2
        assert result.duplication_ratio == pytest.approx(1.0)
        assert result.unique_recall == pytest.approx(1.0)

    def test_selection_follows_probability_order(self) -> None:
        result = unique_outcome_topk(
            [0.1, 0.9], [False, True], [None, "o1"], budget=1, outcomes_available=1
        )
        assert result.unique_outcomes == 1

    def test_zero_budget_is_empty(self) -> None:
        result = unique_outcome_topk([0.9], [True], ["o1"], budget=0, outcomes_available=1)
        assert result.selected == 0
        assert result.unique_recall is None

    def test_empty_input_is_empty(self) -> None:
        assert unique_outcome_topk([], [], [], budget=5, outcomes_available=0).selected == 0

    def test_to_dict_round_trips(self) -> None:
        d = unique_outcome_topk([0.9], [True], ["o1"], 1, 1).to_dict()
        assert d["unique_outcomes"] == 1
        assert d["budget"] == 1


class TestOneToOne:
    def test_only_the_strongest_claimant_keeps_credit(self) -> None:
        kept = one_to_one_labels(
            forecast_ids=["f1", "f2", "f3"],
            matched=[True, True, True],
            outcome_ids=["o1", "o1", "o2"],
            scores=[0.7, 0.9, 0.8],
        )
        assert kept == [False, True, True]

    def test_unmatched_forecasts_stay_unmatched(self) -> None:
        kept = one_to_one_labels(["f1"], [False], [None], [0.0])
        assert kept == [False]

    def test_ties_break_on_forecast_id_not_order(self) -> None:
        a = one_to_one_labels(["fb", "fa"], [True, True], ["o1", "o1"], [0.5, 0.5])
        b = one_to_one_labels(["fa", "fb"], [True, True], ["o1", "o1"], [0.5, 0.5])
        # "fa" wins in both orderings.
        assert a == [False, True]
        assert b == [True, False]

    def test_never_credits_more_than_the_outcome_count(self) -> None:
        kept = one_to_one_labels(
            ["f1", "f2", "f3", "f4"], [True] * 4, ["o1", "o1", "o1", "o1"], [0.9, 0.8, 0.7, 0.6]
        )
        assert sum(kept) == 1


class TestBlockBootstrap:
    def test_interval_brackets_the_mean(self) -> None:
        ci = moving_block_bootstrap([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], block_length=3, reps=500)
        assert ci.low <= ci.point <= ci.high

    def test_constant_series_has_zero_width(self) -> None:
        ci = moving_block_bootstrap([0.4] * 8, block_length=3, reps=300)
        assert ci.low == pytest.approx(0.4)
        assert ci.high == pytest.approx(0.4)

    def test_block_length_is_clamped_to_the_series(self) -> None:
        ci = moving_block_bootstrap([0.1, 0.2, 0.3], block_length=99, reps=200)
        assert ci.block_length == 3

    def test_block_length_has_a_floor(self) -> None:
        ci = moving_block_bootstrap([0.1, 0.2, 0.3, 0.4], block_length=1, reps=200)
        assert ci.block_length >= 2

    def test_empty_series_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot bootstrap an empty series"):
            moving_block_bootstrap([], block_length=3)

    def test_is_deterministic_under_a_fixed_seed(self) -> None:
        args = ([0.1, 0.5, 0.2, 0.9, 0.3, 0.4], 3)
        assert moving_block_bootstrap(*args, reps=400).to_dict() == (
            moving_block_bootstrap(*args, reps=400).to_dict()
        )

    def test_wider_blocks_do_not_narrow_the_interval_to_nothing(self) -> None:
        values = [0.1, 0.9] * 6
        narrow = moving_block_bootstrap(values, 2, reps=800)
        wide = moving_block_bootstrap(values, 6, reps=800)
        assert wide.high - wide.low >= 0.0
        assert narrow.high - narrow.low >= 0.0

    def test_paired_difference_detects_a_real_gap(self) -> None:
        left = [0.5] * 10
        right = [0.1] * 10
        ci = paired_block_bootstrap(left, right, block_length=3, reps=500)
        assert ci.point == pytest.approx(0.4)
        assert ci.excludes_zero

    def test_paired_difference_of_identical_series_includes_zero(self) -> None:
        series = [0.1, 0.4, 0.2, 0.5, 0.3, 0.6]
        ci = paired_block_bootstrap(series, series, block_length=3, reps=500)
        assert not ci.excludes_zero

    def test_paired_requires_equal_lengths(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            paired_block_bootstrap([0.1, 0.2], [0.1], block_length=2)

    def test_ci_dataclass_reports_zero_exclusion(self) -> None:
        assert BootstrapCI(0.5, 0.1, 0.9, 10, 3).excludes_zero
        assert not BootstrapCI(0.0, -0.1, 0.9, 10, 3).excludes_zero
