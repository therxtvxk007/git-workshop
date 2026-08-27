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

import logging
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

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

    Arrives two ways: as an HTTP 407 from a proxy, or as a failed CONNECT while
    establishing the tunnel, which httpx surfaces as
    :class:`httpx.ProxyError`. An origin 403 is deliberately not classified as
    a proxy error.

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


class PermanentHttpError(HttpFetchError):
    """The origin rejected a request that retries cannot repair."""


DEFAULT_SECRET_QUERY_PARAMETERS = frozenset(
    {"api-key", "api_key", "apikey", "access_token", "token", "key"}
)


def redact_url(
    url: str, *, secret_query_parameters: frozenset[str] = DEFAULT_SECRET_QUERY_PARAMETERS
) -> str:
    """Return a log/cache-safe URL, matching query names case-insensitively."""
    try:
        parts = urlsplit(url)
        secrets = {name.casefold() for name in secret_query_parameters}
        query = [
            (name, "<redacted>" if name.casefold() in secrets else value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
        hostname = parts.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = hostname
        if parts.port is not None:
            netloc += f":{parts.port}"
        # Userinfo is never retained. Proxy URLs commonly carry credentials.
        if parts.username is not None:
            netloc = f"<redacted>@{netloc}"
        safe = urlunsplit(
            (parts.scheme, netloc, parts.path, urlencode(query, doseq=True), parts.fragment)
        )
        return safe.replace("\r", "").replace("\n", "")
    except (TypeError, ValueError):
        return "<redacted-url>"


def _secret_values(url: str, secret_query_parameters: frozenset[str]) -> set[str]:
    secrets = {name.casefold() for name in secret_query_parameters}
    try:
        return {
            value
            for name, value in parse_qsl(urlsplit(url).query, keep_blank_values=True)
            if name.casefold() in secrets and value
        }
    except (TypeError, ValueError):
        return set()


def sanitize_error_text(text: str, url: str, secret_query_parameters: frozenset[str]) -> str:
    safe = text
    for value in _secret_values(url, secret_query_parameters):
        for representation in {value, quote(value, safe=""), unquote(value)}:
            if representation:
                safe = safe.replace(representation, "<redacted>")
    # Exceptions often embed the complete request URL. Replacing both forms
    # prevents a malformed value from smuggling line breaks into structured logs.
    safe = safe.replace(url, redact_url(url, secret_query_parameters=secret_query_parameters))
    return safe.replace("\r", "\\r").replace("\n", "\\n")


def _retry_after_seconds(value: str | None, *, maximum: float) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return None
            seconds = (target.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return min(max(seconds, 0.0), maximum)


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
    max_retry_after_seconds: float = 60.0
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
            # httpx's INFO request line contains the complete query string. A
            # query-authenticated API would therefore bypass our redaction even
            # when every project log is safe. Keep transport libraries quiet;
            # project-owned retry/error logs below contain sanitized URLs.
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("httpcore").setLevel(logging.WARNING)
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
                proxy=(
                    redact_url(self.proxy)
                    if self.proxy
                    else "<from environment>"
                    if self.trust_env
                    else "<none>"
                ),
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

    def get(
        self,
        url: str,
        *,
        secret_query_parameters: frozenset[str] = DEFAULT_SECRET_QUERY_PARAMETERS,
        accepted_content_types: frozenset[str] | None = None,
    ) -> bytes:
        safe_url = redact_url(url, secret_query_parameters=secret_query_parameters)
        cache_identity = safe_url
        if accepted_content_types is not None:
            cache_identity += "|content-types=" + ",".join(sorted(accepted_content_types))
        cached = self._cache_path(cache_identity)
        if cached is not None and cached.exists():
            return cached.read_bytes()

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            try:
                response = self.client().get(url)
                if response.status_code == 404:
                    raise NotFoundError(f"404 for {safe_url}")
                if response.status_code == 407:
                    raise ProxyPolicyError(safe_url, "HTTP 407")
                if 400 <= response.status_code < 500 and response.status_code not in {408, 429}:
                    raise PermanentHttpError(
                        f"origin returned HTTP {response.status_code} for {safe_url}"
                    )
                response.raise_for_status()
                if accepted_content_types is not None:
                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                    if content_type not in accepted_content_types:
                        raise PermanentHttpError(
                            f"origin returned unexpected Content-Type "
                            f"{content_type or '<missing>'!r} for {safe_url}"
                        )
                data = response.content
                if cached is not None:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cached.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(cached)
                return data
            except (NotFoundError, PermanentHttpError, ProxyPolicyError):
                raise
            except Exception as error:  # retried below; re-raised as HttpFetchError
                if _is_policy_denial(error):
                    detail = sanitize_error_text(str(error), url, secret_query_parameters)
                    raise ProxyPolicyError(safe_url, detail) from None
                last_error = error
                if attempt == self.max_attempts:
                    break
                fallback = min(
                    self.backoff_seconds * (2 ** (attempt - 1)), self.max_retry_after_seconds
                )
                retry_after = None
                if isinstance(error, httpx.HTTPStatusError):
                    retry_after = _retry_after_seconds(
                        error.response.headers.get("Retry-After"),
                        maximum=self.max_retry_after_seconds,
                    )
                delay = fallback if retry_after is None else retry_after
                log.warning(
                    "http.retry",
                    url=safe_url,
                    attempt=attempt,
                    delay=delay,
                    error=sanitize_error_text(str(error), url, secret_query_parameters),
                )
                time.sleep(delay)
        safe_error = (
            sanitize_error_text(str(last_error), url, secret_query_parameters)
            if last_error is not None
            else "unknown error"
        )
        raise HttpFetchError(
            f"failed to fetch {safe_url} after {self.max_attempts} attempts: {safe_error}"
        )
