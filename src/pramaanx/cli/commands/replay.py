"""Verify and replay stored bronze evidence."""

from __future__ import annotations

from pathlib import Path

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
def replay(
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    dry_run: DryRunOption = False,
    strict: bool = True,
    output: OutputOption = None,
) -> None:
    """Replay bronze, refusing a corpus whose integrity cannot be verified.

    ``--dry-run`` reports what is wrong without producing a replay manifest --
    the read-only half. ``--no-strict`` returns the corpus anyway, for triage on
    a ledger already known to be damaged; its result must not support a claim.
    """
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.ingest.replay import BronzeReplay

    settings = _settings(config, set_)
    engine = BronzeReplay(settings, EvidenceLedger(settings))

    if dry_run:
        findings = engine.verify()
        _emit(
            {
                "kind": "replay",
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
            "kind": "replay",
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
