"""Structured logging.

JSON lines by default, because these logs are read by machines far more often
than by people: drift monitoring, latency percentiles, and the cascade-reduction
figures all come out of this stream. A human-readable formatter is available for
interactive work.

Every record carries the run id, so a log line found six months later can be
tied back to the config fingerprint and dataset manifest that produced it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any

_RUN_ID = os.environ.get("PRAMAAN_RUN_ID") or uuid.uuid4().hex[:12]
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "run_id": _RUN_ID,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = " ".join(
            f"{k}={v}" for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        )
        base = (f"{time.strftime('%H:%M:%S', time.localtime(record.created))} "
                f"{record.levelname:<7} {record.name:<28} {record.getMessage()}")
        return f"{base}  {extras}" if extras else base


def configure(level: str = "INFO", *, json_output: bool | None = None,
              stream=None) -> None:
    """Idempotent. Safe to call from a library entry point or a test."""
    if json_output is None:
        json_output = not sys.stderr.isatty()
    root = logging.getLogger("pramaan_x")
    root.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter() if json_output else HumanFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False


def safe_extra(fields: dict[str, Any]) -> dict[str, Any]:
    """Rename fields that collide with LogRecord's own attributes.

    `logging` raises KeyError when `extra` contains a reserved key such as
    `name`, `module` or `filename`. Those are entirely natural things to want to
    log, so the collision is resolved here rather than left as a trap that fires
    at the first call site to log a field called `name`.
    """
    out: dict[str, Any] = {}
    for k, v in fields.items():
        out[f"{k}_" if k in _RESERVED else k] = v
    return out


class _SafeAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        if kwargs.get("extra"):
            kwargs["extra"] = safe_extra(kwargs["extra"])
        return msg, kwargs


def get_logger(name: str) -> logging.Logger:
    """Returns an adapter that sanitises `extra` before it reaches logging."""
    return _SafeAdapter(logging.getLogger(f"pramaan_x.{name}"), {})


def run_id() -> str:
    return _RUN_ID


@contextmanager
def timed(logger: logging.Logger | logging.LoggerAdapter, stage: str, **fields: Any):
    """Emit a duration for a stage. Used at every cascade boundary so the
    narrowing figures and the per-stage cost come from the same source."""
    t0 = time.perf_counter()
    logger.info(f"{stage} start", extra={"stage": stage, "phase": "start", **fields})
    try:
        yield
    except Exception:
        logger.exception(f"{stage} failed",
                         extra={"stage": stage, "phase": "error",
                                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)})
        raise
    else:
        logger.info(f"{stage} done",
                    extra={"stage": stage, "phase": "end",
                           "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                           **fields})
