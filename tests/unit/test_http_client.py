"""The HTTP fetcher: caching, retries, proxy configuration and policy denials."""

from __future__ import annotations

import ssl
from pathlib import Path

import httpx
import pytest

from pramaanx.ingest.http import (
    HttpClient,
    HttpFetchError,
    NotFoundError,
    ProxyPolicyError,
    _is_policy_denial,
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
        bundle = tmp_path / "ca.pem"
        bundle.write_bytes(Path(ssl.get_default_verify_paths().cafile or "/dev/null").read_bytes())
        client = HttpClient(ca_bundle=str(bundle))
        assert isinstance(client._verify_setting(), ssl.SSLContext)

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

    def test_403_response_is_a_policy_denial(self, tmp_path: Path) -> None:
        client = HttpClient(cache_dir=tmp_path, max_attempts=2, backoff_seconds=0.0)
        client._client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(403))
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
