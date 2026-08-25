"""Connectors shipped with M0.

Two, on purpose:

* :mod:`~pramaanx.ingest.connectors.synthetic` -- a deterministic world, so the
  temporal guarantees can be tested offline and without licensed data;
* :mod:`~pramaanx.ingest.connectors.gdelt` -- one real Tier-0 source, so the
  ledger is exercised against evidence nobody in this repository controls.

Importing this package registers both connectors. The remaining Tier-0 and
Tier-1 sources in the build plan (ACLED, ReliefWeb, data.gov.in, Bluesky,
FIRMS, Copernicus, OpenSky, Global Fishing Watch) are Phase 1 work and are
deliberately absent rather than stubbed: an empty connector is indistinguishable
from a quiet source, and that confusion would corrupt base rates.
"""

from __future__ import annotations

from pramaanx.ingest.connectors.gdelt import GdeltConnector
from pramaanx.ingest.connectors.synthetic import SyntheticConnector

__all__ = ["GdeltConnector", "SyntheticConnector"]
