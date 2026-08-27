"""The HTTP fetcher: caching, retries, proxy configuration and policy denials."""

from __future__ import annotations

import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

import certifi
import httpx
import pytest

from pramaanx.ingest.http import (
    CaBundleError,
    HttpClient,
    HttpFetchError,
    NotFoundError,
    PermanentHttpError,
    ProxyPolicyError,
    RateLimitError,
    _is_policy_denial,
    redact_proxy,
    redact_url,
)


class TestProxyConfiguration:
    def test_environment_is_trusted_by_default(self) -> None:
        # HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY / SSL_CERT_FILE are
        # how every other tool on a restricted network is configured.
        client = HttpClient()
        assert client.trust_env is True
        assert client.proxy is None
        assert client.client().trust_env is True

    def test_explicit_proxy_overrides_the_environment(self) -> None:
        client = HttpClient(proxy="http://127.0.0.1:3128", trust_env=False)
        assert client.client()._mounts  # a proxy transport is mounted
        client.close()

    def test_socks_proxies_are_supported(self) -> None:
        # Requires the httpx[socks] extra; a missing socksio raises here.
        client = HttpClient(proxy="socks5://127.0.0.1:1080")
        assert client.client() is not None
        client.close()

    def test_ca_bundle_becomes_an_ssl_context(self, tmp_path: Path) -> None:
        # httpx deprecated verify=<str>; building the context here also means a
        # bad bundle fails at construction rather than on the first request.
        #
        # The fixture bundle comes from certifi, not from
        # ssl.get_default_verify_paths(). That attribute describes the *host's*
        # trust configuration, and on a uv-managed standalone CPython -- which is
        # what CI installs -- its cafile is None. An earlier version of this test
        # fell back to /dev/null, wrote an empty bundle, and then asserted that a
        # context built from no certificates was an SSLContext. It passed on a
        # system interpreter and failed on CI's, which is a test describing its
        # environment rather than its subject.
        bundle = tmp_path / "ca.pem"
        bundle.write_bytes(Path(certifi.where()).read_bytes())
        assert b"BEGIN CERTIFICATE" in bundle.read_bytes(), "fixture bundle has no certificates"

        client = HttpClient(ca_bundle=str(bundle))
        assert isinstance(client._verify_setting(), ssl.SSLContext)

    def test_the_fixture_bundle_does_not_depend_on_host_trust_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The good-path test must not care how the machine is configured.

        Emulates the CI interpreter: no SSL_CERT_FILE, and a default verify path
        with no cafile at all.
        """
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("SSL_CERT_DIR", raising=False)
        monkeypatch.setattr(
            ssl,
            "get_default_verify_paths",
            lambda: ssl.DefaultVerifyPaths(None, None, "", "", "", ""),
        )
        bundle = tmp_path / "ca.pem"
        bundle.write_bytes(Path(certifi.where()).read_bytes())
        assert isinstance(HttpClient(ca_bundle=str(bundle))._verify_setting(), ssl.SSLContext)

    def test_an_empty_bundle_is_rejected_at_construction(self, tmp_path: Path) -> None:
        # The failure that actually reached CI. Nothing tested it, because the
        # good-path test was accidentally exercising it.
        bundle = tmp_path / "empty.pem"
        bundle.write_bytes(b"")
        with pytest.raises(CaBundleError, match="contains no certificates"):
            HttpClient(ca_bundle=str(bundle))._verify_setting()

    def test_a_malformed_bundle_is_rejected_at_construction(self, tmp_path: Path) -> None:
        bundle = tmp_path / "junk.pem"
        bundle.write_text("not a certificate\n")
        with pytest.raises(CaBundleError, match="contains no certificates"):
            HttpClient(ca_bundle=str(bundle))._verify_setting()

    def test_a_missing_bundle_is_rejected_at_construction(self, tmp_path: Path) -> None:
        with pytest.raises(CaBundleError, match="does not exist"):
            HttpClient(ca_bundle=str(tmp_path / "absent.pem"))._verify_setting()

    def test_the_rejection_names_the_path(self, tmp_path: Path) -> None:
        # "no certificate or crl found" with no path is what an operator saw
        # before; it says nothing about which bundle to go and look at.
        bundle = tmp_path / "empty.pem"
        bundle.write_bytes(b"")
        with pytest.raises(CaBundleError, match=str(bundle)):
            HttpClient(ca_bundle=str(bundle))._verify_setting()

    def test_disabling_verification_is_explicit(self) -> None:
        assert HttpClient(verify=False)._verify_setting() is False

    def test_verification_is_on_by_default(self) -> None:
        assert HttpClient()._verify_setting() is True

    def test_client_is_reused(self) -> None:
        client = HttpClient()
        assert client.client() is client.client()
        client.close()


class TestPolicyDenials:
    def test_connect_time_denial_is_recognised(self) -> None:
        assert _is_policy_denial(httpx.ProxyError("403 Forbidden"))
        assert _is_policy_denial(httpx.ProxyError("407 Proxy Authentication Required"))

    def test_ordinary_transport_errors_are_not_denials(self) -> None:
        assert not _is_policy_denial(httpx.ProxyError("connection reset"))
        assert not _is_policy_denial(httpx.ConnectTimeout("timed out"))

    def test_denials_are_not_retried(self, tmp_path: Path) -> None:
        attempts = 0

        def deny(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ProxyError("403 Forbidden")

        client = HttpClient(cache_dir=tmp_path, max_attempts=4, backoff_seconds=0.0)
        client._client = httpx.Client(transport=httpx.MockTransport(deny))
        with pytest.raises(ProxyPolicyError, match="not permitted by this network's policy"):
            client.get("https://example.org/blocked")
        # Retrying a policy denial only delays the operator learning about it.
        assert attempts == 1

    def test_407_response_is_a_policy_denial(self, tmp_path: Path) -> None:
        # Proxy authentication required: the proxy answered, so the request
        # never reached the destination.
        client = HttpClient(cache_dir=tmp_path, max_attempts=2, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(407))
        )
        with pytest.raises(ProxyPolicyError):
            client.get("https://example.org/blocked")


class TestOriginRefusalIsNotAProxyDenial:
    """An origin 403 must fail a verification, not skip it.

    The live ReliefWeb test skips on ProxyPolicyError. While an ordinary 403
    response was classified as one, an unapproved appname -- which ReliefWeb
    refuses at the origin with a 403 -- would have been reported as "egress
    blocked, skipped" and the run would have looked clean.
    """

    def _client(self, tmp_path: Path, status: int) -> HttpClient:
        client = HttpClient(cache_dir=tmp_path, max_attempts=3, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status))
        )
        return client

    def test_origin_403_is_a_permanent_http_error(self, tmp_path: Path) -> None:
        with pytest.raises(PermanentHttpError) as caught:
            self._client(tmp_path, 403).get("https://api.reliefweb.int/v2/reports")
        assert caught.value.status_code == 403
        assert not isinstance(caught.value, ProxyPolicyError)

    def test_the_shared_403_message_is_source_neutral(self, tmp_path: Path) -> None:
        with pytest.raises(PermanentHttpError, match="destination refused") as caught:
            self._client(tmp_path, 403).get("https://example.org/private")
        assert "ReliefWeb" not in str(caught.value)
        assert "appname" not in str(caught.value)

    def test_origin_401_is_a_permanent_http_error(self, tmp_path: Path) -> None:
        with pytest.raises(PermanentHttpError) as caught:
            self._client(tmp_path, 401).get("https://example.org/private")
        assert caught.value.status_code == 401

    def test_a_permanent_refusal_is_not_retried(self, tmp_path: Path) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(403)

        client = HttpClient(cache_dir=tmp_path, max_attempts=4, backoff_seconds=0.0)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(PermanentHttpError):
            client.get("https://example.org/refused")
        assert attempts == 1

    def test_connect_time_denial_is_still_a_proxy_policy_error(self, tmp_path: Path) -> None:
        # A proxy that refuses at CONNECT cannot return the destination's
        # status, so its denial arrives as a transport error. That one IS a
        # policy denial, and the live test may skip on it.
        def deny(request: httpx.Request) -> httpx.Response:
            raise httpx.ProxyError("403 Forbidden from the gateway")

        client = HttpClient(cache_dir=tmp_path, max_attempts=3, backoff_seconds=0.0)
        client._client = httpx.Client(transport=httpx.MockTransport(deny))
        with pytest.raises(ProxyPolicyError):
            client.get("https://api.reliefweb.int/v2/reports")

    def test_the_three_cases_are_distinguishable_by_type(self, tmp_path: Path) -> None:
        def deny(request: httpx.Request) -> httpx.Response:
            raise httpx.ProxyError("407 proxy authentication required")

        connect = HttpClient(cache_dir=tmp_path, max_attempts=1, backoff_seconds=0.0)
        connect._client = httpx.Client(transport=httpx.MockTransport(deny))

        with pytest.raises(ProxyPolicyError):
            connect.get("https://example.org/x")
        with pytest.raises(ProxyPolicyError):
            self._client(tmp_path, 407).get("https://example.org/x")
        with pytest.raises(PermanentHttpError):
            self._client(tmp_path, 403).get("https://example.org/x")


class TestFetching:
    def _client(self, tmp_path: Path, handler: object) -> HttpClient:
        client = HttpClient(cache_dir=tmp_path, max_attempts=3, backoff_seconds=0.0)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        return client

    def test_successful_fetch_is_cached(self, tmp_path: Path) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, content=b"payload")

        client = self._client(tmp_path, handler)
        assert client.get("https://example.org/a") == b"payload"
        assert client.get("https://example.org/a") == b"payload"
        assert calls == 1

    def test_404_is_distinct_from_a_transient_failure(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, lambda request: httpx.Response(404))
        with pytest.raises(NotFoundError):
            client.get("https://example.org/missing")

    def test_transient_failures_are_retried_then_reported(self, tmp_path: Path) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectTimeout("timed out")

        client = self._client(tmp_path, handler)
        with pytest.raises(HttpFetchError, match="after 3 attempts"):
            client.get("https://example.org/flaky")
        assert attempts == 3

    def test_a_retry_can_succeed(self, tmp_path: Path) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectTimeout("timed out")
            return httpx.Response(200, content=b"recovered")

        client = self._client(tmp_path, handler)
        assert client.get("https://example.org/flaky") == b"recovered"


class TestRateLimiting:
    """429 is an instruction, not a failure: honour Retry-After when given."""

    def _client(self, tmp_path: Path, handler: object, **kwargs: object) -> HttpClient:
        kwargs.setdefault("backoff_seconds", 0.0)
        client = HttpClient(cache_dir=tmp_path, **kwargs)  # type: ignore[arg-type]
        client._client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        return client

    def test_a_429_is_retried_and_can_succeed(self, tmp_path: Path) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, content=b"recovered")

        assert (
            self._client(tmp_path, handler, max_attempts=3).get("https://example.org/x")
            == b"recovered"
        )
        assert attempts == 2

    def test_persistent_429_raises_an_actionable_error(self, tmp_path: Path) -> None:
        client = self._client(
            tmp_path,
            lambda request: httpx.Response(429, headers={"Retry-After": "0"}),
            max_attempts=2,
        )
        with pytest.raises(RateLimitError, match=r"[Ll]ower page_size"):
            client.get("https://example.org/x")

    def test_retry_after_seconds_is_honoured(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, lambda request: httpx.Response(200))
        response = httpx.Response(429, headers={"Retry-After": "7"})
        assert client._retry_after_seconds(response, attempt=1) == 7.0

    def test_retry_after_http_date_is_honoured(self, tmp_path: Path) -> None:
        from email.utils import format_datetime

        client = self._client(tmp_path, lambda request: httpx.Response(200))
        future = datetime.now(UTC) + timedelta(seconds=30)
        response = httpx.Response(429, headers={"Retry-After": format_datetime(future)})
        assert 20.0 < client._retry_after_seconds(response, attempt=1) <= 31.0

    def test_a_past_retry_after_date_does_not_sleep_backwards(self, tmp_path: Path) -> None:
        from email.utils import format_datetime

        client = self._client(tmp_path, lambda request: httpx.Response(200))
        past = datetime.now(UTC) - timedelta(seconds=60)
        response = httpx.Response(429, headers={"Retry-After": format_datetime(past)})
        assert client._retry_after_seconds(response, attempt=1) == 0.0

    def test_a_garbage_retry_after_falls_back_to_backoff(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, lambda request: httpx.Response(200), backoff_seconds=2.0)
        response = httpx.Response(429, headers={"Retry-After": "soon"})
        assert client._retry_after_seconds(response, attempt=2) == 4.0

    def test_no_retry_after_falls_back_to_backoff(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, lambda request: httpx.Response(200), backoff_seconds=1.5)
        assert client._retry_after_seconds(httpx.Response(429), attempt=1) == 1.5


class Recorder:
    """A stand-in logger that keeps what would have been written."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def _record(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))

    debug = info = warning = error = _record

    def field(self, event: str, key: str) -> object:
        for name, fields in self.events:
            if name == event and key in fields:
                return fields[key]
        raise AssertionError(f"no {event}.{key} was logged; got {self.events}")

    def text(self) -> str:
        return repr(self.events)


SECRET_URL = "https://api.reliefweb.int/v2/reports?appname=secret-identity&limit=5"


class TestRedaction:
    """The appname travels in the URL, so every display path has to strip it."""

    def test_the_query_value_is_replaced_not_merely_hidden(self) -> None:
        assert redact_url(SECRET_URL) == (
            "https://api.reliefweb.int/v2/reports?appname=REDACTED&limit=5"
        )

    def test_other_parameters_survive(self) -> None:
        assert "limit=5" in redact_url(SECRET_URL)

    def test_url_userinfo_is_removed(self) -> None:
        assert redact_url("https://user:pass@example.org/x") == "https://REDACTED@example.org/x"
        assert "pass" not in redact_url("https://user:pass@example.org/x")

    def test_userinfo_and_port_survive_together(self) -> None:
        assert (
            redact_url("https://user:pass@example.org:8443/x")
            == "https://REDACTED@example.org:8443/x"
        )

    def test_proxy_credentials_are_removed(self) -> None:
        assert redact_proxy("socks5://user:pass@127.0.0.1:1080") == (
            "socks5://REDACTED@127.0.0.1:1080"
        )
        assert redact_proxy(None) is None

    def test_a_clean_url_is_unchanged(self) -> None:
        assert redact_url("https://example.org/a?b=1") == "https://example.org/a?b=1"

    def test_the_real_request_url_is_not_altered(self, tmp_path: Path) -> None:
        # Redaction is for display only. Redacting the requested URL would
        # break the request; redacting the cache key would make two callers
        # collide in one entry.
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=b"ok")

        client = HttpClient(cache_dir=tmp_path, max_attempts=1, backoff_seconds=0.0)
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        client.get(SECRET_URL)
        assert "secret-identity" in seen[0]

    def test_cache_identity_still_separates_two_callers(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path)
        first = client._cache_path("https://x/y?appname=one")
        second = client._cache_path("https://x/y?appname=two")
        assert first != second

    def test_rate_limit_error_is_redacted(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path, max_attempts=1, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(429))
        )
        with pytest.raises(RateLimitError) as caught:
            client.get(SECRET_URL)
        assert "secret-identity" not in str(caught.value)
        assert "appname=REDACTED" in str(caught.value)

    def test_permanent_http_error_is_redacted(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path, max_attempts=1, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(403))
        )
        with pytest.raises(PermanentHttpError) as caught:
            client.get(SECRET_URL)
        assert "secret-identity" not in str(caught.value)

    def test_not_found_error_is_redacted(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path, max_attempts=1, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404))
        )
        with pytest.raises(NotFoundError) as caught:
            client.get(SECRET_URL)
        assert "secret-identity" not in str(caught.value)

    def test_proxy_policy_error_is_redacted(self, tmp_path: Path) -> None:
        def deny(request: httpx.Request) -> httpx.Response:
            raise httpx.ProxyError("403 Forbidden")

        client = HttpClient(cache_dir=tmp_path, max_attempts=1, backoff_seconds=0.0)
        client._client = httpx.Client(transport=httpx.MockTransport(deny))
        with pytest.raises(ProxyPolicyError) as caught:
            client.get(SECRET_URL)
        assert "secret-identity" not in str(caught.value)

    def test_the_final_fetch_error_is_redacted(self, tmp_path: Path) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"cannot reach {SECRET_URL}")

        client = HttpClient(cache_dir=tmp_path, max_attempts=2, backoff_seconds=0.0)
        client._client = httpx.Client(transport=httpx.MockTransport(boom))
        with pytest.raises(HttpFetchError) as caught:
            client.get(SECRET_URL)
        assert "secret-identity" not in str(caught.value)

    def test_retry_logs_are_redacted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = Recorder()
        monkeypatch.setattr("pramaanx.ingest.http.log", recorder)

        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"cannot reach {SECRET_URL}")

        client = HttpClient(cache_dir=tmp_path, max_attempts=2, backoff_seconds=0.0)
        client._client = httpx.Client(transport=httpx.MockTransport(boom))
        with pytest.raises(HttpFetchError):
            client.get(SECRET_URL)
        assert "secret-identity" not in recorder.text()
        assert recorder.field("http.retry", "url") == redact_url(SECRET_URL)

    def test_rate_limit_logs_are_redacted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = Recorder()
        monkeypatch.setattr("pramaanx.ingest.http.log", recorder)
        client = HttpClient(cache_dir=tmp_path, max_attempts=2, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, headers={"Retry-After": "0"})
            )
        )
        with pytest.raises(RateLimitError):
            client.get(SECRET_URL)
        assert "secret-identity" not in recorder.text()

    def test_configured_proxy_is_logged_without_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = Recorder()
        monkeypatch.setattr("pramaanx.ingest.http.log", recorder)
        client = HttpClient(proxy="http://user:hunter2@127.0.0.1:3128", trust_env=True)
        client.client()
        client.close()
        assert "hunter2" not in recorder.text()
        assert recorder.field("http.client_built", "proxy") == "http://REDACTED@127.0.0.1:3128"


class TestRetryAfterIsBounded:
    """A 429 is an instruction. An unbounded one is a denial of service."""

    def _client(self, tmp_path: Path, **kwargs: object) -> HttpClient:
        kwargs.setdefault("backoff_seconds", 0.0)
        client = HttpClient(cache_dir=tmp_path, **kwargs)  # type: ignore[arg-type]
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200))
        )
        return client

    def test_an_ordinary_retry_after_is_honoured(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, max_retry_after_seconds=60.0)
        response = httpx.Response(429, headers={"Retry-After": "7"})
        assert client._retry_after_seconds(response, attempt=1) == 7.0

    def test_an_excessive_retry_after_is_capped(self, tmp_path: Path) -> None:
        # Without the cap, a header of 86400 parks the ingest for a day inside
        # a retry loop nobody is watching.
        client = self._client(tmp_path, max_retry_after_seconds=30.0)
        response = httpx.Response(429, headers={"Retry-After": "86400"})
        assert client._retry_after_seconds(response, attempt=1) == 30.0

    def test_an_excessive_http_date_is_capped(self, tmp_path: Path) -> None:
        from email.utils import format_datetime

        client = self._client(tmp_path, max_retry_after_seconds=30.0)
        far = datetime.now(UTC) + timedelta(days=2)
        response = httpx.Response(429, headers={"Retry-After": format_datetime(far)})
        assert client._retry_after_seconds(response, attempt=1) == 30.0

    def test_a_negative_retry_after_becomes_zero(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, max_retry_after_seconds=60.0)
        response = httpx.Response(429, headers={"Retry-After": "-5"})
        assert client._retry_after_seconds(response, attempt=1) == 0.0

    def test_a_past_http_date_becomes_zero(self, tmp_path: Path) -> None:
        from email.utils import format_datetime

        client = self._client(tmp_path, max_retry_after_seconds=60.0)
        past = datetime.now(UTC) - timedelta(hours=1)
        response = httpx.Response(429, headers={"Retry-After": format_datetime(past)})
        assert client._retry_after_seconds(response, attempt=1) == 0.0

    def test_a_malformed_retry_after_falls_back_to_bounded_backoff(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, backoff_seconds=2.0, max_retry_after_seconds=5.0)
        response = httpx.Response(429, headers={"Retry-After": "next tuesday"})
        assert client._retry_after_seconds(response, attempt=1) == 2.0
        # The fallback is clamped too: 2 * 2**5 would be 64 seconds.
        assert client._retry_after_seconds(response, attempt=6) == 5.0

    def test_an_absent_header_falls_back_to_bounded_backoff(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, backoff_seconds=2.0, max_retry_after_seconds=5.0)
        assert client._retry_after_seconds(httpx.Response(429), attempt=1) == 2.0
        assert client._retry_after_seconds(httpx.Response(429), attempt=6) == 5.0

    def test_a_non_finite_retry_after_is_capped(self, tmp_path: Path) -> None:
        # float("inf") parses successfully; max(0.0, inf) would sleep forever.
        client = self._client(tmp_path, max_retry_after_seconds=30.0)
        response = httpx.Response(429, headers={"Retry-After": "inf"})
        assert client._retry_after_seconds(response, attempt=1) == 30.0

    def test_the_ordinary_backoff_path_is_bounded_too(self, tmp_path: Path) -> None:
        client = self._client(tmp_path, backoff_seconds=10.0, max_retry_after_seconds=15.0)
        assert client._backoff_seconds_for(1) == 10.0
        assert client._backoff_seconds_for(4) == 15.0

    def test_a_persistent_429_still_raises(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path, max_attempts=2, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(429, headers={"Retry-After": "0"})
            )
        )
        with pytest.raises(RateLimitError, match=r"[Ll]ower page_size"):
            client.get("https://example.org/x")

    def test_no_test_here_actually_sleeps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A capped delay is still a delay; the loop must be exercised with a
        # stubbed clock, never by really waiting.
        slept: list[float] = []
        monkeypatch.setattr("pramaanx.ingest.http.time.sleep", slept.append)
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "99999"})
            return httpx.Response(200, content=b"ok")

        client = HttpClient(
            cache_dir=tmp_path, max_attempts=3, backoff_seconds=0.0, max_retry_after_seconds=45.0
        )
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        assert client.get("https://example.org/x") == b"ok"
        assert 45.0 in slept, "the capped delay must be what the client sleeps for"


class TestReliefWebPassesItsRetryCeiling:
    def test_the_source_option_reaches_the_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pramaanx.config import Settings
        from pramaanx.ingest.connectors.reliefweb import APPNAME_ENV, ReliefWebConnector

        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        connector = ReliefWebConnector(
            Settings(), {"cache": False, "max_retry_after_seconds": 12.5}
        )
        client = connector._client_for().__self__  # type: ignore[attr-defined]
        assert client.max_retry_after_seconds == 12.5
