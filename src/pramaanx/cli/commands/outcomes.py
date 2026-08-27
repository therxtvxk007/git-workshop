"""Outcome registry construction."""

from __future__ import annotations

from pathlib import Path

from pramaanx.cli._app import (
    ConfigOption,
    DryRunOption,
    OutputOption,
    SetOption,
    _emit,
    _settings,
    outcomes_app,
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
