"""Opt-in live contract probe for the selected data.gov.in resource."""

from __future__ import annotations

import os

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.connectors.data_gov_in import (
    API_KEY_ENV,
    SECRET_QUERY_PARAMETERS,
    DataGovInConnector,
    parse_envelope,
)
from pramaanx.ingest.http import HttpClient, ProxyPolicyError

pytestmark = pytest.mark.network

RESOURCE_ID = "869c674d-59a4-4de3-8b09-f2b709983f51"


def test_selected_resource_live_contract() -> None:
    if os.environ.get("PRAMAANX_LIVE_DATA_GOV_IN") != "1":
        pytest.skip("live data.gov.in test is opt-in; set PRAMAANX_LIVE_DATA_GOV_IN=1")
    if not os.environ.get(API_KEY_ENV, "").strip():
        pytest.skip(f"live data.gov.in test requires {API_KEY_ENV}")

    connector = DataGovInConnector(
        Settings(),
        {
            "resource_id": RESOURCE_ID,
            "resource_title": "Attacker-wise incidents during 2023",
            "available_at": "2026-02-14T00:00:00Z",
            "page_size": 10,
            "cache": False,
        },
    )
    url = connector.page_url(offset=0)
    client = HttpClient(cache_dir=None, max_attempts=2, max_retry_after_seconds=10.0)
    try:
        payload = client.get(
            url,
            secret_query_parameters=SECRET_QUERY_PARAMETERS,
            accepted_content_types=frozenset({"application/json"}),
        )
    except ProxyPolicyError as error:  # pragma: no cover - network dependent
        pytest.skip(f"CONNECT/proxy policy blocked the live host: {error}")
    finally:
        client.close()

    records, total = parse_envelope(
        payload, expected_offset=0, expected_limit=10, expected_total=None
    )
    assert total >= len(records)
