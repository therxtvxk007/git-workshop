"""Shared constants for the core tests.

Imported as a sibling module, matching the convention already used by
``tests/unit/_phase2_builders.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)
