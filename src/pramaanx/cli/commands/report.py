"""Human-readable run reports."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pramaanx.cli._app import (
    ConfigOption,
    SetOption,
    _settings,
    app,
)


@app.command()
def report(
    run_id: Annotated[str, typer.Option("--run-id", help="Run id from a backtest.")],
    config: ConfigOption = Path("configs/base.yaml"),
    set_: SetOption = None,
) -> None:
    """Print a stored backtest report."""
    settings = _settings(config, set_)
    path = settings.storage.run_root / run_id / "report.md"
    if not path.exists():
        typer.echo(f"no report for run {run_id} at {path}", err=True)
        raise typer.Exit(code=1)
    typer.echo(path.read_text(encoding="utf-8"))
