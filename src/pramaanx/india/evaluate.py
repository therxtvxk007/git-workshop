"""Walk-forward evaluation: where did the thing that actually happened rank?

The question this answers is the one the judges' brief asks first -- *would it
have identified past attacks?* -- expressed so that it has a number rather than
an anecdote.

**Procedure.** Walk the registry in order. At each incident, set the cutoff to
the instant immediately before that incident became public, fit on everything
known at that cutoff, and record where the incident's own cell and state sat in
the resulting ranking. The incident being scored is never in its own fitting
window, and no later incident is either.

**Why rank and not accuracy.** Accuracy on a rare-event grid is uninformative:
predicting "no incident" in all 84 cells is right almost every time. Rank asks
the operationally meaningful question -- how far down a triage list would the
next real incident have appeared -- and it is comparable across cutoffs where a
probability is not.

**The baseline that decides whether any of this means anything.** A ranking over
``n`` cells that is pure noise still achieves ``hit@k = k/n`` by construction.
Every metric here is therefore reported against that uniform expectation, and
the lift is the only number worth reading. A hit@10 of 0.4 over 84 cells sounds
impressive and is barely above chance; the same figure over 12 cells is nothing
at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from pramaanx.india.hazard import (
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_HORIZON_DAYS,
    DEFAULT_PRIOR_STRENGTH_DAYS,
    fit_hazard,
)
from pramaanx.india.registry import Incident, admissible_at

#: Incidents needed before a fit is attempted. Below this the pooled rate is
#: estimated from too little to rank anything, and scoring it would mostly
#: measure the arbitrary order of the first few rows.
DEFAULT_MIN_HISTORY = 10

#: Reported cut-off depths for hit rates.
DEFAULT_KS = (1, 3, 5, 10)


@dataclass(frozen=True, slots=True)
class TrialResult:
    """One walk-forward trial: one incident, scored against a fit that excludes it."""

    occurred_at: str
    state: str
    city: str
    target_class: str
    cell_rank: int
    state_rank: int
    cells_ranked: int
    states_ranked: int
    cell_probability: float
    prior_driven_cell: bool
    """The model ranked this cell on the prior, not on its own history."""


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Aggregate skill, always paired with the chance expectation."""

    trials: tuple[TrialResult, ...]
    horizon_days: int
    half_life_days: float
    prior_strength_days: float
    cell_hit_at: dict[int, float]
    state_hit_at: dict[int, float]
    cell_chance_at: dict[int, float]
    state_chance_at: dict[int, float]
    cell_lift_at: dict[int, float]
    state_lift_at: dict[int, float]
    median_cell_rank: float
    median_state_rank: float
    mean_reciprocal_cell_rank: float
    prior_driven_cell_fraction: float
    """Share of trials whose cell was ranked on the prior rather than its own
    history. This is the single most important number in the report: it bounds
    how much of the miss rate *any* rate model could recover, because a cell
    with no usable history carries no rate to estimate."""

    @property
    def n_trials(self) -> int:
        return len(self.trials)


def _median(values: list[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def walk_forward(
    incidents: tuple[Incident, ...],
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    prior_strength_days: float = DEFAULT_PRIOR_STRENGTH_DAYS,
    min_history: int = DEFAULT_MIN_HISTORY,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> EvaluationReport:
    """Score every incident that has enough history behind it."""
    trials: list[TrialResult] = []

    for incident in incidents:
        cutoff = incident.first_known_at - timedelta(seconds=1)
        known = admissible_at(incidents, cutoff)
        if len(known) < min_history:
            continue

        fit = fit_hazard(
            incidents,
            cutoff,
            horizon_days=horizon_days,
            half_life_days=half_life_days,
            prior_strength_days=prior_strength_days,
        )
        cell_rank = fit.rank_of(incident.state, incident.target_class)
        state_rank = fit.rank_of_state(incident.state)
        if cell_rank is None or state_rank is None:
            # The state or class had never been seen, so no cell exists for it.
            # Rank it one past the bottom rather than dropping the trial: a
            # dropped trial silently improves every metric below.
            cell_rank = len(fit.cells) + 1
            state_rank = len(fit.state_ranking()) + 1
            probability = 0.0
            prior_driven = True
        else:
            match = fit.cells[cell_rank - 1]
            probability = match.probability
            prior_driven = match.prior_driven

        trials.append(
            TrialResult(
                occurred_at=incident.occurred_at.date().isoformat(),
                state=incident.state,
                city=incident.city,
                target_class=incident.target_class,
                cell_rank=cell_rank,
                state_rank=state_rank,
                cells_ranked=len(fit.cells),
                states_ranked=len(fit.state_ranking()),
                cell_probability=probability,
                prior_driven_cell=prior_driven,
            )
        )

    if not trials:
        raise ValueError("no trial had enough history; lower min_history or extend the registry")

    n = len(trials)
    cell_hit = {k: sum(1 for t in trials if t.cell_rank <= k) / n for k in ks}
    state_hit = {k: sum(1 for t in trials if t.state_rank <= k) / n for k in ks}
    cell_chance = {k: sum(min(k, t.cells_ranked) / t.cells_ranked for t in trials) / n for k in ks}
    state_chance = {
        k: sum(min(k, t.states_ranked) / t.states_ranked for t in trials) / n for k in ks
    }

    return EvaluationReport(
        trials=tuple(trials),
        horizon_days=horizon_days,
        half_life_days=half_life_days,
        prior_strength_days=prior_strength_days,
        cell_hit_at=cell_hit,
        state_hit_at=state_hit,
        cell_chance_at=cell_chance,
        state_chance_at=state_chance,
        cell_lift_at={
            k: (cell_hit[k] / cell_chance[k]) if cell_chance[k] > 0 else float("nan") for k in ks
        },
        state_lift_at={
            k: (state_hit[k] / state_chance[k]) if state_chance[k] > 0 else float("nan") for k in ks
        },
        median_cell_rank=_median([float(t.cell_rank) for t in trials]),
        median_state_rank=_median([float(t.state_rank) for t in trials]),
        mean_reciprocal_cell_rank=sum(1.0 / t.cell_rank for t in trials) / n,
        prior_driven_cell_fraction=sum(1 for t in trials if t.prior_driven_cell) / n,
    )
