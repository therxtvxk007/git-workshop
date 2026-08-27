"""Opt-in live contract probe for the selected data.gov.in resource."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import FetchWindow, RawItem
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
        parsed = parse_envelope(payload, expected_offset=0, expected_limit=10, expected_total=None)
    except DataGovInContractError as error:  # pragma: no cover - network dependent
        contract_failure = f"{error}; safe envelope types: {_safe_type_summary(payload)}"

    if contract_failure is not None:  # pragma: no cover - network dependent
        pytest.fail(f"live data.gov.in contract mismatch: {contract_failure}", pytrace=False)

    assert parsed is not None
    records, total = parsed
    assert total >= len(records)


def test_selected_resource_complete_live_traversal() -> None:
    """Prove terminal pagination through the production connector path."""
    if os.environ.get("PRAMAANX_LIVE_DATA_GOV_IN") != "1":
        pytest.skip("live data.gov.in test is opt-in; set PRAMAANX_LIVE_DATA_GOV_IN=1")
    if not os.environ.get(API_KEY_ENV, "").strip():
        pytest.skip(f"live data.gov.in test requires {API_KEY_ENV}")

    client = HttpClient(cache_dir=None, max_attempts=2, max_retry_after_seconds=10.0)
    requested_offsets: list[int] = []
    observed_total: int | None = None

    def fetch_page(url: str) -> bytes:
        # This frame receives a credential-bearing URL. Never render it in a
        # pytest traceback; the enclosing test converts failures to a safe,
        # traceback-free message.
        __tracebackhide__ = True
        nonlocal observed_total
        query = parse_qs(urlsplit(url).query)
        offset = int(query["offset"][0])
        limit = int(query["limit"][0])
        page = client.get(
            url,
            secret_query_parameters=SECRET_QUERY_PARAMETERS,
            accepted_content_types=frozenset({"application/json"}),
        )
        _, total = parse_envelope(
            page,
            expected_offset=offset,
            expected_limit=limit,
            expected_total=observed_total,
        )
        if observed_total is None:
            observed_total = total
        requested_offsets.append(offset)
        return page

    connector = DataGovInConnector(
        Settings(),
        {
            "resource_id": RESOURCE_ID,
            "resource_title": "Attacker-wise incidents during 2023",
            "available_at": "2026-02-14T00:00:00Z",
            "page_size": 1,
            "cache": False,
        },
        fetcher=fetch_page,
    )
    items: list[RawItem] | None = None
    failure_message: str | None = None
    try:
        items = list(
            connector.guarded_fetch(
                FetchWindow(
                    datetime(2026, 2, 13, tzinfo=UTC),
                    datetime(2026, 2, 15, tzinfo=UTC),
                )
            )
        )
    except ProxyPolicyError as error:  # pragma: no cover - network dependent
        pytest.skip(f"CONNECT/proxy policy blocked the live host: {error}")
    except Exception as error:  # pragma: no cover - network dependent
        failure_message = sanitize_error_text(
            str(error), connector.page_url(offset=0), SECRET_QUERY_PARAMETERS
        )
    finally:
        client.close()

    if failure_message is not None:  # pragma: no cover - network dependent
        pytest.fail(
            f"complete live data.gov.in traversal failed: {failure_message}",
            pytrace=False,
        )

    assert items is not None
    assert observed_total is not None
    assert observed_total > 0
    assert len(items) == observed_total
    assert len(requested_offsets) > 1
    assert requested_offsets[0] == 0
    assert requested_offsets == sorted(set(requested_offsets))
    assert all(item.metadata["resource_id"] == RESOURCE_ID for item in items)
