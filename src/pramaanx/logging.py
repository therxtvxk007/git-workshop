"""Structured logging.

Log records are part of the audit trail: they carry snapshot and cutoff context
so a suspicious forecast can be traced back to the evidence that produced it.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

_CONFIGURED = False


class _LazyStderr:
    """A writer that resolves ``sys.stderr`` on every call.

    Binding the stream object at configuration time looks harmless and is not:
    anything that replaces ``sys.stderr`` afterwards -- a CLI reconfiguring
    logging in-process, a supervisor redirecting output, a test harness swapping
    capture buffers between cases -- leaves the logger holding a handle to a
    stream that is later closed, and the next log line raises
    ``ValueError: I/O operation on closed file``. A logger that can crash the
    program it is describing is worse than no logger.
    """

    def write(self, message: str) -> int:
        return sys.stderr.write(message)

    def flush(self) -> None:
        sys.stderr.flush()

    def isatty(self) -> bool:
        try:
            return sys.stderr.isatty()
        except (AttributeError, ValueError):
            return False


_STDERR = _LazyStderr()


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Configure structlog. Safe to call more than once per process."""
    global _CONFIGURED
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=_STDERR,
        level=numeric_level,
        force=True,
    )

    renderer: Any = (
        structlog.processors.JSONRenderer(sort_keys=True)
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=_STDERR.isatty())
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(_STDERR),  # type: ignore[arg-type]
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)


@contextmanager
def log_context(**bindings: Any) -> Iterator[None]:
    """Bind run context (snapshot id, cutoff, generator) for the enclosed block."""
    tokens = structlog.contextvars.bind_contextvars(**bindings)
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
