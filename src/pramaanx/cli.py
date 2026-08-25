"""Command-line interface.

The project must be operable without notebooks: every step below is a command,
every command accepts ``--dry-run``, and every command prints a machine-readable
manifest to stdout. Notebooks may inspect results; no pipeline logic lives only
in one.

Commands for stages M0 does not implement (graph build, adjudicate, calibrate)
are deliberately absent rather than stubbed. A command that accepts a flag and
does nothing is worse than a missing command.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from pramaanx import __version__
from pramaanx.config import Settings, dotted_overrides, load_settings
from pramaanx.hashing import canonical_json, utc_isoformat
from pramaanx.logging import configure_logging, get_logger

app = typer.Typer(
    name="pramaanx",
    help="Cutoff-safe, open-world future-event forecasting (M0 foundation).",
    no_args_is_help=True,
    add_completion=False,
)
snapshot_app = typer.Typer(help="Build and inspect point-in-time snapshots.", no_args_is_help=True)
candidates_app = typer.Typer(help="Candidate generation.", no_args_is_help=True)
outcomes_app = typer.Typer(help="Outcome registry.", no_args_is_help=True)
audit_app = typer.Typer(help="Leakage and integrity audits.", no_args_is_help=True)
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(candidates_app, name="candidates")
app.add_typer(outcomes_app, name="outcomes")
app.add_typer(audit_app, name="audit")

log = get_logger("pramaanx.cli")

ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Base configuration file.", show_default=True)
]
SetOption = Annotated[
    list[str] | None,
    typer.Option("--set", "-s", help="Override config, e.g. --set generators.proposal_budget=100"),
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Plan the work and emit a manifest without doing it.")
]
OutputOption = Annotated[
    Path | None, typer.Option("--output", "-o", help="Also write the manifest to this path.")
]


def _settings(config: Path, overrides: list[str] | None, log_level: str | None = None) -> Settings:
    settings = load_settings(config, overrides=dotted_overrides(overrides or []))
    configure_logging(log_level or settings.log_level, settings.log_format)
    return settings


def _emit(manifest: dict[str, Any], output: Path | None = None) -> None:
    """Print a manifest as canonical JSON, and optionally persist it."""
    text = canonical_json(manifest)
    typer.echo(text)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def _parse_moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


@app.callback()
def main_callback() -> None:
    """PRAMAAN-X Zero-Base."""


@app.command()
def version() -> None:
    """Print the version and the registered components."""
    from pramaanx.generators.base import available_generators
    from pramaanx.ingest.base import available_connectors

    _emit(
        {
            "kind": "version",
            "pramaanx": __version__,
            "milestone": "M0",
            "connectors": sorted(available_connectors()),
            "generators": sorted(available_generators()),
            "implemented_stages": ["ingest", "snapshot", "extract", "candidates", "backtest"],
            "not_implemented_stages": [
                "graph",
                "retrieval",
                "adjudication",
                "calibration",
                "risk_control",
            ],
        }
    )


@app.command()
def ingest(
    source: Annotated[str, typer.Option("--source", help="Registered connector id.")],
    from_: Annotated[str, typer.Option("--from", help="Window start (inclusive), ISO-8601.")],
    until: Annotated[str, typer.Option("--until", help="Window end (exclusive), ISO-8601.")],
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Acquire evidence from one source into the bronze ledger."""
    from pramaanx.clock import SystemClock
    from pramaanx.ingest.base import FetchWindow
    from pramaanx.ingest.ledger import EvidenceLedger

    settings = _settings(config, set_)
    window = FetchWindow(_parse_moment(from_), _parse_moment(until))
    ledger = EvidenceLedger(settings, clock=SystemClock())
    report = ledger.ingest(source, window, dry_run=dry_run)
    _emit(report.to_manifest(), output)


@snapshot_app.command("build")
def snapshot_build(
    cutoff: Annotated[str, typer.Option("--cutoff", help="Cutoff instant, ISO-8601 UTC.")],
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Freeze the evidence available at a cutoff and hash it."""
    from pramaanx.timeguard.snapshots import SnapshotBuilder, parse_cutoff

    settings = _settings(config, set_)
    builder = SnapshotBuilder(settings)
    moment = parse_cutoff(cutoff)
    snapshot = builder.build(moment, persist=not dry_run)
    _emit(
        {
            "kind": "snapshot",
            "dry_run": dry_run,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_hash": snapshot.snapshot_hash,
            "cutoff_at": utc_isoformat(snapshot.cutoff_at),
            "observations": len(snapshot),
            "sources": snapshot.manifest.source_counts,
            "rejected": snapshot.manifest.rejected_count,
            "config_hash": snapshot.manifest.config_hash,
            "code_hash": snapshot.manifest.code_hash,
        },
        output,
    )


@snapshot_app.command("list")
def snapshot_list(
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
) -> None:
    """List stored snapshots, oldest cutoff first."""
    from pramaanx.timeguard.snapshots import SnapshotBuilder

    settings = _settings(config, set_)
    manifests = SnapshotBuilder(settings).list_snapshots()
    _emit(
        {
            "kind": "snapshot_list",
            "count": len(manifests),
            "snapshots": [
                {
                    "snapshot_id": item.snapshot_id,
                    "cutoff_at": utc_isoformat(item.cutoff_at),
                    "observations": item.observation_count,
                    "snapshot_hash": item.snapshot_hash,
                }
                for item in manifests
            ],
        }
    )


@app.command()
def extract(
    snapshot: Annotated[str, typer.Option("--snapshot", help="Snapshot id.")],
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Extract structured event mentions from a snapshot into silver."""
    from pramaanx.extraction.structured import extract_mentions
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.timeguard.snapshots import SnapshotBuilder

    settings = _settings(config, set_)
    ledger = EvidenceLedger(settings)
    frozen = SnapshotBuilder(settings, ledger).load(snapshot)
    mentions = extract_mentions(ledger, list(frozen.observations))
    written = 0 if dry_run else ledger.write_mentions(mentions).written
    _emit(
        {
            "kind": "extract",
            "dry_run": dry_run,
            "snapshot_id": frozen.snapshot_id,
            "observations": len(frozen),
            "mentions": len(mentions),
            "written": written,
            "extractor": "structured@deterministic",
            "note": "Rule-based mapping for coded sources; the Phase 2 cascade is not built.",
        },
        output,
    )


@candidates_app.command("generate")
def candidates_generate(
    snapshot: Annotated[str, typer.Option("--snapshot", help="Snapshot id.")],
    budget: Annotated[int, typer.Option("--budget", help="Proposal budget.")] = 500,
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Generate candidate future events from a snapshot."""
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.ledger.forecasts import ForecastLedger
    from pramaanx.pipeline import run_cutoff
    from pramaanx.timeguard.snapshots import SnapshotBuilder

    settings = _settings(config, set_, None)
    settings = settings.model_copy(
        update={"generators": settings.generators.model_copy(update={"proposal_budget": budget})}
    )
    ledger = EvidenceLedger(settings)
    frozen = SnapshotBuilder(settings, ledger).load(snapshot)
    run = run_cutoff(settings, ledger, frozen)
    written = 0 if dry_run else ForecastLedger(settings).append(run.forecasts).written

    top = [
        {
            "event_id": item.hypothesis.event_id,
            "event_type": item.hypothesis.event_type,
            "location": item.hypothesis.most_likely_location(),
            "score": item.generator_score,
            "generators": sorted(item.hypothesis.generated_by),
        }
        for item in run.proposals[:10]
    ]
    _emit(
        {
            "kind": "candidates",
            "dry_run": dry_run,
            "snapshot_id": frozen.snapshot_id,
            "snapshot_hash": frozen.snapshot_hash,
            "cutoff_at": utc_isoformat(frozen.cutoff_at),
            "budget": budget,
            "candidates": len(run.proposals),
            "forecasts_written": written,
            "top": top,
        },
        output,
    )


@outcomes_app.command("build")
def outcomes_build(
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Derive the provisional outcome registry from post-event reporting."""
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.ledger.resolutions import adjudication_summary, build_outcome_registry

    settings = _settings(config, set_)
    ledger = EvidenceLedger(settings)
    outcomes = build_outcome_registry(ledger, ledger.read_observations())
    written = 0 if dry_run else ledger.write_outcomes(outcomes).written
    _emit(
        {
            "kind": "outcomes",
            "dry_run": dry_run,
            "outcomes": len(outcomes),
            "written": written,
            "adjudication": adjudication_summary(outcomes),
        },
        output,
    )


@audit_app.command("leakage")
def audit_leakage(
    cutoff: Annotated[str | None, typer.Option("--cutoff", help="Restrict to this cutoff.")] = None,
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    output: OutputOption = None,
) -> None:
    """Screen the ledger for mechanical leakage and integrity failures."""
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.timeguard.cutoff import CutoffGuard
    from pramaanx.timeguard.leakage_audit import LeakageAuditor

    settings = _settings(config, set_)
    ledger = EvidenceLedger(settings)
    moment = _parse_moment(cutoff) if cutoff else None
    observations = (
        CutoffGuard(moment, settings.timeguard).filter(ledger.observations_at_or_before(moment))
        if moment
        else ledger.read_observations()
    )
    report = LeakageAuditor(ledger, settings.timeguard).audit(observations, cutoff_at=moment)
    _emit(report.to_dict(), output)
    if not report.clean:
        raise typer.Exit(code=2)


@app.command()
def backtest(
    experiment: Annotated[Path, typer.Option("--experiment", help="Experiment YAML.")],
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Run a rolling-cutoff backtest and write its report."""
    from pramaanx.evaluation.backtest import Backtester, load_experiment
    from pramaanx.evaluation.reports import write_report

    spec, settings = load_experiment(experiment)
    configure_logging(settings.log_level, settings.log_format)
    if dry_run:
        _emit(
            {
                "kind": "backtest_plan",
                "dry_run": True,
                "experiment": spec.fingerprint(),
                "cutoffs": [utc_isoformat(moment) for moment in spec.cutoffs()],
                "config_hash": settings.config_hash,
            },
            output,
        )
        return

    report = Backtester(settings).run(spec)
    paths = write_report(report, settings.storage.run_root)
    _emit(
        {
            "kind": "backtest",
            "run_id": report.run_id,
            "report_hash": report.report_hash,
            "folds": report.aggregate["folds"],
            "forecasts": report.aggregate["forecasts"],
            "outcomes_scored": report.aggregate["outcomes_scored"],
            "candidate_recall_mean": report.aggregate["candidate_recall"]["mean"],
            "pooled_brier": report.aggregate["pooled"]["brier"],
            "interpretation_limits": report.aggregate["interpretation_limits"],
            "report_json": str(paths["json"]),
            "report_markdown": str(paths["markdown"]),
        },
        output,
    )


@app.command()
def report(
    run_id: Annotated[str, typer.Option("--run-id", help="Run id from a backtest.")],
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
) -> None:
    """Print a stored backtest report."""
    settings = _settings(config, set_)
    path = settings.storage.run_root / run_id / "report.md"
    if not path.exists():
        typer.echo(f"no report for run {run_id} at {path}", err=True)
        raise typer.Exit(code=1)
    typer.echo(path.read_text(encoding="utf-8"))


@app.command()
def sources(
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
) -> None:
    """List registered connectors and the licence terms they carry."""
    from pramaanx.ingest.base import available_connectors

    settings = _settings(config, set_)
    entries = []
    for source_id, cls in available_connectors().items():
        connector = cls(settings, settings.sources.get(source_id, {}))
        record = connector.source_record
        entries.append(
            {
                "source_id": record.source_id,
                "tier": record.tier,
                "display_name": record.display_name,
                "licence": record.licence,
                "redistributable": record.redistributable,
                "reliability_prior": record.reliability_prior,
            }
        )
    _emit({"kind": "sources", "count": len(entries), "sources": entries})


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        typer.echo("interrupted", err=True)
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
