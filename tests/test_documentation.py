"""Documentation claims, checked mechanically.

The failure this guards against is the one that produced the previous README:
numbers and capability claims drifting out of sync with the code, with nothing
that fails when they do. These tests are cheap and they are the only thing
standing between "the docs say so" and "the docs said so once".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()

#: Claims that were withdrawn. They may appear only inside the section that
#: explains the withdrawal, never as a live assertion.
WITHDRAWN = (
    "100% at 39% retention",
    "ARL",
    "0.535",
    "0.751",
    "guarded by a test",
)

REQUIRED_STATES = (
    "integrated and measured",
    "implemented but disconnected",
    "adapter only, never run",
    "not implemented",
)


def _before_withdrawal_section() -> str:
    idx = README.index("## Claims withdrawn")
    return README[:idx]


def test_the_readme_leads_with_what_the_system_is_not():
    head = README[:600]
    assert "does not forecast events" in head
    assert "not implemented" in head


def test_withdrawn_claims_appear_only_in_the_withdrawal_section():
    live = _before_withdrawal_section()
    for claim in WITHDRAWN:
        assert claim not in live, (
            f"withdrawn claim {claim!r} is asserted outside the withdrawal section"
        )


def test_the_implementation_status_table_uses_all_four_states():
    for state in REQUIRED_STATES:
        assert f"| {state} |" in README, f"status table is missing the state {state!r}"


def test_stage_four_and_five_are_reported_as_not_implemented():
    for stage in ("Stage 4 risk models", "Stage 5 conformal risk control"):
        row = next(line for line in README.splitlines() if line.startswith(f"| {stage} |"))
        assert "not implemented" in row


@pytest.mark.parametrize("component", ["ITHI", "LANTERN", "MTRM", "temporal graph"])
def test_disconnected_components_are_labelled_disconnected(component):
    """None of these is reachable from the API, CLI or benchmark. The README
    used to describe them as part of the operating system."""
    row = next(
        (
            line
            for line in README.splitlines()
            if line.startswith("|") and component in line and "disconnected" in line
        ),
        None,
    )
    assert row is not None, f"{component} is not marked disconnected in the status table"


@pytest.mark.parametrize("component", ["Qdrant", "MLflow", "Jina v5", "GLiNER"])
def test_never_run_adapters_are_labelled_as_such(component):
    row = next(
        (
            line
            for line in README.splitlines()
            if line.startswith("|") and component in line and "adapter only, never run" in line
        ),
        None,
    )
    assert row is not None, f"{component} is not marked as an unrun adapter"


def test_stage4_and_stage5_packages_really_are_empty():
    """The status table's claim, checked against the code rather than trusted."""
    for pkg in ("stage4_risk", "stage5_control"):
        init = ROOT / "pramaan_x" / pkg / "__init__.py"
        assert init.exists()
        assert init.read_text().strip() == "", f"{pkg} is no longer empty"
        others = [p for p in (ROOT / "pramaan_x" / pkg).glob("*.py") if p.name != "__init__.py"]
        assert others == [], f"{pkg} gained modules: {others}"


def test_the_benchmark_is_named_accurately_everywhere():
    # Collapse emphasis and line wrapping: the claim is the same claim
    # whether or not markdown broke it across two lines.
    plain = re.sub(r"[\s>*]+", " ", README).lower()
    assert "oracle_target_retrieval" in README
    assert "not an event-forecasting evaluation" in plain
    assert "retrieval_bench" not in README


def test_no_module_still_refers_to_the_old_benchmark_name():
    for path in (ROOT / "pramaan_x").rglob("*.py"):
        assert "retrieval_bench" not in path.read_text(), path


def test_every_reported_number_has_an_artefact_behind_it():
    """The results table cites artefact paths. If a cited artefact is missing,
    the number in the README is unsupported and this fails.

    Skipped rather than failed when no run has been committed yet, because a
    fresh clone before `pramaan bench` is a legitimate state.
    """
    cited = {
        m
        for m in re.findall(r"benchmark_results/[^\s`|)]+\.json", README)
        # `<method>/seed-<n>/<digest>.json` and `**/*.json` are documented
        # path *shapes*, not citations of a particular run.
        if not set("<*") & set(m)
    }
    if not cited:
        pytest.skip("the README cites no artefacts yet")
    for rel in sorted(cited):
        path = ROOT / rel
        assert path.exists(), f"README cites {rel}, which does not exist"
        payload = json.loads(path.read_text())
        assert payload["benchmark"] == "oracle_target_retrieval"
        assert payload["method"] in {"strict_temporal", "contaminated_legacy_diagnostic"}


def test_committed_strict_artefacts_passed_every_invariant():
    """Nothing may be committed under `strict_temporal` that failed the
    firewall. The legacy artefacts are expected to fail and are not checked
    here -- that is what they are for."""
    root = ROOT / "benchmark_results" / "strict_temporal"
    if not root.exists():
        pytest.skip("no strict artefacts committed yet")
    found = 0
    for path in root.rglob("*.json"):
        payload = json.loads(path.read_text())
        assert set(payload["invariants"].values()) == {"pass"}, path
        assert payload["availability_violations"]["total"] == 0, path
        found += 1
    assert found > 0


def test_committed_legacy_artefacts_record_their_failures():
    """The diagnostic is only worth keeping if it says what is wrong with it."""
    root = ROOT / "benchmark_results" / "contaminated_legacy_diagnostic"
    if not root.exists():
        pytest.skip("no legacy artefacts committed yet")
    for path in root.rglob("*.json"):
        payload = json.loads(path.read_text())
        assert any(v.startswith("FAIL") for v in payload["invariants"].values()), path
        assert payload["availability_violations"]["total"] > 0, path


# ------------------------------------------------------ repository hygiene ---


def _tracked_files() -> list[str]:
    import subprocess

    out = subprocess.run(
        ["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True, timeout=30
    )
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return out.stdout.splitlines()


def test_no_bytecode_is_tracked():
    """Regression guard for a mistake made while writing this phase.

    The `__pycache__` files were removed from the index, then a `git reset`
    put them back -- and because pytest had regenerated them on disk in the
    meantime, `git add -A` re-added them as modifications rather than staging
    the deletions. `.gitignore` does not help here: it is ignored for files
    that are already tracked. Only a check like this one notices.
    """
    offenders = [f for f in _tracked_files() if "__pycache__" in f or f.endswith((".pyc", ".pyo"))]
    assert offenders == [], f"{len(offenders)} bytecode files are tracked: {offenders[:5]}"


def test_no_generated_or_environment_files_are_tracked():
    """Caches, virtualenvs, env files and generated corpora are build products.
    `benchmark_results/` is deliberately exempt: those artefacts are evidence."""
    banned_prefixes = (
        ".venv/",
        "venv/",
        "artifacts/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".cache/",
        "build/",
        "dist/",
    )
    offenders = [
        f
        for f in _tracked_files()
        if f.startswith(banned_prefixes)
        or f.endswith((".parquet", ".egg-info"))
        or (f == ".env" or f.startswith(".env."))
    ]
    assert offenders == [], f"generated files are tracked: {offenders[:5]}"


def test_gitignore_covers_what_it_needs_to():
    ignored = (ROOT / ".gitignore").read_text()
    for pattern in (
        "__pycache__/",
        "*.py[cod]",
        ".venv/",
        "artifacts/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".env",
    ):
        assert pattern in ignored, f".gitignore is missing {pattern!r}"
    assert "benchmark_results" not in ignored.replace(
        "# benchmark_results/ is deliberately NOT ignored", ""
    ), "benchmark_results/ must stay tracked -- it is the evidence"
