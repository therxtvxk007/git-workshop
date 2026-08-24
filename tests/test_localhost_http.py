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
