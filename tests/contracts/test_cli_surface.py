"""The CLI's command surface, pinned.

Commands register by import side effect: a Typer decorator *is* the
registration, so a command module that nobody imports is a command that
silently does not exist. That failure mode is invisible -- the CLI starts
fine and simply lacks a command -- which is exactly the kind of thing a
contract test is for.

These tests also guard the seam between the two halves of the build. Both add
command modules, and a merge that drops one side's import line from
``commands/__init__.py`` would otherwise pass every other test in the tree.
"""

from __future__ import annotations

import pkgutil

import pytest
from typer.testing import CliRunner

from pramaanx.cli import app
from pramaanx.cli import commands as commands_package

#: Every command the CLI is expected to expose, as ``(path, ...)`` tuples.
#: Adding a command means adding it here, deliberately: a command appearing
#: that nobody meant to ship is as much a problem as one going missing.
EXPECTED_COMMANDS = {
    ("audit", "leakage"),
    ("backtest",),
    ("candidates", "generate"),
    ("extract",),
    ("ingest",),
    ("outcomes", "build"),
    ("outcomes", "build-panel"),
    ("outcomes", "normalize"),
    ("outcomes", "validate-panel"),
    ("replay", "restore"),
    ("replay", "verify"),
    ("report",),
    ("snapshot", "build"),
    ("snapshot", "list"),
    ("sources",),
    ("version",),
}

#: Stages that exist in the build plan but are not implemented. A command that
#: accepts a flag and does nothing is worse than a missing command, so these
#: must stay absent rather than becoming stubs.
UNBUILT_STAGES = ["graph", "adjudicate", "calibrate"]


def _registered() -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()

    def walk(typer_app: object, prefix: tuple[str, ...]) -> None:
        for command in getattr(typer_app, "registered_commands", []):
            name = command.name or command.callback.__name__.replace("_", "-")
            found.add((*prefix, name))
        for group in getattr(typer_app, "registered_groups", []):
            walk(group.typer_instance, (*prefix, group.name))

    walk(app, ())
    return found


class TestCommandSurface:
    def test_every_expected_command_is_registered(self) -> None:
        assert _registered() >= EXPECTED_COMMANDS

    def test_no_unexpected_command_is_registered(self) -> None:
        # The other direction: splitting the CLI into modules must not have
        # quietly introduced a command, and neither may a merge.
        assert _registered() <= EXPECTED_COMMANDS

    @pytest.mark.parametrize("stage", UNBUILT_STAGES)
    def test_unbuilt_stages_have_no_command(self, stage: str) -> None:
        assert not any(path[0] == stage for path in _registered())

    def test_every_command_module_is_imported_by_the_package(self) -> None:
        # The registration mechanism is an import side effect, so a module
        # present on disk but absent from commands/__init__.py contributes
        # nothing and would fail silently.
        on_disk = {
            module.name
            for module in pkgutil.iter_modules(commands_package.__path__)
            if not module.name.startswith("_")
        }
        imported = set(commands_package.__all__)
        assert on_disk == imported, (
            "command modules on disk and imported by the package have diverged; "
            "a module missing from __init__.py registers nothing"
        )


class TestEntryPointsStillWork:
    def test_help_lists_the_top_level_commands(self) -> None:
        result = CliRunner().invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in ("ingest", "snapshot", "backtest", "sources"):
            assert name in result.stdout

    def test_an_unbuilt_stage_is_an_error_not_a_no_op(self) -> None:
        result = CliRunner().invoke(app, ["calibrate"])
        assert result.exit_code != 0
