"""Model/API wrapper: integration tests against a live HTTP server.

These run a real socket server speaking the OpenAI chat-completions API, so the
wrapper's HTTP path, headers, request body and error handling are all exercised.
A monkeypatched client would test the test, not the wrapper -- and the failures
that actually happen in deployment (a 500 from an overloaded vLLM, a timeout, a
model that ignores the schema) live in exactly the layer a mock removes.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from pramaan_x.stage3_reason.llm import (
    BudgetExceeded,
    LlmClient,
    OfflineBackend,
    OpenAiCompatibleBackend,
    build_client,
)
from pramaan_x.stage3_reason.schema import HypothesisSet, Verdict

PROMPT = """TARGET: Chennai|flood
HORIZON_DAYS: 7
EVIDENCE:
  - [d001] reservoir levels approached the seasonal spill threshold
  - [d002] embankment seepage was reported at two points along the bund
"""

VALID_HYPOTHESES = json.dumps({"hypotheses": [{
    "location": "Chennai", "event_type": "flood", "horizon_days": 7,
    "plausibility": 0.62, "rationale": "reservoir and embankment signals coincide",
    "supporting_doc_ids": ["d001", "d002"],
}]})


class _Handler(BaseHTTPRequestHandler):
    mode: ClassVar[str] = "ok"
    requests: ClassVar[list[dict]] = []

    def log_message(self, *args):        # keep pytest output clean
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append({"path": self.path, "body": body,
                                    "auth": self.headers.get("Authorization")})
        mode = type(self).mode
        if mode == "error":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"engine overloaded"}')
            return
        if mode == "garbage":
            content = "Sure! Here is the answer: {not valid json,,}"
        elif mode == "schema_violation":
            content = json.dumps({"hypotheses": [{
                "location": "Chennai", "event_type": "flood", "horizon_days": 7,
                "plausibility": 4.2, "rationale": "out of range",
                "supporting_doc_ids": [],
            }]})
        else:
            content = VALID_HYPOTHESES
        n = int(body.get("n", 1))
        payload = {
            "choices": [{"message": {"role": "assistant", "content": content}}
                        for _ in range(n)],
            "usage": {"prompt_tokens": 128, "completion_tokens": 64},
        }
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def server(loopback_direct):
    """A real HTTP server on loopback.

    `loopback_direct` is a dependency of the *fixture*, not of each test, so
    every test that takes a live server gets the bypass and none can forget it.
    Without it these tests send their requests to whatever `HTTP_PROXY`,
    `HTTPS_PROXY` or `ALL_PROXY` the environment exports. On a host with a SOCKS
    proxy configured and `socksio` absent, httpx does not even reach the socket:
    it fails at client construction, and every assertion here then reports the
    proxy's absence as a fault in the code under test.

    The bypass is additive -- loopback is added to `no_proxy`, every other proxy
    setting is left as it was, and no TLS verification is disabled.
    """
    _Handler.mode = "ok"
    _Handler.requests = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _backend(url: str) -> OpenAiCompatibleBackend:
    return OpenAiCompatibleBackend(base_url=url, model="Qwen/Qwen3.8-27B",
                                   timeout_s=10.0, name="vllm")


def test_successful_call_parses_into_schema(server):
    _, url = server
    client = LlmClient(backend=_backend(url))
    (resp,) = client.complete(PROMPT, schema=HypothesisSet)
    assert resp.ok
    assert resp.parsed.hypotheses[0].event_type == "flood"
    assert resp.parsed.hypotheses[0].plausibility == pytest.approx(0.62)
    assert client.stats()["calls"] == 1


def test_constrained_decoding_is_requested_both_ways(server):
    """vLLM reads `guided_json`, SGLang reads `response_format`. Both are sent
    so one wrapper serves both servers."""
    _, url = server
    LlmClient(backend=_backend(url)).complete(PROMPT, schema=HypothesisSet)
    body = _Handler.requests[-1]["body"]
    assert body["response_format"]["json_schema"]["name"] == "HypothesisSet"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "guided_json" in body["extra_body"]
    assert body["extra_body"]["guided_json"]["additionalProperties"] is False


def test_auth_header_and_model_are_sent(server):
    _, url = server
    LlmClient(backend=_backend(url)).complete(PROMPT, schema=HypothesisSet)
    req = _Handler.requests[-1]
    assert req["auth"] == "Bearer EMPTY"
    assert req["body"]["model"] == "Qwen/Qwen3.8-27B"
    assert req["path"].endswith("/chat/completions")


def test_n_samples_returns_n_responses(server):
    _, url = server
    out = LlmClient(backend=_backend(url)).complete(PROMPT, schema=HypothesisSet, n=4)
    assert len(out) == 4
    assert all(r.ok for r in out)


def test_server_error_falls_back_to_offline(server):
    """A 500 from an overloaded engine must degrade, not abort the batch."""
    _, url = server
    _Handler.mode = "error"
    client = LlmClient(backend=_backend(url), fallback=OfflineBackend())
    (resp,) = client.complete(PROMPT, schema=HypothesisSet)
    assert resp.ok
    assert resp.provider == "offline"
    assert client.degraded == 1


def test_server_error_without_fallback_returns_error_not_raise(server):
    _, url = server
    _Handler.mode = "error"
    client = LlmClient(backend=_backend(url))
    (resp,) = client.complete(PROMPT, schema=HypothesisSet)
    assert not resp.ok
    assert "500" in resp.error or "Server error" in resp.error


def test_unparseable_response_is_counted_not_raised(server):
    """A model that answers in prose is a routine event, not an exception."""
    _, url = server
    _Handler.mode = "garbage"
    client = LlmClient(backend=_backend(url))
    (resp,) = client.complete(PROMPT, schema=HypothesisSet)
    assert not resp.ok
    assert client.parse_failures == 1
    assert resp.text


def test_schema_violation_is_rejected(server):
    """The server returned syntactically valid JSON with an out-of-range field.
    Constrained decoding is not a guarantee, so validation still gates."""
    _, url = server
    _Handler.mode = "schema_violation"
    client = LlmClient(backend=_backend(url))
    (resp,) = client.complete(PROMPT, schema=HypothesisSet)
    assert not resp.ok
    assert "plausibility" in resp.error


def test_cache_prevents_a_second_call(server, tmp_cache):
    _, url = server
    client = LlmClient(backend=_backend(url), cache=tmp_cache)
    client.complete(PROMPT, schema=HypothesisSet)
    before = len(_Handler.requests)
    (resp,) = client.complete(PROMPT, schema=HypothesisSet)
    assert len(_Handler.requests) == before
    assert resp.cached and resp.ok
    assert client.stats()["cache_hits"] == 1


def test_cache_key_includes_model(server, tmp_cache):
    _, url = server
    a = LlmClient(backend=OpenAiCompatibleBackend(base_url=url, model="model-a"),
                  cache=tmp_cache)
    b = LlmClient(backend=OpenAiCompatibleBackend(base_url=url, model="model-b"),
                  cache=tmp_cache)
    a.complete(PROMPT, schema=HypothesisSet)
    before = len(_Handler.requests)
    b.complete(PROMPT, schema=HypothesisSet)
    assert len(_Handler.requests) == before + 1, "different model must not reuse a cached generation"


def test_budget_degrades_to_fallback(server):
    _, url = server
    client = LlmClient(backend=_backend(url), fallback=OfflineBackend(), max_calls=2)
    for _ in range(2):
        client.complete(PROMPT + str(_), schema=HypothesisSet)
    assert client.calls_made == 2
    (resp,) = client.complete(PROMPT + "third", schema=HypothesisSet)
    assert resp.provider == "offline"
    assert client.calls_made == 2
    assert client.degraded == 1


def test_budget_without_fallback_raises(server):
    _, url = server
    client = LlmClient(backend=_backend(url), max_calls=1)
    client.complete(PROMPT, schema=HypothesisSet)
    with pytest.raises(BudgetExceeded):
        client.complete(PROMPT + "again", schema=HypothesisSet)


def test_timeout_is_handled(server):
    """An unroutable address exercises the connect-failure path."""
    client = LlmClient(
        backend=OpenAiCompatibleBackend(base_url="http://127.0.0.1:1/v1", timeout_s=0.5),
        fallback=OfflineBackend(),
    )
    (resp,) = client.complete(PROMPT, schema=HypothesisSet)
    assert resp.ok and resp.provider == "offline"


def test_offline_backend_is_deterministic():
    client = build_client("stub", cache_dir=None)
    a = [r.text for r in client.complete(PROMPT, schema=HypothesisSet, n=3)]
    b = [r.text for r in client.complete(PROMPT, schema=HypothesisSet, n=3)]
    assert a == b


def test_offline_backend_tracks_evidence_volume():
    client = build_client("stub", cache_dir=None)
    empty = "TARGET: Chennai|flood\nHORIZON_DAYS: 7\nEVIDENCE:\n"
    (thin,) = client.complete(empty, schema=Verdict)
    (thick,) = client.complete(PROMPT, schema=Verdict)
    assert thin.parsed.supported == "insufficient"
    assert thick.parsed.confidence > thin.parsed.confidence
