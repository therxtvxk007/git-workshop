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
from pramaanx.ingest.http import HttpClient, ProxyPolicyError, sanitize_error_text

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
    client = HttpClient(cache_dir=None, max_attempts=2, max_retry_after_seconds=10.0)
    failure_message: str | None = None
    try:
        payload = client.get(
            connector.page_url(offset=0),
            secret_query_parameters=SECRET_QUERY_PARAMETERS,
            accepted_content_types=frozenset({"application/json"}),
        )
    except ProxyPolicyError as error:  # pragma: no cover - network dependent
        pytest.skip(f"CONNECT/proxy policy blocked the live host: {error}")
    except Exception as error:  # pragma: no cover - network dependent
        # Never let pytest render the secret-bearing HTTP stack or arguments.
        # Build the sanitized message while handling the error, then raise the
        # traceback-free failure after leaving the exception context.
        failure_message = sanitize_error_text(
            str(error), connector.page_url(offset=0), SECRET_QUERY_PARAMETERS
        )
    finally:
        client.close()

    if failure_message is not None:  # pragma: no cover - network dependent
        pytest.fail(f"live data.gov.in request failed: {failure_message}", pytrace=False)

    records, total = parse_envelope(
        payload, expected_offset=0, expected_limit=10, expected_total=None
    )
    assert total >= len(records)
