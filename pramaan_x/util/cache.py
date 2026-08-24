"""Content-addressed cache.

Keyed by (namespace, content hash, model identity). Including model identity in
the key is the part people forget: a cached embedding from a superseded model
silently poisons every downstream comparison, and the failure is invisible.
"""

from __future__ import annotations

import pickle
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .hashing import content_hash


class ContentCache:
    def __init__(self, root: str | Path = ".cache/pramaan", *, enabled: bool = True) -> None:
        self.root = Path(root)
        self.enabled = enabled
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        if enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str, model: str) -> Path:
        digest = content_hash(namespace, key, model)
        d = self.root / namespace / digest[:2]
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{digest}.pkl"

    def get(self, namespace: str, key: str, model: str = "-") -> Any | None:
        if not self.enabled:
            return None
        p = self._path(namespace, key, model)
        if not p.exists():
            with self._lock:
                self.misses += 1
            return None
        try:
            with open(p, "rb") as fh:
                value = pickle.load(fh)
            with self._lock:
                self.hits += 1
            return value
        except Exception:
            p.unlink(missing_ok=True)
            with self._lock:
                self.misses += 1
            return None

    def put(self, namespace: str, key: str, value: Any, model: str = "-") -> None:
        if not self.enabled:
            return
        p = self._path(namespace, key, model)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            pickle.dump(value, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(p)

    def memoise(self, namespace: str, key: str, fn: Callable[[], Any], model: str = "-") -> Any:
        hit = self.get(namespace, key, model)
        if hit is not None:
            return hit
        value = fn()
        self.put(namespace, key, value, model)
        return value

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def stats(self) -> dict[str, Any]:
        return {"hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hit_rate, 4), "root": str(self.root)}
