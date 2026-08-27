"""Structured extraction from a snapshot."""

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
    app,
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
