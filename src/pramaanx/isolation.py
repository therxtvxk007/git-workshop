"""Structural isolation of outcome data from the forecasting pass.

The ordering rule -- forecasts are produced before outcomes are read -- was
previously enforced by the order of statements in one function. That is a
convention, and conventions survive exactly until someone adds a line in the
wrong place. Nothing about a leak announces itself; the run simply gets better.

So the rule is enforced by the runtime instead. During a forecasting pass, any
attempt to read outcome data raises :class:`OutcomeAccessError`. The guard
is a context variable, so it covers everything the pass calls, however deep,
without every layer having to know about it.

    with forecasting_pass("backtest"):
        ...                      # snapshots, generators, forecasts
        ledger.read_outcomes()   # -> OutcomeAccessError

This cannot stop a determined caller reading a Parquet file directly. It is not
meant to. It makes the mistake loud in the one place it is actually likely: a
future edit that innocently moves an outcome lookup earlier.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE_PASS: ContextVar[str | None] = ContextVar("pramaanx_forecasting_pass", default=None)


class OutcomeAccessError(RuntimeError):
    """Outcome data was read while forecasts were still being produced."""


@contextmanager
def forecasting_pass(label: str) -> Iterator[None]:
    """Mark a block as producing forecasts, sealing outcome data for its duration."""
    token = _ACTIVE_PASS.set(label)
    try:
        yield
    finally:
        _ACTIVE_PASS.reset(token)


def active_pass() -> str | None:
    """The label of the forecasting pass in progress, if any."""
    return _ACTIVE_PASS.get()


def in_forecasting_pass() -> bool:
    return _ACTIVE_PASS.get() is not None


def guard_outcome_access(operation: str) -> None:
    """Raise if ``operation`` would read or write outcome data mid-forecast."""
    label = _ACTIVE_PASS.get()
    if label is None:
        return
    raise OutcomeAccessError(
        f"{operation} was called during the {label!r} forecasting pass. Outcomes must not "
        "be built, read or written until forecasts for every cutoff have been produced and "
        "persisted; otherwise a backtest is scoring forecasts that could have seen their "
        "own answers."
    )
