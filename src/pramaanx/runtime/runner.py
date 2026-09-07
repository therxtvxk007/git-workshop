"""Durable run attempts, recorded before the work starts.

The plan is blunt about why this is not a pytest fixture (S27.1, S36.1): a
fixture records runs that go through pytest. A direct CLI invocation, a crash,
a timeout and a fit that raised are exactly the runs whose absence from the
ledger matters, and a fixture misses all four.

So the attempt is written *before* any fitting, downloading or publishing, and
the record is append-only. A crash leaves the ``running`` row on disk, which is
the point: recovery can then see an attempt that never finished, rather than
inferring one from a gap. ``finally`` cannot help here, because a process that
is killed does not run ``finally``.

Retries never overwrite. A logical run has many attempts, each with its own id
and its own final state, and a failed one stays in the ledger next to the
succeeding one -- release condition 5 asks for the failed variants too.
"""

from __future__ import annotations

import contextlib
import os
import platform
import socket
import sys
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field

from pramaanx.clock import Clock, SystemClock
from pramaanx.core.errors import ContractViolationError, PramaanError
from pramaanx.hashing import canonical_json, stable_id, utc_isoformat
from pramaanx.logging import get_logger
from pramaanx.schemas.base import UtcDatetime, VersionedModel

log = get_logger(__name__)

ATTEMPTS_FILE = "attempts.jsonl"

#: Config keys whose values are never written to the ledger, whatever they hold.
REDACTED_KEYS: frozenset[str] = frozenset(
    {"token", "api_key", "apikey", "password", "secret", "authorization", "cookie"}
)
REDACTED = "***redacted***"


class RunState(StrEnum):
    """The attempt lifecycle. Exactly the plan's five terminal states."""

    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL: frozenset[RunState] = frozenset(
    {RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED, RunState.TIMED_OUT}
)


def redact(config: Mapping[str, Any]) -> dict[str, Any]:
    """Strip credentials before anything is written down."""
    out: dict[str, Any] = {}
    for key, value in config.items():
        if any(marker in key.lower() for marker in REDACTED_KEYS):
            out[key] = REDACTED
        elif isinstance(value, Mapping):
            out[key] = redact(value)
        else:
            out[key] = value
    return dict(sorted(out.items()))


class Environment(VersionedModel):
    """What ran this attempt. Not part of any data identity; part of replay."""

    python_version: str = Field(default_factory=lambda: sys.version.split()[0])
    platform: str = Field(default_factory=platform.platform)
    host: str = Field(default_factory=socket.gethostname)
    pid: int = Field(default_factory=os.getpid)

    def same_host(self) -> bool:
        return self.host == socket.gethostname()


class Attempt(VersionedModel):
    """One recorded state of one attempt at one stage.

    Rows are appended, never edited, so the file is a history and the latest
    row for an attempt id is its current state.
    """

    run_id: str
    attempt_id: str
    stage: str
    state: RunState
    recorded_at: UtcDatetime
    environment: Environment = Field(default_factory=Environment)
    #: The stage's resolved configuration, credentials removed.
    config: dict[str, Any] = Field(default_factory=dict)
    code_hash: str = ""
    #: Every context this attempt read under, by identity.
    contexts: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    rng: dict[str, Any] = Field(default_factory=dict)
    #: Populated on a terminal row.
    elapsed_seconds: float | None = None
    failure_kind: str = ""
    failure_detail: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL


class AttemptStore:
    """Append-only attempt log. One writer, one file, no rewriting."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / ATTEMPTS_FILE

    def append(self, attempt: Attempt) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(attempt.model_dump(mode="json")) + "\n")
            handle.flush()
            # Durable before the caller proceeds: an attempt recorded in a
            # buffer is not recorded at all if the process is killed next.
            os.fsync(handle.fileno())

    def read(self) -> list[Attempt]:
        if not self.path.exists():
            return []
        return [
            Attempt.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def current(self) -> dict[str, Attempt]:
        """The latest row per attempt id, in file order."""
        latest: dict[str, Attempt] = {}
        for attempt in self.read():
            latest[attempt.attempt_id] = attempt
        return latest

    def unfinished(self) -> list[Attempt]:
        return [attempt for attempt in self.current().values() if not attempt.terminal]


@dataclass
class AttemptHandle:
    """The live attempt. Collects what the terminal row will carry."""

    run_id: str
    attempt_id: str
    stage: str
    started_monotonic: float
    contexts: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rng: dict[str, Any] = field(default_factory=dict)

    def record_context(self, identity: str) -> None:
        self.contexts.append(identity)

    def record_input(self, artifact: str) -> None:
        self.inputs.append(artifact)

    def record_output(self, artifact: str) -> None:
        self.outputs.append(artifact)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


class RunTimeoutError(PramaanError):
    """The attempt exceeded its declared wall-clock budget."""

    code = "pramaanx.run_timeout"


class RunManager:
    """Creates a durable attempt, then runs the work inside it."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Clock | None = None,
        code_hash: str = "",
    ) -> None:
        self.store = AttemptStore(Path(root))
        self.clock = clock or SystemClock()
        self.code_hash = code_hash

    @contextlib.contextmanager
    def attempt(
        self,
        *,
        run_id: str,
        stage: str,
        config: Mapping[str, Any] | None = None,
        rng: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[AttemptHandle]:
        """Record the attempt, run the body, record how it ended.

        A resource failure is a failed attempt, not permission to quietly do
        less work: the exception propagates after the row is written.
        """
        if not run_id or not stage:
            raise ContractViolationError("an attempt needs a run id and a stage")

        started = self.clock.now()
        # The sequence number matters: a fixed clock and a single process make
        # every other component identical, so two retries of the same stage
        # would share an id and the second would look like an edit of the
        # first. Counting what is already recorded keeps ids unique without
        # reaching for a random component.
        sequence = sum(
            1
            for existing in self.store.current().values()
            if existing.run_id == run_id and existing.stage == stage
        )
        attempt_id = stable_id("att", run_id, stage, utc_isoformat(started), os.getpid(), sequence)
        safe_config = redact(config or {})
        base = {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "stage": stage,
            "config": safe_config,
            "code_hash": self.code_hash,
            "rng": dict(rng or {}),
        }

        self.store.append(
            Attempt(state=RunState.CREATED, recorded_at=started, **base)  # type: ignore[arg-type]
        )
        handle = AttemptHandle(
            run_id=run_id,
            attempt_id=attempt_id,
            stage=stage,
            started_monotonic=time.monotonic(),
            rng=dict(rng or {}),
        )
        self.store.append(
            Attempt(state=RunState.RUNNING, recorded_at=self.clock.now(), **base)  # type: ignore[arg-type]
        )

        def finish(state: RunState, *, kind: str = "", detail: str = "") -> None:
            self.store.append(
                Attempt(
                    state=state,
                    recorded_at=self.clock.now(),
                    contexts=tuple(handle.contexts),
                    inputs=tuple(handle.inputs),
                    outputs=tuple(handle.outputs),
                    warnings=tuple(handle.warnings),
                    elapsed_seconds=round(time.monotonic() - handle.started_monotonic, 6),
                    failure_kind=kind,
                    failure_detail=detail,
                    **base,  # type: ignore[arg-type]
                )
            )

        try:
            yield handle
        except KeyboardInterrupt:
            finish(RunState.CANCELLED, kind="interrupted")
            raise
        except BaseException as error:
            finish(
                RunState.FAILED,
                kind=type(error).__name__,
                detail=str(error)[:500],
            )
            raise
        else:
            elapsed = time.monotonic() - handle.started_monotonic
            if timeout_seconds is not None and elapsed > timeout_seconds:
                finish(
                    RunState.TIMED_OUT,
                    kind="timeout",
                    detail=f"took {elapsed:.1f}s against a {timeout_seconds:.1f}s budget",
                )
                raise RunTimeoutError(
                    "stage exceeded its wall-clock budget",
                    stage=stage,
                    elapsed_seconds=round(elapsed, 3),
                    budget_seconds=timeout_seconds,
                )
            finish(RunState.SUCCEEDED)
            log.info("run.attempt.succeeded", run_id=run_id, stage=stage)

    def recover(self, *, dry_run: bool = True) -> list[Attempt]:
        """Close out attempts whose process is gone.

        An attempt left ``running`` by a killed process is indistinguishable
        from one still working, unless the process is checked. On another host
        that check is meaningless, so those are reported and left alone rather
        than guessed at.
        """
        abandoned: list[Attempt] = []
        for attempt in self.store.unfinished():
            if not attempt.environment.same_host():
                continue
            if _process_alive(attempt.environment.pid):
                continue
            closed = attempt.model_copy(
                update={
                    "state": RunState.FAILED,
                    "recorded_at": self.clock.now(),
                    "failure_kind": "abandoned",
                    "failure_detail": (
                        "process ended without recording a terminal state; the "
                        "attempt is closed by recovery, not by the run"
                    ),
                }
            )
            abandoned.append(closed)
            if not dry_run:
                self.store.append(closed)
        return abandoned


def _process_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists and belongs to someone else.
        return True
    return True
