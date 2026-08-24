"""API contract tests.

The functional checks the risk table asks for before the HTTP layer can be
trusted. The two that matter most are `test_search_enforces_publication_cutoff`
-- the API must never hand back evidence that postdates the forecast origin --
and the 503 tests, because an endpoint that returns 200 with empty results when
its index is missing hides an operational fault.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pramaan_x.api import create_app
from pramaan_x.config import Config


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(Config()))


@pytest.fixture(scope="module")
def ready_client(client):
    client.post("/ingest/synthetic", json={"days": 120})
    return client


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_config_exposes_fingerprint(client):
    body = client.get("/config").json()
    assert len(body["fingerprint"]) == 16
    assert body["config"]["stage5"]["epsilon"] > 0


def test_search_before_ingest_returns_503(client):
    fresh = TestClient(create_app(Config()))
    r = fresh.post("/search", json={"query": "anything"})
    assert r.status_code == 503
    assert "corpus" in r.json()["detail"].lower()


def test_ingest_reports_dedup(ready_client):
    body = ready_client.get("/status").json()
    assert body["ready"] is True
    assert body["documents_canonical"] < body["documents_raw"]
    assert 0 < body["stage0"]["dedup"]["reduction"] < 1


def test_search_returns_ordered_results(ready_client):
    body = ready_client.post("/search", json={
        "query": "reservoir levels spill threshold embankment seepage", "k": 10,
    }).json()
    scores = [h["score"] for h in body["results"]]
    assert scores == sorted(scores, reverse=True)
    assert len(body["results"]) <= 10


def test_search_enforces_publication_cutoff(ready_client):
    """The property the whole system rests on."""
    cutoff = "2025-03-01T00:00:00Z"
    body = ready_client.post("/search", json={
        "query": "curfew extended paramilitary units redeployed",
        "as_of": cutoff, "k": 50,
    }).json()
    assert body["results"], "cutoff must not empty the result set"
    for hit in body["results"]:
        assert hit["published_at"] < cutoff


def test_cascade_narrows_monotonically(ready_client):
    body = ready_client.post("/search", json={
        "query": "credential stuffing portal unpatched edge appliance", "k": 20,
    }).json()
    corpus, wide, late, rerank = body["cascade"]["narrowing"]
    assert corpus >= wide >= late >= rerank > 0


def test_stop_after_controls_depth(ready_client):
    sparse = ready_client.post("/search", json={
        "query": "port congestion dwell times", "stop_after": "sparse", "k": 5,
    }).json()
    full = ready_client.post("/search", json={
        "query": "port congestion dwell times", "stop_after": "rerank", "k": 5,
    }).json()
    assert sparse["cascade"]["reranked"] == 0
    assert full["cascade"]["reranked"] > 0
    assert "rerank" not in sparse["cascade"]["timings_ms"]


def test_components_are_returned_for_explanation(ready_client):
    body = ready_client.post("/search", json={
        "query": "union representatives rejected wage offer", "k": 5,
    }).json()
    comps = body["results"][0]["components"]
    assert {"bm25", "dense"} & set(comps), "component scores must be exposed"


def test_unknown_field_is_rejected(ready_client):
    assert ready_client.post("/search", json={"query": "x", "nope": 1}).status_code == 422


def test_invalid_stop_after_is_rejected(ready_client):
    assert ready_client.post(
        "/search", json={"query": "x", "stop_after": "magic"}
    ).status_code == 422


def test_k_bounds_enforced(ready_client):
    assert ready_client.post("/search", json={"query": "x", "k": 0}).status_code == 422
    assert ready_client.post("/search", json={"query": "x", "k": 9999}).status_code == 422


def test_empty_query_rejected(ready_client):
    assert ready_client.post("/search", json={"query": ""}).status_code == 422


def test_document_lookup_and_404(ready_client):
    hit = ready_client.post("/search", json={"query": "flood warning", "k": 1}).json()
    doc_id = hit["results"][0]["doc_id"]
    assert ready_client.get(f"/documents/{doc_id}").json()["doc_id"] == doc_id
    assert ready_client.get("/documents/does-not-exist").status_code == 404


def test_cluster_reports_independence(ready_client):
    hit = ready_client.post("/search", json={"query": "flood warning", "k": 1}).json()
    body = ready_client.get(f"/documents/{hit['results'][0]['doc_id']}/cluster").json()
    assert body["size"] >= 1
    assert 0 < body["independence"] <= 1.0
    assert body["distinct_source_families"] <= body["size"]


def test_timeline(ready_client):
    body = ready_client.get("/timeline?days=30").json()
    assert body["days"] <= 30
    assert all(r["n"] >= 0 for r in body["series"])


def test_openapi_documents_every_route(client):
    spec = client.get("/openapi.json").json()
    for path in ("/search", "/status", "/ingest/synthetic", "/documents/{doc_id}"):
        assert path in spec["paths"]
    assert spec["info"]["title"] == "PRAMAAN-X evidence retrieval"


def test_openapi_does_not_advertise_forecasting(client):
    """The API label has to match what the code does. Stages 4 and 5 are not
    implemented, so nothing in the served description may imply a forecast."""
    info = client.get("/openapi.json").json()["info"]
    blob = f"{info['title']} {info.get('summary', '')} {info.get('description', '')}"
    assert "Not a forecasting service" in blob
    assert "does not forecast events" in blob
    assert "conformal risk control" not in blob.lower().replace(
        "stages 4 (risk models) and 5 (conformal risk control) are not", "")


def test_search_response_states_which_cutoff_rule_it_applied(ready_client):
    """The served index is built once over the whole corpus, so this endpoint
    enforces the publication cutoff only. Saying so in the payload is what
    stops an interactive result being quoted as a backtest number."""
    body = ready_client.post("/search", json={
        "query": "reservoir levels spill threshold",
        "as_of": "2025-03-01T00:00:00Z", "k": 5,
    }).json()
    assert body["cutoff_rule"] == "publication_only"
    assert "not a forecast" in body["measures"]
    assert "not a backtest measurement" in body["measures"]
