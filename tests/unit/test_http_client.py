"""The HTTP fetcher: caching, retries, proxy configuration and policy denials."""

from __future__ import annotations

import ssl
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
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
    _is_policy_denial,
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

    def test_origin_403_is_permanent_not_a_proxy_denial(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path, max_attempts=2, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(403))
        )
        with pytest.raises(PermanentHttpError, match="origin returned HTTP 403"):
            client.get("https://example.org/blocked")

    def test_407_response_is_a_proxy_denial(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path, max_attempts=2, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(407))
        )
        with pytest.raises(ProxyPolicyError):
            client.get("https://example.org/blocked")


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

    def test_unexpected_content_type_is_permanent(self, tmp_path: Path) -> None:
        client = self._client(
            tmp_path,
            lambda request: httpx.Response(
                200, content=b"{}", headers={"Content-Type": "text/html"}
            ),
        )
        with pytest.raises(PermanentHttpError, match="unexpected Content-Type"):
            client.get(
                "https://example.org/data",
                accepted_content_types=frozenset({"application/json"}),
            )

    @pytest.mark.parametrize(
        ("retry_after", "expected"),
        [
            ("999", 3.0),
            ("malformed", 1.0),
        ],
    )
    def test_retry_after_is_bounded(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        retry_after: str,
        expected: float,
    ) -> None:
        attempts = 0
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": retry_after})
            return httpx.Response(200, content=b"ok")

        monkeypatch.setattr("pramaanx.ingest.http.time.sleep", sleeps.append)
        client = HttpClient(
            cache_dir=tmp_path,
            max_attempts=2,
            backoff_seconds=1.0,
            max_retry_after_seconds=3.0,
            min_interval_seconds=0.0,
        )
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        assert client.get("https://example.org/rate") == b"ok"
        assert sleeps == [expected]

    def test_http_date_retry_after_is_clamped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = 0
        sleeps: list[float] = []
        future = format_datetime(datetime.now(UTC) + timedelta(hours=1), usegmt=True)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, headers={"Retry-After": future})
            return httpx.Response(200, content=b"ok")

        monkeypatch.setattr("pramaanx.ingest.http.time.sleep", sleeps.append)
        client = HttpClient(
            cache_dir=tmp_path,
            max_attempts=2,
            max_retry_after_seconds=2.0,
            min_interval_seconds=0.0,
        )
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        assert client.get("https://example.org/busy") == b"ok"
        assert sleeps == [2.0]


class TestSecretRedaction:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.org/x?api-key=topsecret&x=1",
            "https://example.org/x?API-KEY=topsecret&api-key=second",
            "https://example.org/x?x=1&api-key=a%2Fb%3Fc#frag",
            "https://example.org/x?api-key=line%0Abreak",
        ],
    )
    def test_query_secret_is_removed(self, url: str) -> None:
        safe = redact_url(url)
        assert "topsecret" not in safe
        assert "second" not in safe
        assert "a%2Fb%3Fc" not in safe
        assert "line%0Abreak" not in safe
        assert "<redacted>" in safe or "%3Credacted%3E" in safe
        assert "\n" not in safe

    def test_proxy_userinfo_is_removed(self) -> None:
        safe = redact_url("https://user:password@proxy.example:8443/path")
        assert "user" not in safe
        assert "password" not in safe
        assert safe == "https://<redacted>@proxy.example:8443/path"

    def test_cache_identity_does_not_contain_or_depend_on_key(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path)
        first = client._cache_path(redact_url("https://example.org/x?api-key=one&offset=0"))
        second = client._cache_path(redact_url("https://example.org/x?api-key=two&offset=0"))
        assert first == second
        assert first is not None
        assert "one" not in str(first)
        assert "two" not in str(first)

    def test_transport_exception_is_sanitized(self, tmp_path: Path) -> None:
        secret = "transport-secret"

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"failed opening {request.url}")

        client = HttpClient(
            cache_dir=tmp_path,
            max_attempts=1,
            min_interval_seconds=0.0,
        )
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(HttpFetchError) as captured:
            client.get(f"https://example.org/x?api-key={secret}")
        assert secret not in str(captured.value)
