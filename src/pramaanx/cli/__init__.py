"""Command-line interface.

The project must be operable without notebooks: every step below is a command,
every command that writes accepts ``--dry-run``, and every command prints a
machine-readable manifest to stdout. Notebooks may inspect results; no pipeline
logic lives only in one.

The Typer applications and shared options live in :mod:`pramaanx.cli._app`; the
commands themselves live one-per-stage in :mod:`pramaanx.cli.commands`. This
module re-exports ``app`` and ``main`` so that ``pramaanx.cli:main`` remains the
entry point it has always been.
"""

from __future__ import annotations

import sys

import typer

from pramaanx.cli import commands as commands
from pramaanx.cli._app import (
    app,
    audit_app,
    candidates_app,
    outcomes_app,
    snapshot_app,
)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        typer.echo("interrupted", err=True)
        sys.exit(130)


__all__ = [
    "app",
    "audit_app",
    "candidates_app",
    "main",
    "outcomes_app",
    "snapshot_app",
]


if __name__ == "__main__":  # pragma: no cover
    main()
