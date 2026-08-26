"""ACLED connector contract tests; all records are synthetic and offline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.acled import (
    API_CONTRACT,
    REQUESTED_FIELDS,
    AcledAuthenticationError,
    AcledConnector,
    AcledContractError,
    AcledIncompleteIngestError,
    parse_envelope,
    parse_token_response,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "acled"
WINDOW = FetchWindow(datetime(2026, 1, 10, tzinfo=UTC), datetime(2026, 1, 12, tzinfo=UTC))


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def document(name: str) -> dict[str, Any]:
    return json.loads(fixture(name))


class StubHttp:
    def __init__(
        self,
        pages: dict[str, bytes] | None = None,
        token_payload: bytes = b'{"token_type":"Bearer","expires_in":86400,"access_token":"fresh"}',
    ) -> None:
        self.pages = pages or {"0": fixture("page1.json"), "2": fixture("page2.json")}
        self.token_payload = token_payload
        self.get_calls: list[tuple[str, dict[str, str]]] = []
        self.post_calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> bytes:
        self.get_calls.append((url, dict(headers or {})))
        cursor = parse_qs(urlparse(url).query)["cursor"][0]
        return self.pages[cursor]

    def post_form(
        self, url: str, form: dict[str, str], *, headers: dict[str, str] | None = None
    ) -> bytes:
        self.post_calls.append((url, dict(form)))
        return self.token_payload


def connector(
    http: StubHttp | None = None,
    *,
    environ: dict[str, str] | None = None,
    options: dict[str, Any] | None = None,
) -> AcledConnector:
    chosen = {"page_size": 1, "countries": ["India"], **(options or {})}
    return AcledConnector(
        Settings(),
        chosen,
        environ={"PRAMAANX_ACLED_ACCESS_TOKEN": "secret-token"} if environ is None else environ,
        http_client=http or StubHttp(),  # type: ignore[arg-type]
    )


class TestOfficialContract:
    def test_documentation_verification_and_live_verification_are_separate(self) -> None:
        assert API_CONTRACT["verified_against_official_docs"] is True
        assert API_CONTRACT["verified_on"] == "2026-08-26"
        assert API_CONTRACT["genuinely_live_api_verified"] is False

    def test_current_contract_uses_oauth_and_cursor_pagination(self) -> None:
        assert "OAuth" in API_CONTRACT["authentication"]
        assert API_CONTRACT["pagination"].startswith("cursor")

    def test_requested_fields_include_all_temporal_identifiers(self) -> None:
        assert {"event_id_cnty", "event_date", "timestamp"} <= set(REQUESTED_FIELDS)


class TestAuthentication:
    def test_preissued_access_token_never_calls_token_endpoint(self) -> None:
        http = StubHttp()
        items = list(connector(http).fetch(WINDOW))
        assert len(items) == 2
        assert http.post_calls == []
        assert all(call[1]["Authorization"] == "Bearer secret-token" for call in http.get_calls)

    def test_password_grant_uses_post_body_not_url(self) -> None:
        http = StubHttp()
        conn = connector(
            http,
            environ={
                "PRAMAANX_ACLED_USERNAME": "person@example.test",
                "PRAMAANX_ACLED_PASSWORD": "do-not-log",
            },
        )
        list(conn.fetch(WINDOW))
        assert len(http.post_calls) == 1
        url, form = http.post_calls[0]
        assert "do-not-log" not in url
        assert form["password"] == "do-not-log"
        assert form["grant_type"] == "password"
        assert form["client_id"] == "acled"

    def test_missing_credentials_fail_even_in_plan_without_network(self) -> None:
        http = StubHttp()
        conn = connector(http, environ={})
        with pytest.raises(AcledAuthenticationError, match="not configured"):
            conn.plan(WINDOW)
        assert http.get_calls == []
        assert http.post_calls == []

    def test_plan_redacts_credentials_and_does_no_network(self) -> None:
        http = StubHttp()
        plan = connector(http).plan(WINDOW)
        assert plan["credentials"] == "<redacted>"
        assert plan["credential_mode"] == "access_token"
        assert "secret-token" not in json.dumps(plan)
        assert http.get_calls == []
        assert http.post_calls == []

    @pytest.mark.parametrize(
        "payload",
        [
            b"not json",
            b"[]",
            b'{"token_type":"Bearer","expires_in":86400}',
            b'{"access_token":"x","token_type":"mac","expires_in":86400}',
            b'{"access_token":"x","token_type":"Bearer","expires_in":true}',
        ],
    )
    def test_bad_token_responses_fail_without_echoing_tokens(self, payload: bytes) -> None:
        with pytest.raises(AcledAuthenticationError) as error:
            parse_token_response(payload)
        assert 'access_token":"x' not in str(error.value)


class TestEnvelope:
    def test_fixture_page_parses(self) -> None:
        page = parse_envelope(fixture("page1.json"))
        assert page.count == 1
        assert page.total_count == 2
        assert page.next_cursor == "2"

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            (lambda body: body.pop("total_count"), "missing required"),
            (lambda body: body.__setitem__("count", True), "count must"),
            (lambda body: body.__setitem__("count", 0), "does not equal"),
            (lambda body: body.__setitem__("total_count", 0), "smaller"),
            (lambda body: body.__setitem__("data", ["not-object"]), "every data"),
            (lambda body: body.__setitem__("messages", ["review me"]), "operator review"),
            (lambda body: body.__setitem__("next_cursor", {}), "next_cursor"),
            (lambda body: body.__setitem__("success", False), "success"),
        ],
    )
    def test_malformed_envelopes_fail_closed(self, mutate: Any, message: str) -> None:
        body = document("page1.json")
        mutate(body)
        with pytest.raises(AcledContractError, match=message):
            parse_envelope(json.dumps(body).encode())

    def test_non_json_and_non_object_fail(self) -> None:
        with pytest.raises(AcledContractError, match="valid JSON"):
            parse_envelope(b"not-json")
        with pytest.raises(AcledContractError, match="must be an object"):
            parse_envelope(b"[]")


class TestCursorWalk:
    def test_complete_walk_yields_only_after_terminal_cursor(self) -> None:
        http = StubHttp()
        items = list(connector(http).fetch(WINDOW))
        assert len(items) == 2
        assert [parse_qs(urlparse(url).query)["cursor"][0] for url, _ in http.get_calls] == [
            "0",
            "2",
        ]

    def test_url_uses_timestamp_cursor_total_and_explicit_fields(self) -> None:
        query = parse_qs(urlparse(connector().page_url(WINDOW, "0")).query)
        assert query["cursor"] == ["0"]
        assert query["with_total"] == ["true"]
        assert query["country"] == ["India"]
        assert query["fields"][0].split("|") == list(REQUESTED_FIELDS)
        assert "timestamp" in query and "event_date" not in query

    def test_total_change_fails(self) -> None:
        second = document("page2.json")
        second["total_count"] = 3
        http = StubHttp({"0": fixture("page1.json"), "2": json.dumps(second).encode()})
        with pytest.raises(AcledIncompleteIngestError, match="total_count changed"):
            list(connector(http).fetch(WINDOW))

    def test_terminal_shortfall_fails(self) -> None:
        first = document("page1.json")
        first["next_cursor"] = None
        with pytest.raises(AcledIncompleteIngestError, match="expected 2"):
            list(connector(StubHttp({"0": json.dumps(first).encode()})).fetch(WINDOW))

    def test_cursor_cycle_fails(self) -> None:
        first = document("page1.json")
        first["next_cursor"] = 0
        with pytest.raises(AcledIncompleteIngestError, match="cursor cycle"):
            list(connector(StubHttp({"0": json.dumps(first).encode()})).fetch(WINDOW))

    def test_duplicate_id_across_pages_fails(self) -> None:
        second = document("page2.json")
        second["data"][0]["event_id_cnty"] = "INDTEST1"
        http = StubHttp({"0": fixture("page1.json"), "2": json.dumps(second).encode()})
        with pytest.raises(AcledIncompleteIngestError, match="duplicate event"):
            list(connector(http).fetch(WINDOW))

    def test_changed_restrictions_fail(self) -> None:
        second = document("page2.json")
        second["data_query_restrictions"] = {"countries": ["Other"]}
        http = StubHttp({"0": fixture("page1.json"), "2": json.dumps(second).encode()})
        with pytest.raises(AcledIncompleteIngestError, match="restrictions changed"):
            list(connector(http).fetch(WINDOW))

    def test_max_pages_is_not_silent_truncation(self) -> None:
        with pytest.raises(AcledIncompleteIngestError, match="max_pages=1"):
            list(connector(options={"max_pages": 1}).fetch(WINDOW))

    def test_empty_page_with_cursor_fails(self) -> None:
        body = document("empty.json")
        body["total_count"] = 1
        body["next_cursor"] = 2
        with pytest.raises(AcledIncompleteIngestError, match="empty page"):
            list(connector(StubHttp({"0": json.dumps(body).encode()})).fetch(WINDOW))


class TestInstantsAndRows:
    def test_api_timestamp_controls_availability_not_event_date(self) -> None:
        first = next(iter(connector().fetch(WINDOW)))
        assert first.first_observed_at == datetime(2026, 1, 10, 12, tzinfo=UTC)
        assert first.published_at == first.first_observed_at
        assert first.claimed_event_time == datetime(2026, 1, 9, tzinfo=UTC)
        assert first.first_observed_at > first.claimed_event_time

    def test_payload_is_deterministic_and_contains_restrictions(self) -> None:
        first = next(iter(connector().fetch(WINDOW)))
        second = next(iter(connector().fetch(WINDOW)))
        assert first.payload == second.payload
        payload = json.loads(first.payload)
        assert payload["event"]["event_id_cnty"] == "INDTEST1"
        assert payload["data_query_restrictions"]["countries"] == ["India"]

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("event_id_cnty", "", "event_id_cnty"),
            ("timestamp", True, "timestamp"),
            ("event_date", "09-01-2026", "YYYY-MM-DD"),
            ("year", 2025, "does not match"),
            ("latitude", 100.0, "outside"),
            ("fatalities", -1, "fatalities"),
        ],
    )
    def test_invalid_rows_fail(self, field: str, value: Any, message: str) -> None:
        body = document("page1.json")
        body["data"][0][field] = value
        body["total_count"] = 1
        body["next_cursor"] = None
        http = StubHttp({"0": json.dumps(body).encode()})
        with pytest.raises(AcledContractError, match=message):
            list(connector(http).fetch(WINDOW))


class TestSourceRecord:
    def test_terms_and_living_dataset_limit_are_recorded(self) -> None:
        record = connector().source_record
        assert record.redistributable is False
        assert "EULA" in record.licence
        assert "living dataset" in (record.notes or "")
        assert record.source_version.endswith("2026-08-26")

    def test_test_records_are_synthetic(self) -> None:
        assert "hand-written synthetic" in (FIXTURES / "README.md").read_text().lower()
