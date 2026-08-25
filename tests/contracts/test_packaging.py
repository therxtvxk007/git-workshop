"""Packaging metadata is a contract with whoever clones the repository.

`requires-python` decides which interpreter `uv sync` selects. Get it wrong in
either direction and a fresh clone suffers for it: too loose and it installs
against an untested Python, too tight and it refuses one that works.

Version ranges are compared with `packaging.specifiers`, not with a regular
expression over the string. A hand-rolled parser silently mishandles the forms
it was not written for -- `!=`, `~=`, pre-release markers -- and a metadata test
that quietly stops checking is worse than no test.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.specifiers import SpecifierSet
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yaml"


def requires_python() -> SpecifierSet:
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return SpecifierSet(str(metadata["project"]["requires-python"]))


def ci_python_versions() -> list[Version]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["quality"]["strategy"]["matrix"]["python-version"]
    return [Version(str(version)) for version in matrix]


def supported_minors() -> list[Version]:
    """Every 3.x inside the declared range, as a concrete list.

    Probing rather than parsing bounds: whatever specifier syntax is used, this
    asks the same question pip and uv ask.
    """
    specifier = requires_python()
    return [
        Version(f"3.{minor}")
        for minor in range(8, 40)
        if specifier.contains(Version(f"3.{minor}.0"))
    ]


class TestRequiresPython:
    def test_is_parseable(self) -> None:
        assert str(requires_python())

    def test_is_bounded_at_both_ends(self) -> None:
        # An unbounded upper end lets `uv sync` pick the newest interpreter on
        # the machine, which is how a fresh clone once installed against a
        # Python nobody had tested.
        minors = supported_minors()
        assert minors, "requires-python admits no 3.x version at all"
        assert len(minors) < 30, (
            f"requires-python ({requires_python()}) has no upper bound; it admits "
            f"{len(minors)} minor versions, none of which are tested beyond the CI matrix"
        )

    def test_the_running_interpreter_is_supported(self) -> None:
        current = Version(".".join(str(part) for part in sys.version_info[:3]))
        assert requires_python().contains(current, prereleases=True), (
            f"the suite is running on {current}, which requires-python "
            f"({requires_python()}) excludes"
        )


class TestCiMatrixAgrees:
    def test_every_ci_version_is_permitted(self) -> None:
        # The two live in different files and are edited by different people.
        # When they disagree, CI is either testing something unsupported or
        # claiming support for something untested.
        specifier = requires_python()
        for version in ci_python_versions():
            assert specifier.contains(Version(f"{version}.0")), (
                f"CI tests Python {version}, which requires-python ({specifier}) forbids"
            )

    @pytest.mark.parametrize("minor", supported_minors(), ids=str)
    def test_every_supported_version_is_tested(self, minor: Version) -> None:
        tested = {f"{version.major}.{version.minor}" for version in ci_python_versions()}
        assert f"{minor.major}.{minor.minor}" in tested, (
            f"requires-python claims Python {minor} works, but CI never runs it. "
            "Either add it to the matrix or narrow the bound."
        )
