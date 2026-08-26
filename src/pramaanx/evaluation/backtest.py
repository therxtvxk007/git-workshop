"""Rolling-cutoff backtest.

The skeleton the build plan asks for at M0: walk a sequence of cutoffs, freeze
a snapshot at each, forecast from that snapshot alone, then score against
outcomes that were not knowable at the cutoff.

Two ordering rules make this a backtest rather than a fit:

* forecasts for cutoff T are produced and written before any outcome is read;
* an outcome only enters the resolution set if it occurred after T, so nothing
  that scores a forecast could have informed it.

Splits are temporal, always. A random document split would let tomorrow's
reporting explain yesterday's forecast and is not permitted for any claim.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from pramaanx import isolation
from pramaanx.clock import Clock, FixedClock
from pramaanx.config import Settings, load_settings
from pramaanx.evaluation import metrics
from pramaanx.evaluation.matcher import MatchContext, OutcomeMatcher
from pramaanx.hashing import hash_object, stable_id, utc_isoformat
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.ledger.forecasts import ForecastLedger, status_breakdown
from pramaanx.ledger.resolutions import adjudication_summary, build_outcome_registry
from pramaanx.logging import get_logger, log_context
from pramaanx.pipeline import run_cutoff
from pramaanx.schemas.forecast import ForecastRecord, ForecastStatus
from pramaanx.schemas.outcome import MatchResult, OutcomeRecord
from pramaanx.timeguard.snapshots import SnapshotBuilder, code_hash, parse_cutoff

log = get_logger(__name__)


@dataclass(frozen=True)
class ExperimentSpec:
    """A backtest definition, loaded from ``configs/experiments/*.yaml``."""

    name: str
    start: datetime
    end: datetime
    step_days: int
    horizon_days: int
    description: str = ""
    region_scope: list[str] | None = None
    settings_overrides: dict[str, Any] = field(default_factory=dict)

    def cutoffs(self) -> list[datetime]:
        moments: list[datetime] = []
        current = self.start
        while current <= self.end:
            moments.append(current)
            current += timedelta(days=self.step_days)
        return moments

    def fingerprint(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start": utc_isoformat(self.start),
            "end": utc_isoformat(self.end),
            "step_days": self.step_days,
            "horizon_days": self.horizon_days,
            "region_scope": sorted(self.region_scope) if self.region_scope else None,
            "settings_overrides": self.settings_overrides,
        }


def load_experiment(path: Path | str) -> tuple[ExperimentSpec, Settings]:
    """Load an experiment file into a spec plus its resolved settings.

    The file has two top-level blocks: ``backtest`` (the walk) and ``settings``
    (overrides layered onto ``configs/base.yaml``). Keeping them separate means
    the settings hash recorded in the report is exactly the configuration the
    pipeline ran with.
    """
    experiment_path = Path(path)
    raw = yaml.safe_load(experiment_path.read_text(encoding="utf-8")) or {}
    backtest = raw.get("backtest")
    if not backtest:
        raise ValueError(f"{experiment_path} has no 'backtest' block")

    overrides = raw.get("settings", {}) or {}
    settings = load_settings(raw.get("base_config", "configs/base.yaml"), overrides=overrides)
    horizon = int(backtest.get("horizon_days", settings.horizon_days))
    if horizon != settings.horizon_days:
        settings = settings.model_copy(update={"horizon_days": horizon})

    spec = ExperimentSpec(
        name=str(raw.get("name", experiment_path.stem)),
        description=str(raw.get("description", "")),
        start=parse_cutoff(str(backtest["start"])),
        end=parse_cutoff(str(backtest["end"])),
        step_days=int(backtest.get("step_days", settings.evaluation.step_days)),
        horizon_days=horizon,
        region_scope=backtest.get("region_scope"),
        settings_overrides=overrides,
    )
    return spec, settings


@dataclass(frozen=True)
class CutoffPlan:
    """What the forecasting pass produced for one cutoff.

    Deliberately carries no outcome information: this is the whole record that
    crosses from the forecasting pass into the scoring pass.
    """

    cutoff_at: datetime
    snapshot_id: str
    snapshot_hash: str
    observations: int
    forecasts: int


@dataclass
class FoldResult:
    """One cutoff's forecasts, matches and metrics."""

    cutoff_at: datetime
    snapshot_id: str
    snapshot_hash: str
    observations: int
    forecasts: int
    outcomes_in_window: int
    matches: list[MatchResult]
    metrics: dict[str, Any]
    status_counts: dict[str, int]
    scoreable: bool = True
    censoring_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cutoff_at": utc_isoformat(self.cutoff_at),
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "observations": self.observations,
            "forecasts": self.forecasts,
            "outcomes_in_window": self.outcomes_in_window,
            "status_counts": dict(sorted(self.status_counts.items())),
            "metrics": self.metrics if self.scoreable else {},
            "scoreable": self.scoreable,
            "censoring_reason": self.censoring_reason,
            "human_review_queue": sum(1 for item in self.matches if item.requires_human_review),
        }


@dataclass
class BacktestReport:
    experiment: ExperimentSpec
    settings: Settings
    folds: list[FoldResult]
    aggregate: dict[str, Any]
    provenance: dict[str, Any]

    @property
    def run_id(self) -> str:
        return stable_id("run", self.content_fingerprint(), length=20)

    def content_fingerprint(self) -> dict[str, Any]:
        """Everything the report asserts, excluding wall-clock provenance.

        Two runs over the same evidence and configuration must produce the same
        fingerprint, which is what the reproducibility gate checks.
        """
        return {
            "experiment": self.experiment.fingerprint(),
            "config_hash": self.settings.config_hash,
            "code_hash": self.provenance.get("code_hash"),
            "folds": [fold.to_dict() for fold in self.folds],
            "aggregate": self.aggregate,
        }

    @property
    def report_hash(self) -> str:
        return hash_object(self.content_fingerprint())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "backtest_report",
            "run_id": self.run_id,
            "report_hash": self.report_hash,
            **self.content_fingerprint(),
            "provenance": self.provenance,
        }


class CensoredEvaluationError(RuntimeError):
    """Every fold in the walk is right-censored, so nothing can be scored."""


@dataclass(frozen=True)
class ResolutionBoundary:
    """How far the evidence actually reaches, and how late reports arrive.

    A fold is scoreable only when the ledger extends past
    ``cutoff + horizon + reporting delay``. Score a fold whose evidence stops
    earlier and the missing reports look exactly like events that never
    happened -- recall is understated, precision is overstated, and nothing in
    the output says so.
    """

    latest_evidence_at: datetime
    reporting_delay_days: float
    empirical_delay_days: float | None
    configured_delay_days: float

    def required_evidence_end(self, cutoff_at: datetime, horizon_days: int) -> datetime:
        return cutoff_at + timedelta(days=horizon_days + self.reporting_delay_days)

    def censoring_reason(self, cutoff_at: datetime, horizon_days: int) -> str | None:
        required = self.required_evidence_end(cutoff_at, horizon_days)
        if self.latest_evidence_at >= required:
            return None
        shortfall = (required - self.latest_evidence_at).total_seconds() / 86400.0
        return (
            f"right-censored: scoring this fold needs evidence through "
            f"{utc_isoformat(required)} (cutoff + {horizon_days}d horizon + "
            f"{self.reporting_delay_days:.2f}d reporting delay) but the ledger ends at "
            f"{utc_isoformat(self.latest_evidence_at)}, {shortfall:.2f} days short"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "latest_evidence_at": utc_isoformat(self.latest_evidence_at),
            "reporting_delay_days": round(self.reporting_delay_days, 6),
            "empirical_delay_days": (
                round(self.empirical_delay_days, 6)
                if self.empirical_delay_days is not None
                else None
            ),
            "configured_delay_days": round(self.configured_delay_days, 6),
        }


def measure_resolution_boundary(
    observations_latest: datetime,
    outcomes: Sequence[OutcomeRecord],
    configured_delay_days: float,
) -> ResolutionBoundary:
    """Combine the observed reporting lag with the configured floor.

    The empirical maximum is what this corpus actually did; the configured value
    is a floor for the case where the registry is small or empty and the
    empirical maximum is therefore an underestimate.
    """
    delays = [
        (outcome.first_legitimate_resolution_at - outcome.event.occurred_at).total_seconds()
        / 86400.0
        for outcome in outcomes
    ]
    empirical = max(delays) if delays else None
    return ResolutionBoundary(
        latest_evidence_at=observations_latest,
        reporting_delay_days=max(configured_delay_days, empirical or 0.0),
        empirical_delay_days=empirical,
        configured_delay_days=configured_delay_days,
    )


def outcomes_in_window(
    outcomes: Sequence[OutcomeRecord], cutoff_at: datetime, horizon_days: int
) -> list[OutcomeRecord]:
    """Outcomes that occurred strictly after the cutoff, inside the horizon.

    ``occurred_at > cutoff`` is the test rather than the resolution time: an
    event that happened before T was knowable at T and forecasting it is not
    forecasting.
    """
    horizon_end = cutoff_at + timedelta(days=horizon_days)
    selected = [
        outcome for outcome in outcomes if cutoff_at < outcome.event.occurred_at <= horizon_end
    ]
    return sorted(selected, key=lambda item: (item.event.occurred_at, item.outcome_id))


def _fold_metrics(
    forecasts: Sequence[ForecastRecord],
    matches: Sequence[MatchResult],
    window_outcomes: Sequence[OutcomeRecord],
    settings: Settings,
    horizon_days: int,
) -> dict[str, Any]:
    labels = [1 if item.matched else 0 for item in matches]
    probabilities = [item.calibrated_probability for item in forecasts]
    matched_outcome_ids = [item.outcome_id for item in matches if item.matched and item.outcome_id]
    all_outcome_ids = [item.outcome_id for item in window_outcomes]

    regions = len({forecast.hypothesis.most_likely_location() for forecast in forecasts} - {None})
    budget = max(
        1, round(settings.evaluation.alerts_per_region_day * max(regions, 1) * horizon_days)
    )
    alerts = [
        index for index, forecast in enumerate(forecasts) if forecast.status is ForecastStatus.ALERT
    ]
    alert_labels = [labels[index] for index in alerts]

    return {
        "discovery": {
            "candidates": len(forecasts),
            "candidate_recall": metrics.candidate_recall(matched_outcome_ids, all_outcome_ids),
            "outcomes_covered": len(set(matched_outcome_ids)),
            "outcomes_total": len(all_outcome_ids),
        },
        "budgeted": [
            metrics.recall_at_budget(probabilities, labels, size).to_dict()
            for size in sorted(settings.evaluation.proposal_budgets)
        ],
        "alert_budget": {
            "regions": regions,
            "horizon_days": horizon_days,
            "alerts_per_region_day": settings.evaluation.alerts_per_region_day,
            "budget": budget,
            **metrics.recall_at_budget(probabilities, labels, budget).to_dict(),
        },
        "probability": {
            "brier": metrics.brier_score(probabilities, labels),
            "log_loss": metrics.log_loss(probabilities, labels),
            "brier_skill_score": metrics.brier_skill_score(probabilities, labels),
            "base_rate": metrics.base_rate(labels),
            "roc_auc": metrics.roc_auc(probabilities, labels),
            "expected_calibration_error": metrics.expected_calibration_error(
                probabilities, labels, settings.evaluation.reliability_bins
            ),
        },
        "alerts": {
            "count": len(alerts),
            "hits": int(sum(alert_labels)),
            "precision": (round(sum(alert_labels) / len(alerts), 9) if alerts else None),
            "per_region_day": metrics.alerts_per_region_day(
                len(alerts), max(regions, 1), float(horizon_days)
            ),
        },
        "lead_time_days": metrics.lead_time_stats(
            [item.lead_time_days for item in matches if item.matched and item.lead_time_days]
        ),
    }


@dataclass(frozen=True)
class ScoringResult:
    """Everything the scoring pass produced."""

    folds: list[FoldResult]
    boundary: ResolutionBoundary
    outcomes: list[OutcomeRecord]
    probabilities: list[float]
    labels: list[int]


class Backtester:
    """Runs an experiment over rolling cutoffs."""

    def __init__(
        self,
        settings: Settings,
        ledger: EvidenceLedger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger or EvidenceLedger(settings)
        # A fixed clock by default: created_at is metadata, and letting it vary
        # would make otherwise identical runs produce different bytes.
        self.clock = clock or FixedClock(datetime(2000, 1, 1, tzinfo=UTC))
        self.snapshots = SnapshotBuilder(settings, self.ledger, clock=self.clock)
        self.forecast_ledger = ForecastLedger(settings)
        self.matcher = OutcomeMatcher(min_score=settings.evaluation.match_min_score)

    # -- pass A: forecasting ---------------------------------------------
    def forecasting_pass(self, spec: ExperimentSpec) -> list[CutoffPlan]:
        """Build snapshots and persist forecasts. No outcome may be touched.

        The whole pass runs inside :func:`pramaanx.isolation.forecasting_pass`,
        so any outcome read anywhere beneath it -- however many layers down --
        raises instead of quietly improving the result.
        """
        plans: list[CutoffPlan] = []
        with isolation.forecasting_pass(f"backtest:{spec.name}"):
            for cutoff_at in spec.cutoffs():
                with log_context(cutoff=utc_isoformat(cutoff_at), experiment=spec.name):
                    snapshot = self.snapshots.build(cutoff_at)
                    run = run_cutoff(self.settings, self.ledger, snapshot, clock=self.clock)
                    self.forecast_ledger.append(run.forecasts)
                    plans.append(
                        CutoffPlan(
                            cutoff_at=cutoff_at,
                            snapshot_id=snapshot.snapshot_id,
                            snapshot_hash=snapshot.snapshot_hash,
                            observations=len(snapshot),
                            forecasts=len(run.forecasts),
                        )
                    )
        log.info("backtest.forecasting_pass_complete", experiment=spec.name, cutoffs=len(plans))
        return plans

    # -- pass B: scoring ---------------------------------------------------
    def _score_fold(
        self,
        plan: CutoffPlan,
        outcomes: Sequence[OutcomeRecord],
        boundary: ResolutionBoundary,
        horizon_days: int,
    ) -> tuple[FoldResult, list[ForecastRecord]]:
        # Forecasts are re-read from the ledger rather than kept in memory, so
        # what gets scored is provably what was persisted before any outcome
        # was available.
        forecasts = sorted(
            self.forecast_ledger.for_snapshot(plan.snapshot_hash),
            key=lambda item: item.forecast_id,
        )
        censoring = boundary.censoring_reason(plan.cutoff_at, horizon_days)
        window = outcomes_in_window(outcomes, plan.cutoff_at, horizon_days)
        context = MatchContext(cutoff_at=plan.cutoff_at, horizon_days=horizon_days)
        matches = self.matcher.match_all(forecasts, window, context) if censoring is None else []
        fold = FoldResult(
            cutoff_at=plan.cutoff_at,
            snapshot_id=plan.snapshot_id,
            snapshot_hash=plan.snapshot_hash,
            observations=plan.observations,
            forecasts=len(forecasts),
            outcomes_in_window=len(window),
            matches=matches,
            metrics=(
                _fold_metrics(forecasts, matches, window, self.settings, horizon_days)
                if censoring is None
                else {}
            ),
            status_counts=status_breakdown(forecasts),
            scoreable=censoring is None,
            censoring_reason=censoring,
        )
        return fold, forecasts

    def scoring_pass(self, spec: ExperimentSpec, plans: Sequence[CutoffPlan]) -> ScoringResult:
        """Build outcomes and score the frozen forecasts."""
        observations = self.ledger.read_observations()
        if not observations:
            raise CensoredEvaluationError("the ledger is empty; there is nothing to score")
        latest_evidence = max(item.first_observed_at for item in observations)
        outcomes = build_outcome_registry(self.ledger, observations)
        boundary = measure_resolution_boundary(
            latest_evidence, outcomes, self.settings.evaluation.max_reporting_delay_days
        )

        folds: list[FoldResult] = []
        probabilities: list[float] = []
        labels: list[int] = []
        for plan in plans:
            fold, forecasts = self._score_fold(plan, outcomes, boundary, spec.horizon_days)
            folds.append(fold)
            if not fold.scoreable:
                continue
            # Pooled arrays are built here, where the scored forecasts and their
            # match results are both in hand. Re-reading them later would risk
            # the two falling out of alignment for no benefit.
            probabilities.extend(item.calibrated_probability for item in forecasts)
            labels.extend(1 if item.matched else 0 for item in fold.matches)

        scoreable = [fold for fold in folds if fold.scoreable]
        if not scoreable:
            # Failing loudly beats emitting a report whose every number is an
            # artefact of evidence that stops too early.
            raise CensoredEvaluationError(
                f"every fold in {spec.name!r} is right-censored. "
                f"{folds[0].censoring_reason if folds else 'No folds were produced.'} "
                "Ingest evidence past the final cutoff plus the horizon plus the reporting "
                "delay, or move the walk earlier."
            )
        if len(scoreable) < len(folds):
            log.warning(
                "backtest.censored_folds",
                censored=len(folds) - len(scoreable),
                total=len(folds),
            )
        return ScoringResult(
            folds=folds,
            boundary=boundary,
            outcomes=outcomes,
            probabilities=probabilities,
            labels=labels,
        )

    def run(self, spec: ExperimentSpec) -> BacktestReport:
        """Two passes, in this order, always.

        Pass A produces and persists every forecast with outcomes sealed off.
        Pass B unseals them and scores what pass A froze.
        """
        plans = self.forecasting_pass(spec)
        scored = self.scoring_pass(spec, plans)
        folds = scored.folds

        aggregate = self._aggregate(
            folds, scored.probabilities, scored.labels, scored.outcomes, spec
        )
        aggregate["resolution_boundary"] = scored.boundary.to_dict()
        provenance = {
            "code_hash": code_hash(),
            "config_hash": self.settings.config_hash,
            "random_seed": self.settings.random_seed,
            "generators_enabled": list(self.settings.generators.enabled),
            "calibration": "none (identity)",
            "risk_control": "none (fixed thresholds)",
            "evaluation_passes": ["forecasting (outcomes sealed)", "scoring"],
            "snapshot_ids": [fold.snapshot_id for fold in folds],
        }
        report = BacktestReport(
            experiment=spec,
            settings=self.settings,
            folds=folds,
            aggregate=aggregate,
            provenance=provenance,
        )
        log.info(
            "backtest.complete",
            experiment=spec.name,
            folds=len(folds),
            scoreable=sum(1 for fold in folds if fold.scoreable),
            run_id=report.run_id,
            report_hash=report.report_hash,
        )
        return report

    def _aggregate(
        self,
        folds: Sequence[FoldResult],
        probabilities: Sequence[float],
        labels: Sequence[int],
        outcomes: Sequence[OutcomeRecord],
        spec: ExperimentSpec,
    ) -> dict[str, Any]:
        slope, intercept = metrics.calibration_slope_intercept(probabilities, labels)
        scoreable = [fold for fold in folds if fold.scoreable]
        censored = [fold for fold in folds if not fold.scoreable]
        recalls = [
            fold.metrics["discovery"]["candidate_recall"]
            for fold in scoreable
            if fold.metrics["discovery"]["candidate_recall"] is not None
        ]
        return {
            "folds": len(folds),
            "scoreable_folds": len(scoreable),
            "censored_folds": len(censored),
            "forecasts": sum(fold.forecasts for fold in scoreable),
            "outcomes_scored": sum(fold.outcomes_in_window for fold in scoreable),
            "pooled": {
                "brier": metrics.brier_score(probabilities, labels),
                "log_loss": metrics.log_loss(probabilities, labels),
                "brier_skill_score": metrics.brier_skill_score(probabilities, labels),
                "base_rate": metrics.base_rate(labels),
                "roc_auc": metrics.roc_auc(probabilities, labels),
                "expected_calibration_error": metrics.expected_calibration_error(
                    probabilities, labels, self.settings.evaluation.reliability_bins
                ),
                "calibration_slope": slope,
                "calibration_intercept": intercept,
                "reliability_curve": metrics.calibration_curve(
                    probabilities, labels, self.settings.evaluation.reliability_bins
                ),
            },
            "candidate_recall": {
                "mean": round(sum(recalls) / len(recalls), 9) if recalls else None,
                "min": round(min(recalls), 9) if recalls else None,
                "max": round(max(recalls), 9) if recalls else None,
                "folds_with_outcomes": len(recalls),
            },
            "human_review_queue": sum(
                sum(1 for item in fold.matches if item.requires_human_review) for fold in scoreable
            ),
            "outcome_registry": adjudication_summary(outcomes),
            "horizon_days": spec.horizon_days,
            "interpretation_limits": [
                *(
                    [
                        f"{len(censored)} of {len(folds)} folds were right-censored and are "
                        "excluded: the ledger does not reach far enough past their horizon for "
                        "late reports to have arrived."
                    ]
                    if censored
                    else []
                ),
                "Probabilities are uncalibrated generator output; no calibrator was fitted.",
                "Statuses come from fixed placeholder thresholds and carry no miss-rate guarantee.",
                "Outcomes are machine-derived and unadjudicated; these numbers measure agreement "
                "with automated resolution, not with reality.",
                "One generator is enabled, so candidate recall is a single-branch floor, not a "
                "union result.",
            ],
        }


def iter_cutoffs(start: datetime, end: datetime, step_days: int) -> Iterator[datetime]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=step_days)
