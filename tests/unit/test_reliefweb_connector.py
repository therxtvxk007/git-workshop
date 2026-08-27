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
from urllib.parse import parse_qs, urlsplit

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import ConnectorError, FetchWindow
from pramaanx.ingest.connectors.reliefweb import (
    API_CONTRACT,
    API_VERSION,
    APPNAME_ENV,
    OFFICIAL_DOCS,
    REDACTED_APPNAME,
    REQUESTED_FIELDS,
    ReliefWebConnector,
    ReliefWebContractError,
    ReliefWebIncompleteIngestError,
    availability_of,
    instants_of,
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
        payload = fixture(pages[index] if index < len(pages) else "reports_empty")
        # A one-page test fixture represents a complete response, not page one
        # of the two-page pagination scenario encoded in reports_page1.json.
        if len(pages) == 1:
            document = json.loads(payload)
            document["totalCount"] = document["count"]
            return json.dumps(document).encode()
        return payload

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
        assert revised.metadata["revised_after_creation"] is True
        assert revised.metadata["date_created"].startswith("2025-11-04")

    def test_unrevised_report_publishes_and_becomes_available_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        items = list(
            connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW)
        )
        plain = next(item for item in items if item.metadata["report_id"] == "900001")
        assert plain.first_observed_at == plain.published_at
        assert plain.metadata["revised_after_creation"] is False

    def test_every_item_carries_required_provenance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = list(
            connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch).fetch(WINDOW)
        )
        assert items
        for item in items:
            assert item.source_version == f"reliefweb-{API_VERSION}-reports"
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

    def test_max_pages_fails_instead_of_returning_a_partial_walk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def never_ending(url: str) -> bytes:
            return envelope(report(), totalCount=100)

        with pytest.raises(ReliefWebIncompleteIngestError, match="max_pages=2"):
            list(connector(never_ending, monkeypatch=monkeypatch, max_pages=2).fetch(WINDOW))

    def test_an_empty_page_ends_the_walk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fetcher = paging_fetcher("reports_empty")
        assert list(connector(fetcher, monkeypatch=monkeypatch).fetch(WINDOW)) == []
        assert len(fetcher.calls) == 1

    def test_an_empty_page_with_reported_rows_remaining_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps({"totalCount": 10, "count": 0, "data": []}).encode()
        with pytest.raises(ReliefWebIncompleteIngestError, match="empty page"):
            list(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW))

    def test_a_page_cannot_extend_past_the_reported_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = envelope(report(900098), totalCount=2)
        second = envelope(report(900099), totalCount=1)
        calls = 0

        def shrinking_total(url: str) -> bytes:
            nonlocal calls
            calls += 1
            return first if calls == 1 else second

        with pytest.raises(ReliefWebIncompleteIngestError, match="totalCount from 2 to 1"):
            list(connector(shrinking_total, monkeypatch=monkeypatch, page_size=1).fetch(WINDOW))


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
                        "id": 900020,
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
                        "id": 900021,
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
        with pytest.raises(ReliefWebContractError, match="has no top-level id"):
            list(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW))

    def test_contract_keeps_three_verification_statuses_apart(self) -> None:
        # Documentation-verified is NOT live-verified, and neither is
        # fixture-tested. Collapsing them is how a claim becomes a lie.
        assert API_CONTRACT["official_docs_verified"] is True
        assert API_CONTRACT["official_docs_verified_on"] == "2026-08-26"
        assert API_CONTRACT["fixture_tested"] is True
        assert API_CONTRACT["live_api_verified"] is False
        assert "unverified" in API_CONTRACT["live_api_status"]
        assert API_CONTRACT["verification_route"].endswith("test_reliefweb_live.py")

    def test_the_official_sources_are_recorded(self) -> None:
        # A verification claim that does not say what it was checked against is
        # not auditable.
        assert API_CONTRACT["official_docs"] == list(OFFICIAL_DOCS)
        assert "https://apidoc.reliefweb.int/fields-tables" in API_CONTRACT["official_docs"]
        assert "https://reliefweb.int/terms-conditions" in API_CONTRACT["official_docs"]


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

    def test_both_raw_availability_inputs_are_filtered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Changed-only misses records where changed is absent or precedes
        # created. Created-only misses reports revised into the window.
        url = connector(monkeypatch=monkeypatch).build_url(WINDOW, offset=0)
        assert "date.changed" in url
        assert "date.created" in url

    def test_requested_fields_are_exactly_the_declared_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        query = parse_qs(
            urlsplit(connector(monkeypatch=monkeypatch).build_url(WINDOW, offset=0)).query
        )
        assert query["fields[include][]"] == list(REQUESTED_FIELDS)

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


def envelope(*records: dict[str, Any], **overrides: Any) -> bytes:
    """A well-formed envelope, then whatever the test wants to break about it."""
    document: dict[str, Any] = {
        "totalCount": len(records),
        "count": len(records),
        "data": list(records),
    }
    document.update(overrides)
    for key in [k for k, v in overrides.items() if v is _ABSENT]:
        document.pop(key, None)
    return json.dumps(document).encode()


_ABSENT = object()


def report(
    rid: int = 900500,
    *,
    created: str = "2026-03-02T00:00:00+00:00",
    changed: str | None = "2026-03-02T00:00:00+00:00",
    original: str | None = None,
    **field_overrides: Any,
) -> dict[str, Any]:
    dates: dict[str, Any] = {"created": created}
    if changed is not None:
        dates["changed"] = changed
    if original is not None:
        dates["original"] = original
    fields: dict[str, Any] = {"title": f"Synthetic {rid}", "date": dates}
    fields.update(field_overrides)
    return {"id": rid, "fields": fields}


class TestApiVersionIsSingleSourced:
    """v2 everywhere, from one constant, with no v1 literal left anywhere."""

    def test_the_contract_declares_v2(self) -> None:
        assert API_VERSION == "v2"
        assert API_CONTRACT["api_version"] == "v2"

    def test_url_payload_and_source_version_agree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = connector(paging_fetcher("reports_page1"), monkeypatch=monkeypatch)
        url = conn.build_url(WINDOW, offset=0)
        item = next(iter(conn.fetch(WINDOW)))
        assert f"/{API_VERSION}/" in url
        assert json.loads(item.payload)["api_version"] == API_VERSION
        assert item.source_version == f"reliefweb-{API_VERSION}-reports"
        assert conn.source_record.source_version == f"reliefweb-{API_VERSION}-reports"

    def test_no_v1_literal_survives_in_the_tree(self) -> None:
        # One authoritative constant means one place to change. A stray
        # "reliefweb-v1-" or an /v1 base URL would be provenance that lies.
        root = Path(__file__).resolve().parents[2]
        offenders = []
        for path in sorted(root.glob("src/**/*.py")) + sorted(root.glob("configs/**/*.yaml")):
            text = path.read_text(encoding="utf-8")
            if "reliefweb-v1-" in text or "api.reliefweb.int/v1" in text:
                offenders.append(str(path.relative_to(root)))
        assert offenders == []


class TestEnvelopeStrictness:
    """totalCount is required. The old fallback could truncate a window silently."""

    def _fetch(self, payload: bytes, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
        return list(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW))

    def test_missing_total_count_raises_even_when_count_is_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exact defect: falling back to count would make a first page of 1
        # look like a complete result set of 1, and the walk would stop.
        payload = envelope(report(900501), totalCount=_ABSENT)
        with pytest.raises(ReliefWebContractError, match="has no 'totalCount'"):
            self._fetch(payload, monkeypatch)

    def test_a_truncated_walk_cannot_masquerade_as_a_complete_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression proof, stated as the hazard rather than the mechanism: a
        # response with no totalCount must never yield a quietly-short result.
        pages = [envelope(report(900510), totalCount=_ABSENT), envelope(report(900511))]
        calls: list[str] = []

        def fetch(url: str) -> bytes:
            calls.append(url)
            return pages[min(len(calls) - 1, len(pages) - 1)]

        with pytest.raises(ReliefWebContractError):
            list(connector(fetch, monkeypatch=monkeypatch, page_size=1).fetch(WINDOW))
        assert len(calls) == 1, "the walk must abort, not continue on a broken envelope"

    def test_both_totals_absent_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = envelope(report(900502), totalCount=_ABSENT, count=_ABSENT)
        with pytest.raises(ReliefWebContractError, match="has no 'totalCount'"):
            self._fetch(payload, monkeypatch)

    def test_missing_count_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = envelope(report(900503), count=_ABSENT)
        with pytest.raises(ReliefWebContractError, match="has no 'count'"):
            self._fetch(payload, monkeypatch)

    @pytest.mark.parametrize("key", ["totalCount", "count"])
    def test_boolean_totals_are_refused(self, key: str, monkeypatch: pytest.MonkeyPatch) -> None:
        # bool is a subclass of int; True would sail through isinstance(x, int)
        # and then be compared against an offset.
        payload = envelope(report(900504), **{key: True})
        with pytest.raises(ReliefWebContractError, match=f"non-integer {key}"):
            self._fetch(payload, monkeypatch)

    @pytest.mark.parametrize("key", ["totalCount", "count"])
    def test_negative_totals_are_refused(self, key: str, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = envelope(report(900505), **{key: -1})
        with pytest.raises(ReliefWebContractError, match=f"negative {key}"):
            self._fetch(payload, monkeypatch)

    @pytest.mark.parametrize("key", ["totalCount", "count"])
    def test_non_integer_totals_are_refused(
        self, key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = envelope(report(900506), **{key: "5"})
        with pytest.raises(ReliefWebContractError, match=f"non-integer {key}"):
            self._fetch(payload, monkeypatch)

    def test_count_disagreeing_with_data_length_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = envelope(report(900507), count=7, totalCount=9)
        with pytest.raises(ReliefWebContractError, match="but returned 1 items"):
            self._fetch(payload, monkeypatch)

    def test_total_below_count_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = envelope(report(900508), report(900509), totalCount=1)
        with pytest.raises(ReliefWebContractError, match="below count"):
            self._fetch(payload, monkeypatch)

    def test_a_non_object_item_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps({"totalCount": 2, "count": 2, "data": [report(900512), "oops"]})
        with pytest.raises(ReliefWebContractError, match=r"data\[1\] is str"):
            self._fetch(payload.encode(), monkeypatch)

    def test_a_well_formed_envelope_still_parses(self) -> None:
        entries, total = ReliefWebConnector.parse_envelope(
            envelope(report(900513), totalCount=42), url="<test>"
        )
        assert total == 42
        assert [entry["id"] for entry in entries] == [900513]


class TestItemIdContract:
    """Top-level integer id, with no silent substitution from fields.id."""

    def _fetch(self, entry: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[Any]:
        payload = envelope(entry)
        return list(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW))

    def test_a_missing_top_level_id_is_not_taken_from_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = report(900520)
        entry["fields"]["id"] = 900520
        del entry["id"]
        with pytest.raises(ReliefWebContractError, match="has no top-level id"):
            self._fetch(entry, monkeypatch)

    def test_a_string_id_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = report(900521)
        entry["id"] = "900521"
        with pytest.raises(ReliefWebContractError, match="is str, not the integer"):
            self._fetch(entry, monkeypatch)

    def test_a_boolean_id_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = report(900522)
        entry["id"] = True
        with pytest.raises(ReliefWebContractError, match="is bool, not the integer"):
            self._fetch(entry, monkeypatch)

    def test_fields_id_must_match_the_top_level_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = report(900523)
        entry["fields"]["id"] = 900999
        with pytest.raises(ReliefWebContractError, match=r"disagrees with fields\.id"):
            self._fetch(entry, monkeypatch)

    def test_a_non_integer_fields_id_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = report(900524)
        entry["fields"]["id"] = "900524"
        with pytest.raises(ReliefWebContractError, match=r"non-integer fields\.id"):
            self._fetch(entry, monkeypatch)

    def test_a_matching_pair_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = report(900525)
        entry["fields"]["id"] = 900525
        items = self._fetch(entry, monkeypatch)
        assert [item.metadata["report_id"] for item in items] == ["900525"]

    def test_fields_id_may_be_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        items = self._fetch(report(900526), monkeypatch)
        assert [item.metadata["report_id"] for item in items] == ["900526"]


class TestTemporalFidelity:
    """Raw created/changed/original are preserved; nothing is substituted."""

    def test_absent_changed_is_null_not_a_computed_instant(self) -> None:
        # The defect this replaces: metadata.date_changed used to carry the
        # computed availability, so a record the API never said was modified
        # looked as though it had been.
        instants = instants_of({"created": "2026-03-02T00:00:00+00:00"})
        assert instants.changed is None
        assert instants.availability == instants.created
        assert instants.revised_after_creation is False

    def test_absent_changed_reaches_metadata_as_null(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = envelope(report(900530, changed=None))
        item = next(iter(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW)))
        assert item.metadata["date_changed"] is None
        assert item.metadata["date_availability"] == item.metadata["date_created"]
        assert item.metadata["revised_after_creation"] is False

    def test_published_at_is_original_when_present_not_the_minimum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # min(original, created) and "original when present" agree only while
        # original is the earlier one. When it is not, the old code silently
        # published the ReliefWeb posting date instead of the document's own.
        payload = envelope(
            report(
                900531,
                created="2026-03-02T00:00:00+00:00",
                changed="2026-03-03T00:00:00+00:00",
                original="2026-03-02T12:00:00+00:00",
            )
        )
        item = next(iter(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW)))
        assert item.published_at == datetime(2026, 3, 2, 12, tzinfo=UTC)
        assert item.metadata["date_original"].startswith("2026-03-02T12")

    def test_original_earlier_than_created_is_the_publication_date(self) -> None:
        instants = instants_of(
            {
                "created": "2026-03-02T00:00:00+00:00",
                "changed": "2026-03-02T00:00:00+00:00",
                "original": "2025-11-03T00:00:00+00:00",
            }
        )
        assert instants.published == datetime(2025, 11, 3, tzinfo=UTC)
        assert instants.availability == datetime(2026, 3, 2, tzinfo=UTC)

    def test_original_after_availability_is_an_anomaly_not_a_silent_clamp(self) -> None:
        # Clamping published_at down would rewrite what the record says about
        # itself; raising availability would import the document's own date
        # into the field admission depends on. Both are worse than failing.
        with pytest.raises(ReliefWebContractError, match="postdates availability"):
            instants_of(
                {
                    "created": "2026-03-02T00:00:00+00:00",
                    "changed": "2026-03-02T00:00:00+00:00",
                    "original": "2026-03-04T00:00:00+00:00",
                }
            )

    def test_the_anomaly_names_the_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = envelope(
            report(
                900532,
                created="2026-03-02T00:00:00+00:00",
                changed="2026-03-02T00:00:00+00:00",
                original="2026-03-04T00:00:00+00:00",
            )
        )
        with pytest.raises(ReliefWebContractError, match="report 900532"):
            list(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW))

    def test_changed_earlier_than_created_does_not_move_availability_back(self) -> None:
        instants = instants_of(
            {
                "created": "2026-03-02T00:00:00+00:00",
                "changed": "2026-03-01T00:00:00+00:00",
            }
        )
        assert instants.availability == datetime(2026, 3, 2, tzinfo=UTC)
        assert instants.changed == datetime(2026, 3, 1, tzinfo=UTC)
        assert instants.revised_after_creation is False

    @pytest.mark.parametrize(
        "changed",
        [None, "2026-02-28T00:00:00+00:00"],
        ids=["changed-absent", "changed-before-created"],
    )
    def test_created_in_window_candidates_are_not_silently_lost(
        self,
        changed: str | None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        payload = envelope(
            report(
                900534,
                created="2026-03-02T00:00:00+00:00",
                changed=changed,
            )
        )
        items = list(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW))
        assert [item.metadata["report_id"] for item in items] == ["900534"]

    def test_mixed_timezone_offsets_are_compared_in_utc(self) -> None:
        # created 08:00 UTC, changed 07:30 UTC, original 06:00 UTC -- all three
        # written in different offsets. A naive string comparison would order
        # these wrongly.
        instants = instants_of(
            {
                "created": "2026-03-02T13:30:00+05:30",
                "changed": "2026-03-02T02:30:00-05:00",
                "original": "2026-03-02T07:00:00+01:00",
            }
        )
        assert instants.created == datetime(2026, 3, 2, 8, tzinfo=UTC)
        assert instants.changed == datetime(2026, 3, 2, 7, 30, tzinfo=UTC)
        assert instants.original == datetime(2026, 3, 2, 6, tzinfo=UTC)
        assert instants.availability == datetime(2026, 3, 2, 8, tzinfo=UTC)
        assert instants.revised_after_creation is False

    def test_all_four_instants_appear_in_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = envelope(
            report(
                900533,
                created="2026-03-02T00:00:00+00:00",
                changed="2026-03-03T00:00:00+00:00",
                original="2026-02-01T00:00:00+00:00",
            )
        )
        item = next(iter(connector(lambda url: payload, monkeypatch=monkeypatch).fetch(WINDOW)))
        assert item.metadata["date_created"].startswith("2026-03-02")
        assert item.metadata["date_changed"].startswith("2026-03-03")
        assert item.metadata["date_original"].startswith("2026-02-01")
        assert item.metadata["date_availability"].startswith("2026-03-03")
        assert item.metadata["revised_after_creation"] is True


class TestFilterQuerySemantics:
    """The generated query, parsed. Substring checks would pass on bad nesting."""

    def query(self, monkeypatch: pytest.MonkeyPatch, **options: Any) -> dict[str, list[str]]:
        url = connector(monkeypatch=monkeypatch, **options).build_url(WINDOW, offset=0)
        return parse_qs(urlsplit(url).query, keep_blank_values=True)

    def test_the_outer_operator_is_always_and(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Emitted even with only the date condition, so adding a filter later
        # cannot change the query's meaning.
        assert self.query(monkeypatch)["filter[operator]"] == ["AND"]
        assert self.query(monkeypatch, countries=["IND"])["filter[operator]"] == ["AND"]

    def test_the_date_union_uses_from_and_to_for_both_raw_instants(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        query = self.query(monkeypatch)
        prefix = "filter[conditions][0]"
        assert query[f"{prefix}[operator]"] == ["OR"]
        assert query[f"{prefix}[conditions][0][field]"] == ["date.created"]
        assert query[f"{prefix}[conditions][1][field]"] == ["date.changed"]
        for index in (0, 1):
            assert query[f"{prefix}[conditions][{index}][value][from]"] == [
                "2026-03-01T00:00:00+00:00"
            ]
            assert query[f"{prefix}[conditions][{index}][value][to]"] == [
                "2026-03-05T00:00:00+00:00"
            ]

    def test_multiple_values_in_one_condition_are_explicitly_or(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # "any of these countries" is a union. An implicit AND here asks for a
        # report filed under every listed country at once and returns nothing.
        query = self.query(monkeypatch, countries=["IND", "PAK", "BGD"])
        assert query["filter[conditions][1][field]"] == ["country.iso3"]
        assert query["filter[conditions][1][value][]"] == ["IND", "PAK", "BGD"]
        assert query["filter[conditions][1][operator]"] == ["OR"]

    def test_a_single_value_condition_needs_no_inner_operator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        query = self.query(monkeypatch, countries=["IND"])
        assert query["filter[conditions][1][value][]"] == ["IND"]
        assert "filter[conditions][1][operator]" not in query

    def test_each_filter_gets_its_own_condition_index(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        query = self.query(
            monkeypatch,
            languages=["en", "fr"],
            countries=["IND"],
            disaster_types=["Flood", "Drought"],
            formats=["Situation Report"],
        )
        assert query["filter[conditions][0][operator]"] == ["OR"]
        assert query["filter[conditions][0][conditions][0][field]"] == ["date.created"]
        assert query["filter[conditions][0][conditions][1][field]"] == ["date.changed"]
        assert query["filter[conditions][1][field]"] == ["language.code"]
        assert query["filter[conditions][2][field]"] == ["country.iso3"]
        assert query["filter[conditions][3][field]"] == ["disaster_type.name"]
        assert query["filter[conditions][4][field]"] == ["format.name"]
        assert query["filter[conditions][1][operator]"] == ["OR"]
        assert query["filter[conditions][3][operator]"] == ["OR"]
        assert "filter[conditions][2][operator]" not in query
        assert "filter[conditions][4][operator]" not in query

    def test_sort_is_a_total_order_on_two_documented_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self.query(monkeypatch)["sort[]"] == ["date.changed:asc", "id:asc"]

    def test_pagination_and_profile_parameters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        query = self.query(monkeypatch, page_size=250)
        assert query["limit"] == ["250"]
        assert query["offset"] == ["0"]
        assert query["profile"] == ["list"]
        assert query["appname"] == ["pramaanx-test"]

    def test_page_size_stays_inside_the_documented_bounds(self) -> None:
        from pydantic import ValidationError

        from pramaanx.config import ReliefWebSourceConfig

        assert ReliefWebSourceConfig(page_size=1000).page_size == 1000
        with pytest.raises(ValidationError):
            ReliefWebSourceConfig(page_size=1001)

    def test_the_url_targets_the_v2_reports_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        url = connector(monkeypatch=monkeypatch).build_url(WINDOW, offset=0)
        assert urlsplit(url).path == f"/{API_VERSION}/reports"
        assert urlsplit(url).netloc == "api.reliefweb.int"


class TestPlanWithholdsTheCallerIdentity:
    def test_the_serialised_plan_contains_no_appname_anywhere(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Serialising the whole plan is the point: a leak can hide in any
        # nested value, and `--dry-run` prints the whole thing.
        monkeypatch.setenv(APPNAME_ENV, "secret-caller-identity")
        plan = connector(monkeypatch=monkeypatch).plan(WINDOW)
        assert "secret-caller-identity" not in json.dumps(plan)

    def test_the_plan_reports_configuration_without_the_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "secret-caller-identity")
        plan = connector(monkeypatch=monkeypatch).plan(WINDOW)
        assert plan["appname"] == REDACTED_APPNAME
        assert plan["appname_configured"] is True
        assert plan["appname_source"] == APPNAME_ENV
        assert "appname=REDACTED" in plan["first_request_url"]

    def test_a_config_supplied_appname_is_withheld_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(APPNAME_ENV, raising=False)
        conn = ReliefWebConnector(Settings(), {"cache": False, "appname": "secret-from-config"})
        plan = conn.plan(WINDOW)
        assert "secret-from-config" not in json.dumps(plan)
        assert plan["appname_source"] == "config"

    def test_the_plan_states_both_verification_statuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plan = connector(monkeypatch=monkeypatch).plan(WINDOW)
        assert plan["official_docs_verified"] is True
        assert plan["live_api_verified"] is False
        assert plan["api_version"] == API_VERSION


class TestPaginationLimitationIsStated:
    def test_the_source_record_admits_offset_pagination_can_omit_records(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Deduplication proves nothing was repeated. Nothing here proves
        # nothing was missed, and the notes must not imply otherwise.
        notes = connector(monkeypatch=monkeypatch).source_record.notes or ""
        assert "omit records" in notes
        assert "overlap" in notes

    def test_the_contract_records_the_residual_limitation(self) -> None:
        assert "concurrent-mutation" in API_CONTRACT["pagination"]["residual_limitation"]
