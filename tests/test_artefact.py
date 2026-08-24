"""The run artefact.

The artefact is the claim. These tests check that every field the protocol
requires is present, that the path is a deterministic function of what the run
means, and that the two arms of the experiment are distinguishable from the
file alone -- because a reader who only has the JSON must be able to tell a
contaminated diagnostic from a result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pramaan_x.config import Config
from pramaan_x.eval.artefact import (
    BackendIdentity,
    DatasetIdentity,
    GitState,
    aggregate,
    artefact_path,
    build_artefact,
    write_artefact,
)
from pramaan_x.eval.availability import AvailabilityViolation, Rejection
from pramaan_x.eval.harness import prepare, run_method
from pramaan_x.eval.metrics import RetrievalReport
from pramaan_x.eval.oracle_target_retrieval import LEGACY, STRICT
from pramaan_x.eval.protocol import TemporalProtocol

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_TOP_LEVEL = (
    "git",
    "dataset",
    "config_fingerprint",
    "protocol",
    "forecast_origins",
    "queries",
    "availability_violations",
    "backends",
    "metrics",
    "seed",
    "method",
    "invariants",
)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config().apply_profile()


@pytest.fixture(scope="module")
def prep(cfg):
    return prepare(cfg, days=200, seed=7, n_locations=5, n_event_types=4)


@pytest.fixture(scope="module")
def strict_payload(prep, cfg, tmp_path_factory):
    res = run_method(
        prep, cfg, STRICT, stages=("rerank",), results_dir=tmp_path_factory.mktemp("art-strict")
    )
    return res.payload, res.path


@pytest.fixture(scope="module")
def legacy_payload(prep, cfg, tmp_path_factory):
    res = run_method(
        prep, cfg, LEGACY, stages=("rerank",), results_dir=tmp_path_factory.mktemp("art-legacy")
    )
    return res.payload, res.path


def test_every_required_field_is_present(strict_payload):
    payload, _ = strict_payload
    for key in REQUIRED_TOP_LEVEL:
        assert key in payload, f"artefact is missing {key}"


def test_provenance_pins_the_run_to_a_commit_and_a_corpus(strict_payload):
    payload, _ = strict_payload
    git = payload["git"]
    assert "commit" in git and "dirty" in git
    assert isinstance(git["dirty"], bool)
    ds = payload["dataset"]
    assert len(ds["logical_hash"]) == 64
    assert len(ds["file_hash"]) == 64
    assert ds["logical_hash"] != ds["file_hash"], "two different questions, two hashes"
    assert ds["n_documents"] > 0
    assert ds["generator"]["synthetic"] is True


def test_temporal_windows_and_origins_are_recorded(strict_payload, prep):
    payload, _ = strict_payload
    proto = payload["protocol"]
    for key in (
        "train_start",
        "train_end",
        "calibration_start",
        "calibration_end",
        "test_start",
        "test_end",
        "embargo_days",
        "effective_embargo_days",
        "availability_rule",
        "query_generation_rule",
        "permitted_fitting",
    ):
        assert key in proto
    assert payload["forecast_origins"] == [o.isoformat() for o in prep.protocol.origins("test")]
    assert payload["n_forecast_origins"] == len(payload["forecast_origins"])
    assert payload["protocol_fingerprint"] == prep.protocol.fingerprint()


def test_metric_families_are_all_reported(strict_payload):
    payload, _ = strict_payload
    m = payload["metrics"]["rerank"]
    assert {"recall@10", "precision@10", "ndcg@10", "mrr"} <= set(m)
    assert any(k.startswith("latency_ms.") for k in m)
    assert m["queries"] > 0
    assert payload["queries"]["relevant_documents"] > 0
    assert payload["queries"]["train"] > 0


def test_backends_are_named_concretely(strict_payload):
    payload, _ = strict_payload
    b = payload["backends"]
    assert b["embedder"].startswith("hashing")
    assert b["reranker"] == "lexical"
    assert b["vector_engine"] == "memory"
    assert b["fusion_backend"] in {"lambdarank", "ridge", "none (heuristic ordering)"}


def test_the_artefact_says_what_it_does_not_measure(strict_payload):
    payload, _ = strict_payload
    assert payload["benchmark"] == "oracle_target_retrieval"
    assert "forecasting" in payload["does_not_measure"]
    assert "oracle" in payload["measures"]


def test_strict_and_legacy_are_distinguishable_from_the_file_alone(strict_payload, legacy_payload):
    strict, _ = strict_payload
    legacy, _ = legacy_payload
    assert strict["method"] == STRICT and legacy["method"] == LEGACY
    assert set(strict["invariants"].values()) == {"pass"}
    assert any(v.startswith("FAIL") for v in legacy["invariants"].values())
    assert strict["availability_violations"]["total"] == 0
    assert legacy["availability_violations"]["total"] > 0
    assert "available strictly before" in strict["extra"]["index_scope"]
    assert "including documents from after" in legacy["extra"]["index_scope"]


def test_artefact_is_written_and_reloadable(strict_payload):
    payload, path = strict_payload
    assert path is not None and path.exists()
    reloaded = json.loads(path.read_text())
    assert reloaded["protocol_fingerprint"] == payload["protocol_fingerprint"]
    assert reloaded["metrics"] == payload["metrics"]


def test_artefact_path_is_deterministic_in_what_the_run_means(strict_payload, tmp_path):
    payload, _ = strict_payload
    a = artefact_path(payload, tmp_path)
    assert artefact_path(dict(payload), tmp_path) == a
    assert a.parent.name == f"seed-{payload['seed']}"
    assert a.parent.parent.name == payload["method"]
    moved = {**payload, "seed": payload["seed"] + 1}
    assert artefact_path(moved, tmp_path) != a
    rescoped = {**payload, "protocol_fingerprint": "0" * 16}
    assert artefact_path(rescoped, tmp_path).name != a.name


def test_availability_violations_are_counted_by_reason(tmp_path):
    proto = TemporalProtocol.from_span(
        datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)
    )
    violations = [
        AvailabilityViolation("a", Rejection.RETRIEVED_AFTER_ORIGIN, "2025-01-01"),
        AvailabilityViolation("b", Rejection.RETRIEVED_AFTER_ORIGIN, "2025-01-01"),
        AvailabilityViolation("c", Rejection.MISSING_ACQUISITION_TIME, "2025-01-01"),
    ]
    payload = build_artefact(
        method=LEGACY,
        protocol=proto,
        dataset=DatasetIdentity("d", 1, "x" * 64, None, None, None, None, {}),
        backends=BackendIdentity("e", "r", "m", "ridge"),
        config_fingerprint="cfg",
        seed=1,
        reports={
            "rerank": RetrievalReport(
                recall={10: 0.5}, ndcg={10: 0.4}, mrr=0.3, n_queries=2, precision={10: 0.1}
            )
        },
        availability_violations=violations,
        n_train_queries=1,
        n_test_queries=2,
        n_index_builds=0,
        invariants={"no_post_origin_results": "FAIL: 3"},
    )
    av = payload["availability_violations"]
    assert av["total"] == 3
    assert av["by_reason"] == {"retrieved_after_origin": 2, "missing_acquisition_time": 1}
    assert len(av["sample"]) == 3
    path = write_artefact(payload, tmp_path)
    assert json.loads(path.read_text())["availability_violations"]["total"] == 3


def test_aggregate_reports_mean_std_and_every_seed():
    payloads = [
        {"seed": s, "metrics": {"rerank": {"recall@10": r, "mrr": m}}}
        for s, r, m in [(1, 0.40, 0.60), (2, 0.50, 0.70), (3, 0.60, 0.80)]
    ]
    agg = aggregate(payloads, stage="rerank")
    assert agg["n_seeds"] == 3
    assert agg["statistics"]["recall@10"]["mean"] == pytest.approx(0.5)
    assert agg["statistics"]["recall@10"]["std"] == pytest.approx(0.1)
    assert agg["statistics"]["recall@10"]["n"] == 3
    assert [row["seed"] for row in agg["per_seed"]] == [1, 2, 3]


def test_aggregate_of_a_single_seed_reports_zero_spread_not_nan():
    agg = aggregate([{"seed": 1, "metrics": {"rerank": {"mrr": 0.5}}}], stage="rerank")
    assert agg["statistics"]["mrr"]["std"] == 0.0
    assert agg["statistics"]["mrr"]["n"] == 1


def test_git_state_reads_a_dirty_worktree_flag():
    state = GitState.read()
    assert isinstance(state.dirty, bool)
    if state.commit is not None:
        assert len(state.commit) == 40


def test_dataset_identity_separates_logical_and_byte_hashes(prep):
    ds = prep.dataset
    assert ds.file_bytes and ds.file_bytes > 0
    assert ds.earliest < ds.latest
    assert ds.generator["seed"] == 7


def test_protocol_notes_carry_the_synthetic_disclaimer(prep):
    assert any("synthetic" in n for n in prep.protocol.notes)


def test_windows_do_not_overlap_in_the_artefact(strict_payload):
    payload, _ = strict_payload
    p = payload["protocol"]
    order = [
        p["train_start"],
        p["train_end"],
        p["calibration_start"],
        p["calibration_end"],
        p["test_start"],
        p["test_end"],
    ]
    parsed = [datetime.fromisoformat(x) for x in order]
    assert parsed == sorted(parsed)
    assert parsed[2] - parsed[1] >= timedelta(days=p["effective_embargo_days"])
    assert parsed[4] - parsed[3] >= timedelta(days=p["effective_embargo_days"])


# ------------------------------------------------------- reproducibility ---


def test_repeated_runs_of_the_same_protocol_agree_exactly(prep, cfg):
    """A recorded seed that does not determine the result is worse than none."""
    a = run_method(prep, cfg, STRICT, stages=("rerank",), write=False)
    b = run_method(prep, cfg, STRICT, stages=("rerank",), write=False)
    assert _stable(a.payload) == _stable(b.payload)
    assert a.fusion_weights == b.fusion_weights


def test_results_do_not_depend_on_the_python_hash_seed(tmp_path):
    """Regression guard for a real defect.

    The learned lexicon selected its top-k terms with `sorted(..., key=-score)`
    over a set, so ties were broken by dict iteration order and therefore by
    PYTHONHASHSEED. Different hash seeds produced different query text and
    every metric in the benchmark moved, while the artefact still reported the
    same `seed`. CI pinned PYTHONHASHSEED=0, which hid it rather than fixing
    it -- so this test runs subprocesses with *different* seeds on purpose.
    """
    import os
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent("""
        import json
        from pramaan_x.config import Config
        from pramaan_x.eval.harness import prepare, run_method
        from pramaan_x.eval.oracle_target_retrieval import STRICT

        cfg = Config().apply_profile()
        prep = prepare(cfg, days=170, seed=4, n_locations=4, n_event_types=3)
        res = run_method(prep, cfg, STRICT, stages=("rerank",), write=False)
        m = res.payload["metrics"]["rerank"]
        print(json.dumps({
            "metrics": {k: v for k, v in m.items() if not k.startswith("latency")},
            "dataset": prep.dataset.logical_hash,
            "protocol": prep.protocol.fingerprint(),
            "queries": [q.text for q in res.test_queries[:5]],
        }, sort_keys=True))
    """)
    outputs = []
    for hash_seed, threads in (("0", "1"), ("12345", "4")):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "OMP_NUM_THREADS": threads}
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            timeout=900,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        outputs.append(proc.stdout.strip().splitlines()[-1])
    assert outputs[0] == outputs[1], (
        "the benchmark result depends on PYTHONHASHSEED / thread count:\n"
        f"{outputs[0]}\n{outputs[1]}"
    )


def _stable(payload):
    """Everything a re-run must reproduce: metrics minus wall-clock latency."""
    return {
        stage: {k: v for k, v in metrics.items() if not k.startswith("latency_ms")}
        for stage, metrics in payload["metrics"].items()
    }


def test_artefact_records_how_large_each_fitted_corpus_was(strict_payload, legacy_payload):
    """The evidence behind the legacy-vs-strict comparison.

    A snapshot index sees a growing prefix; the legacy index sees the whole
    corpus at every origin. Without these numbers a reader has to take on trust
    the explanation for why the two arms differ.
    """
    strict, _ = strict_payload
    legacy, _ = legacy_payload
    s = strict["extra"]["fitted_corpus_sizes"]
    ll = legacy["extra"]["fitted_corpus_sizes"]
    assert s["distinct"] > 1, "snapshot indexes must not all be the same size"
    assert ll["distinct"] == 1, "the legacy index is the whole corpus every time"
    assert s["max"] <= ll["max"]
    assert s["mean"] < ll["mean"]
