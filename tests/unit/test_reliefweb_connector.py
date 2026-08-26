"""ReliefWeb connector: temporal semantics, pagination, and refusal to guess.

Everything here runs against hand-written fixtures. That proves the connector's
*logic* -- ordering, deduplication, the availability rule, contract failures --
and proves nothing about whether the real API returns this shape. The only test
that can establish the latter is `tests/network/test_reliefweb_live.py`, which
is opt-in.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import ConnectorError, FetchWindow
from pramaanx.ingest.connectors.reliefweb import (
    API_CONTRACT,
    APPNAME_ENV,
    REQUESTED_FIELDS,
    ReliefWebConnector,
    ReliefWebContractError,
    availability_of,
    parse_api_datetime,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "reliefweb"
WINDOW = FetchWindow(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 5, tzinfo=UTC))


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def paging_fetcher(*names: str) -> Any:
    """Serve fixtures in order, one per request, recording the URLs asked for."""
    pages = list(names)
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        index = len(calls) - 1
        return fixture(pages[index] if index < len(pages) else "reports_empty")

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def connector(
    fetcher: Any = None, /, monkeypatch: pytest.MonkeyPatch | None = None, **options: Any
) -> ReliefWebConnector:
    if monkeypatch is not None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
    settings = Settings()
    return ReliefWebConnector(settings, {"cache": False, **options}, fetcher=fetcher)


class TestAvailabilityRule:
    """first_observed_at = max(date.created, date.changed). Never date.original."""

    def test_unrevised_report_is_available_when_created(self) -> None:
        dates = {"created": "2026-03-01T08:00:00+00:00", "changed": "2026-03-01T08:00:00+00:00"}
        assert availability_of(dates) == datetime(2026, 3, 1, 8, tzinfo=UTC)

    def test_revised_report_is_available_only_from_its_revision(self) -> None:
        # The body in hand is the revised body. Back-dating it to the original
        # posting would hand a 2025 cutoff a sentence written in 2026.
        dates = {"created": "2025-11-04T09:30:00+00:00", "changed": "2026-03-02T06:15:00+00:00"}
        assert availability_of(dates) == datetime(2026, 3, 2, 6, 15, tzinfo=UTC)

    def test_original_publication_date_never_sets_availability(self) -> None:
        dates = {
            "created": "2026-03-01T08:00:00+00:00",
            "changed": "2026-03-01T08:00:00+00:00",
            "original": "2019-01-01T00:00:00+00:00",
        }
        assert availability_of(dates).year == 2026

    def test_absent_changed_is_treated_as_never_revised(self) -> None:
        assert availability_of({"created": "2026-03-01T08:00:00+00:00"}) == datetime(
            2026, 3, 1, 8, tzinfo=UTC
        )

    def test_the_rule_is_declared_in_the_api_contract(self) -> None:
        assert API_CONTRACT["availability_rule"] == "max(date.created, date.changed)"


class TestTimestampParsing:
    def test_offsets_normalise_to_utc(self) -> None:
        assert parse_api_datetime("2026-03-01T13:30:00+05:30", field="t") == datetime(
            2026, 3, 1, 8, tzinfo=UTC
        )

    def test_naive_timestamps_are_refused(self) -> None:
        # Assuming UTC for a bare local time is how an hour of leakage gets in.
        with pytest.raises(ReliefWebContractError, match="no timezone offset"):
            parse_api_datetime("2026-03-01 08:00:00", field="date.created")

    def test_missing_timestamps_are_refused(self) -> None:
        with pytest.raises(ReliefWebContractError, match="missing or not a string"):
            parse_api_datetime(None, field="date.created")

    def test_nonsense_timestamps_are_refused(self) -> None:
        with pytest.raises(ReliefWebContractError, match="not an ISO-8601"):
            parse_api_datetime("last tuesday", field="date.created")


class TestItemMapping:
    def test_four_instants_are_kept_distinct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = list(
            connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW)
        )
        revised = next(item for item in items if item.metadata["report_id"] == "900003")

        # availability: the revision
        assert revised.first_observed_at == datetime(2026, 3, 2, 6, 15, tzinfo=UTC)
        # publication: the author's own date, earlier than the ReliefWeb posting
        assert revised.published_at == datetime(2025, 11, 3, tzinfo=UTC)
        # event time: not asserted by report metadata, so not invented
        assert revised.claimed_event_time is None
        # modification is preserved for audit
        assert revised.metadata["revised_after_publication"] is True
        assert revised.metadata["date_created"].startswith("2025-11-04")

    def test_unrevised_report_publishes_and_becomes_available_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        items = list(
            connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW)
        )
        plain = next(item for item in items if item.metadata["report_id"] == "900001")
        assert plain.first_observed_at == plain.published_at
        assert plain.metadata["revised_after_publication"] is False

    def test_every_item_carries_required_provenance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = list(
            connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW)
        )
        assert items
        for item in items:
            assert item.source_version == "reliefweb-v1-reports"
            assert item.uri and item.uri.startswith("https://")
            assert item.licence and "ReliefWeb" in item.licence
            assert item.language == "en"
            assert item.payload  # hashed by the ledger

    def test_payload_never_carries_the_caller_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The request URL is kept for provenance; the appname in it is not.
        monkeypatch.setenv(APPNAME_ENV, "secret-caller-identity")
        items = list(
            connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW)
        )
        for item in items:
            assert b"secret-caller-identity" not in item.payload
            assert b"appname=REDACTED" in item.payload

    def test_payload_is_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first = list(
            connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW)
        )
        second = list(
            connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW)
        )
        assert [item.payload for item in first] == [item.payload for item in second]

    def test_payload_is_canonical_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        item = next(
            iter(connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW))
        )
        decoded = json.loads(item.payload)
        assert decoded["source"] == "reliefweb"
        assert decoded["availability_basis"] == API_CONTRACT["availability_rule"]


class TestPagination:
    def test_pages_are_walked_until_the_total_is_reached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetcher = paging_fetcher("reports_page1", "reports_page2")
        items = list(connector(fetcher, monkeypatch=monkeypatch, page_size=3).fetch(WINDOW))
        assert len(fetcher.calls) == 2
        assert "offset=0" in fetcher.calls[0]
        assert "offset=3" in fetcher.calls[1]
        assert len(items) == 4

    def test_ordering_is_stable_and_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A date-only sort repeats or drops records at page boundaries when
        # timestamps collide, so the request asks for an id tiebreaker too.
        fetcher = paging_fetcher("reports_page1", "reports_page2")
        list(connector(fetcher, monkeypatch=monkeypatch).fetch(WINDOW))
        assert "sort%5B%5D=date.changed%3Aasc" in fetcher.calls[0]
        assert "sort%5B%5D=id%3Aasc" in fetcher.calls[0]

    def test_duplicate_records_across_pages_are_ingested_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 900003 appears on both fixture pages.
        items = list(
            connector(
                paging_fetcher("reports_page1", "reports_page2"),
                monkeypatch=monkeypatch,
                page_size=3,
            ).fetch(WINDOW)
        )
        ids = [item.metadata["report_id"] for item in items]
        assert ids.count("900003") == 1
        assert len(ids) == len(set(ids))

    def test_max_items_bounds_a_first_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = list(
            connector(
                paging_fetcher("reports_page1", "reports_page2"),
                monkeypatch=monkeypatch,
                max_items=2,
            ).fetch(WINDOW)
        )
        assert len(items) == 2

    def test_max_pages_stops_an_unbounded_walk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def never_ending(url: str) -> bytes:
            return fixture("reports_page1")

        items = list(connector(never_ending, monkeypatch=monkeypatch, max_pages=2).fetch(WINDOW))
        # Deduplication means the second page adds nothing, but the walk stops.
        assert len(items) == 3

    def test_an_empty_page_ends_the_walk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fetcher = paging_fetcher("reports_empty")
        assert list(connector(fetcher, monkeypatch=monkeypatch).fetch(WINDOW)) == []
        assert len(fetcher.calls) == 1


class TestWindowBoundaries:
    """FetchWindow is half-open; the API's range bounds are inclusive."""

    def test_items_outside_the_half_open_window_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The API may return a record exactly at the exclusive end bound.
        boundary = json.dumps(
            {
                "totalCount": 1,
                "count": 1,
                "data": [
                    {
                        "id": "900020",
                        "fields": {
                            "title": "Exactly at the end bound",
                            "date": {
                                "created": "2026-03-05T00:00:00+00:00",
                                "changed": "2026-03-05T00:00:00+00:00",
                            },
                        },
                    }
                ],
            }
        ).encode()
        assert list(connector(lambda url: boundary, monkeypatch=monkeypatch).fetch(WINDOW)) == []

    def test_an_item_exactly_at_the_start_bound_is_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        boundary = json.dumps(
            {
                "totalCount": 1,
                "count": 1,
                "data": [
                    {
                        "id": "900021",
                        "fields": {
                            "title": "Exactly at the start bound",
                            "date": {
                                "created": "2026-03-01T00:00:00+00:00",
                                "changed": "2026-03-01T00:00:00+00:00",
                            },
                        },
                    }
                ],
            }
        ).encode()
        items = list(connector(lambda url: boundary, monkeypatch=monkeypatch).fetch(WINDOW))
        assert [item.metadata["report_id"] for item in items] == ["900021"]

    def test_guarded_fetch_accepts_everything_fetch_emits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The base class re-checks the window; nothing the connector yields may
        # trip it.
        conn = connector(paging_fetcher("reports_page1", "reports_page2"), monkeypatch=monkeypatch)
        assert list(conn.guarded_fetch(WINDOW))


class TestContractFailures:
    """A shape the connector does not understand is an error, never a gap."""

    @pytest.mark.parametrize(
        ("name", "match"),
        [
            ("malformed_no_data", "no 'data' list"),
            ("malformed_api_error", "returned an API error"),
            ("partial_no_date", "has no date object"),
            ("partial_naive_timestamp", "no timezone offset"),
        ],
    )
    def test_malformed_responses_raise(
        self, name: str, match: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(ReliefWebContractError, match=match):
            list(connector(lambda url: fixture(name), monkeypatch=monkeypatch).fetch(WINDOW))

    def test_non_json_body_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(ReliefWebContractError, match="non-JSON body"):
            list(
                connector(lambda url: b"<html>maintenance</html>", monkeypatch=monkeypatch).fetch(
                    WINDOW
                )
            )

    def test_item_without_an_id_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps(
            {
                "totalCount": 1,
                "count": 1,
                "data": [{"fields": {"date": {"created": "2026-03-01T00:00:00+00:00"}}}],
            }
        ).encode()
        with pytest.raises(ReliefWebContractError, match="has no id"):
            list(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW))

    def test_contract_declares_itself_unverified(self) -> None:
        # Honest until the live test says otherwise.
        assert API_CONTRACT["verified_against_official_docs"] is False
        assert API_CONTRACT["verification_route"].endswith("test_reliefweb_live.py")


class TestAppname:
    def test_missing_appname_is_an_actionable_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(APPNAME_ENV, raising=False)
        conn = ReliefWebConnector(Settings(), {"cache": False}, fetcher=lambda url: b"{}")
        with pytest.raises(ConnectorError, match=APPNAME_ENV):
            list(conn.fetch(WINDOW))

    def test_config_appname_wins_over_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "from-environment")
        conn = ReliefWebConnector(Settings(), {"cache": False, "appname": "from-config"})
        assert conn.appname() == "from-config"

    def test_environment_is_used_when_config_is_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "from-environment")
        assert ReliefWebConnector(Settings(), {"cache": False}).appname() == "from-environment"

    def test_appname_reaches_the_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fetcher = paging_fetcher("reports_empty")
        list(connector(fetcher, monkeypatch=monkeypatch).fetch(WINDOW))
        assert "appname=pramaanx-test" in fetcher.calls[0]


class TestRequestBuilding:
    def test_filters_reach_the_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = connector(
            paging_fetcher("reports_empty"),
            monkeypatch=monkeypatch,
            languages=["en"],
            countries=["IND"],
            disaster_types=["Flood"],
            formats=["Situation Report"],
        )
        url = conn.build_url(WINDOW, offset=0)
        assert "language.code" in url
        assert "country.iso3" in url
        assert "Flood" in url
        assert "Situation+Report" in url
        assert "filter%5Boperator%5D=AND" in url

    def test_availability_field_is_what_is_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Filtering on date.created would miss reports revised into the window.
        url = connector(monkeypatch=monkeypatch).build_url(WINDOW, offset=0)
        assert "date.changed" in url
        assert "date.created" not in url.split("filter")[1] if "filter" in url else True

    def test_requested_fields_are_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        url = connector(monkeypatch=monkeypatch).build_url(WINDOW, offset=0)
        for name in REQUESTED_FIELDS:
            assert name.replace(".", ".") in url.replace("%5B", "[").replace("%5D", "]")

    def test_url_is_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = connector(monkeypatch=monkeypatch)
        assert conn.build_url(WINDOW, offset=0) == conn.build_url(WINDOW, offset=0)


class TestEgressConfiguration:
    def test_proxy_tls_and_ca_reach_the_http_client(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        conn = ReliefWebConnector(
            Settings(),
            {
                "proxy": "socks5://127.0.0.1:1080",
                "ca_bundle": "/etc/ssl/corp.pem",
                "trust_env": False,
                "timeout_seconds": 12.0,
                "max_attempts": 2,
                "min_interval_seconds": 1.5,
                "cache": False,
            },
        )
        client = conn._client_for().__self__  # type: ignore[attr-defined]
        assert client.proxy == "socks5://127.0.0.1:1080"
        assert client.ca_bundle == "/etc/ssl/corp.pem"
        assert client.trust_env is False
        assert client.timeout_seconds == 12.0
        assert client.max_attempts == 2
        assert client.min_interval_seconds == 1.5
        assert client.cache_dir is None

    def test_cache_directory_is_used_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        from pramaanx.config import StorageConfig

        settings = Settings(storage=StorageConfig(data_root=tmp_path / "data"))
        conn = ReliefWebConnector(settings, {"cache": True})
        client = conn._client_for().__self__  # type: ignore[attr-defined]
        assert client.cache_dir == tmp_path / "data" / "http_cache" / "reliefweb"


class TestSourceRecord:
    def test_licence_is_recorded_and_not_redistributable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        record = connector(monkeypatch=monkeypatch).source_record
        assert record.tier == 0
        assert record.redistributable is False
        assert "ReliefWeb" in record.licence
        assert record.licence_url
        assert "max(date.created" in (record.notes or "")

    def test_coverage_bias_is_stated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A source whose coverage follows operational response, not severity,
        # must say so where a modeller will read it.
        assert "response-driven" in (connector(monkeypatch=monkeypatch).source_record.notes or "")
