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

import math
import re
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from pramaanx.hashing import hash_text, short_hash
from pramaanx.logging import get_logger

log = get_logger(__name__)

Fetcher = Callable[[str], bytes]
"""Anything that turns a URL into bytes. Injected in tests to stay offline."""

REDACTED = "REDACTED"

#: Query parameters whose *values* identify the caller and must never be logged,
#: persisted or put in an exception message. ``appname`` is ReliefWeb's required
#: caller identity and it travels in the URL, so every display path has to strip
#: it -- an exception string is as public as a log line.
SENSITIVE_QUERY_KEYS = ("appname", "api_key", "apikey", "key", "token", "access_token")

_SENSITIVE_QUERY = re.compile(
    r"(?i)\b(" + "|".join(re.escape(name) for name in SENSITIVE_QUERY_KEYS) + r")=[^&#]*"
)


def redact_url(url: str) -> str:
    """The display form of a URL: no caller identity, no credentials.

    Used for every log line, exception message and persisted provenance record.
    It never touches the URL that is actually requested or the string the cache
    is keyed on -- redacting those would either break the request or make two
    different callers collide in one cache entry.
    """
    if not url:
        return url
    redacted = _SENSITIVE_QUERY.sub(lambda match: f"{match.group(1)}={REDACTED}", url)
    return _redact_userinfo(redacted)


def _redact_userinfo(url: str) -> str:
    """``https://user:pass@host/x`` -> ``https://REDACTED@host/x``."""
    try:
        parts = urlsplit(url)
    except ValueError:  # pragma: no cover - urlsplit is very forgiving
        return url
    if not parts.hostname or "@" not in parts.netloc:
        return url
    host = parts.hostname
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    netloc = f"{REDACTED}@{host}"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def redact_proxy(proxy: str | None) -> str | None:
    """A proxy URL safe to log. ``socks5://user:pass@host`` hides the userinfo."""
    if not proxy:
        return proxy
    return _redact_userinfo(proxy)


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


class RateLimitError(HttpFetchError):
    """The server asked the caller to slow down (HTTP 429), and it kept asking.

    Retried with the server's own ``Retry-After`` when it supplies one, because
    guessing a backoff against a service that has just told you the answer is
    both rude and slower.
    """

    def __init__(self, url: str, attempts: int) -> None:
        super().__init__(
            f"{redact_url(url)} returned HTTP 429 on {attempts} consecutive attempts. Lower "
            "page_size, raise min_interval_seconds, or narrow the fetch window."
        )
        self.url = redact_url(url)
        self.attempts = attempts


class PermanentHttpError(HttpFetchError):
    """The destination answered, and the answer will not change on a retry.

    HTTP 401 and 403 *from the origin*: the request was delivered and refused.
    Kept distinct from :class:`ProxyPolicyError` because the two have opposite
    meanings and opposite remedies. A proxy denial means the request never left
    the network and the host needs allowlisting; an origin 403 means the
    destination rejected the caller. Source-specific remediation belongs in the
    connector or its live test; this shared client is also used by GDELT and
    future sources.

    Conflating them is not cosmetic. The live test skips on a proxy denial, so
    an origin 403 filed under the same class would turn "ReliefWeb rejected our
    identity" into "verification skipped", and the run would look clean.
    """

    def __init__(self, url: str, status_code: int, detail: str = "") -> None:
        remedy = {
            401: "The API rejected the caller's credentials.",
            403: "The destination refused this caller or request.",
        }.get(status_code, "The server refused this request and a retry will not change that.")
        super().__init__(
            f"{redact_url(url)} returned HTTP {status_code}. {remedy}"
            + (f" ({detail})" if detail else "")
        )
        self.url = redact_url(url)
        self.status_code = status_code
        self.detail = detail


class ProxyPolicyError(HttpFetchError):
    """An egress proxy refused to carry the request.

    Two shapes, both of which mean the request never reached the destination:
    an HTTP 407 (proxy authentication required) response, or a failed CONNECT
    while establishing the tunnel, which httpx surfaces as
    :class:`httpx.ProxyError`.

    An ordinary 403 *response* is deliberately NOT one of these -- that is an
    answer from the origin, and it is :class:`PermanentHttpError`. A proxy that
    denies at CONNECT time cannot produce an HTTP response at all, which is why
    its denial arrives as a transport error rather than a status code.

    Never retried either way. A policy denial is not a transient failure, and
    hammering it three more times changes nothing except how long the operator
    waits before learning which host needs allowlisting.
    """

    def __init__(self, url: str, detail: str) -> None:
        super().__init__(
            f"egress proxy refused {redact_url(url)} ({redact_url(detail)}). The destination "
            "host is not permitted by this network's policy. Ask for the host to be "
            "allowlisted; do not route around it or disable certificate verification."
        )
        self.url = redact_url(url)
        self.detail = redact_url(detail)


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
    #: Ceiling on a server-supplied ``Retry-After``. A 429 is an instruction,
    #: but an unbounded one is a denial of service by cooperation: a header of
    #: 86400 would park an ingest for a day inside a retry loop nobody watches.
    #: Applies to both the delta-seconds and the HTTP-date form, and to the
    #: exponential fallback, so no path can sleep longer than this.
    max_retry_after_seconds: float = 60.0
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
                # Never the raw proxy URL: a proxy string routinely carries
                # userinfo credentials, and a debug log is not a secret store.
                proxy=redact_proxy(self.proxy) or "<from environment>"
                if self.trust_env
                else "<none>",
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

    def _clamp_delay(self, seconds: float) -> float:
        """Never negative, never longer than ``max_retry_after_seconds``.

        Every delay this client sleeps for goes through here, including the
        exponential fallback: a cap that only covers the header would still let
        a long backoff on a high attempt number park the process.
        """
        if not math.isfinite(seconds):
            return self.max_retry_after_seconds
        return min(max(0.0, seconds), self.max_retry_after_seconds)

    def _backoff_seconds_for(self, attempt: int) -> float:
        return self._clamp_delay(self.backoff_seconds * (2 ** (attempt - 1)))

    def _retry_after_seconds(self, response: httpx.Response, attempt: int) -> float:
        """Honour ``Retry-After`` when present, else fall back to the backoff.

        The header comes in two forms -- delta-seconds and an HTTP date -- and
        both appear in the wild. Both are clamped: the server is telling us how
        long *it* wants to wait, which is not the same as how long this process
        may block, and the header is attacker-influenced on any hop that can
        rewrite responses.
        """
        raw = response.headers.get("Retry-After", "").strip()
        fallback = self._backoff_seconds_for(attempt)
        if not raw:
            return fallback
        try:
            return self._clamp_delay(float(raw))
        except ValueError:
            pass
        try:
            target = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return fallback
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return self._clamp_delay((target - datetime.now(UTC)).total_seconds())

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
                    raise NotFoundError(f"404 for {redact_url(url)}")
                if response.status_code == 407:
                    # Proxy authentication required: the proxy answered, so the
                    # request never reached the destination.
                    raise ProxyPolicyError(url, "HTTP 407")
                if response.status_code in {401, 403}:
                    # The ORIGIN answered and refused. Not a proxy denial: a
                    # proxy that refuses cannot return the destination's status.
                    raise PermanentHttpError(url, response.status_code)
                if response.status_code == 429:
                    if attempt == self.max_attempts:
                        raise RateLimitError(url, attempt)
                    delay = self._retry_after_seconds(response, attempt)
                    log.warning(
                        "http.rate_limited",
                        url=redact_url(url),
                        attempt=attempt,
                        delay=round(delay, 3),
                    )
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                data = response.content
                if cached is not None:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cached.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(cached)
                return data
            except (NotFoundError, PermanentHttpError, ProxyPolicyError, RateLimitError):
                raise
            except Exception as error:  # retried below; re-raised as HttpFetchError
                if _is_policy_denial(error):
                    raise ProxyPolicyError(url, str(error)) from error
                last_error = error
                if attempt == self.max_attempts:
                    break
                delay = self._backoff_seconds_for(attempt)
                log.warning(
                    "http.retry",
                    url=redact_url(url),
                    attempt=attempt,
                    delay=delay,
                    error=redact_url(str(error)),
                )
                time.sleep(delay)
        raise HttpFetchError(
            f"failed to fetch {redact_url(url)} after {self.max_attempts} attempts: "
            f"{redact_url(str(last_error))}"
        )
