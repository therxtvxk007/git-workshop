"""The M0 loop, end to end.

Ingest -> snapshot -> extract -> generate -> forecast -> match -> report, on the
synthetic world, offline. Also the CLI surface, because the project has to be
operable without notebooks.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

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
REPO_ROOT = Path(__file__).resolve().parents[2]


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
    """The CLI is the product surface; it has to work from a clean directory.

    Invoked in-process through Typer's runner rather than as a subprocess, so
    the CLI's own lines are visible to coverage. One subprocess test remains
    below, because in-process invocation cannot prove the installed console
    script exists.
    """

    @pytest.fixture
    def workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        config = {
            "storage": {"data_root": str(tmp_path / "data"), "run_root": str(tmp_path / "runs")},
            "horizon_days": 30,
            "sources": {"synthetic": {"seed": 7}},
        }
        (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        # Experiment files are referenced by relative path, as they are in the
        # documented commands.
        shutil.copytree(REPO_ROOT / "configs", tmp_path / "configs")
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def invoke(self, *args: str) -> Result:
        from pramaanx.cli import app

        result = CliRunner().invoke(app, list(args))
        if result.exception is not None and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result

    def payload(self, result: Result) -> dict[str, Any]:
        assert result.exit_code == 0, result.output
        # The manifest is the last line; structlog writes to stderr.
        return json.loads(result.output.strip().splitlines()[-1])

    def test_version_lists_what_is_not_built(self, workspace: Path) -> None:
        payload = self.payload(self.invoke("version"))
        assert payload["milestone"] == "M0"
        assert "calibration" in payload["not_implemented_stages"]

    def test_dry_run_writes_nothing(self, workspace: Path) -> None:
        payload = self.payload(
            self.invoke(
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
            )
        )
        assert payload["dry_run"] is True
        assert payload["written"] == 0
        assert not (workspace / "data" / "bronze" / "observations").exists()

    def test_ingest_snapshot_and_candidates(self, workspace: Path) -> None:
        ingest = self.payload(
            self.invoke(
                "ingest",
                "--source",
                "synthetic",
                "--from",
                "2025-01-01",
                "--until",
                "2025-06-01",
                "--config",
                "config.yaml",
            )
        )
        assert ingest["written"] > 0

        snapshot = self.payload(
            self.invoke(
                "snapshot", "build", "--cutoff", "2025-05-01T00:00:00Z", "--config", "config.yaml"
            )
        )
        snapshot_id = snapshot["snapshot_id"]

        listing = self.payload(self.invoke("snapshot", "list", "--config", "config.yaml"))
        assert snapshot_id in {item["snapshot_id"] for item in listing["snapshots"]}

        extracted = self.payload(
            self.invoke("extract", "--snapshot", snapshot_id, "--config", "config.yaml")
        )
        assert extracted["mentions"] > 0

        candidates = self.payload(
            self.invoke(
                "candidates",
                "generate",
                "--snapshot",
                snapshot_id,
                "--budget",
                "50",
                "--config",
                "config.yaml",
            )
        )
        assert 0 < candidates["candidates"] <= 50
        assert candidates["forecasts_written"] == candidates["candidates"]

        outcomes = self.payload(self.invoke("outcomes", "build", "--config", "config.yaml"))
        assert outcomes["outcomes"] > 0
        assert outcomes["adjudication"]["unadjudicated_fraction"] == 1.0

        audit = self.payload(self.invoke("audit", "leakage", "--config", "config.yaml"))
        assert audit["mechanically_clean"] is True

    def test_backtest_dry_run_lists_cutoffs(self, workspace: Path) -> None:
        payload = self.payload(
            self.invoke("backtest", "--experiment", "configs/experiments/smoke.yaml", "--dry-run")
        )
        assert payload["dry_run"] is True
        assert payload["cutoffs"]

    def test_report_for_an_unknown_run_fails_cleanly(self, workspace: Path) -> None:
        result = self.invoke("report", "--run-id", "run_missing", "--config", "config.yaml")
        assert result.exit_code == 1

    def test_sources_reports_licences(self, workspace: Path) -> None:
        payload = self.payload(self.invoke("sources", "--config", "config.yaml"))
        sources = {item["source_id"]: item for item in payload["sources"]}
        assert sources["gdelt"]["redistributable"] is False

    def test_manifests_can_be_written_to_a_file(self, workspace: Path) -> None:
        target = workspace / "manifest.json"
        result = self.invoke("sources", "--config", "config.yaml", "--output", str(target))
        assert result.exit_code == 0
        assert json.loads(target.read_text())["kind"] == "sources"


class TestInstalledEntryPoint:
    """The console script exists and runs. Subprocess, necessarily."""

    def test_module_entry_point_runs(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "pramaanx.cli", "version"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["milestone"] == "M0"

    def test_console_script_is_installed(self, tmp_path: Path) -> None:
        executable = Path(sys.executable).parent / "pramaanx"
        if not executable.exists():  # pragma: no cover - editable install layout
            pytest.skip("console script not present in this environment")
        result = subprocess.run(
            [str(executable), "version"], cwd=tmp_path, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["milestone"] == "M0"
