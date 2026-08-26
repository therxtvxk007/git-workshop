"""Opt-in ACLED contract checks against the real credentialed API.

An egress-proxy CONNECT refusal is the only skip after opt-in. Origin auth,
rate-limit, schema, item, and pagination failures are test failures.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.acled import API_CONTRACT, AcledConnector, parse_envelope
from pramaanx.ingest.http import ProxyPolicyError

pytestmark = pytest.mark.network


def live_connector() -> AcledConnector:
    if os.getenv("PRAMAANX_LIVE_ACLED") != "1":
        pytest.skip("set PRAMAANX_LIVE_ACLED=1 to execute the ACLED API contract")
    return AcledConnector(
        Settings(),
        {"countries": ["India"], "page_size": 100, "max_pages": 100},
    )


def tiny_window() -> FetchWindow:
    end = datetime.now(UTC).replace(microsecond=0)
    return FetchWindow(end - timedelta(seconds=60), end)


def test_raw_live_envelope_matches_the_documented_cursor_contract() -> None:
    connector = live_connector()
    try:
        token = connector._access_token()
        payload = connector._http.get(
            connector.page_url(tiny_window(), "0"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        page = parse_envelope(payload)
    except ProxyPolicyError as error:
        pytest.skip(f"CONNECT to acleddata.com was refused by egress policy: {error}")
    assert page.count == len(page.items)
    assert page.total_count >= page.count
    assert API_CONTRACT["genuinely_live_api_verified"] is False


def test_live_cursor_walk_completes_for_a_tiny_timestamp_window() -> None:
    connector = live_connector()
    window = tiny_window()
    try:
        items = list(connector.fetch(window))
    except ProxyPolicyError as error:
        pytest.skip(f"CONNECT to acleddata.com was refused by egress policy: {error}")
    assert all(window.contains(item.first_observed_at) for item in items)
