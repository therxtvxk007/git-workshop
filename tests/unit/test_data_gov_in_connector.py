"""Strict, fully offline tests for the data.gov.in resource connector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from pramaanx.config import Settings, StorageConfig
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.data_gov_in import (
    API_CONTRACT,
    API_KEY_ENV,
    DataGovInConnector,
    DataGovInContractError,
    DataGovInCredentialError,
    parse_envelope,
)
from pramaanx.ingest.http import PermanentHttpError, ProxyPolicyError
from pramaanx.ingest.ledger import EvidenceLedger

RESOURCE_ID = "869c674d-59a4-4de3-8b09-f2b709983f51"
AVAILABLE = datetime(2026, 2, 14, tzinfo=UTC)
WINDOW = FetchWindow(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
TEST_KEY = "fixture-credential-never-persist"


def options(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "resource_id": RESOURCE_ID,
        "resource_title": "Synthetic security aggregate",
        "resource_page_url": "https://www.data.gov.in/resource/synthetic-security-aggregate",
        "portal_published_date": "2026-02-13",
        "portal_updated_date": "2026-02-13",
        "available_at": AVAILABLE.isoformat(),
        "page_size": 2,
        "max_pages": 5,
        "max_items": 10,
        "cache": False,
    }
    base.update(overrides)
    return base


def envelope(
    records: list[object],
    *,
    total: object,
    offset: object,
    limit: object = 2,
    count: object | None = None,
    status: object = "ok",
) -> bytes:
    return json.dumps(
        {
            "status": status,
            "total": total,
            "count": len(records) if count is None else count,
            "limit": limit,
            "offset": offset,
            "records": records,
        }
    ).encode()


def connector(
    pages: dict[int, bytes] | None = None,
    *,
    config: dict[str, Any] | None = None,
    key: str = TEST_KEY,
    calls: list[str] | None = None,
) -> DataGovInConnector:
    page_map = pages or {0: envelope([], total=0, offset=0)}

    def fetch(url: str) -> bytes:
        if calls is not None:
            calls.append(url)
        offset = int(parse_qs(urlsplit(url).query)["offset"][0])
        return page_map[offset]

    return DataGovInConnector(
        Settings(),
        config or options(),
        fetcher=fetch,
        environ={API_KEY_ENV: key} if key else {},
    )


class TestPlanningAndRequests:
    def test_missing_api_key_fails_before_fetch(self) -> None:
        calls: list[str] = []
        target = connector(key="", calls=calls)
        with pytest.raises(DataGovInCredentialError, match=API_KEY_ENV):
            target.plan(WINDOW)
        assert calls == []

    def test_plan_is_deterministic_and_redacted(self) -> None:
        target = connector()
        first = target.plan(WINDOW)
        assert first == target.plan(WINDOW)
        rendered = json.dumps(first)
        assert TEST_KEY not in rendered
        assert first["api_key"] == {"configured": True, "source": API_KEY_ENV}
        assert first["would_fetch"] is True

    def test_request_path_and_parameter_order_are_exact(self) -> None:
        url = connector().page_url(offset=20)
        assert url.startswith(f"https://api.data.gov.in/resource/{RESOURCE_ID}?")
        assert url.split("?", 1)[1] == (f"api-key={TEST_KEY}&format=json&offset=20&limit=2")

    def test_window_without_availability_does_not_fetch(self) -> None:
        calls: list[str] = []
        target = connector(calls=calls)
        old = FetchWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
        assert list(target.guarded_fetch(old)) == []
        assert calls == []

    def test_dry_run_has_no_network_or_storage_side_effect(self, tmp_path: Path) -> None:
        def forbidden(url: str) -> bytes:
            raise AssertionError(f"network opened during dry-run: {url}")

        settings = Settings(
            storage=StorageConfig(data_root=tmp_path / "data", run_root=tmp_path / "runs")
        )
        target = DataGovInConnector(
            settings,
            options(),
            fetcher=forbidden,
            environ={API_KEY_ENV: TEST_KEY},
        )
        report = EvidenceLedger(settings).ingest(
            "data_gov_in", WINDOW, dry_run=True, connector=target
        )
        assert report.dry_run
        assert not (tmp_path / "data").exists()
        assert not (tmp_path / "runs").exists()


class TestEnvelopeContract:
    def test_contract_records_completed_live_verification(self) -> None:
        assert API_CONTRACT["genuinely_live_api_verified"] is True
        assert API_CONTRACT["live_verified_at"] == "2026-08-27"
        assert "forced multi-page" in API_CONTRACT["live_verification_scope"]

    def test_valid_page(self) -> None:
        records, total = parse_envelope(
            envelope([{"row": 1}], total=1, offset=0),
            expected_offset=0,
            expected_limit=2,
            expected_total=None,
        )
        assert records == [{"row": 1}]
        assert total == 1

    @pytest.mark.parametrize("field", ["status", "total", "count", "limit", "offset", "records"])
    def test_required_envelope_field(self, field: str) -> None:
        raw = json.loads(envelope([], total=0, offset=0))
        del raw[field]
        with pytest.raises(DataGovInContractError, match="missing required fields"):
            parse_envelope(
                json.dumps(raw).encode(),
                expected_offset=0,
                expected_limit=2,
                expected_total=None,
            )

    @pytest.mark.parametrize("field", ["total", "count"])
    @pytest.mark.parametrize("bad", [True, -1, "1", 1.5, None])
    def test_authoritative_counts_are_strict_integers(self, field: str, bad: object) -> None:
        raw = json.loads(envelope([], total=0, offset=0))
        raw[field] = bad
        with pytest.raises(DataGovInContractError, match=field):
            parse_envelope(
                json.dumps(raw).encode(),
                expected_offset=0,
                expected_limit=2,
                expected_total=None,
            )

    def test_live_observed_string_pagination_echoes_are_normalized(self) -> None:
        records, total = parse_envelope(
            envelope([{"row": 1}], total=1, offset="0", limit="2"),
            expected_offset=0,
            expected_limit=2,
            expected_total=None,
        )
        assert records == [{"row": 1}]
        assert total == 1

    @pytest.mark.parametrize("field", ["limit", "offset"])
    @pytest.mark.parametrize(
        "bad", [True, -1, 1.5, None, "", " 1", "+1", "01", "1.0", "1e0", "\uff11\uff12"]
    )
    def test_pagination_echoes_reject_ambiguous_values(self, field: str, bad: object) -> None:
        raw = json.loads(envelope([], total=0, offset=0))
        raw[field] = bad
        with pytest.raises(DataGovInContractError, match=field):
            parse_envelope(
                json.dumps(raw).encode(),
                expected_offset=0,
                expected_limit=2,
                expected_total=None,
            )

    @pytest.mark.parametrize("payload", [b"not-json", b"[]", b"\xff"])
    def test_non_object_json_is_rejected(self, payload: bytes) -> None:
        with pytest.raises(DataGovInContractError):
            parse_envelope(payload, expected_offset=0, expected_limit=2, expected_total=None)

    @pytest.mark.parametrize(
        "payload",
        [
            b'{"status":"ok","status":"ok","total":0,"count":0,"limit":2,"offset":0,"records":[]}',
            b'{"status":"ok","total":0,"count":0,"limit":2,"offset":0,"records":[],"x":NaN}',
        ],
    )
    def test_non_strict_json_extensions_are_rejected(self, payload: bytes) -> None:
        with pytest.raises(DataGovInContractError):
            parse_envelope(payload, expected_offset=0, expected_limit=2, expected_total=None)

    def test_non_object_record_is_rejected(self) -> None:
        with pytest.raises(DataGovInContractError, match="entry must be an object"):
            parse_envelope(
                envelope(["not-an-object"], total=1, offset=0),
                expected_offset=0,
                expected_limit=2,
                expected_total=None,
            )

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            (envelope([{"x": 1}], total=1, offset=0, count=0), "records length"),
            (envelope([{"x": 1}], total=0, offset=0), "exceeds total"),
            (envelope([], total=1, offset=0), "empty page"),
            (envelope([], total=0, offset=1), "pagination echo"),
            (envelope([], total=0, offset=0, limit=1), "pagination echo"),
            (envelope([], total=0, offset=0, status="error"), "status is not"),
        ],
    )
    def test_internal_inconsistency_is_rejected(self, payload: bytes, message: str) -> None:
        with pytest.raises(DataGovInContractError, match=message):
            parse_envelope(payload, expected_offset=0, expected_limit=2, expected_total=None)


class TestTraversalAndItems:
    def test_complete_pages_are_sorted_deterministically(self) -> None:
        pages = {
            0: envelope([{"state": "B"}, {"state": "A"}], total=3, offset=0),
            2: envelope([{"state": "C"}], total=3, offset=2),
        }
        items = list(connector(pages).guarded_fetch(WINDOW))
        assert len(items) == 3
        record_ids = [json.loads(item.payload)["record_id"] for item in items]
        assert record_ids == sorted(record_ids)
        assert all(item.first_observed_at == AVAILABLE for item in items)
        assert all(item.published_at is None for item in items)

    def test_total_change_fails_without_yielding_partial_rows(self) -> None:
        pages = {
            0: envelope([{"state": "A"}, {"state": "B"}], total=3, offset=0),
            2: envelope([{"state": "C"}], total=4, offset=2),
        }
        with pytest.raises(DataGovInContractError, match="total changed"):
            list(connector(pages).guarded_fetch(WINDOW))

    def test_max_pages_before_completion_fails(self) -> None:
        pages = {0: envelope([{"a": 1}, {"a": 2}], total=3, offset=0)}
        with pytest.raises(DataGovInContractError, match="max_pages 1"):
            list(connector(pages, config=options(max_pages=1)).guarded_fetch(WINDOW))

    def test_max_items_is_a_failure_not_silent_truncation(self) -> None:
        pages = {0: envelope([{"a": 1}, {"a": 2}], total=3, offset=0)}
        with pytest.raises(DataGovInContractError, match="exceeds max_items"):
            list(connector(pages, config=options(max_items=2)).guarded_fetch(WINDOW))

    def test_duplicate_record_across_pages_fails(self) -> None:
        pages = {
            0: envelope([{"state": "A"}, {"state": "B"}], total=3, offset=0),
            2: envelope([{"state": "A"}], total=3, offset=2),
        }
        with pytest.raises(DataGovInContractError, match="duplicate stable record id"):
            list(connector(pages).guarded_fetch(WINDOW))

    @pytest.mark.parametrize("bad", [None, "", True, {"nested": 1}, [1]])
    def test_configured_stable_id_field_must_be_scalar(self, bad: object) -> None:
        pages = {0: envelope([{"row_id": bad}], total=1, offset=0)}
        target = connector(pages, config=options(stable_id_fields=["row_id"]))
        with pytest.raises(DataGovInContractError, match="stable ID field"):
            list(target.guarded_fetch(WINDOW))

    def test_claimed_event_time_is_distinct_and_normalized(self) -> None:
        pages = {
            0: envelope([{"id": "1", "event_at": "2025-01-01T05:30:00+05:30"}], total=1, offset=0)
        }
        target = connector(
            pages,
            config=options(stable_id_fields=["id"], claimed_event_time_field="event_at"),
        )
        item = next(target.guarded_fetch(WINDOW))
        assert item.claimed_event_time == datetime(2025, 1, 1, tzinfo=UTC)
        assert item.first_observed_at == AVAILABLE
        assert item.published_at is None

    @pytest.mark.parametrize("bad", [None, "", "2025-01-01", "not-a-time"])
    def test_bad_claimed_time_fails(self, bad: object) -> None:
        pages = {0: envelope([{"id": "1", "event_at": bad}], total=1, offset=0)}
        target = connector(
            pages,
            config=options(stable_id_fields=["id"], claimed_event_time_field="event_at"),
        )
        with pytest.raises(DataGovInContractError, match="event_at"):
            list(target.guarded_fetch(WINDOW))

    def test_json_key_order_does_not_change_payload(self) -> None:
        first = next(
            connector({0: envelope([{"a": 1, "b": 2}], total=1, offset=0)}).guarded_fetch(WINDOW)
        )
        second = next(
            connector({0: envelope([{"b": 2, "a": 1}], total=1, offset=0)}).guarded_fetch(WINDOW)
        )
        assert first.payload == second.payload

    def test_raw_network_exception_is_sanitized(self) -> None:
        def fail(url: str) -> bytes:
            raise RuntimeError(f"request failed for {url}\nforbidden")

        target = DataGovInConnector(
            Settings(),
            options(),
            fetcher=fail,
            environ={API_KEY_ENV: TEST_KEY},
        )
        with pytest.raises(Exception) as captured:
            list(target.guarded_fetch(WINDOW))
        message = str(captured.value)
        assert TEST_KEY not in message
        assert "\\n" in message

    @pytest.mark.parametrize(
        "error",
        [
            ProxyPolicyError("https://api.data.gov.in/resource/x", "HTTP 407"),
            PermanentHttpError("origin returned HTTP 403"),
        ],
    )
    def test_http_failure_class_survives_connector_boundary(self, error: Exception) -> None:
        def fail(url: str) -> bytes:
            raise error

        target = DataGovInConnector(
            Settings(),
            options(),
            fetcher=fail,
            environ={API_KEY_ENV: TEST_KEY},
        )
        with pytest.raises(type(error)):
            list(target.guarded_fetch(WINDOW))
