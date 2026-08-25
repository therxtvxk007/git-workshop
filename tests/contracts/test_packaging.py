"""Packaging metadata is a contract with whoever clones the repository.

`requires-python` decides which interpreter `uv sync` selects. Get it wrong and
a fresh clone installs against a Python the code does not work on, failing
before the first test — which is how the 3.14 incompatibility was found.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yaml"


def pyproject() -> dict[str, object]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def ci_python_versions() -> list[str]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["quality"]["strategy"]["matrix"]["python-version"]
    return [str(version) for version in matrix]


class TestRequiresPython:
    def test_has_both_bounds(self) -> None:
        requires = pyproject()["project"]["requires-python"]  # type: ignore[index]
        assert ">=" in requires and "<" in requires, (
            f"requires-python is {requires!r}. An unbounded upper end lets uv sync pick an "
            "interpreter nobody has tested; see docs/python_versions.md."
        )

    def test_the_running_interpreter_satisfies_it(self) -> None:
        requires = str(pyproject()["project"]["requires-python"])  # type: ignore[index]
        lower = re.search(r">=\s*(\d+)\.(\d+)", requires)
        upper = re.search(r"<\s*(\d+)\.(\d+)", requires)
        assert lower and upper
        current = sys.version_info[:2]
        assert current >= (int(lower.group(1)), int(lower.group(2)))
        assert current < (int(upper.group(1)), int(upper.group(2)))


class TestCiMatrixAgrees:
    def test_every_ci_version_is_permitted_by_the_metadata(self) -> None:
        # The two are edited in different files by different people. When they
        # disagree, CI is either testing something unsupported or claiming
        # support for something untested.
        requires = str(pyproject()["project"]["requires-python"])  # type: ignore[index]
        lower = re.search(r">=\s*(\d+)\.(\d+)", requires)
        upper = re.search(r"<\s*(\d+)\.(\d+)", requires)
        assert lower and upper
        low = (int(lower.group(1)), int(lower.group(2)))
        high = (int(upper.group(1)), int(upper.group(2)))

        for version in ci_python_versions():
            major, minor = (int(part) for part in version.split("."))
            assert low <= (major, minor) < high, (
                f"CI tests Python {version}, which requires-python ({requires}) forbids"
            )

    def test_the_lowest_supported_version_is_tested(self) -> None:
        requires = str(pyproject()["project"]["requires-python"])  # type: ignore[index]
        lower = re.search(r">=\s*(\d+\.\d+)", requires)
        assert lower
        assert lower.group(1) in ci_python_versions(), (
            "the minimum supported version must be in the CI matrix, or the claim that it "
            "works is untested"
        )
