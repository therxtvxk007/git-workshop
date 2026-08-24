"""Experiment tracking.

MLflow when it is reachable, a local JSONL run store otherwise. The fallback is
not a stub: it records the same parameters, metrics, tags and artefact paths to
disk, so a run made on a laptop with no tracking server is still reproducible and
still comparable. What it does not give you is the UI.

Every run automatically carries the config fingerprint, the dataset manifest
hash and the git commit. Those three together are what makes a metric mean
something; a run without them is a number in a chat window.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .util.logging import get_logger, run_id

log = get_logger("tracking")


class Tracker(Protocol):
    def start_run(self, name: str, tags: dict[str, str] | None = None) -> str: ...
    def log_params(self, params: dict[str, Any]) -> None: ...
    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None: ...
    def log_artifact(self, path: str | Path, kind: str = "file") -> None: ...
    def end_run(self, status: str = "FINISHED") -> None: ...


@dataclass
class LocalTracker:
    """JSONL run store. One directory per run, one line per event."""

    root: Path = field(default_factory=lambda: Path("artifacts/runs"))
    _run_dir: Path | None = None
    _run_id: str | None = None

    def start_run(self, name: str, tags: dict[str, str] | None = None) -> str:
        self._run_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{run_id()}"
        self._run_dir = self.root / self._run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._write("meta", {"name": name, "tags": tags or {},
                             "started_at": time.time(), "run_id": self._run_id})
        log.info("run started", extra={"run": self._run_id, "run_name": name})
        return self._run_id

    def log_params(self, params: dict[str, Any]) -> None:
        self._write("params", params)

    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        self._write("metrics", {"step": step, **{k: _num(v) for k, v in metrics.items()}})

    def log_artifact(self, path: str | Path, kind: str = "file") -> None:
        self._write("artifact", {"path": str(Path(path).resolve()), "kind": kind})

    def end_run(self, status: str = "FINISHED") -> None:
        self._write("end", {"status": status, "ended_at": time.time()})
        log.info("run ended", extra={"run": self._run_id, "status": status})

    def _write(self, kind: str, payload: dict[str, Any]) -> None:
        if self._run_dir is None:
            raise RuntimeError("start_run must be called first")
        line = json.dumps({"kind": kind, "ts": time.time(), **payload}, default=str)
        with open(self._run_dir / "events.jsonl", "a") as fh:
            fh.write(line + "\n")

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Read back past runs -- the minimum needed to compare two experiments
        without a server."""
        out: list[dict[str, Any]] = []
        if not self.root.exists():
            return out
        for d in sorted(self.root.iterdir(), reverse=True)[:limit]:
            f = d / "events.jsonl"
            if not f.exists():
                continue
            events = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
            meta = next((e for e in events if e["kind"] == "meta"), {})
            metrics: dict[str, Any] = {}
            for e in events:
                if e["kind"] == "metrics":
                    metrics.update({k: v for k, v in e.items()
                                    if k not in ("kind", "ts", "step")})
            out.append({"run_id": d.name, "name": meta.get("name"),
                        "tags": meta.get("tags", {}), "metrics": metrics})
        return out


@dataclass
class MlflowTracker:
    uri: str = "http://localhost:5000"
    experiment: str = "pramaan-x"
    _mlflow: Any = None
    _active: Any = None

    def _connect(self):
        if self._mlflow is None:
            import mlflow

            mlflow.set_tracking_uri(self.uri)
            mlflow.set_experiment(self.experiment)
            self._mlflow = mlflow
        return self._mlflow

    def start_run(self, name: str, tags: dict[str, str] | None = None) -> str:
        mlflow = self._connect()
        self._active = mlflow.start_run(run_name=name, tags=tags or {})
        return self._active.info.run_id

    def log_params(self, params: dict[str, Any]) -> None:
        mlflow = self._connect()
        # MLflow rejects long values; the full config lives in the artefact.
        mlflow.log_params({k: str(v)[:500] for k, v in _flatten(params).items()})

    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        mlflow = self._connect()
        clean = {k: _num(v) for k, v in metrics.items() if _num(v) is not None}
        mlflow.log_metrics(clean, step=step)

    def log_artifact(self, path: str | Path, kind: str = "file") -> None:
        self._connect().log_artifact(str(path))

    def end_run(self, status: str = "FINISHED") -> None:
        self._connect().end_run(status=status)
        self._active = None


def build_tracker(kind: str = "local", *, uri: str = "http://localhost:5000",
                  experiment: str = "pramaan-x", root: str = "artifacts/runs") -> Tracker:
    """Falls back to local on any MLflow failure.

    A tracking outage must never fail a forecast run. Losing the record is bad;
    losing the forecast because the record could not be written is worse.
    """
    if kind == "mlflow":
        try:
            t = MlflowTracker(uri=uri, experiment=experiment)
            t._connect()
            return t
        except Exception as exc:
            log.warning("mlflow unavailable, falling back to local tracker",
                        extra={"error": str(exc)[:200], "uri": uri})
    return LocalTracker(root=Path(root))


def _num(v: Any) -> float | None:
    import math

    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out |= _flatten(v, f"{key}.")
        else:
            out[key] = v
    return out
