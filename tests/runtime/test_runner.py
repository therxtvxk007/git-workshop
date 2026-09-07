"""Attempts survive the failures that matter: crashes, timeouts and raises."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pramaanx.clock import FixedClock
from pramaanx.core.errors import ContractViolationError
from pramaanx.runtime.runner import (
    Attempt,
    AttemptStore,
    Environment,
    RunManager,
    RunState,
    RunTimeoutError,
    redact,
)

NOW = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture
def manager(tmp_path: Path) -> RunManager:
    return RunManager(tmp_path / "runs", clock=FixedClock(NOW), code_hash="sha256:code")


def _states(manager: RunManager) -> list[RunState]:
    return [attempt.state for attempt in manager.store.read()]


def test_the_attempt_is_recorded_before_the_work_starts(manager: RunManager) -> None:
    """Not after. An attempt written on success records only successes."""
    seen: list[list[RunState]] = []
    with manager.attempt(run_id="r1", stage="fit"):
        seen.append(_states(manager))
    assert seen[0] == [RunState.CREATED, RunState.RUNNING]
    assert _states(manager)[-1] is RunState.SUCCEEDED


def test_a_raising_stage_still_leaves_a_terminal_row(manager: RunManager) -> None:
    with pytest.raises(ValueError, match="boom"), manager.attempt(run_id="r1", stage="fit"):
        raise ValueError("boom")

    final = manager.store.read()[-1]
    assert final.state is RunState.FAILED
    assert final.failure_kind == "ValueError"
    assert "boom" in final.failure_detail


def test_an_interrupt_is_cancelled_rather_than_failed(manager: RunManager) -> None:
    with pytest.raises(KeyboardInterrupt), manager.attempt(run_id="r1", stage="fit"):
        raise KeyboardInterrupt

    assert manager.store.read()[-1].state is RunState.CANCELLED


def test_a_stage_over_its_budget_times_out(manager: RunManager) -> None:
    """A resource failure is a failed attempt, not permission to do less."""
    with (
        pytest.raises(RunTimeoutError),
        manager.attempt(run_id="r1", stage="fit", timeout_seconds=0.0),
    ):
        pass

    final = manager.store.read()[-1]
    assert final.state is RunState.TIMED_OUT
    assert final.failure_kind == "timeout"


def test_a_retry_never_overwrites_the_failed_attempt(manager: RunManager) -> None:
    """Release condition 5 asks for the failed variants too."""
    with pytest.raises(RuntimeError), manager.attempt(run_id="r1", stage="fit"):
        raise RuntimeError("first try")
    with manager.attempt(run_id="r1", stage="fit"):
        pass

    terminal = [attempt for attempt in manager.store.read() if attempt.terminal]
    assert [attempt.state for attempt in terminal] == [RunState.FAILED, RunState.SUCCEEDED]
    assert len({attempt.attempt_id for attempt in terminal}) == 2


def test_the_handle_collects_what_the_terminal_row_carries(manager: RunManager) -> None:
    with manager.attempt(run_id="r1", stage="predict", rng={"root_seed": 7}) as handle:
        handle.record_context("sha256:ctx")
        handle.record_input("sha256:panel")
        handle.record_output("sha256:forecast")
        handle.warn("district 999 has no history")

    final = manager.store.read()[-1]
    assert final.contexts == ("sha256:ctx",)
    assert final.inputs == ("sha256:panel",)
    assert final.outputs == ("sha256:forecast",)
    assert final.warnings == ("district 999 has no history",)
    assert final.rng == {"root_seed": 7}
    assert final.elapsed_seconds is not None


def test_credentials_never_reach_the_ledger(manager: RunManager) -> None:
    with manager.attempt(
        run_id="r1",
        stage="ingest",
        config={"url": "https://x", "api_key": "sk-secret", "nested": {"TOKEN": "t"}},
    ):
        pass

    config = manager.store.read()[-1].config
    assert config["url"] == "https://x"
    assert config["api_key"] == "***redacted***"
    assert config["nested"]["TOKEN"] == "***redacted***"


def test_redaction_matches_on_substrings_and_case() -> None:
    assert redact({"Authorization": "x", "db_password": "y", "count": 1}) == {
        "Authorization": "***redacted***",
        "count": 1,
        "db_password": "***redacted***",
    }


def test_an_attempt_needs_a_run_id_and_a_stage(manager: RunManager) -> None:
    with (
        pytest.raises(ContractViolationError, match="run id and a stage"),
        manager.attempt(run_id="", stage="fit"),
    ):
        pass


# -- crash recovery --------------------------------------------------------
def test_a_killed_process_leaves_a_visible_running_row(tmp_path: Path) -> None:
    """``finally`` does not run when a process is killed, which is precisely
    why the row is written first (S36.1)."""
    root = tmp_path / "runs"
    script = f"""
import os, signal
from datetime import UTC, datetime
from pathlib import Path
from pramaanx.clock import FixedClock
from pramaanx.runtime.runner import RunManager

manager = RunManager(Path({str(root)!r}), clock=FixedClock(datetime(2026, 6, 1, tzinfo=UTC)))
with manager.attempt(run_id="r1", stage="fit"):
    os.kill(os.getpid(), signal.SIGKILL)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, check=False, timeout=60
    )
    assert result.returncode != 0

    store = AttemptStore(root)
    assert [attempt.state for attempt in store.read()] == [RunState.CREATED, RunState.RUNNING]
    assert len(store.unfinished()) == 1


def test_recovery_closes_an_attempt_whose_process_is_gone(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = AttemptStore(root)
    # A pid that is certainly not running: 0 is never a user process, and the
    # liveness check treats a lookup failure as dead.
    dead = Environment(pid=999_999_999)
    store.append(
        Attempt(
            run_id="r1",
            attempt_id="att_stale",
            stage="fit",
            state=RunState.RUNNING,
            recorded_at=NOW,
            environment=dead,
        )
    )
    manager = RunManager(root, clock=FixedClock(NOW))

    preview = manager.recover()
    assert [attempt.failure_kind for attempt in preview] == ["abandoned"]
    assert len(manager.store.unfinished()) == 1

    manager.recover(dry_run=False)
    assert manager.store.unfinished() == []
    assert manager.store.current()["att_stale"].state is RunState.FAILED


def test_recovery_leaves_a_live_attempt_alone(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = AttemptStore(root)
    store.append(
        Attempt(
            run_id="r1",
            attempt_id="att_live",
            stage="fit",
            state=RunState.RUNNING,
            recorded_at=NOW,
            environment=Environment(pid=os.getpid()),
        )
    )
    assert RunManager(root, clock=FixedClock(NOW)).recover(dry_run=False) == []


def test_recovery_does_not_guess_about_another_host(tmp_path: Path) -> None:
    """A pid on another machine says nothing about a process here."""
    root = tmp_path / "runs"
    AttemptStore(root).append(
        Attempt(
            run_id="r1",
            attempt_id="att_remote",
            stage="fit",
            state=RunState.RUNNING,
            recorded_at=NOW,
            environment=Environment(host="some-other-machine", pid=1234),
        )
    )
    manager = RunManager(root, clock=FixedClock(NOW))
    assert manager.recover(dry_run=False) == []
    assert len(manager.store.unfinished()) == 1
