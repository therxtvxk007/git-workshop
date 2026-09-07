"""The baseline ladder, in the paper's order.

Five rungs so far. Three of them produce daily paths and two do not, and that
asymmetry is a finding rather than an omission: persistence and a rolling
empirical distribution predict window totals, and the plan forbids an adapter
from inventing the daily process they lack (S42).
"""

from __future__ import annotations

from pramaanx.models.ladder.climatology import Climatology
from pramaanx.models.ladder.empirical_bayes import EmpiricalBayes
from pramaanx.models.ladder.hist12 import Hist12
from pramaanx.models.ladder.persistence import Persistence
from pramaanx.models.ladder.zero import ZeroBaseline

#: The ladder in rung order. Rungs 6-12 (GLMM, hurdle, logistic, random
#: forest, GBM, OMM, distributional random forest) are absent, not stubbed.
LADDER: tuple[type, ...] = (ZeroBaseline, Climatology, Persistence, Hist12, EmpiricalBayes)

__all__ = ["LADDER", "Climatology", "EmpiricalBayes", "Hist12", "Persistence", "ZeroBaseline"]
