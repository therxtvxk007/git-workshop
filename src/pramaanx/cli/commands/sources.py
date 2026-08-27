"""Connectors and their licence terms."""

from __future__ import annotations

from pathlib import Path

from pramaanx.cli._app import (
    ConfigOption,
    OutputOption,
    SetOption,
    _emit,
    _settings,
    app,
)


@app.command()
def sources(
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
    output: OutputOption = None,
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
    _emit({"kind": "sources", "count": len(entries), "sources": entries}, output)
