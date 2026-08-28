"""Region/target-class hazard: forward ranking, and walk-forward scoring.

Three commands, kept separate because they have different evidential standing
and must not be mistaken for one another:

``forecast``       ranks cells over a horizon from everything known at a date.
``retrospective``  ranks cells at a historical cutoff and then, and only then,
                   reveals what actually happened next.
``backtest``       walks the whole registry and reports skill against chance.

Every manifest carries ``interpretation_limits``. A ranking quoted without them
is a different and less honest object than the one this module computes.
"""

from __future__ import annotations

from typing import Annotated

import typer

from pramaanx.cli._app import OutputOption, _emit, _parse_moment, app
from pramaanx.india.evaluate import walk_forward
from pramaanx.india.hazard import (
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_HORIZON_DAYS,
    DEFAULT_PRIOR_STRENGTH_DAYS,
    fit_hazard,
)
from pramaanx.india.registry import DEFAULT_REGISTRY, load_incidents

hazard_app = typer.Typer(
    help="Region and target-class hazard ranking over the incident registry.",
    no_args_is_help=True,
)
app.add_typer(hazard_app, name="hazard")

_LIMITS = [
    "A cell is a state and a broad target class over a horizon of weeks. It is "
    "not a site, a date, or an actor, and narrowing the horizon does not make "
    "it one.",
    "The registry holds tens of incidents. Rates are shrunk hard toward a "
    "pooled prior and the credible intervals are correspondingly wide.",
    "Fatality counts are description only and are never a model input.",
    "Cells flagged prior_driven are ranked on the prior, not on their own "
    "history. Their position is not evidence about them.",
    "Ranking is not detection. See the backtest command for skill against "
    "chance before reading any single ranking as informative.",
]

TopOption = Annotated[int, typer.Option("--top", "-n", help="How many cells to report.")]
HorizonOption = Annotated[int, typer.Option("--horizon", help="Forecast horizon in days.")]
HalfLifeOption = Annotated[float, typer.Option("--half-life", help="Recency half-life in days.")]
PriorOption = Annotated[float, typer.Option("--prior", help="Prior strength as pseudo-days.")]
RegistryOption = Annotated[str, typer.Option("--registry", help="Incident registry CSV.")]


def _cell_rows(fit, limit):  # type: ignore[no-untyped-def]
    return [
        {
            "rank": i,
            "state": c.state,
            "target_class": c.target_class,
            "probability": round(c.probability, 6),
            "rate_per_year": round(c.rate_per_year, 5),
            "rate_ci90": [round(c.rate_lo, 5), round(c.rate_hi, 5)],
            "incidents": c.raw_count,
            "weighted_incidents": round(c.weighted_count, 4),
            "prior_driven": c.prior_driven,
        }
        for i, c in enumerate(fit.top(limit), start=1)
    ]


@hazard_app.command()
def forecast(
    as_of: Annotated[str, typer.Option("--as-of", help="Cutoff instant, ISO-8601.")],
    top: TopOption = 10,
    horizon: HorizonOption = DEFAULT_HORIZON_DAYS,
    half_life: HalfLifeOption = DEFAULT_HALF_LIFE_DAYS,
    prior: PriorOption = DEFAULT_PRIOR_STRENGTH_DAYS,
    registry: RegistryOption = str(DEFAULT_REGISTRY),
    output: OutputOption = None,
) -> None:
    """Rank cells by modelled hazard using only what was known at ``--as-of``."""
    incidents = load_incidents(registry)
    cutoff = _parse_moment(as_of)
    fit = fit_hazard(
        incidents,
        cutoff,
        horizon_days=horizon,
        half_life_days=half_life,
        prior_strength_days=prior,
    )
    _emit(
        {
            "kind": "hazard_forecast",
            "cutoff": cutoff.isoformat(),
            "horizon_days": horizon,
            "incidents_known": fit.incidents_used,
            "cells_ranked": len(fit.cells),
            "pooled_rate_per_year": round(fit.pooled_rate_per_year, 5),
            "effective_exposure_days": round(fit.effective_exposure_days, 1),
            "cells": _cell_rows(fit, top),
            "states": [
                {"rank": i, "state": s, "probability": round(p, 6)}
                for i, (s, p) in enumerate(fit.state_ranking()[:top], start=1)
            ],
            "interpretation_limits": _LIMITS,
        },
        output,
    )


@hazard_app.command()
def retrospective(
    cutoff: Annotated[str, typer.Option("--cutoff", help="Historical cutoff, ISO-8601.")],
    top: TopOption = 10,
    horizon: HorizonOption = DEFAULT_HORIZON_DAYS,
    registry: RegistryOption = str(DEFAULT_REGISTRY),
    output: OutputOption = None,
) -> None:
    """Rank at a historical cutoff, then reveal what actually happened next.

    The fit is computed before the outcome is looked up, in that order, for the
    same reason the backtest runs in two passes.
    """
    incidents = load_incidents(registry)
    moment = _parse_moment(cutoff)
    fit = fit_hazard(incidents, moment, horizon_days=horizon)

    # Only now is the outcome read.
    later = [i for i in incidents if i.first_known_at > moment]
    actual = later[0] if later else None

    outcome: dict[str, object] | None = None
    if actual is not None:
        rank = fit.rank_of(actual.state, actual.target_class)
        match = fit.cells[rank - 1] if rank is not None else None
        outcome = {
            "occurred_at": actual.occurred_at.date().isoformat(),
            "state": actual.state,
            "city": actual.city,
            "target_class": actual.target_class,
            "days_after_cutoff": round((actual.occurred_at - moment).total_seconds() / 86400.0, 2),
            "cell_rank": rank,
            "cells_ranked": len(fit.cells),
            "state_rank": fit.rank_of_state(actual.state),
            "states_ranked": len(fit.state_ranking()),
            "cell_prior_driven": match.prior_driven if match else None,
            "cell_prior_incidents": match.raw_count if match else None,
        }

    _emit(
        {
            "kind": "hazard_retrospective",
            "cutoff": moment.isoformat(),
            "horizon_days": horizon,
            "incidents_known": fit.incidents_used,
            "cells": _cell_rows(fit, top),
            "states": [
                {"rank": i, "state": s, "probability": round(p, 6)}
                for i, (s, p) in enumerate(fit.state_ranking()[:top], start=1)
            ],
            "actual_next_incident": outcome,
            "interpretation_limits": _LIMITS,
        },
        output,
    )


@hazard_app.command()
def backtest(
    horizon: HorizonOption = DEFAULT_HORIZON_DAYS,
    half_life: HalfLifeOption = DEFAULT_HALF_LIFE_DAYS,
    prior: PriorOption = DEFAULT_PRIOR_STRENGTH_DAYS,
    registry: RegistryOption = str(DEFAULT_REGISTRY),
    output: OutputOption = None,
) -> None:
    """Walk the registry and report rank skill against chance."""
    incidents = load_incidents(registry)
    report = walk_forward(
        incidents,
        horizon_days=horizon,
        half_life_days=half_life,
        prior_strength_days=prior,
    )
    _emit(
        {
            "kind": "hazard_backtest",
            "trials": report.n_trials,
            "horizon_days": horizon,
            "half_life_days": half_life,
            "prior_strength_days": prior,
            "cell": {
                "hit_at": {str(k): round(v, 4) for k, v in report.cell_hit_at.items()},
                "chance_at": {str(k): round(v, 4) for k, v in report.cell_chance_at.items()},
                "lift_at": {str(k): round(v, 3) for k, v in report.cell_lift_at.items()},
                "median_rank": report.median_cell_rank,
                "mean_reciprocal_rank": round(report.mean_reciprocal_cell_rank, 4),
            },
            "state": {
                "hit_at": {str(k): round(v, 4) for k, v in report.state_hit_at.items()},
                "chance_at": {str(k): round(v, 4) for k, v in report.state_chance_at.items()},
                "lift_at": {str(k): round(v, 3) for k, v in report.state_lift_at.items()},
                "median_rank": report.median_state_rank,
            },
            "prior_driven_cell_fraction": round(report.prior_driven_cell_fraction, 4),
            "interpretation_limits": [
                *_LIMITS,
                "Lift, not hit rate, is the number to read: a random ranking "
                "achieves hit@k = k/n by construction.",
            ],
        },
        output,
    )
