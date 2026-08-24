"""Dashboard functional checks.

The risk table allows the dashboard to be drafted freely but only after
functional checks. These verify it is served, that it is self-contained (a
strict deployment blocks third-party origins), and that every endpoint it calls
actually exists -- a dashboard referencing a route that was renamed fails
silently in the browser and nowhere else.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from pramaan_x.api import create_app
from pramaan_x.config import Config


@pytest.fixture(scope="module")
def client():
    c = TestClient(create_app(Config()))
    c.post("/ingest/synthetic", json={"days": 120})
    return c


@pytest.fixture(scope="module")
def html(client):
    return client.get("/").text


def test_dashboard_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_dashboard_is_self_contained(html):
    """No external scripts, styles or fonts: one origin, nothing to block."""
    assert not re.search(r'<script[^>]+src=', html)
    assert not re.search(r'<link[^>]+href="https?://', html)
    assert "cdn" not in html.lower()


def test_every_endpoint_the_dashboard_calls_exists(client, html):
    """Catches a renamed route before a user finds it."""
    spec = client.get("/openapi.json").json()["paths"]
    called = set(re.findall(r'api\("(/[^"?`]+)', html))
    called |= {re.sub(r'\$\{[^}]+\}', "{doc_id}", m)
               for m in re.findall(r'api\(`(/[^`?]+)', html)}
    assert called, "no API calls found in the dashboard"
    for path in called:
        assert path.split("?")[0] in spec, f"dashboard calls unknown route {path}"


def test_dashboard_surfaces_source_independence(html):
    """The one number an analyst must not miss: many copies, one voice."""
    assert "independence" in html
    assert "republished, not corroboration" in html


def test_dashboard_explains_the_cutoff(html):
    assert "forecast origin" in html


def test_dashboard_respects_dark_mode(html):
    assert "prefers-color-scheme:dark" in html.replace(" ", "")


def test_openapi_still_excludes_the_dashboard_route(client):
    assert "/" not in client.get("/openapi.json").json()["paths"]
