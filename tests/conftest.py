"""Shared fixtures.

Every fixture here is hermetic: a temporary data root, a fixed clock and the
synthetic world. No test in this suite touches the network or the developer's
real ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pramaanx.clock import FixedClock
from pramaanx.config import Settings, StorageConfig
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.ledger import EvidenceLedger

WORLD_START = datetime(2025, 1, 1, tzinfo=UTC)
WORLD_END = datetime(2026, 4, 1, tzinfo=UTC)
CUTOFF = datetime(2025, 7, 1, tzinfo=UTC)
BOOTSTRAP_INSTANT = datetime(2026, 8, 25, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A Settings pointing at an isolated data root."""
    return Settings(
        storage=StorageConfig(data_root=tmp_path / "data", run_root=tmp_path / "runs"),
        horizon_days=30,
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(BOOTSTRAP_INSTANT)


@pytest.fixture
def ledger(settings: Settings, clock: FixedClock) -> EvidenceLedger:
    return EvidenceLedger(settings, clock=clock)


@pytest.fixture
def window() -> FetchWindow:
    """A short world span: enough structure, fast enough for every test."""
    return FetchWindow(WORLD_START, datetime(2025, 10, 1, tzinfo=UTC))


@pytest.fixture
def populated_ledger(ledger: EvidenceLedger, window: FetchWindow) -> EvidenceLedger:
    ledger.ingest("synthetic", window)
    return ledger
