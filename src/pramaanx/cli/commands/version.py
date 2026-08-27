"""What is registered and what is not."""

from __future__ import annotations

from pramaanx import __version__
from pramaanx.cli._app import (
    OutputOption,
    _emit,
    app,
)


@app.command()
def version(output: OutputOption = None) -> None:
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
        },
        output,
    )
