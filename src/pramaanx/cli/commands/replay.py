"""Verify stored bronze, and restore an archived copy of it.

Two operations that are easy to conflate and must not be. ``verify`` asks
whether the bronze in this data root is intact. ``restore`` asks whether an
archived bronze can be put somewhere else and still be the same evidence.
Neither answers the other's question, and both refuse rather than degrade.
"""

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
    replay_app,
)


@replay_app.command("verify")
def replay_verify(
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    strict: bool = True,
    output: OutputOption = None,
) -> None:
    """Replay bronze in place, refusing a corpus it cannot vouch for.

    ``--dry-run`` reports defects without producing a manifest. ``--no-strict``
    returns the corpus anyway, for triage on a ledger already known to be
    damaged; its result must not support a claim.
    """
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.ingest.replay import BronzeReplay

    settings = _settings(config, set_)
    engine = BronzeReplay(settings, EvidenceLedger(settings))

    if dry_run:
        findings = engine.verify()
        _emit(
            {
                "kind": "replay.verify",
                "dry_run": True,
                "defects": len(findings),
                "findings": [finding.model_dump(mode="json") for finding in findings],
            },
            output,
        )
        return

    result = engine.replay(strict=strict, persist=True)
    _emit(
        {
            "kind": "replay.verify",
            "dry_run": False,
            "strict": strict,
            "replay_id": result.manifest.replay_id,
            "replay_hash": result.replay_hash,
            "observations": len(result),
            "payload_bytes": result.manifest.payload_bytes,
            "source_contracts": result.manifest.source_contracts,
            "dependency_lock_hash": result.manifest.dependency_lock_hash,
        },
        output,
    )


@replay_app.command("restore")
def replay_restore(
    source: Annotated[Path, typer.Option("--source", help="Data root holding the bronze archive.")],
    expected_bronze_hash: Annotated[
        str | None,
        typer.Option("--expect-hash", help="Refuse any archive that does not hash to this."),
    ] = None,
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Restore an archived bronze into this config's data root, atomically.

    Never merges into a non-empty destination: a ledger assembled from two
    archives has provenance belonging to neither. Restoring the identical
    archive twice is a no-op, so the operation is safe to retry.
    """
    from pramaanx.ingest.replay import restore_archive

    settings = _settings(config, set_)
    report = restore_archive(
        settings,
        source,
        expected_bronze_hash=expected_bronze_hash,
        dry_run=dry_run,
    )
    _emit({"kind": "replay.restore", **report.model_dump(mode="json")}, output)
