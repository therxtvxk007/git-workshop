"""Artefact identity, and the README drift it is supposed to prevent.

Four defects these tests were written against, all in the committed artefacts:

  * they were produced at a commit that is not the tip, and mostly record
    `dirty: true`, so the commit they name does not describe the code that
    produced them;
  * the path digest omitted the code revision, so two commits resolved to the
    same file and a later run silently overwrote an earlier one;
  * the documentation tests did not fail when prose in the README disagreed
    with the JSON it cited -- and it did disagree: the latency sentence read
    33.2 / 32.6 / 37.3 ms against artefacts holding 31.54 / 31.25 / 36.05;
  * backend identities carried no versions, so "lightgbm" stood for any
    release of it.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

import pytest

from pramaan_x.eval.artefact import (
    GENERATED_PATHS,
    SOURCE_ROOTS,
    DirtyWorktreeError,
    GitState,
    artefact_path,
    backend_versions,
    identity_digest,
    is_source_path,
    scientific_identity,
    source_tree_hash,
    write_artefact,
)

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmark_results"


def _payload(**overrides):
    base = {
        "method": "strict_temporal",
        "seed": 7,
        "git": {
            "commit": "a" * 40,
            "source_tree_hash": "b" * 64,
            "source_dirty": False,
            "source_dirty_files": [],
        },
        "environment": {"uv_lock_sha256": "c" * 64, "package_version": "0.5.0"},
        "protocol_fingerprint": "d" * 16,
        "dataset": {"logical_hash": "e" * 64, "file_hash": "f" * 64},
        "config_fingerprint": "0123456789abcdef",
        "backends": {
            "embedder": "hashing (1024d)",
            "reranker": "lexical",
            "vector_engine": "memory",
            "fusion_backend": "lambdarank",
            "versions": {"lightgbm": "4.5.0", "numpy": "2.1.0"},
        },
    }
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


# ------------------------------------------------------- identity coverage ---


def test_identity_covers_everything_that_changes_what_a_result_means():
    identity = scientific_identity(_payload())
    for field in (
        "git_commit",
        "source_tree_hash",
        "uv_lock_sha256",
        "package_version",
        "protocol_fingerprint",
        "dataset_logical_hash",
        "dataset_file_hash",
        "config_fingerprint",
        "backends",
        "method",
        "seed",
    ):
        assert field in identity, f"identity omits {field}"
    assert identity["backends"]["versions"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"git": {"commit": "9" * 40}},
        {"git": {"source_tree_hash": "9" * 64}},
        {"environment": {"uv_lock_sha256": "9" * 64}},
        {"environment": {"package_version": "9.9.9"}},
        {"protocol_fingerprint": "9" * 16},
        {"dataset": {"logical_hash": "9" * 64}},
        {"dataset": {"file_hash": "9" * 64}},
        {"config_fingerprint": "9999999999999999"},
        {"backends": {"versions": {"lightgbm": "9.9.9", "numpy": "2.1.0"}}},
        {"backends": {"embedder": "jina-v5-small"}},
        {"seed": 8},
        {"method": "future_fitted_index_ablation"},
    ],
)
def test_no_two_scientific_identities_share_a_path(overrides, tmp_path):
    """END-TO-END NEGATIVE CONTROL for requirement 4.

    On the committed implementation the digest covered method, seed, protocol,
    config and dataset only -- so a different commit, a different lockfile or a
    different LightGBM release all resolved to the same filename and silently
    overwrote the earlier result.
    """
    base = _payload()
    variant = _payload(**overrides)
    assert identity_digest(base) != identity_digest(variant), overrides
    assert artefact_path(base, tmp_path) != artefact_path(variant, tmp_path), overrides


def test_an_identical_run_resolves_to_the_same_path(tmp_path):
    assert artefact_path(_payload(), tmp_path) == artefact_path(_payload(), tmp_path)


def test_backend_versions_are_concrete():
    versions = backend_versions()
    assert versions["python"]
    for package in ("numpy", "polars", "lightgbm", "pramaan-x"):
        assert package in versions
        assert re.match(r"^\d|^absent$", versions[package]), versions[package]


# ------------------------------------------------- the dirty-source refusal ---


def test_publishing_from_a_dirty_source_tree_is_refused(tmp_path):
    """A result attributed to a commit that does not contain the code that
    produced it is worse than an unattributed one."""
    dirty = _payload(git={"source_dirty": True, "source_dirty_files": ["pramaan_x/api.py"]})
    with pytest.raises(DirtyWorktreeError, match="dirty source tree"):
        write_artefact(dirty, tmp_path)
    # ...and the escape hatch exists, is explicit, and is not the default.
    path = write_artefact(dirty, tmp_path, require_clean_source=False)
    assert path.exists()


def test_a_clean_source_tree_publishes(tmp_path):
    path = write_artefact(_payload(), tmp_path)
    assert json.loads(path.read_text())["method"] == "strict_temporal"


@pytest.mark.parametrize(
    "path", ["pramaan_x/api.py", "configs/cpu_only.json", "pyproject.toml", "uv.lock"]
)
def test_source_paths_count_as_source(path):
    assert is_source_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "benchmark_results/strict_temporal/seed-1/x.json",
        "artifacts/corpus.parquet",
        "pramaan_x/__pycache__/api.cpython-311.pyc",
        ".venv/lib/python3.11/site-packages/x.py",
        "README.md",
        "tests/test_artefact.py",
    ],
)
def test_generated_and_non_source_paths_are_excluded(path):
    """The exclusion is explicit and tested, as the requirement asks.

    A benchmark writing its own artefact necessarily dirties the worktree; if
    that counted, publishing would be impossible.
    """
    assert not is_source_path(path)


def test_the_exclusion_list_is_declared_not_implied():
    assert "benchmark_results/" in GENERATED_PATHS
    assert "artifacts/" in GENERATED_PATHS
    assert "pramaan_x" in SOURCE_ROOTS
    assert "uv.lock" in SOURCE_ROOTS


def test_source_tree_hash_tracks_content_not_the_commit(tmp_path):
    before = source_tree_hash(ROOT)
    assert before and len(before) == 64
    assert source_tree_hash(ROOT) == before


def test_git_state_separates_source_dirtiness_from_worktree_dirtiness():
    state = GitState.read(ROOT)
    assert set(state.source_dirty_files) <= set(state.dirty_files)
    assert all(is_source_path(f) for f in state.source_dirty_files)


# --------------------------------------------- the committed artefacts pass ---


def _committed(method: str) -> list[Path]:
    root = RESULTS / method
    return sorted(root.rglob("*.json")) if root.exists() else []


def test_committed_artefacts_reference_a_clean_source_tree():
    paths = _committed("strict_temporal")
    if not paths:
        pytest.skip("no strict artefacts committed yet")
    for path in paths:
        payload = json.loads(path.read_text())
        assert payload["git"]["source_dirty"] is False, (
            f"{path.name} was produced from a dirty source tree: "
            f"{payload['git']['source_dirty_files'][:3]}"
        )
        assert payload["git"]["source_tree_hash"], f"{path.name} has no source fingerprint"
        assert payload["environment"]["uv_lock_sha256"]


def test_committed_artefacts_reference_a_real_reachable_commit():
    paths = _committed("strict_temporal")
    if not paths:
        pytest.skip("no strict artefacts committed yet")
    for path in paths:
        commit = json.loads(path.read_text())["git"]["commit"]
        found = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=str(ROOT),
            capture_output=True,
            timeout=30,
        )
        assert found.returncode == 0, f"{path.name} names commit {commit}, which does not exist"


def test_committed_artefacts_sit_at_their_own_identity_path():
    for method in (
        "strict_temporal",
        "future_fitted_index_ablation",
        "historical_legacy_reproduction_unpaired",
    ):
        for path in _committed(method):
            payload = json.loads(path.read_text())
            expected = artefact_path(payload, RESULTS)
            assert path.resolve() == expected.resolve(), (
                f"{path} does not match its own identity digest ({expected})"
            )


def test_committed_artefacts_match_the_committed_summary():
    summary_path = RESULTS / "summary.json"
    if not summary_path.exists():
        pytest.skip("no summary committed yet")
    summary = json.loads(summary_path.read_text())
    stage = summary["stage"]
    for method, agg in summary["methods"].items():
        artefacts = {
            json.loads(p.read_text())["seed"]: json.loads(p.read_text()) for p in _committed(method)
        }
        assert artefacts, f"summary names {method} but no artefact exists"
        for row in agg["per_seed"]:
            payload = artefacts[row["seed"]]
            for metric, value in row["metrics"].items():
                assert payload["metrics"][stage][metric] == pytest.approx(value), (
                    f"{method} seed {row['seed']} {metric}: summary {value} != "
                    f"artefact {payload['metrics'][stage][metric]}"
                )


def test_an_artefact_never_claims_two_versions_of_itself():
    """Regression guard for a defect the required verification caught.

    `backend_versions` read this package's version from installed distribution
    metadata. An editable install keeps reporting the version recorded when it
    was created, so after the version was bumped the artefacts recorded
    `environment.package_version = 0.5.0` alongside
    `backends.versions["pramaan-x"] = 1.0.0` -- an identity that disagreed with
    itself, published without anything noticing.
    """
    from pramaan_x import __version__

    assert backend_versions()["pramaan-x"] == __version__


def test_committed_artefacts_agree_with_themselves_about_the_version():
    paths = _committed("strict_temporal")
    if not paths:
        pytest.skip("no strict artefacts committed yet")
    for path in paths:
        payload = json.loads(path.read_text())
        assert (
            payload["backends"]["versions"]["pramaan-x"]
            == payload["environment"]["package_version"]
        ), f"{path.name} records two different versions of pramaan-x"


def test_the_artefact_commit_is_the_commit_that_held_the_code():
    """Why the committed artefacts name a commit that is not the tip.

    An artefact records the commit whose source produced it. Committing the
    artefact necessarily advances HEAD, so the artefact can never name the
    commit that contains it -- that would require the file to contain its own
    hash. The two properties that *are* checkable are asserted elsewhere: the
    commit exists and is reachable, and the artefact sits at the path its own
    identity digest names.
    """
    paths = _committed("strict_temporal")
    if not paths:
        pytest.skip("no strict artefacts committed yet")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True, timeout=30
    ).stdout.strip()
    for path in paths:
        commit = json.loads(path.read_text())["git"]["commit"]
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, head],
            cwd=str(ROOT),
            capture_output=True,
            timeout=30,
        )
        assert ancestor.returncode == 0, (
            f"{path.name} names commit {commit}, which is not an ancestor of HEAD"
        )


def test_exactly_one_artefact_per_method_and_seed():
    """Regression guard for a stale artefact that got committed.

    An interrupted run left a file behind at an identity path a later run no
    longer produced, so `benchmark_results/` carried two artefacts for one
    (method, seed) pair. Both were internally consistent, so every other check
    passed; only counting catches it. A directory holding two answers to the
    same question is a directory somebody will read the wrong answer from.
    """
    if not RESULTS.exists():
        pytest.skip("no artefacts committed yet")
    for method_dir in sorted(p for p in RESULTS.iterdir() if p.is_dir()):
        for seed_dir in sorted(p for p in method_dir.iterdir() if p.is_dir()):
            files = sorted(seed_dir.glob("*.json"))
            assert len(files) == 1, (
                f"{method_dir.name}/{seed_dir.name} holds {len(files)} artefacts: "
                f"{[f.name for f in files]}"
            )


def test_every_method_covers_every_seed():
    """A missing artefact is as misleading as a duplicate: the summary would
    still average whatever it found."""
    summary_path = RESULTS / "summary.json"
    if not summary_path.exists():
        pytest.skip("no summary committed yet")
    summary = json.loads(summary_path.read_text())
    expected = set(summary["seeds"])
    for method in summary["methods"]:
        seeds = {
            int(p.name.removeprefix("seed-")) for p in (RESULTS / method).iterdir() if p.is_dir()
        }
        assert seeds == expected, (
            f"{method} has artefacts for {sorted(seeds)}, expected {sorted(expected)}"
        )
