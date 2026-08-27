"""The Typer applications, shared options and manifest helpers.

Everything here is imported by more than one command module. Commands
themselves live in :mod:`pramaanx.cli.commands`, one file per stage, so that
two people adding commands for different stages add files rather than lines to
the same file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from pramaanx.config import Settings, dotted_overrides, load_settings
from pramaanx.hashing import canonical_json
from pramaanx.logging import configure_logging, get_logger

app = typer.Typer(
    name="pramaanx",
    help="Cutoff-safe, open-world future-event forecasting (M0 foundation).",
    no_args_is_help=True,
    add_completion=False,
)
snapshot_app = typer.Typer(help="Build and inspect point-in-time snapshots.", no_args_is_help=True)
candidates_app = typer.Typer(help="Candidate generation.", no_args_is_help=True)
outcomes_app = typer.Typer(help="Outcome registry.", no_args_is_help=True)
audit_app = typer.Typer(help="Leakage and integrity audits.", no_args_is_help=True)
replay_app = typer.Typer(help="Verify and restore stored bronze evidence.", no_args_is_help=True)
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(candidates_app, name="candidates")
app.add_typer(outcomes_app, name="outcomes")
app.add_typer(audit_app, name="audit")
app.add_typer(replay_app, name="replay")

log = get_logger("pramaanx.cli")

ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Base configuration file.", show_default=True)
]
SetOption = Annotated[
    list[str] | None,
    typer.Option("--set", "-s", help="Override config, e.g. --set generators.proposal_budget=100"),
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Plan the work and emit a manifest without doing it.")
]
OutputOption = Annotated[
    Path | None, typer.Option("--output", "-o", help="Also write the manifest to this path.")
]


def _settings(config: Path, overrides: list[str] | None, log_level: str | None = None) -> Settings:
    settings = load_settings(config, overrides=dotted_overrides(overrides or []))
    configure_logging(log_level or settings.log_level, settings.log_format)
    return settings


def _emit(manifest: dict[str, Any], output: Path | None = None) -> None:
    """Print a manifest as canonical JSON, and optionally persist it."""
    text = canonical_json(manifest)
    typer.echo(text)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def _parse_moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


@app.callback()
def main_callback() -> None:
    """PRAMAAN-X Zero-Base."""
