"""CutoffGuard: the admission rule and the cases that slip past it.

M0 gate: future records cannot affect a past cutoff.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.config import TimeguardConfig
from pramaanx.schemas.observation import Modality, Observation
from pramaanx.timeguard.cutoff import (
    CutoffGuard,
    LeakageError,
    ViolationKind,
    partition_by_cutoff,
)

CUTOFF = datetime(2026, 1, 15, tzinfo=UTC)
BEFORE = CUTOFF - timedelta(days=1)
AFTER = CUTOFF + timedelta(days=1)
RETRIEVED = datetime(2026, 8, 25, tzinfo=UTC)  # a backtest fetches long afterwards


def observation(
    observation_id: str = "obs_1",
    *,
    first_observed_at: datetime = BEFORE,
    published_at: datetime | None = None,
    retrieved_at: datetime = RETRIEVED,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        source_id="synthetic",
        source_type="synthetic",
        modality=Modality.TEXT,
        retrieved_at=retrieved_at,
        first_observed_at=first_observed_at,
        published_at=published_at,
        raw_content_hash="sha256:abc",
        payload_ref="ab/cd/abc.bin",
    )


class TestAdmissionRule:
    def test_admits_evidence_from_before_the_cutoff(self) -> None:
        assert CutoffGuard(CUTOFF).is_admissible(observation())

    def test_admits_evidence_exactly_at_the_cutoff(self) -> None:
        # The rule is <=, so the boundary instant is inside the snapshot.
        assert CutoffGuard(CUTOFF).is_admissible(observation(first_observed_at=CUTOFF))

    def test_rejects_evidence_from_after_the_cutoff(self) -> None:
        violations = CutoffGuard(CUTOFF).inspect(observation(first_observed_at=AFTER))
        assert [item.kind for item in violations] == [ViolationKind.FUTURE_OBSERVATION]

    def test_retrieval_long_after_the_cutoff_is_normal(self) -> None:
        # A historical backtest necessarily fetches its evidence today; that is
        # not leakage, and treating it as such would ban backtesting entirely.
        assert CutoffGuard(CUTOFF).is_admissible(observation(retrieved_at=RETRIEVED))


class TestSubtlerViolations:
    def test_publication_after_the_cutoff_is_rejected(self) -> None:
        # An old URL whose body was updated later: the stored body is not the
        # body that existed at the cutoff.
        violations = CutoffGuard(CUTOFF).inspect(
            observation(first_observed_at=BEFORE, published_at=AFTER)
        )
        kinds = {item.kind for item in violations}
        assert ViolationKind.PUBLISHED_AFTER_CUTOFF in kinds
        assert ViolationKind.OBSERVED_BEFORE_PUBLISHED in kinds

    def test_updated_body_check_can_be_disabled_explicitly(self) -> None:
        config = TimeguardConfig(reject_updated_bodies=False)
        violations = CutoffGuard(CUTOFF, config).inspect(
            observation(first_observed_at=BEFORE, published_at=AFTER)
        )
        assert ViolationKind.PUBLISHED_AFTER_CUTOFF not in {item.kind for item in violations}
        # The impossible timeline is still reported.
        assert ViolationKind.OBSERVED_BEFORE_PUBLISHED in {item.kind for item in violations}

    def test_skew_allowance_is_zero_by_default(self) -> None:
        just_after = CUTOFF + timedelta(seconds=1)
        assert not CutoffGuard(CUTOFF).is_admissible(observation(first_observed_at=just_after))
        lenient = CutoffGuard(CUTOFF, TimeguardConfig(max_future_skew_seconds=60))
        assert lenient.is_admissible(observation(first_observed_at=just_after))


class TestStrictMode:
    def test_strict_mode_raises_rather_than_dropping(self) -> None:
        # Silently dropping an inadmissible record makes a leak look like a
        # thin news day, so strict is the default.
        guard = CutoffGuard(CUTOFF)
        with pytest.raises(LeakageError, match="cutoff violation"):
            guard.screen([observation(), observation("obs_2", first_observed_at=AFTER)])

    def test_permissive_mode_reports_instead(self) -> None:
        guard = CutoffGuard(CUTOFF, TimeguardConfig(strict=False))
        report = guard.screen([observation(), observation("obs_2", first_observed_at=AFTER)])
        assert report.admitted_count == 1
        assert report.rejected_count == 1
        assert report.counts_by_kind() == {"future_observation": 1}

    def test_naive_cutoff_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            CutoffGuard(datetime(2026, 1, 15))  # noqa: DTZ001


class TestOrdering:
    def test_filter_output_is_deterministic(self) -> None:
        guard = CutoffGuard(CUTOFF)
        batch = [
            observation("obs_3", first_observed_at=BEFORE),
            observation("obs_1", first_observed_at=BEFORE - timedelta(days=2)),
            observation("obs_2", first_observed_at=BEFORE),
        ]
        first = [item.observation_id for item in guard.filter(batch)]
        second = [item.observation_id for item in guard.filter(list(reversed(batch)))]
        assert first == second == ["obs_1", "obs_2", "obs_3"]

    def test_partition_splits_past_from_future(self) -> None:
        past, future = partition_by_cutoff(
            [observation("a"), observation("b", first_observed_at=AFTER)], CUTOFF
        )
        assert [item.observation_id for item in past] == ["a"]
        assert [item.observation_id for item in future] == ["b"]
