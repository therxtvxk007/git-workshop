"""ReliefWeb inside the M0 machinery: dry-run purity, the ledger, and the gate.

The connector is only worth having if it preserves what M0 established. These
tests drive it through the real ingest path and the real snapshot builder.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from pramaanx.config import Settings, StorageConfig
from pramaanx.hashing import canonical_bytes
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.reliefweb import (
    API_VERSION,
    APPNAME_ENV,
    REDACTED_APPNAME,
    ReliefWebConnector,
    ReliefWebIncompleteIngestError,
)
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.timeguard.cutoff import CutoffGuard
from pramaanx.timeguard.snapshots import SnapshotBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "reliefweb"
REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOW = FetchWindow(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 5, tzinfo=UTC))


def page(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def complete_page(name: str) -> bytes:
    """Turn a pagination fixture into a self-contained one-page response."""
    document = json.loads(page(name))
    document["totalCount"] = document["count"]
    return json.dumps(document).encode()


def record(rid: int, changed: str, created: str | None = None) -> dict[str, Any]:
    return {
        "id": rid,
        "fields": {
            "id": rid,
            "title": f"Synthetic report {rid}",
            "url": f"https://example.invalid/report/{rid}",
            "date": {"created": created or changed, "changed": changed},
            "language": [{"code": "en", "name": "English"}],
        },
    }


def envelope(*records: dict[str, Any]) -> bytes:
    return json.dumps(
        {"totalCount": len(records), "count": len(records), "data": list(records)}
    ).encode()


@pytest.fixture
def rw_settings(tmp_path: Path) -> Settings:
    return Settings(
        storage=StorageConfig(data_root=tmp_path / "data", run_root=tmp_path / "runs"),
        horizon_days=30,
    )


class TestDryRunPurity:
    """--dry-run must make no request and write nothing. Both, not either."""

    def test_plan_makes_no_request(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(url: str) -> bytes:
            raise AssertionError(f"--dry-run performed a network request: {url}")

        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        connector = ReliefWebConnector(rw_settings, {"cache": False}, fetcher=explode)
        plan = connector.plan(WINDOW)
        assert plan["source_id"] == "reliefweb"
        assert plan["availability_rule"] == "max(date.created, date.changed)"

    def test_plan_does_not_leak_the_caller_identity(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "secret-caller-identity")
        connector = ReliefWebConnector(rw_settings, {"cache": False}, fetcher=lambda u: b"{}")
        plan = connector.plan(WINDOW)
        assert "appname=REDACTED" in plan["first_request_url"]
        assert "appname" not in plan["options"]
        # The whole plan, serialised: a leak can hide in any nested value.
        assert "secret-caller-identity" not in json.dumps(plan)
        assert plan["appname"] == REDACTED_APPNAME

    def test_dry_run_ingest_writes_nothing(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(url: str) -> bytes:
            raise AssertionError(f"--dry-run performed a network request: {url}")

        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        ledger = EvidenceLedger(rw_settings)
        connector = ReliefWebConnector(rw_settings, {"cache": False}, fetcher=explode)
        report = ledger.ingest("reliefweb", WINDOW, dry_run=True, connector=connector)

        assert report.dry_run is True
        assert (report.written, report.fetched) == (0, 0)
        assert not (rw_settings.storage.bronze / "observations").exists()
        assert not (rw_settings.storage.bronze / "payloads").exists()

    def test_dry_run_still_fails_on_a_missing_appname(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Better to learn the identity is missing during a dry run than on the
        # first real request.
        monkeypatch.delenv(APPNAME_ENV, raising=False)
        connector = ReliefWebConnector(rw_settings, {"cache": False}, fetcher=lambda u: b"{}")
        with pytest.raises(Exception, match=APPNAME_ENV):
            connector.plan(WINDOW)


class TestLedgerIntegration:
    def test_items_reach_bronze_with_full_provenance(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        ledger = EvidenceLedger(rw_settings)
        connector = ReliefWebConnector(
            rw_settings, {"cache": False}, fetcher=lambda url: complete_page("reports_page1")
        )
        report = ledger.ingest("reliefweb", WINDOW, connector=connector)
        assert report.written == 3

        observations = ledger.read_observations()
        assert len(observations) == 3
        for observation in observations:
            assert observation.source_id == "reliefweb"
            assert observation.raw_content_hash.startswith("sha256:")
            assert observation.language == "en"
            assert observation.licence and "ReliefWeb" in observation.licence
            assert observation.uri is not None
            assert observation.first_observed_at <= observation.retrieved_at
            # Publication never postdates availability, or CutoffGuard would
            # rightly call it a leak.
            assert observation.published_at is not None
            assert observation.published_at <= observation.first_observed_at

        sources = {item.source_id: item for item in ledger.read_source_records()}
        assert sources["reliefweb"].source_version == f"reliefweb-{API_VERSION}-reports"

    def test_reingesting_the_same_window_writes_nothing_new(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        ledger = EvidenceLedger(rw_settings)

        def build() -> ReliefWebConnector:
            return ReliefWebConnector(
                rw_settings,
                {"cache": False},
                fetcher=lambda url: complete_page("reports_page1"),
            )

        first = ledger.ingest("reliefweb", WINDOW, connector=build())
        second = ledger.ingest("reliefweb", WINDOW, connector=build())
        assert first.written == 3
        assert second.written == 0
        assert second.skipped == second.fetched

    def test_identical_records_hash_identically(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        connector = ReliefWebConnector(
            rw_settings, {"cache": False}, fetcher=lambda url: complete_page("reports_page1")
        )
        first = [item.payload for item in connector.fetch(WINDOW)]
        second = [item.payload for item in connector.fetch(WINDOW)]
        assert first == second
        assert all(isinstance(payload, bytes) for payload in first)

    @pytest.mark.parametrize("failure", ["empty-page", "max-pages"])
    def test_incomplete_walk_writes_no_partial_observations(
        self,
        failure: str,
        rw_settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        first = json.dumps(
            {
                "totalCount": 2,
                "count": 1,
                "data": [record(900050, "2026-03-02T00:00:00+00:00")],
            }
        ).encode()
        empty_with_rows_remaining = json.dumps({"totalCount": 2, "count": 0, "data": []}).encode()
        calls = 0

        def fetch(url: str) -> bytes:
            nonlocal calls
            calls += 1
            return first if calls == 1 else empty_with_rows_remaining

        options: dict[str, Any] = {"cache": False, "page_size": 1}
        if failure == "max-pages":
            options["max_pages"] = 1

        ledger = EvidenceLedger(rw_settings)
        connector = ReliefWebConnector(rw_settings, options, fetcher=fetch)
        with pytest.raises(ReliefWebIncompleteIngestError):
            ledger.ingest("reliefweb", WINDOW, connector=connector)

        assert ledger.read_observations() == []
        assert not (rw_settings.storage.bronze / "payloads").exists()


class TestCutoffSafety:
    """The M0 gate, now with a real API-shaped source behind it."""

    def test_a_report_revised_after_the_cutoff_cannot_enter_an_earlier_snapshot(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exact hazard the availability rule exists for: a document posted
        # long before the cutoff, but revised after it. The body in hand is the
        # revised body, so it must not appear at the earlier cutoff.
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        cutoff = datetime(2026, 3, 3, tzinfo=UTC)
        window = FetchWindow(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 10, tzinfo=UTC))

        payload = envelope(
            record(900100, "2026-03-02T00:00:00+00:00"),
            # created well before the cutoff, revised after it
            record(900101, "2026-03-06T00:00:00+00:00", created="2026-03-01T00:00:00+00:00"),
        )
        ledger = EvidenceLedger(rw_settings)
        connector = ReliefWebConnector(rw_settings, {"cache": False}, fetcher=lambda url: payload)
        ledger.ingest("reliefweb", window, connector=connector)

        admitted = CutoffGuard(cutoff, rw_settings.timeguard).filter(
            ledger.observations_at_or_before(cutoff)
        )
        ids = set()
        for observation in admitted:
            ids.add(json.loads(ledger.payload_text(observation))["report_id"])
        assert ids == {"900100"}, "a report revised after the cutoff entered an earlier snapshot"

    def test_future_records_do_not_change_a_pre_cutoff_snapshot(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        cutoff = datetime(2026, 3, 5, tzinfo=UTC)
        past = FetchWindow(datetime(2026, 3, 1, tzinfo=UTC), cutoff)
        future = FetchWindow(cutoff, datetime(2026, 3, 12, tzinfo=UTC))

        ledger = EvidenceLedger(rw_settings)
        ledger.ingest(
            "reliefweb",
            past,
            connector=ReliefWebConnector(
                rw_settings,
                {"cache": False},
                fetcher=lambda url: envelope(record(900200, "2026-03-02T00:00:00+00:00")),
            ),
        )
        builder = SnapshotBuilder(rw_settings, ledger)
        before = builder.build(cutoff, persist=False)

        added = ledger.ingest(
            "reliefweb",
            future,
            connector=ReliefWebConnector(
                rw_settings,
                {"cache": False},
                fetcher=lambda url: envelope(
                    record(900201, "2026-03-07T00:00:00+00:00"),
                    record(900202, "2026-03-09T00:00:00+00:00"),
                ),
            ),
        )
        assert added.written == 2, "the injection must actually add documents"

        after = builder.build(cutoff, persist=False)
        assert after.snapshot_hash == before.snapshot_hash
        assert after.manifest.observation_hashes == before.manifest.observation_hashes

    def test_the_injected_records_are_visible_at_a_later_cutoff(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Negative control: without this, the test above could pass because the
        # connector silently ingested nothing.
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        ledger = EvidenceLedger(rw_settings)
        ledger.ingest(
            "reliefweb",
            FetchWindow(datetime(2026, 3, 6, tzinfo=UTC), datetime(2026, 3, 12, tzinfo=UTC)),
            connector=ReliefWebConnector(
                rw_settings,
                {"cache": False},
                fetcher=lambda url: envelope(record(900300, "2026-03-07T00:00:00+00:00")),
            ),
        )
        builder = SnapshotBuilder(rw_settings, ledger)
        early = builder.build(datetime(2026, 3, 5, tzinfo=UTC), persist=False)
        late = builder.build(datetime(2026, 3, 8, tzinfo=UTC), persist=False)
        assert len(early) == 0
        assert len(late) == 1

    def test_the_payload_hash_does_not_depend_on_when_it_was_fetched(
        self, rw_settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(APPNAME_ENV, "pramaanx-test")
        connector = ReliefWebConnector(
            rw_settings, {"cache": False}, fetcher=lambda url: complete_page("reports_page1")
        )
        payloads = [item.payload for item in connector.fetch(WINDOW)]
        # No wall clock anywhere in the payload.
        for payload in payloads:
            decoded = json.loads(payload)
            assert "retrieved_at" not in decoded
            assert canonical_bytes(decoded) == payload


class TestCliSurface:
    """`pramaanx sources` and `pramaanx ingest --dry-run` know the connector."""

    @pytest.fixture
    def workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        config = {
            "storage": {"data_root": str(tmp_path / "data"), "run_root": str(tmp_path / "runs")},
            "sources": {"reliefweb": {"appname": "pramaanx-cli-test", "cache": False}},
        }
        (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def invoke(self, *args: str) -> Any:
        from pramaanx.cli import app

        result = CliRunner().invoke(app, list(args))
        if result.exception is not None and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result

    def test_sources_lists_reliefweb(self, workspace: Path) -> None:
        result = self.invoke("sources", "--config", "config.yaml")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip().splitlines()[-1])
        entries = {item["source_id"]: item for item in payload["sources"]}
        assert "reliefweb" in entries
        assert entries["reliefweb"]["redistributable"] is False
        assert entries["reliefweb"]["tier"] == 0

    def test_version_lists_reliefweb_as_registered(self, workspace: Path) -> None:
        result = self.invoke("version")
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert "reliefweb" in payload["connectors"]

    def test_ingest_dry_run_touches_nothing(self, workspace: Path) -> None:
        result = self.invoke(
            "ingest",
            "--source",
            "reliefweb",
            "--from",
            "2026-03-01",
            "--until",
            "2026-03-05",
            "--config",
            "config.yaml",
            "--dry-run",
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["dry_run"] is True
        assert payload["written"] == 0
        # The CLI prints the plan to stdout, so it must not carry the identity
        # even though this workspace configures one.
        assert payload["plan"]["appname"] == REDACTED_APPNAME
        assert payload["plan"]["appname_configured"] is True
        assert payload["plan"]["appname_source"] == "config"
        assert "pramaanx-cli-test" not in result.output
        assert not (workspace / "data" / "bronze").exists()


class TestShippedConfiguration:
    def test_the_reliefweb_source_config_validates(self) -> None:
        from pramaanx.config import load_settings

        settings = load_settings(REPO_ROOT / "configs/sources/reliefweb_india.yaml", environ={})
        options = settings.source_options("reliefweb")
        assert options.countries == ["IND"]
        assert options.languages == ["en"]

    def test_no_appname_is_committed_in_any_config(self) -> None:
        # The identity belongs in the environment, not in a tracked file.
        for path in sorted((REPO_ROOT / "configs").rglob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            reliefweb = (raw.get("sources") or {}).get("reliefweb") or {}
            assert "appname" not in reliefweb, f"{path} commits an appname"
