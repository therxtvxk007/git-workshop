"""Logging and experiment tracking."""

from __future__ import annotations

import io
import json

from pramaan_x.tracking import LocalTracker, build_tracker
from pramaan_x.util.logging import configure, get_logger, safe_extra, timed


def _records(buf: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in buf.getvalue().strip().splitlines() if line]


def test_json_records_carry_run_id():
    buf = io.StringIO()
    configure("INFO", json_output=True, stream=buf)
    get_logger("t").info("hello", extra={"docs": 3})
    (rec,) = _records(buf)
    assert rec["msg"] == "hello" and rec["docs"] == 3
    assert len(rec["run_id"]) == 12


def test_reserved_keys_do_not_raise():
    """`extra={"name": ...}` raises KeyError in stdlib logging. Natural field
    names must not be landmines."""
    buf = io.StringIO()
    configure("INFO", json_output=True, stream=buf)
    get_logger("t").info("x", extra={"name": "corpus", "module": "m", "docs": 1})
    (rec,) = _records(buf)
    assert rec["name_"] == "corpus" and rec["module_"] == "m" and rec["docs"] == 1


def test_safe_extra_leaves_clean_keys_alone():
    assert safe_extra({"stage": "s0", "name": "x"}) == {"stage": "s0", "name_": "x"}


def test_timed_emits_duration():
    buf = io.StringIO()
    configure("INFO", json_output=True, stream=buf)
    with timed(get_logger("t"), "stage1", docs=10):
        pass
    start, end = _records(buf)
    assert start["phase"] == "start" and end["phase"] == "end"
    assert end["elapsed_ms"] >= 0 and end["docs"] == 10


def test_timed_logs_and_reraises_on_failure():
    buf = io.StringIO()
    configure("INFO", json_output=True, stream=buf)
    try:
        with timed(get_logger("t"), "stage1"):
            raise ValueError("boom")
    except ValueError:
        pass
    assert _records(buf)[-1]["phase"] == "error"


def test_local_tracker_roundtrip(tmp_path):
    t = LocalTracker(root=tmp_path)
    t.start_run("exp", {"suite": "unit"})
    t.log_params({"stage2": {"rrf_k": 60}})
    t.log_metrics({"recall@10": 0.53})
    t.end_run()
    (run,) = LocalTracker(root=tmp_path).history()
    assert run["name"] == "exp" and run["metrics"]["recall@10"] == 0.53


def test_non_finite_metrics_are_dropped(tmp_path):
    """NaN in a metrics payload must not corrupt the run record."""
    t = LocalTracker(root=tmp_path)
    t.start_run("exp")
    t.log_metrics({"good": 1.0, "nan": float("nan"), "inf": float("inf")})
    t.end_run()
    metrics = LocalTracker(root=tmp_path).history()[0]["metrics"]
    assert metrics["good"] == 1.0
    assert metrics["nan"] is None and metrics["inf"] is None


def test_mlflow_failure_falls_back_to_local(tmp_path):
    """A tracking outage must never fail a forecast run."""
    tracker = build_tracker("mlflow", uri="http://127.0.0.1:1", root=str(tmp_path))
    assert isinstance(tracker, LocalTracker)
    tracker.start_run("fallback")
    tracker.end_run()
