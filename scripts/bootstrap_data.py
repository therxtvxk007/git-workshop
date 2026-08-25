#!/usr/bin/env python
"""Populate the ledger with the synthetic world.

Everything M0 demonstrates can be reproduced offline from this script: no
credentials, no network, no licensed data. The clock is fixed so that two
bootstraps produce identical bytes, which is what the reproducibility and
leakage tests rely on.

    uv run python scripts/bootstrap_data.py --from 2025-01-01 --until 2026-05-01

The default window deliberately runs past the last experiment cutoff plus its
horizon plus the reporting delay. Stop earlier and the final folds are
right-censored: late reports have not arrived yet, and a missing report is
indistinguishable from an event that never happened.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from pramaanx.clock import FixedClock
from pramaanx.config import dotted_overrides, load_settings
from pramaanx.hashing import canonical_json
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.ledger import EvidenceLedger
from pramaanx.ledger.resolutions import adjudication_summary, build_outcome_registry
from pramaanx.logging import configure_logging

BOOTSTRAP_INSTANT = datetime(2026, 8, 25, tzinfo=UTC)
"""Fixed retrieval time. Synthetic evidence has no real retrieval moment, and
inventing a moving one would make bronze non-reproducible."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument("--from", dest="start", default="2025-01-01T00:00:00Z")
    parser.add_argument("--until", dest="end", default="2026-05-01T00:00:00Z")
    parser.add_argument(
        "--set", dest="overrides", action="append", default=[], help="config override"
    )
    parser.add_argument(
        "--skip-outcomes",
        action="store_true",
        help="Ingest only; do not derive the provisional outcome registry.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings(args.config, overrides=dotted_overrides(args.overrides))
    configure_logging(settings.log_level, settings.log_format)

    clock = FixedClock(BOOTSTRAP_INSTANT)
    ledger = EvidenceLedger(settings, clock=clock)
    window = FetchWindow.from_dates(args.start, args.end)
    report = ledger.ingest("synthetic", window)

    manifest = {"ingest": report.to_manifest()}
    if not args.skip_outcomes:
        outcomes = build_outcome_registry(ledger, ledger.read_observations())
        written = ledger.write_outcomes(outcomes).written
        manifest["outcomes"] = {
            "derived": len(outcomes),
            "written": written,
            "adjudication": adjudication_summary(outcomes),
        }

    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
