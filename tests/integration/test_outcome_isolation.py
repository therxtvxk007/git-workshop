"""Outcomes cannot be reached while forecasts are being produced.

The ordering rule used to be enforced by the order of two statements in one
function. This suite proves it is now enforced by the runtime, using a ledger
that detonates on any outcome access: if the forecasting pass touches outcome
data anywhere, however deep in the call stack, pass A fails outright.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx import isolation
from pramaanx.config import Settings
from pramaanx.evaluation.backtest import Backtester, ExperimentSpec
from pramaanx.evaluation.matcher import MatchContext, OutcomeMatcher
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.isolation import OutcomeAccessError, forecasting_pass, in_forecasting_pass
from pramaanx.ledger.resolutions import build_outcome_registry
from pramaanx.schemas.outcome import OutcomeRecord

CUTOFF = datetime(2025, 6, 1, tzinfo=UTC)


class ExplodingOutcomeLedger(EvidenceLedger):
    """A ledger that records -- and refuses -- every outcome access.

    Stronger than a mock: the forecasting pass runs against a real ledger for
    everything it is allowed to do, and only outcome access is booby-trapped.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.outcome_calls: list[str] = []

    def read_outcomes(self) -> list[OutcomeRecord]:
        self.outcome_calls.append("read_outcomes")
        raise AssertionError("read_outcomes was called during the forecasting pass")

    def write_outcomes(self, outcomes: object) -> object:
        self.outcome_calls.append("write_outcomes")
        raise AssertionError("write_outcomes was called during the forecasting pass")

    def read_resolved_events(self) -> list[object]:
        self.outcome_calls.append("read_resolved_events")
        raise AssertionError("read_resolved_events was called during the forecasting pass")


@pytest.fixture
def spy_ledger(settings: Settings, clock: object) -> ExplodingOutcomeLedger:
    ledger = ExplodingOutcomeLedger(settings, clock=clock)  # type: ignore[arg-type]
    from pramaanx.ingest.base import FetchWindow

    ledger.ingest(
        "synthetic",
        FetchWindow(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 10, 1, tzinfo=UTC)),
    )
    return ledger


@pytest.fixture
def spec() -> ExperimentSpec:
    return ExperimentSpec(
        name="isolation_walk",
        start=CUTOFF,
        end=CUTOFF + timedelta(days=7),
        step_days=7,
        horizon_days=30,
    )


class TestGuardMechanics:
    def test_guard_is_inactive_by_default(self) -> None:
        assert not in_forecasting_pass()
        isolation.guard_outcome_access("anything")  # does not raise

    def test_guard_blocks_inside_a_pass(self) -> None:
        with forecasting_pass("test"), pytest.raises(OutcomeAccessError, match="test"):
            isolation.guard_outcome_access("EvidenceLedger.read_outcomes")

    def test_guard_is_released_afterwards(self) -> None:
        with forecasting_pass("test"):
            assert isolation.active_pass() == "test"
        assert not in_forecasting_pass()

    def test_guard_is_released_after_an_exception(self) -> None:
        with pytest.raises(RuntimeError, match="boom"), forecasting_pass("test"):
            raise RuntimeError("boom")
        assert not in_forecasting_pass()


class TestSealedOperations:
    def test_registry_construction_is_sealed(self, populated_ledger: EvidenceLedger) -> None:
        with forecasting_pass("backtest"), pytest.raises(OutcomeAccessError):
            build_outcome_registry(populated_ledger, populated_ledger.read_observations())

    def test_ledger_reads_are_sealed(self, populated_ledger: EvidenceLedger) -> None:
        with forecasting_pass("backtest"):
            with pytest.raises(OutcomeAccessError):
                populated_ledger.read_outcomes()
            with pytest.raises(OutcomeAccessError):
                populated_ledger.read_resolved_events()
            with pytest.raises(OutcomeAccessError):
                populated_ledger.write_outcomes([])

    def test_matching_is_sealed(self) -> None:
        # Scoring is outcome access by definition, whatever it is called.
        with forecasting_pass("backtest"), pytest.raises(OutcomeAccessError):
            OutcomeMatcher().score(
                _minimal_forecast(),
                _minimal_outcome(),
                MatchContext(cutoff_at=CUTOFF, horizon_days=30),
            )

    def test_observations_remain_readable(self, populated_ledger: EvidenceLedger) -> None:
        # The seal must not block the evidence the forecasting pass needs.
        with forecasting_pass("backtest"):
            assert populated_ledger.read_observations()


class TestTwoPassBacktest:
    def test_forecasting_pass_never_touches_outcomes(
        self, settings: Settings, spy_ledger: ExplodingOutcomeLedger, spec: ExperimentSpec
    ) -> None:
        plans = Backtester(settings, spy_ledger).forecasting_pass(spec)
        assert len(plans) == len(spec.cutoffs())
        assert all(plan.forecasts > 0 for plan in plans)
        assert spy_ledger.outcome_calls == []

    def test_pass_a_output_carries_no_outcome_data(
        self, settings: Settings, spy_ledger: ExplodingOutcomeLedger, spec: ExperimentSpec
    ) -> None:
        plans = Backtester(settings, spy_ledger).forecasting_pass(spec)
        fields = set(vars(plans[0]))
        assert fields == {
            "cutoff_at",
            "snapshot_id",
            "snapshot_hash",
            "observations",
            "forecasts",
        }

    def test_scoring_pass_reads_forecasts_back_from_the_ledger(
        self, settings: Settings, populated_ledger: EvidenceLedger, spec: ExperimentSpec
    ) -> None:
        # What gets scored is what was persisted before outcomes existed, not a
        # convenient in-memory copy.
        backtester = Backtester(settings, populated_ledger)
        plans = backtester.forecasting_pass(spec)
        assert backtester.forecast_ledger.count() == sum(plan.forecasts for plan in plans)
        scored = backtester.scoring_pass(spec, plans)
        assert [fold.forecasts for fold in scored.folds] == [plan.forecasts for plan in plans]
        assert len(scored.probabilities) == len(scored.labels)

    def test_run_completes_both_passes(
        self, settings: Settings, populated_ledger: EvidenceLedger, spec: ExperimentSpec
    ) -> None:
        report = Backtester(settings, populated_ledger).run(spec)
        assert report.provenance["evaluation_passes"] == [
            "forecasting (outcomes sealed)",
            "scoring",
        ]
        assert report.aggregate["scoreable_folds"] > 0
        assert not in_forecasting_pass()


def _minimal_forecast() -> object:
    from pramaanx.schemas.event import EventHypothesis
    from pramaanx.schemas.forecast import ForecastRecord, ForecastStatus

    return ForecastRecord(
        forecast_id="fc_1",
        cutoff_at=CUTOFF,
        created_at=CUTOFF,
        hypothesis=EventHypothesis(event_id="evt_1", event_type="protest"),
        raw_probability=0.5,
        calibrated_probability=0.5,
        epistemic_uncertainty=0.1,
        status=ForecastStatus.WATCH,
        snapshot_hash="sha256:abc",
    )


def _minimal_outcome() -> OutcomeRecord:
    from pramaanx.schemas.event import ResolvedEvent
    from pramaanx.schemas.outcome import MatchTolerance

    return OutcomeRecord(
        outcome_id="out_1",
        registry_version="auto-v1",
        event=ResolvedEvent(
            resolved_event_id="rev_1",
            event_type="protest",
            occurred_at=CUTOFF + timedelta(days=3),
        ),
        first_legitimate_resolution_at=CUTOFF + timedelta(days=3),
        tolerance=MatchTolerance(event_family="protest"),
    )
