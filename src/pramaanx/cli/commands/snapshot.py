"""Build and inspect point-in-time snapshots."""

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
    snapshot_app,
)
from pramaanx.hashing import utc_isoformat


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
    output: OutputOption = None,
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
        },
        output,
    )
