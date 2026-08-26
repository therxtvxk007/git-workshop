"""Recency is judged on when a claim became available, not on when it predicts.

Four cases, each of which the previous implementation got wrong by filtering on
``event_time_start``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pramaanx.generators.base import ForecastContext
from pramaanx.generators.base_rate import BaseRateGenerator
from pramaanx.schemas.event import EventMention

CUTOFF = datetime(2026, 1, 15, tzinfo=UTC)
BUCKETS = ["0-1d", "2-3d", "4-7d", "8-14d", "15-30d", "31-90d"]
ACTOR = "Farmers Union Federation"
REGION = "IN-DL"


def claim(
    index: int,
    *,
    observed_days_before: float,
    event_days_after: float | None,
    modality: str = "planned",
) -> EventMention:
    """A forward-looking claim, with availability and event time set apart."""
    event_time = CUTOFF + timedelta(days=event_days_after) if event_days_after is not None else None
    return EventMention(
        mention_id=f"men_{index:04d}",
        observation_id=f"obs_{index:04d}",
        observed_at=CUTOFF - timedelta(days=observed_days_before),
        subject=ACTOR,
        relation="participates_in",
        object=None,
        event_type="protest",
        location_text=REGION,
        event_time_start=event_time,
        event_time_end=event_time,
        modality=modality,  # type: ignore[arg-type]
        extraction_probability=0.8,
        supporting_span=f"claim {index}",
    )


def history(count: int = 12) -> list[EventMention]:
    """Enough occurred events for the stream to have a rate at all."""
    return [
        EventMention(
            mention_id=f"hist_{index:04d}",
            observation_id=f"hobs_{index:04d}",
            observed_at=CUTOFF - timedelta(days=index * 10),
            subject=ACTOR,
            relation="participates_in",
            object=None,
            event_type="protest",
            location_text=REGION,
            event_time_start=CUTOFF - timedelta(days=index * 10),
            event_time_end=CUTOFF - timedelta(days=index * 10),
            modality="asserted",
            extraction_probability=0.9,
            supporting_span=f"history {index}",
        )
        for index in range(1, count + 1)
    ]


def score(mentions: list[EventMention], recent_activity_days: int = 30) -> float:
    generator = BaseRateGenerator(
        mentions, time_buckets=BUCKETS, recent_activity_days=recent_activity_days
    )
    context = ForecastContext(
        cutoff_at=CUTOFF, evidence_snapshot_id="snap_test", proposal_budget=50, horizon_days=30
    )
    proposals = [
        item
        for item in generator.propose(context)
        if item.hypothesis.event_type == "protest"
        and item.hypothesis.most_likely_location() == REGION
    ]
    assert proposals, "the stream should always yield a candidate"
    return proposals[0].generator_score


def activity_count(mentions: list[EventMention]) -> int:
    generator = BaseRateGenerator(mentions, time_buckets=BUCKETS, recent_activity_days=30)
    context = ForecastContext(
        cutoff_at=CUTOFF, evidence_snapshot_id="snap_test", proposal_budget=50, horizon_days=30
    )
    proposal = next(
        item for item in generator.propose(context) if item.hypothesis.event_type == "protest"
    )
    return int(proposal.trace["forward_looking_mentions"])


class TestAvailabilityDrivesRecency:
    def test_an_old_undated_claim_has_no_effect(self) -> None:
        # Said a year ago, no event date. Previously kept forever, because the
        # filter had nothing to compare against and defaulted to keeping it.
        baseline = score(history())
        stale = score([*history(), claim(1, observed_days_before=365, event_days_after=None)])
        assert stale == baseline
        assert (
            activity_count([*history(), claim(1, observed_days_before=365, event_days_after=None)])
            == 0
        )

    def test_a_recent_undated_claim_does_affect_the_candidate(self) -> None:
        # Said three days ago, no event date. This is most real chatter.
        baseline = score(history())
        fresh = score([*history(), claim(1, observed_days_before=3, event_days_after=None)])
        assert fresh > baseline
        assert (
            activity_count([*history(), claim(1, observed_days_before=3, event_days_after=None)])
            == 1
        )

    def test_a_far_future_event_time_does_not_discard_current_evidence(self) -> None:
        # Said yesterday, about an event 60 days out -- outside the 30-day
        # activity window if you (wrongly) filter on event time.
        baseline = score(history())
        distant = score([*history(), claim(1, observed_days_before=1, event_days_after=60)])
        assert distant > baseline
        assert (
            activity_count([*history(), claim(1, observed_days_before=1, event_days_after=60)]) == 1
        )

    def test_a_stale_claim_about_an_imminent_event_does_not_count_as_new(self) -> None:
        # Said 200 days ago about something happening tomorrow. Filtering on
        # event time would treat this as fresh activity.
        baseline = score(history())
        stale = score([*history(), claim(1, observed_days_before=200, event_days_after=1)])
        assert stale == baseline
        assert (
            activity_count([*history(), claim(1, observed_days_before=200, event_days_after=1)])
            == 0
        )

    def test_the_window_boundary_is_inclusive(self) -> None:
        inside = activity_count(
            [*history(), claim(1, observed_days_before=30, event_days_after=None)]
        )
        outside = activity_count(
            [*history(), claim(1, observed_days_before=30.5, event_days_after=None)]
        )
        assert (inside, outside) == (1, 0)

    def test_claims_made_after_the_cutoff_never_count(self) -> None:
        future_claim = claim(1, observed_days_before=-5, event_days_after=10)
        assert activity_count([*history(), future_claim]) == 0

    def test_reports_observed_after_the_cutoff_do_not_set_a_rate(self) -> None:
        from pramaanx.generators.base_rate import estimate_rates

        # An old event, but the report of it only became available tomorrow.
        late_report = EventMention(
            mention_id="men_late",
            observation_id="obs_late",
            observed_at=CUTOFF + timedelta(days=1),
            subject=ACTOR,
            relation="participates_in",
            object=None,
            event_type="protest",
            location_text=REGION,
            event_time_start=CUTOFF - timedelta(days=5),
            event_time_end=CUTOFF - timedelta(days=5),
            modality="asserted",
            extraction_probability=0.9,
            supporting_span="late report",
        )
        with_late = estimate_rates([*history(), late_report], cutoff_at=CUTOFF, lookback_days=365)
        without = estimate_rates(history(), cutoff_at=CUTOFF, lookback_days=365)
        assert (
            with_late[("protest", REGION, ACTOR)].count == without[("protest", REGION, ACTOR)].count
        )


class TestMentionHelper:
    def test_is_recent_uses_observed_at_only(self) -> None:
        mention = claim(1, observed_days_before=5, event_days_after=90)
        window_start = CUTOFF - timedelta(days=30)
        assert mention.is_recent(window_start=window_start, cutoff_at=CUTOFF)

        old = claim(2, observed_days_before=90, event_days_after=1)
        assert not old.is_recent(window_start=window_start, cutoff_at=CUTOFF)

    def test_extraction_populates_observed_at_from_the_observation(
        self, populated_ledger: object
    ) -> None:
        from pramaanx.extraction.structured import extract_mentions

        observations = populated_ledger.read_observations()[:20]  # type: ignore[attr-defined]
        mentions = extract_mentions(populated_ledger, observations)  # type: ignore[arg-type]
        by_id = {item.observation_id: item for item in observations}
        for mention in mentions:
            assert mention.observed_at == by_id[mention.observation_id].first_observed_at
