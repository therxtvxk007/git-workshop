"""Acquire evidence from one source into bronze."""

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
    _parse_moment,
    _settings,
    app,
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
