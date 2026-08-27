"""Ledger, cutoff, hashing and failure containment for data.gov.in."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from pramaanx.clock import FixedClock
from pramaanx.config import Settings, StorageConfig
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.data_gov_in import API_KEY_ENV, DataGovInConnector
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.timeguard.leakage_audit import LeakageAuditor
from pramaanx.timeguard.snapshots import SnapshotBuilder

RESOURCE_ID = "869c674d-59a4-4de3-8b09-f2b709983f51"
SECRET = "integration-fixture-credential"
AVAILABLE = datetime(2026, 2, 14, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures" / "data_gov_in"


def source_options(available_at: datetime = AVAILABLE) -> dict[str, object]:
    return {
        "resource_id": RESOURCE_ID,
        "resource_title": "Synthetic security aggregate",
        "resource_page_url": "https://www.data.gov.in/resource/synthetic-security-aggregate",
        "available_at": available_at.isoformat(),
        "portal_published_date": "2026-02-13",
        "stable_id_fields": ["row_id"],
        "page_size": 2,
        "max_pages": 3,
        "max_items": 3,
        "cache": False,
    }


def settings_at(tmp_path: Path) -> Settings:
    return Settings(
        storage=StorageConfig(data_root=tmp_path / "data", run_root=tmp_path / "runs"),
        sources={"data_gov_in": source_options()},
    )


def fixture_fetcher(url: str) -> bytes:
    offset = int(parse_qs(urlsplit(url).query)["offset"][0])
    return (FIXTURES / f"page_{offset}.json").read_bytes()


def build_connector(settings: Settings, *, fetcher=fixture_fetcher) -> DataGovInConnector:
    return DataGovInConnector(
        settings,
        settings.source_options("data_gov_in"),
        fetcher=fetcher,
        environ={API_KEY_ENV: SECRET},
    )


def test_ingest_snapshot_and_cutoff_exclusion(tmp_path: Path) -> None:
    settings = settings_at(tmp_path)
    ledger = EvidenceLedger(settings, clock=FixedClock(datetime(2026, 8, 26, tzinfo=UTC)))
    window = FetchWindow(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
    report = ledger.ingest("data_gov_in", window, connector=build_connector(settings))
    assert (report.fetched, report.written) == (3, 3)

    before = SnapshotBuilder(settings, ledger).build(
        datetime(2026, 2, 13, 23, 59, tzinfo=UTC), persist=False
    )
    after = SnapshotBuilder(settings, ledger).build(AVAILABLE, persist=False)
    assert len(before) == 0
    assert len(after) == 3
    assert after.manifest.source_counts == {"data_gov_in": 3}
    assert RESOURCE_ID in after.manifest.source_versions["data_gov_in"]
    assert LeakageAuditor(ledger).audit(after.observations, cutoff_at=AVAILABLE).clean


def test_future_injection_does_not_change_past_snapshot_and_negative_control(
    tmp_path: Path,
) -> None:
    settings = settings_at(tmp_path)
    ledger = EvidenceLedger(settings, clock=FixedClock(datetime(2026, 8, 26, tzinfo=UTC)))
    cutoff = datetime(2026, 3, 1, tzinfo=UTC)
    builder = SnapshotBuilder(settings, ledger)
    before = builder.build(cutoff, persist=False)

    future_available = datetime(2026, 3, 15, tzinfo=UTC)
    future_options = source_options(future_available)
    future_options["max_items"] = 1
    future_options["page_size"] = 1

    def future_fetcher(url: str) -> bytes:
        return b'{"status":"ok","total":1,"count":1,"limit":1,"offset":0,"records":[{"row_id":"future","incidents":9}]}'

    connector = DataGovInConnector(
        settings,
        future_options,
        fetcher=future_fetcher,
        environ={API_KEY_ENV: SECRET},
    )
    ledger.ingest(
        "data_gov_in",
        FetchWindow(datetime(2026, 3, 14, tzinfo=UTC), datetime(2026, 3, 16, tzinfo=UTC)),
        connector=connector,
    )
    still_past = builder.build(cutoff, persist=False)
    later = builder.build(datetime(2026, 3, 16, tzinfo=UTC), persist=False)
    assert still_past.snapshot_hash == before.snapshot_hash
    assert len(still_past) == 0
    assert len(later) == 1  # negative control: injected evidence really exists


def test_later_page_failure_writes_no_observation(tmp_path: Path) -> None:
    settings = settings_at(tmp_path)
    ledger = EvidenceLedger(settings, clock=FixedClock(datetime(2026, 8, 26, tzinfo=UTC)))

    def broken_fetcher(url: str) -> bytes:
        offset = int(parse_qs(urlsplit(url).query)["offset"][0])
        if offset == 0:
            return (FIXTURES / "page_0.json").read_bytes()
        return (
            b'{"status":"ok","total":4,"count":1,"limit":2,"offset":2,"records":[{"row_id":"x"}]}'
        )

    with pytest.raises(Exception, match="total changed"):
        ledger.ingest(
            "data_gov_in",
            FetchWindow(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)),
            connector=build_connector(settings, fetcher=broken_fetcher),
        )
    assert ledger.observations.count() == 0
    assert ledger.sources.count() == 0


def test_secret_is_absent_from_all_persisted_files_and_report(tmp_path: Path) -> None:
    settings = settings_at(tmp_path)
    ledger = EvidenceLedger(settings, clock=FixedClock(datetime(2026, 8, 26, tzinfo=UTC)))
    report = ledger.ingest(
        "data_gov_in",
        FetchWindow(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)),
        connector=build_connector(settings),
    )
    SnapshotBuilder(settings, ledger).build(AVAILABLE)
    assert SECRET not in str(report.to_manifest())
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes(), f"secret leaked into {path}"
