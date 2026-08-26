"""Live ReliefWeb requests. Opt-in, and the only thing that can verify the wire format.

What this test is for
---------------------
``API_CONTRACT`` was read from ReliefWeb's official documentation by external
review on 2026-08-26, so ``official_docs_verified`` is true. Documentation is
not a response. Nothing in this repository has ever parsed one: the development
environment's egress policy refuses CONNECT to ``api.reliefweb.int``, and
``live_api_verified`` is false because of it.

This module is what would change that. It checks a specific, enumerated list of
claims -- written out in :data:`LIVE_CHECKS` so the claim and the assertions can
be compared -- rather than asserting that it checks "every entry" in the
contract, which it never did.

What counts as a verification
-----------------------------
Only a completed run of these tests against the real service. Explicitly **not**
a verification:

* a skip, for any reason;
* an HTTP 403 from ReliefWeb (that is the origin refusing the caller, and it
  now *fails* this module rather than skipping it);
* a TLS tunnel that established;
* a URL that was constructed correctly;
* an empty result set.

Nothing here writes to ``API_CONTRACT``. Flipping ``live_api_verified`` is a
deliberate edit a human makes after reading a passing run.

Run it deliberately, with an appname ReliefWeb has approved:

    PRAMAANX_LIVE_RELIEFWEB=1 PRAMAANX_RELIEFWEB_APPNAME=your-approved-app \\
      uv run pytest tests/network -m network -v
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.reliefweb import (
    API_CONTRACT,
    API_VERSION,
    APPNAME_ENV,
    REQUESTED_FIELDS,
    ReliefWebConnector,
    ReliefWebContractError,
)
from pramaanx.ingest.http import (
    HttpFetchError,
    PermanentHttpError,
    ProxyPolicyError,
    RateLimitError,
)

#: Exactly what a completed run of this module establishes. Not "every entry in
#: API_CONTRACT" -- that claim was never true, and an overstated scope is worse
#: than a narrow one because it stops anyone looking for the gap.
LIVE_CHECKS = (
    "the v2 reports endpoint answers",
    "appname is accepted as the required query parameter",
    "the filter, sort and field parameters are accepted as constructed",
    "the raw envelope carries data, count and totalCount",
    "count equals len(data) and totalCount is at least count",
    "each item carries a top-level integer id beside a fields object",
    "fields.date carries created, and changed where the record has been revised",
    "parsed items carry this connector's provenance and source_version",
)

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("PRAMAANX_LIVE_RELIEFWEB") != "1",
        reason="live ReliefWeb test is opt-in; set PRAMAANX_LIVE_RELIEFWEB=1",
    ),
    pytest.mark.skipif(
        not os.environ.get(APPNAME_ENV, "").strip(),
        reason=(
            f"ReliefWeb requires a pre-approved appname; set {APPNAME_ENV}. "
            "Since 2025-11-01 the name must be approved by ReliefWeb in advance."
        ),
    ),
]

APPNAME_HINT = (
    "ReliefWeb refused this caller. The appname is mandatory and, since 2025-11-01, must be "
    "pre-approved: check that PRAMAANX_RELIEFWEB_APPNAME holds a name ReliefWeb has approved. "
    "This is NOT a blocked-egress skip -- the request reached the service and was rejected."
)


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


def raw_page_or_skip(connector: ReliefWebConnector, url: str) -> dict[str, Any]:
    """One page, decoded but NOT passed through the connector's parser.

    The parser is what is under test here. Reading the envelope raw is the only
    way to check the keys the official result structure promises rather than
    the keys this connector chose to look for.
    """
    try:
        payload = connector._client_for()(url)
    except ProxyPolicyError as error:  # pragma: no cover - network dependent
        # The only legitimate skip: the request never left the network.
        pytest.skip(f"egress policy denied the tunnel, so nothing was verified: {error}")
    except PermanentHttpError as error:  # pragma: no cover - network dependent
        if error.status_code == 403:
            pytest.fail(f"{APPNAME_HINT}\n{error}")
        pytest.fail(f"ReliefWeb refused the request permanently: {error}")
    except RateLimitError as error:  # pragma: no cover - network dependent
        pytest.skip(f"rate limited by ReliefWeb: {error}")
    except HttpFetchError as error:  # pragma: no cover - network dependent
        pytest.fail(f"live ReliefWeb fetch failed: {error}")

    document = json.loads(payload)
    assert isinstance(document, dict), "the API returned something that is not a JSON object"
    return document


def fetch_or_skip(connector: ReliefWebConnector, window: FetchWindow) -> list[Any]:
    try:
        return list(connector.guarded_fetch(window))
    except ProxyPolicyError as error:  # pragma: no cover - network dependent
        pytest.skip(f"egress policy denied the tunnel, so nothing was verified: {error}")
    except PermanentHttpError as error:  # pragma: no cover - network dependent
        if error.status_code == 403:
            pytest.fail(f"{APPNAME_HINT}\n{error}")
        pytest.fail(f"ReliefWeb refused the request permanently: {error}")
    except RateLimitError as error:  # pragma: no cover - network dependent
        pytest.skip(f"rate limited by ReliefWeb: {error}")
    except ReliefWebContractError as error:  # pragma: no cover - network dependent
        pytest.fail(
            f"the live API does not match API_CONTRACT: {error}\n"
            "This is the failure this module exists to catch. Correct the contract and the "
            "parsing in src/pramaanx/ingest/connectors/reliefweb.py against the official "
            "documentation at https://apidoc.reliefweb.int/."
        )
    except HttpFetchError as error:  # pragma: no cover - network dependent
        pytest.fail(f"live ReliefWeb fetch failed: {error}")


def test_the_request_is_built_against_the_v2_contract() -> None:
    """Offline half: what is sent. No excuse for getting this wrong on the wire."""
    connector = live_connector()
    url = connector.build_url(recent_window(), offset=0)
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)

    assert parts.path == f"/{API_VERSION}/reports"
    assert query["appname"], "appname is a required query parameter"
    assert query["profile"] == ["list"]
    assert query["fields[include][]"] == list(REQUESTED_FIELDS)
    assert query["sort[]"] == ["date.changed:asc", "id:asc"]
    assert query["filter[operator]"] == ["AND"]
    assert query["filter[conditions][0][field]"] == ["date.changed"]
    assert query["filter[conditions][0][value][from]"]
    assert query["filter[conditions][0][value][to]"]


def test_the_live_envelope_matches_the_documented_result_structure() -> None:
    """The raw response, before this connector's parser touches it."""
    connector = live_connector()
    url = connector.build_url(recent_window(), offset=0)
    document = raw_page_or_skip(connector, url)

    assert "error" not in document, f"the API returned an error envelope: {document.get('error')!r}"
    for key in ("data", "count", "totalCount"):
        assert key in document, (
            f"the live envelope has no {key!r}; the official result structure promises it "
            f"(keys present: {sorted(document)})"
        )

    total, count, data = document["totalCount"], document["count"], document["data"]
    assert isinstance(total, int) and not isinstance(total, bool)
    assert isinstance(count, int) and not isinstance(count, bool)
    assert isinstance(data, list)
    assert count == len(data), f"count={count} but the page holds {len(data)} items"
    assert total >= count, f"totalCount={total} is below count={count}"
    assert data, (
        "ReliefWeb returned no reports for the last three days. Either the window logic or the "
        "filter syntax in build_url() is wrong -- an empty result here is a failure, not a "
        "quiet pass."
    )


def test_live_items_carry_a_top_level_integer_id_and_a_fields_object() -> None:
    connector = live_connector()
    document = raw_page_or_skip(connector, connector.build_url(recent_window(), offset=0))

    for position, entry in enumerate(document["data"]):
        assert isinstance(entry, dict), f"data[{position}] is not an object"
        assert "id" in entry, f"data[{position}] has no top-level id"
        assert isinstance(entry["id"], int) and not isinstance(entry["id"], bool), (
            f"data[{position}] id is {entry['id']!r}, not the integer the fields table specifies"
        )
        assert isinstance(entry.get("fields"), dict), f"data[{position}] has no fields object"
        if "id" in entry["fields"]:
            assert entry["fields"]["id"] == entry["id"], "fields.id disagrees with the item id"

        dates = entry["fields"].get("date")
        assert isinstance(dates, dict), f"report {entry['id']} has no date object"
        assert "created" in dates, f"report {entry['id']} has no date.created"


def test_the_live_api_matches_the_asserted_contract() -> None:
    """The parsed half: what this connector makes of a real response."""
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
        assert item.source_version == f"reliefweb-{API_VERSION}-reports"
        assert item.licence and "ReliefWeb" in item.licence
        assert item.payload.startswith(b"{")
        assert b"appname=REDACTED" in item.payload

        decoded = json.loads(item.payload)
        assert decoded["api_version"] == API_VERSION
        fields = decoded["fields"]
        assert "date" in fields, "date object absent; the contract has drifted"
        assert "created" in fields["date"]
        # Publication never postdates availability.
        assert item.published_at is not None
        assert item.published_at <= item.first_observed_at
        # Report metadata carries no event time, so none is invented.
        assert item.claimed_event_time is None
        # The raw instants are preserved, and none is substituted for another.
        assert item.metadata["date_created"]
        assert item.metadata["date_availability"]
        if item.metadata["date_changed"] is None:
            assert item.metadata["revised_after_creation"] is False


def test_pagination_reports_a_total() -> None:
    """totalCount is what the pagination loop terminates on, and it is required."""
    connector = live_connector()
    document = raw_page_or_skip(connector, connector.build_url(recent_window(), offset=0))

    entries, total = ReliefWebConnector.parse_envelope(json.dumps(document).encode(), url="<live>")
    assert isinstance(total, int) and total >= len(entries)
    assert API_CONTRACT["pagination"]["total_key"] == "totalCount"


def test_this_module_does_not_overstate_what_it_verifies() -> None:
    """A meta-check, and the reason it is here is that the claim was once false.

    Runs without the network. The previous version of this file said it checked
    "every assumption in API_CONTRACT" while checking a handful, which is the
    kind of claim that stops anyone going to look.
    """
    assert len(LIVE_CHECKS) == 8
    assert API_CONTRACT["live_api_verified"] is False, (
        "live_api_verified is set true, but nothing in this repository sets it from a passing "
        "run -- it is a deliberate human edit after reading one. If a live run has genuinely "
        "passed, this assertion is what should be updated, and only then."
    )
    assert API_CONTRACT["official_docs_verified"] is True
