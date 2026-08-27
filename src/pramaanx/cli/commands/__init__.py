"""Command modules, one per pipeline stage.

Importing this package registers every command on the Typer applications in
:mod:`pramaanx.cli._app`. Registration happens by import side effect, which is
the one place in this project where that is the right mechanism: Typer's
decorators *are* the registration, and a command that is never imported is a
command that silently does not exist.

Adding a stage means adding a module here and one line below. Two people
working on different stages therefore add files, not lines to a shared file.

Commands for stages that are not implemented (graph build, adjudicate,
calibrate) are deliberately absent rather than stubbed. A command that accepts
a flag and does nothing is worse than a missing command.
"""

from __future__ import annotations

from pramaanx.cli.commands import (
    audit,
    backtest,
    candidates,
    extract,
    ingest,
    outcomes,
    replay,
    report,
    snapshot,
    sources,
    version,
)

__all__ = [
    "audit",
    "backtest",
    "candidates",
    "extract",
    "ingest",
    "outcomes",
    "replay",
    "report",
    "snapshot",
    "sources",
    "version",
]
