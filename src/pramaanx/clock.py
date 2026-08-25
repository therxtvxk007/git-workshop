"""Injectable clocks.

Wall-clock reads are hidden behind this interface so that runs are replayable.
A pipeline that calls ``datetime.now()`` in three places cannot be shown to be
deterministic, and a pipeline that cannot be shown deterministic cannot be
shown leak-free.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Real UTC time. The default in production paths."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock that does not move. Used by tests and reproducible bootstraps."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware instant")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant


class StepClock:
    """A clock that advances by a fixed step on every read.

    Useful where records need distinct but reproducible ``retrieved_at`` values.
    """

    def __init__(self, start: datetime, step: timedelta = timedelta(seconds=1)) -> None:
        if start.tzinfo is None:
            raise ValueError("StepClock requires a timezone-aware start")
        self._current = start.astimezone(UTC)
        self._step = step

    def now(self) -> datetime:
        value = self._current
        self._current = self._current + self._step
        return value
