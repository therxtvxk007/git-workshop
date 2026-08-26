"""A small HTTP fetcher for public-data connectors.

Connectors need four things beyond ``httpx.get``: bounded retries with backoff,
polite pacing, an on-disk cache so re-running a backtest does not re-download a
year of files, and a proxy story. The cache is keyed by URL content hash and is
disposable -- deleting it costs bandwidth, never correctness.

**Proxies.** Many of the environments this will run in -- research networks,
CI, corporate egress, this project's own sandbox -- reach the internet only
through a proxy, and some intercept TLS with a private CA. The client therefore
reads the standard environment (``HTTP_PROXY``, ``HTTPS_PROXY``, ``ALL_PROXY``,
``NO_PROXY``, ``SSL_CERT_FILE``, ``SSL_CERT_DIR``) by default, and every part of
that is overridable from source config:

.. code-block:: yaml

    sources:
      gdelt:
        proxy: "socks5://127.0.0.1:1080"   # explicit; beats the environment
        trust_env: true                     # false to ignore the environment
        ca_bundle: /etc/ssl/corp-root.pem   # or verify: false, with a warning

SOCKS support comes from the ``httpx[socks]`` extra, which is a declared
dependency. Verification is never disabled implicitly: turning it off takes an
explicit ``verify: false`` and logs a warning every time a client is built.
"""

from __future__ import annotations

import ssl
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


class CaBundleError(HttpFetchError):
    """A configured ``ca_bundle`` cannot be used.

    Raised at client construction rather than on the first request, and always
    naming the path. OpenSSL's own message for this is
    ``[X509: NO_CERTIFICATE_OR_CRL_FOUND] no certificate or crl found``, which
    tells an operator who mistyped ``ca_bundle`` nothing about which file to go
    and look at.
    """


class ProxyPolicyError(HttpFetchError):
    """An egress proxy refused the destination.

    Arrives two ways, because a proxy can refuse at two moments: as a 403/407
    response to a plain request, or as a failed CONNECT while establishing the
    tunnel, which httpx surfaces as :class:`httpx.ProxyError`.

    Never retried either way. A policy denial is not a transient failure, and
    hammering it three more times changes nothing except how long the operator
    waits before learning which host needs allowlisting.
    """

    def __init__(self, url: str, detail: str) -> None:
        super().__init__(
            f"egress proxy refused {url} ({detail}). The destination host is not permitted "
            "by this network's policy. Ask for the host to be allowlisted; do not route "
            "around it or disable certificate verification."
        )
        self.url = url
        self.detail = detail


PROXY_DENIAL_MARKERS = ("403", "407", "forbidden", "proxy authentication")


def _is_policy_denial(error: Exception) -> bool:
    """Does this transport failure look like a refusal rather than a hiccup?"""
    if not isinstance(error, httpx.ProxyError):
        return False
    text = str(error).lower()
    return any(marker in text for marker in PROXY_DENIAL_MARKERS)


@dataclass
class HttpClient:
    """Retrying, rate-limited, proxy-aware, optionally caching HTTP client."""

    cache_dir: Path | None = None
    timeout_seconds: float = 60.0
    max_attempts: int = 4
    backoff_seconds: float = 2.0
    min_interval_seconds: float = 0.2
    user_agent: str = "pramaan-x-zero-base/0.1 (research; contact repository owner)"
    headers: Mapping[str, str] | None = None
    #: Explicit proxy URL (``http://``, ``https://``, ``socks5://``). Overrides
    #: the environment. ``None`` means "use whatever the environment says".
    proxy: str | None = None
    #: Read HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY / SSL_CERT_FILE.
    trust_env: bool = True
    #: Path to a CA bundle, for environments whose proxy terminates TLS.
    ca_bundle: str | None = None
    #: Disabling verification requires saying so, and says so in the log.
    verify: bool = True
    _last_request_at: float = 0.0
    _client: httpx.Client | None = None

    def _verify_setting(self) -> bool | ssl.SSLContext:
        if not self.verify:
            log.warning(
                "http.tls_verification_disabled",
                note="certificate verification is off for this client; set verify: true "
                "and supply ca_bundle instead wherever possible",
            )
            return False
        if self.ca_bundle:
            # An SSLContext rather than a path string: httpx deprecated the
            # latter, and building the context here surfaces a bad bundle
            # immediately instead of on the first request.
            bundle = Path(self.ca_bundle)
            if not bundle.exists():
                raise CaBundleError(f"ca_bundle {self.ca_bundle!r} does not exist")
            try:
                return ssl.create_default_context(cafile=self.ca_bundle)
            except ssl.SSLError as error:
                raise CaBundleError(
                    f"ca_bundle {self.ca_bundle!r} contains no certificates OpenSSL could "
                    f"load ({error}). Check the file is a PEM bundle and not empty."
                ) from error
        return True

    def client(self) -> httpx.Client:
        """The underlying client, built once and reused.

        Reuse matters beyond speed: one connection pool means the pacing below
        actually paces a single stream of requests.
        """
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                trust_env=self.trust_env,
                proxy=self.proxy,
                verify=self._verify_setting(),
                headers={"User-Agent": self.user_agent, **dict(self.headers or {})},
            )
            log.debug(
                "http.client_built",
                proxy=self.proxy or "<from environment>" if self.trust_env else "<none>",
                trust_env=self.trust_env,
                ca_bundle=self.ca_bundle,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

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

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            try:
                response = self.client().get(url)
                if response.status_code == 404:
                    raise NotFoundError(f"404 for {url}")
                if response.status_code in {403, 407}:
                    raise ProxyPolicyError(url, f"HTTP {response.status_code}")
                response.raise_for_status()
                data = response.content
                if cached is not None:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cached.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(cached)
                return data
            except (NotFoundError, ProxyPolicyError):
                raise
            except Exception as error:  # retried below; re-raised as HttpFetchError
                if _is_policy_denial(error):
                    raise ProxyPolicyError(url, str(error)) from error
                last_error = error
                if attempt == self.max_attempts:
                    break
                delay = self.backoff_seconds * (2 ** (attempt - 1))
                log.warning("http.retry", url=url, attempt=attempt, delay=delay, error=str(error))
                time.sleep(delay)
        raise HttpFetchError(
            f"failed to fetch {url} after {self.max_attempts} attempts: {last_error}"
        )
