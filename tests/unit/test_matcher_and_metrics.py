"""Outcome matching and the metric primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pramaanx.evaluation import metrics
from pramaanx.evaluation.matcher import MatchContext, OutcomeMatcher
from pramaanx.schemas.event import EventHypothesis, ResolvedEvent
from pramaanx.schemas.forecast import ForecastRecord, ForecastStatus
from pramaanx.schemas.outcome import (
    AdjudicationDecision,
    HumanAdjudication,
    MatchTolerance,
    OutcomeRecord,
)

CUTOFF = datetime(2026, 1, 15, tzinfo=UTC)
CONTEXT = MatchContext(cutoff_at=CUTOFF, horizon_days=30)


def forecast(
    event_type: str = "protest",
    region: str = "IN-DL",
    actor: str = "Farmers Union Federation",
) -> ForecastRecord:
    hypothesis = EventHypothesis(
        event_id="evt_1",
        event_type=event_type,
        actor_ids=[actor],
        location_cells={region: 1.0},
        time_bucket_probabilities={"0-1d": 1.0},
    )
    return ForecastRecord(
        forecast_id="fc_1",
        cutoff_at=CUTOFF,
        created_at=CUTOFF,
        hypothesis=hypothesis,
        raw_probability=0.5,
        calibrated_probability=0.5,
        epistemic_uncertainty=0.2,
        status=ForecastStatus.WATCH,
        snapshot_hash="sha256:abc",
    )


def outcome(
    event_type: str = "protest",
    region: str = "IN-DL",
    actor: str = "Farmers Union Federation",
    *,
    days_after: float = 5.0,
    tolerance: MatchTolerance | None = None,
    adjudicated: bool = False,
) -> OutcomeRecord:
    occurred = CUTOFF + timedelta(days=days_after)
    event = ResolvedEvent(
        resolved_event_id="rev_1",
        event_type=event_type,
        actor_ids=[actor],
        location_cell=region,
        occurred_at=occurred,
    )
    adjudications = (
        [
            HumanAdjudication(
                adjudicator_id="analyst_1",
                decided_at=occurred + timedelta(days=1),
                decision=AdjudicationDecision.ACCEPTED,
                rationale="confirmed",
                blinded=True,
            )
        ]
        if adjudicated
        else []
    )
    return OutcomeRecord(
        outcome_id="out_1",
        registry_version="auto-v1",
        event=event,
        first_legitimate_resolution_at=occurred,
        tolerance=tolerance or MatchTolerance(event_family=event_type),
        adjudications=adjudications,
    )


class TestMatching:
    def test_exact_agreement_matches(self) -> None:
        result = OutcomeMatcher().score(forecast(), outcome(), CONTEXT)
        assert result.matched
        assert result.lead_time_days == 5.0

    def test_wrong_location_never_matches(self) -> None:
        # Getting the event type right is the cheapest of the four claims; it
        # must not be able to carry a match on its own.
        result = OutcomeMatcher().score(forecast(region="IN-DL"), outcome(region="BR-SP"), CONTEXT)
        assert not result.matched
        assert "different location" in result.reason

    def test_wrong_actor_never_matches_when_the_family_requires_one(self) -> None:
        result = OutcomeMatcher().score(
            forecast(actor="Metro Workers Collective"),
            outcome(actor="Coastal Fisheries Board"),
            CONTEXT,
        )
        assert not result.matched
        assert "actor" in result.reason

    def test_families_can_waive_the_actor_requirement(self) -> None:
        tolerance = MatchTolerance(event_family="flood", require_actor_match=False)
        result = OutcomeMatcher().score(
            forecast(event_type="flood", actor="Metro Workers Collective"),
            outcome(event_type="flood", actor="Coastal Fisheries Board", tolerance=tolerance),
            CONTEXT,
        )
        assert result.matched

    def test_wrong_event_type_never_matches(self) -> None:
        result = OutcomeMatcher().score(forecast("protest"), outcome("flood"), CONTEXT)
        assert not result.matched
        assert "event type" in result.reason

    def test_outcome_outside_the_horizon_never_matches(self) -> None:
        result = OutcomeMatcher().score(forecast(), outcome(days_after=90), CONTEXT)
        assert not result.matched
        assert "horizon" in result.reason

    def test_outcome_before_the_cutoff_never_matches(self) -> None:
        # Predicting something that already happened is not forecasting.
        result = OutcomeMatcher().score(forecast(), outcome(days_after=-5), CONTEXT)
        assert not result.matched

    def test_unadjudicated_matches_are_queued_for_review(self) -> None:
        assert OutcomeMatcher().score(forecast(), outcome(), CONTEXT).requires_human_review

    def test_adjudicated_clear_matches_are_not_queued(self) -> None:
        result = OutcomeMatcher().score(forecast(), outcome(adjudicated=True), CONTEXT)
        assert result.matched
        assert not result.requires_human_review

    def test_no_outcomes_yields_a_recorded_non_match(self) -> None:
        result = OutcomeMatcher().best_match(forecast(), [], CONTEXT)
        assert not result.matched
        assert result.outcome_id is None


class TestMetrics:
    def test_brier_rewards_accuracy(self) -> None:
        assert metrics.brier_score([1.0, 0.0], [1, 0]) == 0.0
        assert metrics.brier_score([0.0, 1.0], [1, 0]) == 1.0

    def test_log_loss_stays_finite_on_a_confident_miss(self) -> None:
        value = metrics.log_loss([1.0], [0])
        assert value is not None and value < 100.0

    def test_brier_skill_is_zero_for_the_base_rate(self) -> None:
        outcomes = [1, 0, 1, 0, 1, 0, 1, 0]
        assert metrics.brier_skill_score([0.5] * 8, outcomes) == 0.0

    def test_roc_auc_detects_ranking(self) -> None:
        assert metrics.roc_auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
        assert metrics.roc_auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0

    def test_roc_auc_undefined_with_one_class(self) -> None:
        # Rare events routinely produce single-class folds; that must be
        # reported as "undefined", not silently rendered as 0.5.
        assert metrics.roc_auc([0.4, 0.6], [1, 1]) is None

    def test_calibration_slope_undefined_with_one_class(self) -> None:
        assert metrics.calibration_slope_intercept([0.5] * 20, [1] * 20) == (None, None)

    def test_perfect_calibration_has_zero_error(self) -> None:
        probabilities = [0.0] * 50 + [1.0] * 50
        outcomes = [0] * 50 + [1] * 50
        assert metrics.expected_calibration_error(probabilities, outcomes) == 0.0

    def test_recall_at_budget_takes_the_top_scores(self) -> None:
        result = metrics.recall_at_budget([0.9, 0.1, 0.8, 0.2], [1, 0, 1, 0], budget=2)
        assert result.hits == 2
        assert result.recall == 1.0
        assert result.precision == 1.0

    def test_recall_at_budget_handles_no_positives(self) -> None:
        result = metrics.recall_at_budget([0.9, 0.1], [0, 0], budget=1)
        assert result.recall is None
        assert result.precision == 0.0

    def test_candidate_recall_is_over_distinct_outcomes(self) -> None:
        assert metrics.candidate_recall(["a", "a", "b"], ["a", "b", "c"]) == round(2 / 3, 9)

    def test_candidate_recall_undefined_without_outcomes(self) -> None:
        assert metrics.candidate_recall([], []) is None

    def test_wilson_interval_brackets_the_estimate(self) -> None:
        low, high = metrics.wilson_interval(50, 100)
        assert low < 0.5 < high

    def test_wilson_interval_is_uninformative_with_no_trials(self) -> None:
        assert metrics.wilson_interval(0, 0) == (0.0, 1.0)

    def test_lead_time_stats_on_empty_input(self) -> None:
        assert metrics.lead_time_stats([])["count"] == 0
