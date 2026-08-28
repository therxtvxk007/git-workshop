"""Rolling-origin splits, the derived embargo, and the sealed reservation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.models.spatial.contracts import ReportingDelayPolicy
from pramaanx.models.spatial.splits import (
    SealedSplitError,
    SplitPolicy,
    SplitPurpose,
    build_rolling_origin_plan,
    select_rows,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def cutoffs(count: int, *, spacing_days: int = 30) -> list[datetime]:
    return [START + timedelta(days=spacing_days * index) for index in range(count)]


def delay(*, horizon: int = 30, reporting: int = 3) -> ReportingDelayPolicy:
    return ReportingDelayPolicy(
        reporting_delay_days=reporting,
        observation_end=START + timedelta(days=3650),
        horizon_days=horizon,
    )


def test_folds_are_chronological_and_never_train_on_the_future() -> None:
    plan = build_rolling_origin_plan(cutoffs(12), policy=SplitPolicy(), reporting_delay=delay())
    assert plan.folds
    for fold in plan.folds:
        assert fold.train_end < fold.validation_start
        assert list(fold.train_cutoffs) == sorted(fold.train_cutoffs)
        assert max(fold.train_cutoffs) < min(fold.validation_cutoffs)


def test_training_windows_expand_by_default() -> None:
    plan = build_rolling_origin_plan(cutoffs(12), policy=SplitPolicy(), reporting_delay=delay())
    sizes = [len(fold.train_cutoffs) for fold in plan.folds]
    assert sizes == sorted(sizes)
    assert sizes[-1] > sizes[0]


def test_a_sliding_window_keeps_a_fixed_span() -> None:
    policy = SplitPolicy(expanding=False, sliding_train_cutoffs=2)
    plan = build_rolling_origin_plan(cutoffs(12), policy=policy, reporting_delay=delay())
    assert {len(fold.train_cutoffs) for fold in plan.folds} == {2}


def test_the_embargo_is_derived_from_horizon_plus_reporting_delay() -> None:
    policy = SplitPolicy()
    plan = build_rolling_origin_plan(
        cutoffs(12), policy=policy, reporting_delay=delay(horizon=30, reporting=3)
    )
    assert all(fold.embargo_days == 33 for fold in plan.folds)
    for fold in plan.folds:
        for cutoff in fold.train_cutoffs:
            # Every training label was knowable before the validation cutoff.
            assert cutoff + timedelta(days=33) <= fold.validation_start


def test_additional_embargo_lengthens_but_never_shortens() -> None:
    base = SplitPolicy()
    longer = SplitPolicy(additional_embargo_days=10)
    assert longer.embargo_days(delay()) == base.embargo_days(delay()) + 10


def test_cutoffs_closer_than_the_embargo_produce_no_fold() -> None:
    # At three-day spacing no training cutoff clears a 33-day embargo before
    # any validation cutoff, so there is no honest fold to build. Emitting one
    # anyway would be the leak this refusal exists to prevent.
    with pytest.raises(ValueError, match="no fold survived"):
        build_rolling_origin_plan(
            cutoffs(12, spacing_days=3), policy=SplitPolicy(), reporting_delay=delay()
        )


def test_wider_spacing_lets_folds_survive_the_same_embargo() -> None:
    # The complement of the test above: the refusal is about spacing versus
    # embargo, not about a hard-coded cutoff count.
    plan = build_rolling_origin_plan(
        cutoffs(12, spacing_days=30), policy=SplitPolicy(), reporting_delay=delay()
    )
    assert plan.folds


def test_reservations_are_taken_from_the_most_recent_cutoffs() -> None:
    every = cutoffs(12)
    plan = build_rolling_origin_plan(
        every,
        policy=SplitPolicy(final_test_cutoffs=3, calibration_cutoffs=2),
        reporting_delay=delay(),
    )
    assert list(plan.final_test_cutoffs) == every[-3:]
    assert list(plan.calibration_cutoffs) == every[-5:-3]
    assert set(plan.modelling_cutoffs()).isdisjoint(plan.final_test_cutoffs)
    assert set(plan.modelling_cutoffs()).isdisjoint(plan.calibration_cutoffs)


def test_final_test_rows_cannot_be_opened() -> None:
    plan = build_rolling_origin_plan(cutoffs(12), policy=SplitPolicy(), reporting_delay=delay())
    with pytest.raises(SealedSplitError, match="sealed"):
        select_rows([], plan=plan, fold=plan.folds[0], purpose=SplitPurpose.FINAL_TEST)


def test_naive_cutoffs_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_rolling_origin_plan(
            [datetime(2026, 1, 1), datetime(2026, 2, 1)],  # noqa: DTZ001 - the point of the test
            policy=SplitPolicy(),
            reporting_delay=delay(),
        )


def test_too_few_cutoffs_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot support"):
        build_rolling_origin_plan(cutoffs(3), policy=SplitPolicy(), reporting_delay=delay())


def test_the_plan_hash_moves_with_the_reporting_delay() -> None:
    every = cutoffs(12)
    first = build_rolling_origin_plan(
        every, policy=SplitPolicy(), reporting_delay=delay(reporting=3)
    )
    second = build_rolling_origin_plan(
        every, policy=SplitPolicy(), reporting_delay=delay(reporting=9)
    )
    assert first.plan_hash() != second.plan_hash()
