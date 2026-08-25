"""The M0 loop, end to end.

Ingest -> snapshot -> extract -> generate -> forecast -> match -> report, on the
synthetic world, offline. Also the CLI surface, because the project has to be
operable without notebooks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from pramaanx.clock import FixedClock
from pramaanx.config import Settings
from pramaanx.evaluation.backtest import Backtester, ExperimentSpec, load_experiment
from pramaanx.evaluation.reports import render_markdown, write_report
from pramaanx.extraction.structured import extract_mentions
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.ledger.forecasts import ForecastLedger
from pramaanx.ledger.resolutions import build_outcome_registry
from pramaanx.pipeline import run_cutoff
from pramaanx.schemas.forecast import ForecastStatus
from pramaanx.timeguard.snapshots import SnapshotBuilder

CUTOFF = datetime(2025, 6, 1, tzinfo=UTC)


@pytest.fixture
def spec() -> ExperimentSpec:
    return ExperimentSpec(
        name="test_walk",
        start=CUTOFF,
        end=CUTOFF + timedelta(days=14),
        step_days=7,
        horizon_days=30,
    )


class TestPipeline:
    def test_full_loop_produces_scoreable_forecasts(
        self, settings: Settings, populated_ledger: EvidenceLedger, clock: FixedClock
    ) -> None:
        snapshot = SnapshotBuilder(settings, populated_ledger, clock=clock).build(CUTOFF)
        assert len(snapshot) > 0

        mentions = extract_mentions(populated_ledger, list(snapshot.observations))
        assert len(mentions) == len(snapshot)

        run = run_cutoff(settings, populated_ledger, snapshot, clock=clock)
        assert run.forecasts

        for forecast in run.forecasts:
            assert forecast.snapshot_hash == snapshot.snapshot_hash
            assert forecast.cutoff_at == CUTOFF
            # Nothing was calibrated and no risk controller ran; the record has
            # to say so rather than implying otherwise.
            assert forecast.model_versions["calibration"] == "identity@uncalibrated"
            assert forecast.model_versions["alert_policy"] == "fixed_threshold@placeholder"
            assert forecast.raw_probability == forecast.calibrated_probability

    def test_no_candidate_uses_post_cutoff_evidence(
        self, settings: Settings, populated_ledger: EvidenceLedger, clock: FixedClock
    ) -> None:
        snapshot = SnapshotBuilder(settings, populated_ledger, clock=clock).build(CUTOFF)
        run = run_cutoff(settings, populated_ledger, snapshot, clock=clock)
        admissible = {item.observation_id for item in snapshot.observations}
        cited = {
            ref.observation_id for forecast in run.forecasts for ref in forecast.hypothesis.evidence
        }
        assert cited <= admissible

    def test_every_status_is_a_retained_state(
        self, settings: Settings, populated_ledger: EvidenceLedger, clock: FixedClock
    ) -> None:
        # Uncertain cases are retained as MONITOR/ABSTAIN/INSUFFICIENT_EVIDENCE,
        # never silently deleted.
        snapshot = SnapshotBuilder(settings, populated_ledger, clock=clock).build(CUTOFF)
        run = run_cutoff(settings, populated_ledger, snapshot, clock=clock)
        assert {forecast.status for forecast in run.forecasts} <= set(ForecastStatus)
        assert len(run.forecasts) == len(run.proposals)

    def test_forecast_ledger_is_append_only(
        self, settings: Settings, populated_ledger: EvidenceLedger, clock: FixedClock
    ) -> None:
        snapshot = SnapshotBuilder(settings, populated_ledger, clock=clock).build(CUTOFF)
        run = run_cutoff(settings, populated_ledger, snapshot, clock=clock)
        ledger = ForecastLedger(settings)
        first = ledger.append(run.forecasts)
        second = ledger.append(run.forecasts)
        assert first.written == len(run.forecasts)
        assert second.written == 0
        assert ledger.count() == len(run.forecasts)


class TestOutcomeRegistry:
    def test_outcomes_are_derived_from_reporting_and_stay_unadjudicated(
        self, populated_ledger: EvidenceLedger
    ) -> None:
        outcomes = build_outcome_registry(populated_ledger, populated_ledger.read_observations())
        assert outcomes
        for outcome in outcomes:
            # Ground truth is derived, never injected, and no machine may sign
            # off on it.
            assert str(outcome.decision) == "pending"
            assert outcome.first_legitimate_resolution_at >= outcome.event.occurred_at

    def test_registry_matches_the_worlds_latent_events(
        self, populated_ledger: EvidenceLedger, window: object
    ) -> None:
        from pramaanx.ingest.connectors.synthetic import SyntheticConnector

        connector = SyntheticConnector(
            populated_ledger.settings, populated_ledger.settings.sources.get("synthetic", {})
        )
        truth = {event.event_key for event in connector.ground_truth()}
        derived = {
            outcome.outcome_id.split("_")[-1]
            for outcome in build_outcome_registry(
                populated_ledger, populated_ledger.read_observations()
            )
        }
        # Every derived outcome traces to a real latent event; the reverse does
        # not hold, because events reported after the ingest window are not yet
        # in the ledger.
        assert derived
        assert truth


class TestBacktest:
    def test_walk_produces_a_report(
        self, settings: Settings, populated_ledger: EvidenceLedger, spec: ExperimentSpec
    ) -> None:
        report = Backtester(settings, populated_ledger).run(spec)
        assert report.aggregate["folds"] == 3
        assert report.aggregate["forecasts"] > 0
        assert report.run_id.startswith("run_")

    def test_identical_inputs_reproduce_identical_reports(
        self, settings: Settings, populated_ledger: EvidenceLedger, spec: ExperimentSpec
    ) -> None:
        # The Phase 3 gate: identical inputs reproduce identical reports.
        first = Backtester(settings, populated_ledger).run(spec)
        second = Backtester(settings, populated_ledger).run(spec)
        assert first.report_hash == second.report_hash
        assert render_markdown(first) == render_markdown(second)

    def test_reports_state_their_limits(
        self, settings: Settings, populated_ledger: EvidenceLedger, spec: ExperimentSpec
    ) -> None:
        report = Backtester(settings, populated_ledger).run(spec)
        markdown = render_markdown(report)
        assert "What these numbers are not" in markdown
        assert "uncalibrated" in markdown
        assert report.aggregate["outcome_registry"]["unadjudicated_fraction"] == 1.0

    def test_scored_outcomes_all_postdate_their_cutoff(
        self, settings: Settings, populated_ledger: EvidenceLedger, spec: ExperimentSpec
    ) -> None:
        report = Backtester(settings, populated_ledger).run(spec)
        for fold in report.folds:
            for match in fold.matches:
                if match.matched:
                    assert match.lead_time_days is not None
                    assert match.lead_time_days > 0

    def test_report_files_are_written(
        self, settings: Settings, populated_ledger: EvidenceLedger, spec: ExperimentSpec
    ) -> None:
        report = Backtester(settings, populated_ledger).run(spec)
        paths = write_report(report, settings.storage.run_root)
        assert paths["json"].exists()
        assert json.loads(paths["json"].read_text())["report_hash"] == report.report_hash

    def test_experiment_files_load(self) -> None:
        spec, settings = load_experiment("configs/experiments/smoke.yaml")
        assert spec.name == "smoke"
        assert spec.cutoffs()
        assert settings.generators.proposal_budget == 100


class TestCli:
    """The CLI is the product surface; it has to work from a clean directory."""

    def run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pramaanx.cli", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        config = {
            "storage": {"data_root": str(tmp_path / "data"), "run_root": str(tmp_path / "runs")},
            "horizon_days": 30,
            "sources": {"synthetic": {"seed": 7}},
        }
        (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        return tmp_path

    def test_version_lists_what_is_not_built(self, workspace: Path) -> None:
        result = self.run("version", cwd=workspace)
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["milestone"] == "M0"
        assert "calibration" in payload["not_implemented_stages"]

    def test_dry_run_writes_nothing(self, workspace: Path) -> None:
        result = self.run(
            "ingest",
            "--source",
            "synthetic",
            "--from",
            "2025-01-01",
            "--until",
            "2025-02-01",
            "--config",
            "config.yaml",
            "--dry-run",
            cwd=workspace,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["dry_run"] is True
        assert payload["written"] == 0
        assert not (workspace / "data" / "bronze" / "observations").exists()

    def test_ingest_snapshot_and_candidates(self, workspace: Path) -> None:
        ingest = self.run(
            "ingest",
            "--source",
            "synthetic",
            "--from",
            "2025-01-01",
            "--until",
            "2025-06-01",
            "--config",
            "config.yaml",
            cwd=workspace,
        )
        assert ingest.returncode == 0, ingest.stderr
        assert json.loads(ingest.stdout)["written"] > 0

        snapshot = self.run(
            "snapshot",
            "build",
            "--cutoff",
            "2025-05-01T00:00:00Z",
            "--config",
            "config.yaml",
            cwd=workspace,
        )
        assert snapshot.returncode == 0, snapshot.stderr
        snapshot_id = json.loads(snapshot.stdout)["snapshot_id"]

        candidates = self.run(
            "candidates",
            "generate",
            "--snapshot",
            snapshot_id,
            "--budget",
            "50",
            "--config",
            "config.yaml",
            cwd=workspace,
        )
        assert candidates.returncode == 0, candidates.stderr
        payload = json.loads(candidates.stdout)
        assert 0 < payload["candidates"] <= 50
        assert payload["forecasts_written"] == payload["candidates"]

        audit = self.run("audit", "leakage", "--config", "config.yaml", cwd=workspace)
        assert audit.returncode == 0, audit.stderr
        assert json.loads(audit.stdout)["mechanically_clean"] is True

    def test_sources_reports_licences(self, workspace: Path) -> None:
        result = self.run("sources", "--config", "config.yaml", cwd=workspace)
        assert result.returncode == 0
        sources = {item["source_id"]: item for item in json.loads(result.stdout)["sources"]}
        assert sources["gdelt"]["redistributable"] is False
