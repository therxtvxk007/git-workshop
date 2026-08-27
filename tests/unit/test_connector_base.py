"""The connector contract itself: windows, the registry and the fetch guard."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.config import Settings, SourceOptions, SyntheticSourceConfig
from pramaanx.ingest.base import (
    Connector,
    ConnectorError,
    FetchWindow,
    RawItem,
    available_connectors,
    build_connector,
    get_connector_class,
    register_connector,
)
from pramaanx.schemas.observation import SourceRecord

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 8, tzinfo=UTC)


class StrayConnector(Connector):
    """Returns an item from outside the requested window. Not registered."""

    source_id = "stray"
    tier = 0
    # Not registered, so register_connector never assigned one.
    options_model = SourceOptions

    @property
    def source_record(self) -> SourceRecord:
        return SourceRecord(
            source_id=self.source_id,
            source_type="test",
            display_name="Stray",
            tier=0,
            licence="CC0-1.0",
        )

    def fetch(self, window: FetchWindow) -> Iterator[RawItem]:
        yield RawItem(payload=b"{}", first_observed_at=window.end + timedelta(days=1))


class TestFetchWindow:
    def test_half_open_bounds(self) -> None:
        window = FetchWindow(START, END)
        assert window.contains(START)
        assert not window.contains(END)
        assert window.days == 7.0

    def test_empty_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty fetch window"):
            FetchWindow(START, START)

    def test_naive_bounds_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            FetchWindow(datetime(2026, 1, 1), END)  # noqa: DTZ001

    def test_from_dates_accepts_plain_dates(self) -> None:
        window = FetchWindow.from_dates("2026-01-01", "2026-01-08")
        assert (window.start, window.end) == (START, END)


class TestGuardedFetch:
    def test_out_of_window_items_are_a_hard_error(self) -> None:
        # A connector that reports the wrong observation time is the one bug
        # that would silently defeat every cutoff guarantee downstream.
        connector = StrayConnector(Settings())
        with pytest.raises(ConnectorError, match="outside the requested window"):
            list(connector.guarded_fetch(FetchWindow(START, END)))


class TestRegistry:
    def test_phase1c_registers_exactly_three_connectors(self) -> None:
        assert sorted(available_connectors()) == ["data_gov_in", "gdelt", "synthetic"]

    def test_unknown_connector_names_the_known_ones(self) -> None:
        with pytest.raises(KeyError, match="registered: data_gov_in, gdelt, synthetic"):
            get_connector_class("acled")

    def test_build_connector_passes_validated_source_options(self) -> None:
        settings = Settings(sources={"synthetic": {"seed": 7}})
        options = build_connector("synthetic", settings).options
        assert isinstance(options, SyntheticSourceConfig)
        assert options.seed == 7

    def test_registration_requires_an_options_model(self) -> None:
        # A connector whose options nothing validates would reintroduce the
        # silent-typo failure one source at a time.
        class Unregistered(Connector):
            source_id = "not_in_the_registry"

            @property
            def source_record(self) -> SourceRecord:  # pragma: no cover - never reached
                raise NotImplementedError

            def fetch(self, window: FetchWindow) -> Iterator[RawItem]:  # pragma: no cover
                raise NotImplementedError

        with pytest.raises(ConnectorError, match="no options model registered"):
            register_connector(Unregistered)
