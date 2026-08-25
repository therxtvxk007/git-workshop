"""Localhost HTTP under an inherited proxy configuration.

A test that talks to 127.0.0.1 must reach 127.0.0.1. On a runner that exports
`HTTP_PROXY`, an unguarded client sends the request to the proxy instead, and
the test then measures the proxy's behaviour rather than the service's.

The guard is `loopback_direct`, which prepends the loopback hosts to `no_proxy`.
It is additive by design: the proxy stays configured for everything else, and
nothing here disables certificate verification.
"""

from __future__ import annotations

import os
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"direct")

    def log_message(self, *_args):  # keep the suite output clean
        pass


@pytest.fixture
def loopback_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_fixture_adds_loopback_without_dropping_existing_bypasses(loopback_direct):
    entries = os.environ["NO_PROXY"].split(",")
    for host in loopback_direct:
        assert host in entries
    assert "127.0.0.1" in entries
    assert os.environ["no_proxy"] == os.environ["NO_PROXY"]


def test_fixture_does_not_unset_the_proxy_variables(monkeypatch, loopback_direct):
    """Bypassing loopback must not turn the proxy off for everything else."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    assert os.environ["HTTPS_PROXY"] == "http://proxy.invalid:3128"
    assert "proxy.invalid" not in os.environ["NO_PROXY"]


def test_loopback_request_reaches_the_local_server_through_a_dead_proxy(
    monkeypatch, loopback_direct, loopback_server
):
    """The real check: point the proxy variables at a port nothing is listening
    on, and prove the loopback request still succeeds."""
    dead = f"http://127.0.0.1:{_closed_port()}"
    monkeypatch.setenv("http_proxy", dead)
    monkeypatch.setenv("HTTP_PROXY", dead)
    with urllib.request.urlopen(loopback_server, timeout=10) as resp:
        assert resp.status == 200
        assert resp.read() == b"direct"


def test_without_the_bypass_the_dead_proxy_is_used(monkeypatch, loopback_server):
    """Negative control. If this passed anyway, the fixture would be proving
    nothing -- so the unguarded case must actually fail."""
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    dead = f"http://127.0.0.1:{_closed_port()}"
    monkeypatch.setenv("http_proxy", dead)
    monkeypatch.setenv("HTTP_PROXY", dead)
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(loopback_server, timeout=10)


def test_mlflow_fallback_is_measured_against_the_local_port_not_the_proxy(
    monkeypatch, loopback_direct, tmp_path
):
    """`build_tracker` decides to fall back when the tracking server is
    unreachable. Under an inherited proxy that decision would be made about the
    proxy, so the bypass has to be in place for the assertion to mean what it
    says."""
    from pramaan_x.tracking import LocalTracker, build_tracker

    dead = f"http://proxy.invalid:{_closed_port()}"
    monkeypatch.setenv("HTTP_PROXY", dead)
    monkeypatch.setenv("HTTPS_PROXY", dead)
    tracker = build_tracker("mlflow", uri=f"http://127.0.0.1:{_closed_port()}", root=str(tmp_path))
    assert isinstance(tracker, LocalTracker)


def _closed_port() -> int:
    """A port that was bound and released, so nothing is listening on it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------- live-server clients and proxies ---


def test_loopback_urls_are_recognised():
    from pramaan_x.stage3_reason.llm import is_loopback_url

    for url in (
        "http://localhost:8000/v1",
        "http://127.0.0.1:9/v1",
        "http://[::1]:8000/v1",
        "http://127.0.0.5:1234",
    ):
        assert is_loopback_url(url), url
    for url in (
        "https://api.openai.com/v1",
        "http://vllm.internal:8000/v1",
        "http://10.0.0.4:8000",
        "not a url at all",
        "",
    ):
        assert not is_loopback_url(url), url


def test_a_remote_backend_still_honours_the_environment_proxy(monkeypatch):
    """NEGATIVE CONTROL: the loopback carve-out must not become a blanket
    opt-out. Every non-loopback host keeps whatever proxy the environment
    configures.

    The assertion captures the argument the backend passes rather than
    inspecting a constructed client, because under a SOCKS environment without
    `socksio` a remote client cannot be built at all -- which is correct
    behaviour, and would otherwise make this test unrunnable in exactly the
    environment it exists for.
    """
    import httpx

    from pramaan_x.stage3_reason.llm import OpenAiCompatibleBackend

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")

    captured: list[dict] = []

    class _Recorder:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", _Recorder)

    OpenAiCompatibleBackend(base_url="https://api.example.com/v1")._http()
    assert captured[-1]["trust_env"] is True, "a remote backend stopped trusting the environment"

    OpenAiCompatibleBackend(base_url="http://127.0.0.1:8000/v1")._http()
    assert captured[-1]["trust_env"] is False

    # The environment itself is untouched either way.
    assert os.environ["HTTPS_PROXY"] == "http://proxy.invalid:3128"


def test_a_socks_proxy_without_socksio_breaks_an_unguarded_client(monkeypatch):
    """NEGATIVE CONTROL, reproducing the reported failure exactly.

    With `ALL_PROXY` set to SOCKS and `socksio` absent, httpx raises at *client
    construction* -- before any request is routed -- so `no_proxy` cannot help
    and the loopback carve-out has to be made when the client is built.
    """
    import httpx

    try:
        import socksio  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("socksio is installed, so the reported failure cannot occur here")

    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:9")

    with pytest.raises(ImportError, match="socksio"):
        httpx.Client(base_url="http://127.0.0.1:9/v1", trust_env=True)

    # ...and the guarded client, built the way the backend builds it, is fine.
    httpx.Client(base_url="http://127.0.0.1:9/v1", trust_env=False).close()


def test_no_proxy_alone_does_not_rescue_a_socks_environment(monkeypatch):
    """Why the fix is at construction and not in `no_proxy`.

    The bypass mount is created correctly -- and httpx still fails, because it
    builds a transport for every mount including the SOCKS one.
    """
    import httpx

    try:
        import socksio  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("socksio is installed, so the reported failure cannot occur here")

    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1")

    from httpx._utils import get_environment_proxies

    mounts = get_environment_proxies()
    assert mounts.get("all://127.0.0.1", "missing") is None, "the bypass mount is present"
    with pytest.raises(ImportError, match="socksio"):
        httpx.Client(base_url="http://127.0.0.1:9/v1", trust_env=True)


def test_the_live_server_fixture_carries_the_bypass():
    """Every live-server test must inherit the guard from the fixture rather
    than remembering to ask for it."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent / "test_llm_integration.py").read_text()
    tree = ast.parse(source)
    fixture = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "server"
    )
    params = [a.arg for a in fixture.args.args]
    assert "loopback_direct" in params, (
        "the live-server fixture does not depend on loopback_direct, so a new "
        "test using it would be unprotected"
    )


def test_nothing_in_the_suite_disables_tls_verification():
    """NEGATIVE CONTROL for the forbidden shortcut."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    me = pathlib.Path(__file__).resolve()
    offenders = []
    for path in [*(root / "tests").glob("*.py"), *(root / "pramaan_x").rglob("*.py")]:
        # This file names the forbidden strings in order to search for them.
        if path.resolve() == me:
            continue
        text = path.read_text()
        for needle in ("verify=False", "VERIFY_NONE", "CERT_NONE", "PYTHONHTTPSVERIFY"):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert offenders == [], f"TLS verification is disabled somewhere: {offenders}"
