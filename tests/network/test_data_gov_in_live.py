"""Opt-in live contract probe for the selected data.gov.in resource."""

from __future__ import annotations

import json
import os

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.connectors.data_gov_in import (
    API_KEY_ENV,
    SECRET_QUERY_PARAMETERS,
    DataGovInConnector,
    DataGovInContractError,
    parse_envelope,
)
from pramaanx.ingest.http import HttpClient, ProxyPolicyError, sanitize_error_text

pytestmark = pytest.mark.network

RESOURCE_ID = "869c674d-59a4-4de3-8b09-f2b709983f51"
ENVELOPE_FIELDS = ("status", "total", "count", "limit", "offset", "records")


def _safe_type_summary(payload: bytes) -> str:
    """Describe contract shape without printing records, URLs, or credentials."""
    try:
        envelope = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "top_level=invalid_json"
    if not isinstance(envelope, dict):
        return f"top_level={type(envelope).__name__}"
    return ", ".join(
        f"{field}={type(envelope[field]).__name__}" if field in envelope else f"{field}=<missing>"
        for field in ENVELOPE_FIELDS
    )


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

    parsed: tuple[list[dict[str, object]], int] | None = None
    contract_failure: str | None = None
    try:
        parsed = parse_envelope(
            payload, expected_offset=0, expected_limit=10, expected_total=None
        )
    except DataGovInContractError as error:  # pragma: no cover - network dependent
        contract_failure = f"{error}; safe envelope types: {_safe_type_summary(payload)}"

    if contract_failure is not None:  # pragma: no cover - network dependent
        pytest.fail(f"live data.gov.in contract mismatch: {contract_failure}", pytrace=False)

    assert parsed is not None
    records, total = parsed
    assert total >= len(records)
