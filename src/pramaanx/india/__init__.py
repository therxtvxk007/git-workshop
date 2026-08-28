"""India incident registry and region/target-class hazard estimation.

This package answers two questions the project is repeatedly asked, and keeps
them apart because they have different evidential standing:

1. *Retrospective.* Fitted only on incidents that had already occurred and been
   publicly reported at a chosen cutoff, how did the eventual next incident's
   region and target class rank? This is scoreable against history.
2. *Prospective.* Given everything reported to date, which
   ``(state, target_class)`` cells carry the highest modelled hazard over a
   stated horizon?

Both produce a **ranked distribution over region-window cells with intervals**,
which is the object the conflict-forecasting literature actually estimates.
Neither produces a named next target, a date, or a site. That is not a
squeamishness setting: the estimator is a rate model over coarse cells fitted on
tens of events, and an instance-level assertion is not a quantity it computes.
"""

from __future__ import annotations

from pramaanx.india.hazard import CellForecast, HazardFit, fit_hazard
from pramaanx.india.registry import Incident, admissible_at, load_incidents

__all__ = [
    "CellForecast",
    "HazardFit",
    "Incident",
    "admissible_at",
    "fit_hazard",
    "load_incidents",
]
