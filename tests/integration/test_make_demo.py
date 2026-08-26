"""The documented demo entry point actually runs.

`make demo` is the first thing anyone types after cloning, and it was broken:
it passed `--world demo`, an argument the bootstrap script has never accepted.
Nothing caught it because no test executed the documented command -- the tests
called the Python API instead, which is precisely the gap that lets an entry
point rot.

So this test does not re-implement the demo. It *reads the recipe out of the
Makefile* and runs it. Edit the recipe and this test runs the edit; break it and
this test breaks.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

_ASSIGNMENT = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*\??=\s*(.*?)\s*$")
_VARIABLE = re.compile(r"\$\((\w+)\)")


def makefile_variables() -> dict[str, str]:
    variables: dict[str, str] = {}
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            name, value = match.groups()
            variables[name] = _VARIABLE.sub(lambda m: variables.get(m.group(1), ""), value)
    return variables


def demo_recipe() -> list[list[str]]:
    """The command lines `make demo` would run, with variables expanded."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("demo:"))
    except StopIteration:  # pragma: no cover - the target exists
        pytest.fail("Makefile has no 'demo' target")

    variables = makefile_variables()
    commands: list[list[str]] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        expanded = _VARIABLE.sub(lambda m: variables.get(m.group(1), ""), line.strip())
        commands.append(expanded.split())
    return commands


def as_local_invocation(command: list[str]) -> list[str]:
    """Rewrite `uv run ...` to use the interpreter already running the tests.

    The recipe's own arguments are preserved verbatim; only the launcher
    changes, so a broken argument in the Makefile still fails here.
    """
    parts = list(command)
    if parts[:2] == ["uv", "run"]:
        parts = parts[2:]
    if parts and parts[0] == "python":
        return [sys.executable, *parts[1:]]
    if parts and parts[0] == "pramaanx":
        return [sys.executable, "-m", "pramaanx.cli", *parts[1:]]
    return parts  # pragma: no cover - the recipe uses only the two above


class TestDemoRecipe:
    def test_recipe_is_parsed(self) -> None:
        commands = demo_recipe()
        assert commands, "the demo target has no commands"
        # No unexpanded variables survived, and no phantom arguments remain.
        flat = " ".join(" ".join(part) for part in commands)
        assert "$(" not in flat
        assert "--world" not in flat, "bootstrap_data.py accepts no --world argument"

    def test_bootstrap_accepts_every_documented_argument(self) -> None:
        # The original failure mode: an argument in the recipe that argparse
        # rejects. Checking the parser directly pins it without a full run.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bootstrap_data", REPO_ROOT / "scripts" / "bootstrap_data.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        bootstrap = next(cmd for cmd in demo_recipe() if "bootstrap_data.py" in " ".join(cmd))
        arguments = bootstrap[bootstrap.index("scripts/bootstrap_data.py") + 1 :]
        original = sys.argv
        try:
            sys.argv = ["bootstrap_data.py", *arguments]
            parsed = module.parse_args()
        finally:
            sys.argv = original
        assert parsed.start and parsed.end

    def test_ingestion_window_outruns_the_final_fold(self) -> None:
        """The demo must not produce a report whose last folds are censored."""
        from pramaanx.evaluation.backtest import load_experiment
        from pramaanx.timeguard.snapshots import parse_cutoff

        variables = makefile_variables()
        spec, settings = load_experiment(REPO_ROOT / variables["DEMO_EXPERIMENT"])
        evidence_end = parse_cutoff(variables["DEMO_UNTIL"])
        required = spec.cutoffs()[-1] + __import__("datetime").timedelta(
            days=spec.horizon_days + settings.evaluation.max_reporting_delay_days
        )
        assert evidence_end >= required, (
            f"demo ingests to {evidence_end.isoformat()} but scoring the final fold needs "
            f"evidence through {required.isoformat()}"
        )


@pytest.mark.slow
class TestDemoRuns:
    def test_demo_runs_end_to_end_offline(self, tmp_path: Path) -> None:
        """Run the real recipe in a scratch workspace, with no network."""
        workspace = tmp_path / "demo"
        workspace.mkdir()
        # Everything the recipe references by relative path, and nothing else --
        # a scratch clone, not the developer's working tree.
        shutil.copytree(REPO_ROOT / "configs", workspace / "configs")
        shutil.copytree(REPO_ROOT / "scripts", workspace / "scripts")

        environment = {
            **os.environ,
            "PRAMAANX_DATA_ROOT": str(workspace / "data"),
            "PRAMAANX_RUN_ROOT": str(workspace / "runs"),
            "PRAMAANX_LOG_LEVEL": "WARNING",
            # A connector that reached the network here would hang or fail; the
            # demo is meant to need neither credentials nor egress.
            "no_proxy": "*",
        }

        outputs: list[str] = []
        for command in demo_recipe():
            result = subprocess.run(
                as_local_invocation(command),
                cwd=workspace,
                capture_output=True,
                text=True,
                env=environment,
                check=False,
                timeout=600,
            )
            assert result.returncode == 0, (
                f"`{' '.join(command)}` failed with code {result.returncode}\n"
                f"stdout: {result.stdout[-2000:]}\nstderr: {result.stderr[-2000:]}"
            )
            outputs.append(result.stdout)

        report = json.loads(outputs[-1])
        assert report["kind"] == "backtest"
        assert report["folds"] > 0
        assert report["forecasts"] > 0
        # A demo that silently scored nothing would look identical to one that
        # worked, so the assertion has to reach the numbers.
        assert report["candidate_recall_mean"] is not None
        assert report["interpretation_limits"]
        assert Path(workspace / report["report_markdown"]).exists()
