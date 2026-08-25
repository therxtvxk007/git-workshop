"""GDELT connector: slot arithmetic, parsing, and what it refuses to ingest.

No network. The fetcher is injected, which is the only way a connector test can
be both meaningful and hermetic.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.config import Settings
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.gdelt import (
    EXCLUDED_COLUMNS,
    GdeltConnector,
    parse_export_csv,
    slot_times,
)
from pramaanx.ingest.http import NotFoundError

# GDELT 2.0 export rows have 61 tab-separated columns.
COLUMN_COUNT = 61


def make_row(
    global_event_id: str = "1234567890",
    event_date: str = "20260114",
    root_code: str = "14",
    country: str = "IN",
    date_added: str = "20260115000000",
) -> str:
    fields = [""] * COLUMN_COUNT
    fields[0] = global_event_id
    fields[1] = event_date
    fields[5] = "IND"
    fields[6] = "FARMERS UNION"
    fields[7] = "IND"
    fields[9] = "SIKH"  # Actor1EthnicCode -- must never be read
    fields[10] = "HIN"  # Actor1Religion1Code -- must never be read
    fields[15] = "GOV"
    fields[16] = "STATE SECRETARIAT"
    fields[26] = f"{root_code}0"
    fields[27] = f"{root_code}0"
    fields[28] = root_code
    fields[31] = "12"
    fields[32] = "4"
    fields[52] = "New Delhi, Delhi, India"
    fields[53] = country
    fields[59] = date_added
    fields[60] = "https://example.org/story"
    return "\t".join(fields)


def make_zip(rows: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("20260115000000.export.CSV", "\n".join(rows))
    return buffer.getvalue()


class TestSlotArithmetic:
    def test_slots_are_every_fifteen_minutes(self) -> None:
        window = FetchWindow(
            datetime(2026, 1, 15, 0, 0, tzinfo=UTC), datetime(2026, 1, 15, 1, 0, tzinfo=UTC)
        )
        slots = slot_times(window, lag_minutes=15)
        assert len(slots) == 4
        assert all(slot.minute % 15 == 0 for slot in slots)

    def test_publication_lag_shifts_the_window(self) -> None:
        window = FetchWindow(
            datetime(2026, 1, 15, 0, 0, tzinfo=UTC), datetime(2026, 1, 15, 1, 0, tzinfo=UTC)
        )
        # With a 15-minute lag, the 00:45 file is published at 01:00 and falls
        # outside a window ending at 01:00.
        assert slot_times(window, lag_minutes=15)[-1] == datetime(2026, 1, 15, 0, 30, tzinfo=UTC)
        assert slot_times(window, lag_minutes=0)[-1] == datetime(2026, 1, 15, 0, 45, tzinfo=UTC)

    def test_slots_never_precede_the_gdelt_v2_epoch(self) -> None:
        window = FetchWindow(datetime(2010, 1, 1, tzinfo=UTC), datetime(2015, 2, 19, tzinfo=UTC))
        assert all(
            slot >= datetime(2015, 2, 18, 23, 0, tzinfo=UTC)
            for slot in slot_times(window, lag_minutes=15)
        )


class TestParsing:
    def test_selected_fields_are_extracted(self) -> None:
        rows = parse_export_csv(make_row().encode())
        assert len(rows) == 1
        assert rows[0]["event_root_code"] == "14"
        assert rows[0]["actor1_name"] == "FARMERS UNION"
        assert rows[0]["action_geo_country_code"] == "IN"

    def test_protected_attribute_columns_are_never_read(self) -> None:
        # This project forecasts population-level and organisational events. It
        # must not use protected identity as a risk proxy, so the columns are
        # dropped at ingestion rather than filtered downstream.
        parsed = parse_export_csv(make_row().encode())[0]
        assert "SIKH" not in parsed.values()
        assert "HIN" not in parsed.values()
        assert set(EXCLUDED_COLUMNS) & set(parsed) == set()

    def test_short_rows_are_skipped_by_default(self) -> None:
        assert parse_export_csv(b"one\ttwo\tthree") == []

    def test_short_rows_raise_in_strict_mode(self) -> None:
        with pytest.raises(Exception, match="expected at least"):
            parse_export_csv(b"one\ttwo\tthree", strict=True)


class TestFetch:
    def test_first_observed_at_is_publication_not_event_date(self) -> None:
        # SQLDATE would back-date every row by however long the reporting took.
        settings = Settings()
        payload = make_zip([make_row(event_date="20251201")])
        connector = GdeltConnector(settings, {"cache": False}, fetcher=lambda _: payload)
        window = FetchWindow(
            datetime(2026, 1, 15, 0, 0, tzinfo=UTC), datetime(2026, 1, 15, 0, 30, tzinfo=UTC)
        )
        items = list(connector.fetch(window))
        assert items
        item = items[0]
        # The 23:45 file becomes observable at 00:00, the first instant in the
        # half-open window.
        assert item.first_observed_at == datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
        assert item.claimed_event_time == datetime(2025, 12, 1, tzinfo=UTC)
        assert item.first_observed_at > item.claimed_event_time

    def test_filters_apply(self) -> None:
        payload = make_zip([make_row(country="IN"), make_row(global_event_id="2", country="GB")])
        connector = GdeltConnector(
            Settings(), {"cache": False, "country_filter": ["IN"]}, fetcher=lambda _: payload
        )
        window = FetchWindow(
            datetime(2026, 1, 15, 0, 0, tzinfo=UTC), datetime(2026, 1, 15, 0, 30, tzinfo=UTC)
        )
        items = list(connector.fetch(window))
        assert all(b'"action_geo_country_code":"IN"' in item.payload for item in items)

    def test_missing_files_are_skipped_not_fatal(self) -> None:
        def fetcher(url: str) -> bytes:
            raise NotFoundError(url)

        connector = GdeltConnector(Settings(), {"cache": False}, fetcher=fetcher)
        window = FetchWindow(
            datetime(2026, 1, 15, 0, 0, tzinfo=UTC), datetime(2026, 1, 15, 1, 0, tzinfo=UTC)
        )
        assert list(connector.fetch(window)) == []

    def test_plan_needs_no_network(self) -> None:
        def fetcher(url: str) -> bytes:
            raise AssertionError("plan must not fetch")

        connector = GdeltConnector(Settings(), {"cache": False}, fetcher=fetcher)
        window = FetchWindow(
            datetime(2026, 1, 15, tzinfo=UTC),
            datetime(2026, 1, 15, tzinfo=UTC) + timedelta(hours=1),
        )
        plan = connector.plan(window)
        assert plan["files"] == 4
        assert plan["excluded_columns"] == list(EXCLUDED_COLUMNS)


class TestSourceRecord:
    def test_licence_is_recorded_and_not_redistributable(self) -> None:
        record = GdeltConnector(Settings(), {"cache": False}, fetcher=lambda _: b"").source_record
        assert record.tier == 0
        assert not record.redistributable
        assert "GDELT" in record.licence
