"""Leakage and integrity audits."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pramaanx.cli._app import (
    ConfigOption,
    OutputOption,
    SetOption,
    _emit,
    _parse_moment,
    _settings,
    audit_app,
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
