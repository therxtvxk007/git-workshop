"""One live ReliefWeb request. Opt-in, and the only thing that verifies the contract.

Everything the connector believes about the wire format lives in
``API_CONTRACT``, and it was written without access to ReliefWeb's official
documentation -- the development environment had no route to reliefweb.int.
Fixture tests prove the connector's logic; they cannot prove the shape is real.
This test can, and until it has actually run and passed, the contract is an
assertion.

Run it deliberately:

    PRAMAANX_LIVE_RELIEFWEB=1 PRAMAANX_RELIEFWEB_APPNAME=your-app \\
      uv run pytest tests/network -m network -v

Skips (never silently passes) when not enabled, when no appname is configured,
or when egress is blocked. A skip is not a verification, and the report must
not describe it as one.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.reliefweb import (
    API_CONTRACT,
    APPNAME_ENV,
    ReliefWebConnector,
    ReliefWebContractError,
)
from pramaanx.ingest.http import HttpFetchError, ProxyPolicyError, RateLimitError

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("PRAMAANX_LIVE_RELIEFWEB") != "1",
        reason="live ReliefWeb test is opt-in; set PRAMAANX_LIVE_RELIEFWEB=1",
    ),
    pytest.mark.skipif(
        not os.environ.get(APPNAME_ENV, "").strip(),
        reason=f"ReliefWeb requires caller identification; set {APPNAME_ENV}",
    ),
]


def recent_window() -> FetchWindow:
    """A few days back, so there is certainly something posted."""
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return FetchWindow(end - timedelta(days=3), end)


def live_connector() -> ReliefWebConnector:
    options: dict[str, object] = {"cache": False, "page_size": 5, "max_items": 5, "max_attempts": 2}
    if bundle := os.environ.get("PRAMAANX_CA_BUNDLE"):
        options["ca_bundle"] = bundle
    if proxy := os.environ.get("PRAMAANX_HTTP_PROXY"):
        options["proxy"] = proxy
    return ReliefWebConnector(Settings(), options)


def fetch_or_skip(connector: ReliefWebConnector, window: FetchWindow) -> list:
    try:
        return list(connector.guarded_fetch(window))
    except ProxyPolicyError as error:  # pragma: no cover - network dependent
        pytest.skip(f"blocked by egress policy: {error}")
    except RateLimitError as error:  # pragma: no cover - network dependent
        pytest.skip(f"rate limited by ReliefWeb: {error}")
    except ReliefWebContractError as error:  # pragma: no cover - network dependent
        pytest.fail(
            f"the live API does not match API_CONTRACT: {error}\n"
            "This is the failure this test exists to catch. Update the contract and the "
            "parsing in src/pramaanx/ingest/connectors/reliefweb.py against the official "
            "documentation at https://apidoc.reliefweb.int/."
        )
    except HttpFetchError as error:  # pragma: no cover - network dependent
        pytest.fail(f"live ReliefWeb fetch failed: {error}")


def test_the_live_api_matches_the_asserted_contract() -> None:
    """Every assumption in API_CONTRACT, checked against the real service."""
    connector = live_connector()
    window = recent_window()
    items = fetch_or_skip(connector, window)

    assert items, (
        "ReliefWeb returned no reports for the last three days. Either the window logic or "
        "the filter syntax in build_url() is wrong -- an empty result here is a failure, "
        "not a quiet pass."
    )

    for item in items:
        # Availability, and the half-open window the base class also enforces.
        assert window.contains(item.first_observed_at)
        # Provenance every accepted item must carry.
        assert item.source_version == "reliefweb-v1-reports"
        assert item.licence and "ReliefWeb" in item.licence
        assert item.payload.startswith(b"{")
        assert b"appname=REDACTED" in item.payload

        decoded = json.loads(item.payload)
        fields = decoded["fields"]
        # The date fields the availability rule depends on.
        assert "date" in fields, "date object absent; the contract has drifted"
        assert "created" in fields["date"]
        assert "changed" in fields["date"]
        # Publication never postdates availability.
        assert item.published_at is not None
        assert item.published_at <= item.first_observed_at
        # Report metadata carries no event time, so none is invented.
        assert item.claimed_event_time is None


def test_pagination_reports_a_total() -> None:
    """totalCount is what the pagination loop terminates on."""
    connector = live_connector()
    window = recent_window()
    try:
        payload = connector._client_for()(connector.build_url(window, offset=0))
    except ProxyPolicyError as error:  # pragma: no cover - network dependent
        pytest.skip(f"blocked by egress policy: {error}")
    except HttpFetchError as error:  # pragma: no cover - network dependent
        pytest.fail(f"live ReliefWeb fetch failed: {error}")

    entries, total = ReliefWebConnector.parse_envelope(payload, url="<live>")
    assert isinstance(total, int) and total >= len(entries)
    assert API_CONTRACT["pagination"]["total_key"] == "totalCount"
