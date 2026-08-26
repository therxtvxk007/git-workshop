"""Right-censored folds are never scored silently.

A fold whose evidence stops before ``cutoff + horizon + reporting delay`` has
not seen the reports that would resolve it. Score it anyway and the missing
reports look exactly like events that never happened: recall is understated,
precision is overstated, and no number in the output hints at it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.config import Settings
from pramaanx.evaluation.backtest import (
    Backtester,
    CensoredEvaluationError,
    ExperimentSpec,
    ResolutionBoundary,
    measure_resolution_boundary,
)
from pramaanx.evaluation.reports import render_markdown
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.ledger import EvidenceLedger

WORLD_START = datetime(2025, 1, 1, tzinfo=UTC)
EVIDENCE_END = datetime(2025, 7, 1, tzinfo=UTC)


@pytest.fixture
def short_ledger(settings: Settings, clock: object) -> EvidenceLedger:
    """Evidence that stops on 1 July 2025."""
    ledger = EvidenceLedger(settings, clock=clock)  # type: ignore[arg-type]
    ledger.ingest("synthetic", FetchWindow(WORLD_START, EVIDENCE_END))
    return ledger


def walk(start: datetime, end: datetime, horizon_days: int = 30) -> ExperimentSpec:
    return ExperimentSpec(
        name="censoring_walk", start=start, end=end, step_days=14, horizon_days=horizon_days
    )


class TestBoundaryArithmetic:
    def test_required_end_includes_horizon_and_delay(self) -> None:
        boundary = ResolutionBoundary(
            latest_evidence_at=EVIDENCE_END,
            reporting_delay_days=3.0,
            empirical_delay_days=2.25,
            configured_delay_days=3.0,
        )
        cutoff = datetime(2025, 5, 1, tzinfo=UTC)
        assert boundary.required_evidence_end(cutoff, 30) == cutoff + timedelta(days=33)

    def test_a_fold_with_enough_evidence_is_not_censored(self) -> None:
        boundary = ResolutionBoundary(EVIDENCE_END, 3.0, 2.25, 3.0)
        assert boundary.censoring_reason(datetime(2025, 5, 1, tzinfo=UTC), 30) is None

    def test_a_fold_without_enough_evidence_reports_the_shortfall(self) -> None:
        boundary = ResolutionBoundary(EVIDENCE_END, 3.0, 2.25, 3.0)
        reason = boundary.censoring_reason(datetime(2025, 6, 20, tzinfo=UTC), 30)
        assert reason is not None
        assert "right-censored" in reason
        assert "days short" in reason

    def test_delay_is_the_larger_of_configured_and_observed(self) -> None:
        from pramaanx.schemas.event import ResolvedEvent
        from pramaanx.schemas.outcome import MatchTolerance, OutcomeRecord

        occurred = datetime(2025, 3, 1, tzinfo=UTC)
        outcome = OutcomeRecord(
            outcome_id="out_1",
            registry_version="auto-v1",
            event=ResolvedEvent(
                resolved_event_id="rev_1", event_type="flood", occurred_at=occurred
            ),
            # This corpus once took 9 days to report an event.
            first_legitimate_resolution_at=occurred + timedelta(days=9),
            tolerance=MatchTolerance(event_family="flood"),
        )
        boundary = measure_resolution_boundary(EVIDENCE_END, [outcome], configured_delay_days=3.0)
        assert boundary.empirical_delay_days == pytest.approx(9.0)
        assert boundary.reporting_delay_days == pytest.approx(9.0)

    def test_the_configured_value_is_a_floor(self) -> None:
        # With an empty or tiny registry the empirical maximum understates the
        # delay, so the configured floor takes over.
        boundary = measure_resolution_boundary(EVIDENCE_END, [], configured_delay_days=3.0)
        assert boundary.empirical_delay_days is None
        assert boundary.reporting_delay_days == 3.0


class TestCensoredFolds:
    def test_late_folds_are_marked_unscoreable(
        self, settings: Settings, short_ledger: EvidenceLedger
    ) -> None:
        # The walk runs right up to the edge of the evidence.
        spec = walk(datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 6, 24, tzinfo=UTC))
        report = Backtester(settings, short_ledger).run(spec)

        censored = [fold for fold in report.folds if not fold.scoreable]
        scoreable = [fold for fold in report.folds if fold.scoreable]
        assert censored, "folds near the end of the evidence should be censored"
        assert scoreable, "early folds should still be scoreable"
        assert all("right-censored" in (fold.censoring_reason or "") for fold in censored)

    def test_censored_folds_are_excluded_from_the_aggregate(
        self, settings: Settings, short_ledger: EvidenceLedger
    ) -> None:
        spec = walk(datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 6, 24, tzinfo=UTC))
        report = Backtester(settings, short_ledger).run(spec)
        aggregate = report.aggregate
        assert aggregate["scoreable_folds"] + aggregate["censored_folds"] == aggregate["folds"]
        assert aggregate["censored_folds"] > 0
        assert aggregate["forecasts"] == sum(
            fold.forecasts for fold in report.folds if fold.scoreable
        )

    def test_censored_folds_are_still_forecast_and_still_counted(
        self, settings: Settings, short_ledger: EvidenceLedger
    ) -> None:
        # Censoring is an evaluation limit, not a reason to skip the work: the
        # forecasts exist and are in the ledger, they simply cannot be scored.
        spec = walk(datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 6, 24, tzinfo=UTC))
        report = Backtester(settings, short_ledger).run(spec)
        censored = [fold for fold in report.folds if not fold.scoreable]
        assert all(fold.forecasts > 0 for fold in censored)
        assert all(fold.metrics == {} for fold in censored)

    def test_the_report_says_which_folds_were_dropped(
        self, settings: Settings, short_ledger: EvidenceLedger
    ) -> None:
        spec = walk(datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 6, 24, tzinfo=UTC))
        report = Backtester(settings, short_ledger).run(spec)
        markdown = render_markdown(report)
        assert "censored" in markdown
        assert "### Censored folds" in markdown
        assert any("right-censored" in limit for limit in report.aggregate["interpretation_limits"])

    def test_a_wholly_censored_walk_fails_loudly(
        self, settings: Settings, short_ledger: EvidenceLedger
    ) -> None:
        # Every fold past the evidence: there is nothing honest to report, so
        # the run raises rather than emitting a report of artefacts.
        spec = walk(datetime(2025, 6, 20, tzinfo=UTC), datetime(2025, 6, 28, tzinfo=UTC))
        with pytest.raises(CensoredEvaluationError, match="right-censored"):
            Backtester(settings, short_ledger).run(spec)

    def test_an_empty_ledger_fails_loudly(self, settings: Settings) -> None:
        spec = walk(datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 4, 15, tzinfo=UTC))
        backtester = Backtester(settings, EvidenceLedger(settings))
        with pytest.raises(CensoredEvaluationError, match="nothing to score"):
            backtester.run(spec)

    def test_boundary_is_recorded_in_the_report(
        self, settings: Settings, short_ledger: EvidenceLedger
    ) -> None:
        spec = walk(datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 5, 1, tzinfo=UTC))
        report = Backtester(settings, short_ledger).run(spec)
        boundary = report.aggregate["resolution_boundary"]
        assert boundary["latest_evidence_at"][:10] <= "2025-07-01"
        assert boundary["reporting_delay_days"] >= settings.evaluation.max_reporting_delay_days


class TestShippedExperimentsAreNotCensored:
    @pytest.mark.parametrize("name", ["smoke", "e2e_v1"])
    def test_demo_experiments_fit_inside_the_demo_window(self, name: str) -> None:
        from pramaanx.evaluation.backtest import load_experiment
        from pramaanx.timeguard.snapshots import parse_cutoff

        spec, config = load_experiment(f"configs/experiments/{name}.yaml")
        # The window the demo and the bootstrap script actually ingest.
        evidence_end = parse_cutoff("2026-05-01T00:00:00Z")
        required = spec.cutoffs()[-1] + timedelta(
            days=spec.horizon_days + config.evaluation.max_reporting_delay_days
        )
        assert evidence_end >= required
