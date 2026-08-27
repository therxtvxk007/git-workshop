"""The pinned calibration fixture reproduces on a clean workspace.

This is the assertion that gives the fixture its value. Anything fitted
against the sample -- a calibrator, a conformal bound -- inherits its
identity, so if the sample can drift silently then every number downstream of
it is unreproducible.

The test therefore does not call the loader against the developer's ledger.
It bootstraps a scratch world from the seed, runs the repository's own
verification script against the committed manifest, and requires it to pass.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "research" / "fixtures" / "calibration_v1.json"
MAKEFILE = REPO_ROOT / "Makefile"
SMOKE = REPO_ROOT / "configs" / "experiments" / "smoke.yaml"


def demo_window() -> tuple[str, str]:
    """The ingestion window `make demo` uses, read from the Makefile.

    Hardcoding it here would let the fixture and the demo drift apart
    silently, and the manifest is pinned against this exact window.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    found = {}
    for name in ("DEMO_FROM", "DEMO_UNTIL"):
        match = re.search(rf"^{name}\s*\??=\s*(\S+)\s*$", text, re.MULTILINE)
        assert match, f"Makefile has no {name}"
        found[name] = match.group(1)
    return found["DEMO_FROM"], found["DEMO_UNTIL"]


@pytest.mark.slow
class TestFixtureReproduces:
    def test_manifest_is_committed(self) -> None:
        # A verification script with nothing to verify against passes vacuously.
        assert MANIFEST.exists(), (
            f"{MANIFEST.relative_to(REPO_ROOT)} is missing. Pin it with "
            "`python scripts/build_calibration_fixture.py --write`."
        )

    def test_regenerates_from_seed_and_matches_the_manifest(self, tmp_path: Path) -> None:
        workspace = tmp_path / "fixture"
        workspace.mkdir()
        shutil.copytree(REPO_ROOT / "configs", workspace / "configs")
        shutil.copytree(REPO_ROOT / "scripts", workspace / "scripts")
        shutil.copytree(REPO_ROOT / "research", workspace / "research")

        environment = {
            **os.environ,
            "PRAMAANX_DATA_ROOT": str(workspace / "data"),
            "PRAMAANX_RUN_ROOT": str(workspace / "runs"),
            "PRAMAANX_LOG_LEVEL": "WARNING",
            # The synthetic world needs neither credentials nor egress; a
            # connector reaching the network here would hang.
            "no_proxy": "*",
        }

        start, until = demo_window()
        bootstrap = subprocess.run(
            [sys.executable, "scripts/bootstrap_data.py", "--from", start, "--until", until],
            cwd=workspace,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
            timeout=600,
        )
        assert bootstrap.returncode == 0, (
            f"bootstrap failed ({bootstrap.returncode})\n{bootstrap.stderr[-2000:]}"
        )

        verify = subprocess.run(
            [sys.executable, "scripts/build_calibration_fixture.py"],
            cwd=workspace,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
            timeout=900,
        )
        assert verify.returncode == 0, (
            "the fixture did not reproduce its pinned manifest on a clean "
            f"workspace ({verify.returncode})\n"
            f"stdout: {verify.stdout[-2000:]}\nstderr: {verify.stderr[-3000:]}"
        )
        assert "reproduces its manifest" in verify.stdout


@pytest.mark.slow
class TestLoaderInProcess:
    """The loader itself, called directly rather than through the script."""

    @pytest.fixture
    def scratch_world(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """A synthetic world under an isolated data root."""
        monkeypatch.setenv("PRAMAANX_DATA_ROOT", str(tmp_path / "data"))
        monkeypatch.setenv("PRAMAANX_RUN_ROOT", str(tmp_path / "runs"))
        monkeypatch.chdir(REPO_ROOT)

        from pramaanx.evaluation.backtest import load_experiment
        from pramaanx.ingest.base import FetchWindow
        from pramaanx.ingest.ledger import EvidenceLedger

        # The ledger must be built from the settings the loader itself will
        # resolve. A bare Settings() does not read PRAMAANX_DATA_ROOT, so
        # constructing one here would ingest into the repository's own data
        # directory and leave the scratch root empty.
        _, settings = load_experiment(SMOKE)
        assert settings.storage.data_root == tmp_path / "data"
        ledger = EvidenceLedger(settings)
        start, until = demo_window()
        ledger.ingest("synthetic", FetchWindow.from_dates(start, until))
        return tmp_path

    def test_sample_is_internally_consistent(self, scratch_world: Path) -> None:
        from pramaanx.fixtures import build_manifest, load_calibration_sample, verify_manifest

        sample = load_calibration_sample(SMOKE)

        assert len(sample) == len(sample.probabilities) == len(sample.labels)
        assert sample.folds, "a scoreable walk must produce at least one fold"
        assert sum(len(fold) for fold in sample.folds) == len(sample)
        assert 0 <= sample.positives <= len(sample)
        # A sample of all-zero labels would fit a degenerate calibrator and
        # look like success, so the fixture has to actually contain positives.
        assert sample.positives > 0
        assert "not with reality" in sample.caveat

        # A sample verifies against a manifest built from itself, which is the
        # invariant the pinned manifest relies on.
        verify_manifest(sample, build_manifest(sample))

    def test_rows_are_canonically_ordered_within_each_fold(self, scratch_world: Path) -> None:
        # Row order is otherwise path-dependent: forecast identifiers derive
        # from snapshot hashes, which fold in config_hash, which embeds
        # storage.data_root.
        from pramaanx.fixtures import load_calibration_sample

        sample = load_calibration_sample(SMOKE)
        for fold in sample.folds:
            rows = list(
                zip(
                    sample.probabilities[fold.start : fold.stop],
                    sample.labels[fold.start : fold.stop],
                    strict=True,
                )
            )
            assert rows == sorted(rows)

    def test_temporal_split_covers_the_whole_sample(self, scratch_world: Path) -> None:
        from pramaanx.fixtures import load_calibration_sample

        sample = load_calibration_sample(SMOKE)
        if len(sample.folds) < 2:
            pytest.skip("the smoke walk produced a single scoreable fold")

        earlier, later = sample.split_at_fold(1)
        assert len(earlier) + len(later) == len(sample)
        assert earlier.probabilities + later.probabilities == sample.probabilities
        assert later.folds[0].start == 0
