"""Candidate generation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pramaanx.cli._app import (
    ConfigOption,
    DryRunOption,
    OutputOption,
    SetOption,
    _emit,
    _settings,
    candidates_app,
)
from pramaanx.hashing import utc_isoformat


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
