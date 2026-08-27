"""Connectors shipped with M0.

Three, on purpose:

* :mod:`~pramaanx.ingest.connectors.synthetic` -- a deterministic world, so the
  temporal guarantees can be tested offline and without licensed data;
* :mod:`~pramaanx.ingest.connectors.gdelt` -- machine-coded event records, so
  the ledger is exercised against evidence nobody in this repository controls;
* :mod:`~pramaanx.ingest.connectors.reliefweb` -- curated humanitarian
  reporting, whose posting and revision timestamps make honest point-in-time
  reconstruction possible where a news archive's would not.

Importing this package registers all three. The remaining Tier-0 and Tier-1
sources in the build plan (ACLED, data.gov.in, Bluesky, FIRMS, Copernicus,
OpenSky, Global Fishing Watch) are later phases and are deliberately absent
rather than stubbed: an empty connector is indistinguishable from a quiet
source, and that confusion would corrupt base rates.
"""

from __future__ import annotations

from pramaanx.ingest.connectors.gdelt import GdeltConnector
from pramaanx.ingest.connectors.reliefweb import ReliefWebConnector
from pramaanx.ingest.connectors.synthetic import SyntheticConnector

__all__ = ["GdeltConnector", "ReliefWebConnector", "SyntheticConnector"]
