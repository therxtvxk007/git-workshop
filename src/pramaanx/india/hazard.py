"""Recency-weighted Gamma-Poisson hazard over ``(state, target_class)`` cells.

The estimator is deliberately the plainest thing that can be defended, for the
reason G0 gives: elaborate models routinely lose to a well-estimated base rate
on rare events, and a base rate is the floor any later generator must clear.

**Model.** Incidents in a cell are treated as a Poisson process whose rate is
estimated from recency-weighted history and shrunk toward a pooled global rate
through a Gamma prior. An incident ``d`` days before the cutoff contributes
``0.5 ** (d / half_life)``, so a 2008 wave informs a 2026 forecast weakly rather
than equally or not at all. The same decay defines the *effective exposure*, so
weighted counts are divided by a weighted denominator rather than a raw span.

Writing the posterior explicitly, for a cell with weighted count ``k`` and
effective exposure ``E`` days, under prior ``Gamma(a0, b0)``::

    a = a0 + k
    b = b0 + E
    P(at least one incident in the next h days) = 1 - (b / (b + h)) ** a

which is the negative-binomial zero term of the posterior predictive -- it
carries the estimation uncertainty, unlike ``1 - exp(-k/E * h)``, which would
treat a rate estimated from two events as if it were known exactly.

**What shrinkage does here, and why it matters for reading the output.** A cell
with no prior incident does not get probability zero; it inherits the pooled
rate. That is the honest treatment of a target class a state has not yet seen,
and it is the difference between a model that can rank a prior_driven pairing at all
and one that cannot represent it. Cells at or near the prior are flagged
``prior_driven``, because a rank driven entirely by the prior is not evidence about
that cell -- it is the absence of evidence, displayed in its correct place.

**What this does not estimate.** A cell is a state and a broad target class over
a horizon of weeks. It is not a site, a date, or an actor. Ranking cells does
not become instance prediction by narrowing the horizon; it becomes a worse
estimate of the same quantity, because the event count in the fitting window
does not grow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from scipy import stats  # type: ignore[import-untyped]

from pramaanx.india.registry import TARGET_CLASS_TAXONOMY, Incident, admissible_at, states

#: Half-life of an incident's contribution, in days. Roughly five years: long
#: enough that the 2005-2011 urban wave still informs a present-day fit, short
#: enough that it does not dominate it.
DEFAULT_HALF_LIFE_DAYS = 1825.0

#: Prior strength as pseudo-exposure in days. Larger shrinks harder toward the
#: pooled rate. At 3650 a cell needs several years of its own history before it
#: departs much from the pool -- appropriate when the whole registry holds tens
#: of events.
DEFAULT_PRIOR_STRENGTH_DAYS = 3650.0

#: Forecast horizon in days.
DEFAULT_HORIZON_DAYS = 90

#: Below this weighted count a cell's rank is carried by the prior. Note this
#: is a *weighted* count, so an old cell can be prior-driven despite a non-zero
#: raw count -- which is why the flag is named for its cause, not for novelty.
PRIOR_DRIVEN_THRESHOLD = 0.25

_LN2 = math.log(2.0)


@dataclass(frozen=True, slots=True)
class CellForecast:
    """Modelled hazard for one ``(state, target_class)`` cell."""

    state: str
    target_class: str
    probability: float
    """Posterior predictive P(at least one incident within the horizon)."""
    rate_per_year: float
    """Posterior mean rate, expressed per year for readability."""
    rate_lo: float
    rate_hi: float
    """Bounds of the 90% credible interval on the rate, per year."""
    weighted_count: float
    """Recency-weighted incidents in this cell before the cutoff."""
    raw_count: int
    """Unweighted incidents in this cell before the cutoff."""
    prior_driven: bool
    """True when the cell's rank is carried by the prior rather than its own
    history -- either it has no incidents at all, or the incidents it has are
    old enough that recency weighting has decayed them below the threshold.
    Both cases mean the same thing for a reader: this rank is not evidence
    about this cell."""

    @property
    def cell(self) -> tuple[str, str]:
        return (self.state, self.target_class)


@dataclass(frozen=True, slots=True)
class HazardFit:
    """A complete fit: the ranking plus everything needed to reproduce it."""

    cutoff: datetime
    horizon_days: int
    half_life_days: float
    prior_strength_days: float
    effective_exposure_days: float
    pooled_rate_per_year: float
    incidents_used: int
    cells: tuple[CellForecast, ...]
    """Ranked by probability, descending."""

    def top(self, n: int) -> tuple[CellForecast, ...]:
        return self.cells[:n]

    def rank_of(self, state: str, target_class: str) -> int | None:
        """1-based rank of a cell, or None if absent from the pool."""
        for position, cell in enumerate(self.cells, start=1):
            if cell.state == state and cell.target_class == target_class:
                return position
        return None

    def state_ranking(self) -> tuple[tuple[str, float], ...]:
        """States ranked by P(at least one incident of any class in the horizon).

        Cells within a state are combined as independent Poisson components,
        which is the model's own assumption rather than a new one: the union
        probability is ``1 - prod(1 - p_i)``.

        This matters for reading a retrospective. A state can be correctly
        ranked high while the specific class that materialises is prior_driven there,
        and reporting only cell rank would hide that the regional signal was
        present and the class signal was not.
        """
        by_state: dict[str, float] = {}
        for cell in self.cells:
            survival = by_state.get(cell.state, 1.0)
            by_state[cell.state] = survival * (1.0 - cell.probability)
        ranked = [(state, 1.0 - survival) for state, survival in by_state.items()]
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return tuple(ranked)

    def rank_of_state(self, state: str) -> int | None:
        for position, (name, _) in enumerate(self.state_ranking(), start=1):
            if name == state:
                return position
        return None


def _effective_exposure_days(history_days: float, half_life_days: float) -> float:
    """Integral of the decay weight over the observed history.

    ``∫₀ᴰ 0.5^(u/H) du = (H / ln 2) · (1 - 0.5^(D/H))``. As ``D`` grows this
    saturates at ``H / ln 2``: adding older history stops adding exposure, which
    is the intended behaviour -- a 1993 incident should not keep enlarging the
    denominator of a 2026 rate.
    """
    if history_days <= 0.0:
        return 0.0
    return (half_life_days / _LN2) * (1.0 - 0.5 ** (history_days / half_life_days))


def fit_hazard(
    incidents: tuple[Incident, ...],
    cutoff: datetime,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    prior_strength_days: float = DEFAULT_PRIOR_STRENGTH_DAYS,
    target_class_vocabulary: tuple[str, ...] = TARGET_CLASS_TAXONOMY,
) -> HazardFit:
    """Fit cell hazards using only incidents publicly known at ``cutoff``.

    The state list is taken from observed history, the class list from the fixed
    taxonomy. The asymmetry is deliberate and has a stated consequence: classes
    form a small closed vocabulary, so carrying all of them costs nothing and
    keeps an unprecedented pairing rankable, whereas carrying every Indian state
    would add dozens of zero-history cells whose only content is the prior. A
    first-ever incident in an unseen *state* is therefore outside the pool, and
    the evaluator scores it one past the bottom rather than discarding it.

    The admissibility filter runs first and unconditionally. Nothing downstream
    of it can reach an incident it excluded, which is the same rule the wider
    project applies to observations.
    """
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if half_life_days <= 0.0:
        raise ValueError("half_life_days must be positive")
    if prior_strength_days <= 0.0:
        raise ValueError("prior_strength_days must be positive")

    known = admissible_at(incidents, cutoff)
    if not known:
        raise ValueError(f"no incidents are publicly known at {cutoff.isoformat()}")

    history_days = (cutoff - min(i.first_known_at for i in known)).total_seconds() / 86400.0
    exposure = _effective_exposure_days(history_days, half_life_days)
    if exposure <= 0.0:
        raise ValueError("effective exposure is zero; cutoff is at the start of history")

    weighted: dict[tuple[str, str], float] = {}
    raw: dict[tuple[str, str], int] = {}
    for incident in known:
        age_days = (cutoff - incident.first_known_at).total_seconds() / 86400.0
        weight = 0.5 ** (age_days / half_life_days)
        weighted[incident.cell] = weighted.get(incident.cell, 0.0) + weight
        raw[incident.cell] = raw.get(incident.cell, 0) + 1

    cell_states = states(known)
    cell_classes = tuple(sorted(set(target_class_vocabulary) | {i.target_class for i in known}))
    n_cells = len(cell_states) * len(cell_classes)
    pooled_rate = sum(weighted.values()) / (n_cells * exposure)

    beta_0 = prior_strength_days
    alpha_0 = pooled_rate * beta_0

    forecasts: list[CellForecast] = []
    for state in cell_states:
        for target_class in cell_classes:
            key = (state, target_class)
            k = weighted.get(key, 0.0)
            alpha = alpha_0 + k
            beta = beta_0 + exposure
            probability = 1.0 - (beta / (beta + horizon_days)) ** alpha
            lo, hi = stats.gamma.ppf([0.05, 0.95], alpha, scale=1.0 / beta)
            forecasts.append(
                CellForecast(
                    state=state,
                    target_class=target_class,
                    probability=float(probability),
                    rate_per_year=float(alpha / beta * 365.25),
                    rate_lo=float(lo * 365.25),
                    rate_hi=float(hi * 365.25),
                    weighted_count=float(k),
                    raw_count=raw.get(key, 0),
                    prior_driven=k < PRIOR_DRIVEN_THRESHOLD,
                )
            )

    forecasts.sort(key=lambda f: (-f.probability, f.state, f.target_class))
    return HazardFit(
        cutoff=cutoff,
        horizon_days=horizon_days,
        half_life_days=half_life_days,
        prior_strength_days=prior_strength_days,
        effective_exposure_days=exposure,
        pooled_rate_per_year=pooled_rate * 365.25,
        incidents_used=len(known),
        cells=tuple(forecasts),
    )
