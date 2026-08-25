"""G0: rate estimation, hazard buckets and the generator contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.generators.base import CandidateGenerator, ForecastContext
from pramaanx.generators.base_rate import (
    BaseRateGenerator,
    estimate_rates,
    parse_buckets,
    seasonal_multiplier,
)
from pramaanx.schemas.event import EventMention

CUTOFF = datetime(2026, 1, 15, tzinfo=UTC)
BUCKETS = ["0-1d", "2-3d", "4-7d", "8-14d", "15-30d", "31-90d"]


def mention(
    index: int,
    *,
    event_type: str = "protest",
    region: str = "IN-DL",
    actor: str = "Farmers Union Federation",
    modality: str = "asserted",
    days_before: float = 10.0,
) -> EventMention:
    moment = CUTOFF - timedelta(days=days_before)
    return EventMention(
        mention_id=f"men_{index:04d}",
        observation_id=f"obs_{index:04d}",
        subject=actor,
        relation="participates_in",
        object=None,
        event_type=event_type,
        location_text=region,
        event_time_start=moment,
        event_time_end=moment,
        modality=modality,  # type: ignore[arg-type]
        extraction_probability=0.8,
        supporting_span=f"span {index}",
    )


class TestBuckets:
    def test_buckets_are_contiguous(self) -> None:
        parsed = parse_buckets(BUCKETS)
        assert parsed[0] == ("0-1d", 0.0, 1.0)
        # "2-3d" starts where "0-1d" ended: printed labels describe whole days,
        # so reading the printed start literally would leave uncovered gaps.
        assert parsed[1] == ("2-3d", 1.0, 3.0)
        assert [end for _, _, end in parsed] == [1.0, 3.0, 7.0, 14.0, 30.0, 90.0]

    def test_unparsable_bucket_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot parse time bucket"):
            parse_buckets(["soon"])

    def test_labels_are_sorted_by_end_not_by_input_order(self) -> None:
        assert [label for label, _, _ in parse_buckets(["4-7d", "0-1d", "2-3d"])] == [
            "0-1d",
            "2-3d",
            "4-7d",
        ]

    def test_buckets_that_cover_no_time_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not extend past"):
            parse_buckets(["0-3d", "1-3d"])


class TestRateEstimation:
    def test_rate_reflects_frequency(self) -> None:
        frequent = [mention(i, days_before=i) for i in range(1, 41)]
        rare = [mention(100, region="IN-MH")]
        estimates = estimate_rates([*frequent, *rare], cutoff_at=CUTOFF, lookback_days=365)
        busy = estimates[("protest", "IN-DL", "Farmers Union Federation")]
        quiet = estimates[("protest", "IN-MH", "Farmers Union Federation")]
        assert busy.rate > quiet.rate
        assert busy.count == 40

    def test_rare_streams_are_shrunk_not_zeroed(self) -> None:
        estimates = estimate_rates([mention(1)], cutoff_at=CUTOFF, lookback_days=365)
        estimate = estimates[("protest", "IN-DL", "Farmers Union Federation")]
        # One sighting in a year is neither "never" nor "once a day".
        assert 0.0 < estimate.rate < 0.05
        assert estimate.lower < estimate.rate < estimate.upper

    def test_only_occurred_events_count_towards_a_rate(self) -> None:
        planned = [mention(i, modality="planned") for i in range(20)]
        assert estimate_rates(planned, cutoff_at=CUTOFF, lookback_days=365) == {}

    def test_events_after_the_cutoff_are_excluded(self) -> None:
        future = [mention(1, days_before=-30)]
        assert estimate_rates(future, cutoff_at=CUTOFF, lookback_days=365) == {}

    def test_occurrence_probability_rises_with_horizon(self) -> None:
        estimates = estimate_rates(
            [mention(i, days_before=i) for i in range(1, 30)],
            cutoff_at=CUTOFF,
            lookback_days=365,
        )
        estimate = next(iter(estimates.values()))
        assert estimate.occurrence_probability(7) < estimate.occurrence_probability(90)


class TestSeasonality:
    def test_concentrated_months_raise_the_multiplier(self) -> None:
        # Every flood in the history happened in January.
        januaries = [mention(i, event_type="flood", days_before=i) for i in range(1, 15)]
        assert seasonal_multiplier(januaries, "flood", 1, cutoff_at=CUTOFF, lookback_days=365) > 1.5

    def test_no_history_means_no_adjustment(self) -> None:
        assert seasonal_multiplier([], "flood", 7, cutoff_at=CUTOFF, lookback_days=365) == 1.0


class TestProposals:
    def build(self, mentions: list[EventMention]) -> BaseRateGenerator:
        return BaseRateGenerator(mentions, time_buckets=BUCKETS)

    def context(self, budget: int = 100, horizon: int = 30) -> ForecastContext:
        return ForecastContext(
            cutoff_at=CUTOFF,
            evidence_snapshot_id="snap_test",
            proposal_budget=budget,
            horizon_days=horizon,
        )

    def test_implements_the_generator_protocol(self) -> None:
        assert isinstance(self.build([]), CandidateGenerator)

    def test_proposals_carry_a_valid_bucket_distribution(self) -> None:
        generator = self.build([mention(i, days_before=i) for i in range(1, 30)])
        proposal = generator.propose(self.context())[0]
        buckets = proposal.hypothesis.time_bucket_probabilities
        assert abs(sum(buckets.values()) - 1.0) < 1e-6

    def test_budget_is_respected_and_ranked(self) -> None:
        mentions = [mention(i, region=f"R-{i % 20}", days_before=i % 300) for i in range(200)]
        proposals = self.build(mentions).propose(self.context(budget=5))
        assert len(proposals) == 5
        scores = [item.generator_score for item in proposals]
        assert scores == sorted(scores, reverse=True)

    def test_forward_looking_chatter_raises_the_score(self) -> None:
        history = [mention(i, days_before=i) for i in range(1, 30)]
        chatter = [mention(500 + i, modality="planned", days_before=3) for i in range(5)]
        quiet = self.build(history).propose(self.context())[0].generator_score
        noisy = self.build([*history, *chatter]).propose(self.context())[0].generator_score
        assert noisy > quiet

    def test_streams_with_no_history_still_get_a_candidate(self) -> None:
        # A generator that can only predict repeats would never see anything new.
        chatter = [mention(1, region="NEW-REGION", modality="possible", days_before=2)]
        proposals = self.build(chatter).propose(self.context())
        assert [item.hypothesis.most_likely_location() for item in proposals] == ["NEW-REGION"]
        assert proposals[0].hypothesis.novelty_score == 1.0

    def test_denials_are_kept_as_contradicting_evidence(self) -> None:
        mentions = [
            *[mention(i, days_before=i) for i in range(1, 10)],
            mention(99, modality="denied", days_before=2),
        ]
        proposal = self.build(mentions).propose(self.context())[0]
        stances = {item.stance for item in proposal.hypothesis.evidence}
        assert "contradicts" in stances

    def test_region_scope_filters_proposals(self) -> None:
        mentions = [
            mention(1, region="IN-DL", days_before=5),
            mention(2, region="GB-LND", days_before=5),
        ]
        context = self.context().model_copy(update={"region_scope": ["IN-DL"]})
        proposals = self.build(mentions).propose(context)
        assert {item.hypothesis.most_likely_location() for item in proposals} == {"IN-DL"}

    def test_trace_records_the_reasoning(self) -> None:
        proposal = self.build([mention(i, days_before=i) for i in range(1, 10)]).propose(
            self.context()
        )[0]
        assert proposal.trace["historical_count"] == 9
        assert proposal.trace["probability_lower"] <= proposal.trace["probability_upper"]
        assert proposal.generator_name == "base_rate"

    def test_output_is_deterministic(self) -> None:
        mentions = [mention(i, region=f"R-{i % 7}", days_before=i % 200) for i in range(80)]
        first = self.build(mentions).propose(self.context())
        second = self.build(list(reversed(mentions))).propose(self.context())
        assert [item.hypothesis.event_id for item in first] == [
            item.hypothesis.event_id for item in second
        ]
        assert [item.generator_score for item in first] == [item.generator_score for item in second]
