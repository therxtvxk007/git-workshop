"""One live GDELT file. Manually triggered, never part of ordinary CI.

Ordinary CI must stay offline: a green build has to mean "the code is correct",
never "GDELT happened to be reachable". But an entirely offline connector suite
cannot tell you that the URL scheme still exists, that the column count has not
changed, or that egress works through this network's proxy -- and those are
exactly the things that break silently.

So this runs on demand:

    PRAMAANX_LIVE_GDELT=1 uv run pytest tests/network -m network -v

or through the ``live-gdelt`` GitHub Actions workflow. It fetches a single
15-minute export file. Proxy settings come from the standard environment
(``HTTPS_PROXY`` and friends) or from ``--proxy``/``--ca-bundle`` style source
config; see :mod:`pramaanx.ingest.http`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.gdelt import GdeltConnector, slot_times
from pramaanx.ingest.http import HttpFetchError, ProxyPolicyError

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("PRAMAANX_LIVE_GDELT") != "1",
        reason="live GDELT test is opt-in; set PRAMAANX_LIVE_GDELT=1",
    ),
]


def recent_window() -> FetchWindow:
    """A window a few hours back, so the file is certainly published."""
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    return FetchWindow(end - timedelta(minutes=30), end)


def proxy_options() -> dict[str, object]:
    options: dict[str, object] = {"cache": False, "max_rows_per_file": 25, "max_attempts": 2}
    if bundle := os.environ.get("PRAMAANX_CA_BUNDLE"):
        options["ca_bundle"] = bundle
    if proxy := os.environ.get("PRAMAANX_HTTP_PROXY"):
        options["proxy"] = proxy
    return options


def test_one_live_export_file_parses() -> None:
    connector = GdeltConnector(Settings(), proxy_options())
    window = recent_window()
    assert slot_times(window, lag_minutes=connector.publication_lag_minutes)

    try:
        items = list(connector.guarded_fetch(window))
    except ProxyPolicyError as error:  # pragma: no cover - network dependent
        # A policy denial is a fact about this network, not a code regression.
        # Skipping with the host named is the actionable outcome; retrying or
        # routing around it is not.
        pytest.skip(f"blocked by egress policy: {error}")
    except HttpFetchError as error:  # pragma: no cover - network dependent
        pytest.fail(
            f"live GDELT fetch failed: {error}. If this environment reaches the internet "
            "through a proxy, set HTTPS_PROXY (and PRAMAANX_CA_BUNDLE if it terminates TLS)."
        )

    assert items, "GDELT returned no rows; the export format or URL scheme may have changed"
    item = items[0]
    assert window.contains(item.first_observed_at)
    assert item.payload.startswith(b"{")
    # The two properties that would silently corrupt a ledger if GDELT changed.
    assert b'"event_root_code"' in item.payload
    assert b"EthnicCode" not in item.payload
