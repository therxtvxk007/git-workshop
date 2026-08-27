"""Evidence connectors registered by this package.

Four, on purpose:

* :mod:`~pramaanx.ingest.connectors.synthetic` -- a deterministic world, so the
  temporal guarantees can be tested offline and without licensed data;
* :mod:`~pramaanx.ingest.connectors.gdelt` -- machine-coded event records, so
  the ledger is exercised against evidence nobody in this repository controls;
* :mod:`~pramaanx.ingest.connectors.reliefweb` -- curated humanitarian
  reporting, whose posting and revision timestamps make honest point-in-time
  reconstruction possible where a news archive's would not;
* :mod:`~pramaanx.ingest.connectors.data_gov_in` -- official Indian
  administrative tables, which supply the denominators and context a rate
  estimated from reporting alone cannot.

Importing this package registers all four. The remaining Tier-0 and Tier-1
sources in the build plan (ACLED, Bluesky, FIRMS, Copernicus, OpenSky, Global
Fishing Watch) are later phases and are deliberately absent rather than
stubbed: an empty connector is indistinguishable from a quiet source, and that
confusion would corrupt base rates.
"""

from __future__ import annotations

from pramaanx.ingest.connectors.data_gov_in import DataGovInConnector
from pramaanx.ingest.connectors.gdelt import GdeltConnector
from pramaanx.ingest.connectors.reliefweb import ReliefWebConnector
from pramaanx.ingest.connectors.synthetic import SyntheticConnector

__all__ = [
    "DataGovInConnector",
    "GdeltConnector",
    "ReliefWebConnector",
    "SyntheticConnector",
]
