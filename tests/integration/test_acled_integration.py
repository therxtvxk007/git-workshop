"""ACLED through the real ledger, snapshot, and structured extraction paths."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from pramaanx.clock import FixedClock
from pramaanx.config import Settings, StorageConfig
from pramaanx.extraction.structured import extract_mentions
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.acled import AcledConnector, AcledIncompleteIngestError
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.timeguard.snapshots import SnapshotBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "acled"
WINDOW = FetchWindow(datetime(2026, 1, 10, tzinfo=UTC), datetime(2026, 1, 12, tzinfo=UTC))


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_bytes())


class StubHttp:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.calls = 0

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> bytes:
        self.calls += 1
        cursor = parse_qs(urlparse(url).query)["cursor"][0]
        return self.pages[cursor]

    def post_form(
        self, url: str, form: dict[str, str], *, headers: dict[str, str] | None = None
    ) -> bytes:
        raise AssertionError("pre-issued token should avoid OAuth POST")


def settings(tmp_path: Path) -> Settings:
    return Settings(storage=StorageConfig(data_root=tmp_path / "data", run_root=tmp_path / "runs"))


def connector(
    config: Settings,
    pages: dict[str, bytes],
    *,
    max_pages: int = 10,
) -> AcledConnector:
    return AcledConnector(
        config,
        {"page_size": 1, "countries": ["India"], "max_pages": max_pages},
        environ={"PRAMAANX_ACLED_ACCESS_TOKEN": "fixture-token"},
        http_client=StubHttp(pages),  # type: ignore[arg-type]
    )


def one_page(item: dict[str, Any]) -> bytes:
    body = load("empty.json")
    body.update({"count": 1, "total_count": 1, "data": [item], "next_cursor": None})
    return json.dumps(body).encode()


class TestBronzePath:
    def test_complete_cursor_walk_writes_hashed_observations(self, tmp_path: Path) -> None:
        config = settings(tmp_path)
        conn = connector(
            config,
            {
                "0": (FIXTURES / "page1.json").read_bytes(),
                "2": (FIXTURES / "page2.json").read_bytes(),
            },
        )
        ledger = EvidenceLedger(config, clock=FixedClock(datetime(2026, 1, 20, tzinfo=UTC)))
        report = ledger.ingest("acled", WINDOW, connector=conn)
        assert report.fetched == 2
        assert report.written == 2
        observations = ledger.read_observations()
        assert len(observations) == 2
        assert all(item.source_id == "acled" for item in observations)
        assert all(
            ledger.payloads.verify(item.payload_ref, item.raw_content_hash) for item in observations
        )

    def test_incomplete_walk_writes_nothing(self, tmp_path: Path) -> None:
        config = settings(tmp_path)
        second = load("page2.json")
        second["total_count"] = 3
        conn = connector(
            config,
            {
                "0": (FIXTURES / "page1.json").read_bytes(),
                "2": json.dumps(second).encode(),
            },
        )
        ledger = EvidenceLedger(config, clock=FixedClock(datetime(2026, 1, 20, tzinfo=UTC)))
        with pytest.raises(AcledIncompleteIngestError):
            ledger.ingest("acled", WINDOW, connector=conn)
        assert ledger.read_observations() == []
        assert ledger.read_source_records() == []
        assert not (config.storage.bronze / "payloads").exists()

    def test_dry_run_has_no_network_or_filesystem_effects(self, tmp_path: Path) -> None:
        config = settings(tmp_path)

        class NoNetwork(StubHttp):
            def get(self, url: str, *, headers: dict[str, str] | None = None) -> bytes:
                raise AssertionError("dry-run touched the network")

        conn = AcledConnector(
            config,
            {"countries": ["India"]},
            environ={"PRAMAANX_ACLED_ACCESS_TOKEN": "fixture-token"},
            http_client=NoNetwork({}),  # type: ignore[arg-type]
        )
        report = EvidenceLedger(config).ingest("acled", WINDOW, dry_run=True, connector=conn)
        assert report.dry_run is True
        assert report.written == 0
        assert not config.storage.data_root.exists()


class TestExtraction:
    def test_coded_acled_event_reaches_silver_deterministically(self, tmp_path: Path) -> None:
        config = settings(tmp_path)
        first = load("page1.json")["data"][0]
        ledger = EvidenceLedger(config, clock=FixedClock(datetime(2026, 1, 20, tzinfo=UTC)))
        ledger.ingest("acled", WINDOW, connector=connector(config, {"0": one_page(first)}))
        observation = ledger.read_observations()[0]
        mentions = extract_mentions(ledger, [observation])
        assert len(mentions) == 1
        mention = mentions[0]
        assert mention.event_type == "protests"
        assert mention.relation == "peaceful_protest"
        assert mention.subject == "Synthetic civic group"
        assert mention.observed_at == observation.first_observed_at


class TestCutoffSafety:
    def test_future_injection_is_invariant_and_negative_control_changes(
        self, tmp_path: Path
    ) -> None:
        config = settings(tmp_path)
        clock = FixedClock(datetime(2026, 1, 20, tzinfo=UTC))
        ledger = EvidenceLedger(config, clock=clock)
        first = load("page1.json")["data"][0]
        ledger.ingest("acled", WINDOW, connector=connector(config, {"0": one_page(first)}))

        cutoff = datetime(2026, 1, 10, 18, tzinfo=UTC)
        builder = SnapshotBuilder(config, ledger, clock=clock)
        before = builder.build(cutoff, persist=False)
        assert len(before) == 1

        future = load("page2.json")["data"][0]
        future_window = FetchWindow(
            datetime(2026, 1, 11, tzinfo=UTC), datetime(2026, 1, 12, tzinfo=UTC)
        )
        ledger.ingest(
            "acled",
            future_window,
            connector=connector(config, {"0": one_page(future)}),
        )
        after_future = builder.build(cutoff, persist=False)
        assert after_future.snapshot_hash == before.snapshot_hash
        assert [item.observation_id for item in after_future.observations] == [
            item.observation_id for item in before.observations
        ]

        past = dict(future)
        past["event_id_cnty"] = "INDTEST3"
        past["event_date"] = "2026-01-10"
        past["timestamp"] = 1768050000  # 2026-01-10 13:00:00Z, before cutoff
        past["notes"] = "Synthetic negative-control event."
        ledger.ingest("acled", WINDOW, connector=connector(config, {"0": one_page(past)}))
        after_past = builder.build(cutoff, persist=False)
        assert after_past.snapshot_hash != before.snapshot_hash
        assert len(after_past) == 2
