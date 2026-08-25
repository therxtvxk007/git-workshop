"""A small HTTP fetcher for public-data connectors.

Connectors need three things beyond ``httpx.get``: bounded retries with
backoff, polite pacing, and an on-disk cache so that re-running a backtest does
not re-download a year of files. The cache is keyed by URL content hash and is
disposable -- deleting it costs bandwidth, never correctness.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from pramaanx.hashing import hash_text, short_hash
from pramaanx.logging import get_logger

log = get_logger(__name__)

Fetcher = Callable[[str], bytes]
"""Anything that turns a URL into bytes. Injected in tests to stay offline."""


class HttpFetchError(RuntimeError):
    """A URL could not be fetched after the configured retries."""


class NotFoundError(HttpFetchError):
    """The resource does not exist (HTTP 404).

    Distinguished from transient failures because a missing 15-minute file is a
    normal gap in an archive, while a timeout is not.
    """


@dataclass
class HttpClient:
    """Retrying, rate-limited, optionally caching HTTP client."""

    cache_dir: Path | None = None
    timeout_seconds: float = 60.0
    max_attempts: int = 4
    backoff_seconds: float = 2.0
    min_interval_seconds: float = 0.2
    user_agent: str = "pramaan-x-zero-base/0.1 (research; contact repository owner)"
    headers: Mapping[str, str] | None = None
    _last_request_at: float = 0.0

    def _cache_path(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = short_hash(hash_text(url), 24)
        return self.cache_dir / digest[:2] / f"{digest}.bin"

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def get(self, url: str) -> bytes:
        cached = self._cache_path(url)
        if cached is not None and cached.exists():
            return cached.read_bytes()

        headers = {"User-Agent": self.user_agent, **dict(self.headers or {})}
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            try:
                response = httpx.get(
                    url, timeout=self.timeout_seconds, headers=headers, follow_redirects=True
                )
                if response.status_code == 404:
                    raise NotFoundError(f"404 for {url}")
                response.raise_for_status()
                data = response.content
                if cached is not None:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cached.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(cached)
                return data
            except NotFoundError:
                raise
            except Exception as error:  # retried below; re-raised as HttpFetchError
                last_error = error
                if attempt == self.max_attempts:
                    break
                delay = self.backoff_seconds * (2 ** (attempt - 1))
                log.warning("http.retry", url=url, attempt=attempt, delay=delay, error=str(error))
                time.sleep(delay)
        raise HttpFetchError(
            f"failed to fetch {url} after {self.max_attempts} attempts: {last_error}"
        )
