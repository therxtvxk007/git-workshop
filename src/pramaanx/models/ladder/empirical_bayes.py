"""Rung 5: Gamma-Poisson shrinkage per district-family.

The first rung that borrows strength. A district with three observed windows
and one incident has a rate estimate of roughly nothing or roughly everything
depending on which window you drop; pooling it towards the family's overall
rate gives an estimate that survives its own sample size.

The prior is fitted by moments from the observed cells rather than chosen, so
two runs over the same panel shrink by the same amount, and the amount is
recorded in the artifact rather than tuned per cell.

The daily construction is the same declared homogeneous Poisson process rung 2
uses, over the shrunk rate. Shared deliberately: two rungs that differ only in
how they estimate a rate should not also differ in what they assume about time,
or the comparison measures both differences at once.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from pramaanx.core.contexts import FitContext, ForecastContext
from pramaanx.core.rng import RandomStreams
from pramaanx.hashing import utc_isoformat
from pramaanx.models.base import ForecastArtifact, ModelArtifact
from pramaanx.models.capabilities import Capability, CapabilityManifest
from pramaanx.models.ladder._history import build_history, issue_keys, issue_window
from pramaanx.models.ladder.climatology import DAILY_CONSTRUCTION, daily_paths
from pramaanx.models.samples import PathSamples
from pramaanx.panel.windows import CalendarContract, Window

MODEL_ID = "ladder.empirical_bayes"


def fit_gamma_prior(rates: list[float], exposures: list[float]) -> tuple[float, float]:
    """Moment-matched Gamma prior over cell rates.

    Returns ``(shape, rate)``. Where the observed spread is at or below what
    Poisson noise alone would produce, there is no evidence of real
    heterogeneity, and the prior collapses towards complete pooling -- which is
    the right answer, not a degenerate case to be patched around.
    """
    if not rates:
        return (1.0, 1.0)
    mean = float(np.mean(rates))
    variance = float(np.var(rates))
    if mean <= 0.0:
        return (1.0, 1.0)
    mean_exposure = float(np.mean(exposures)) or 1.0
    poisson_share = mean / mean_exposure
    excess = max(variance - poisson_share, 0.0)
    if excess <= 0.0:
        # Complete pooling: a very tight prior at the overall mean.
        return (1e6, 1e6 / mean)
    shape = mean**2 / excess
    return (shape, shape / mean)


class EmpiricalBayes:
    """Per-cell rates shrunk towards a moment-matched family prior."""

    model_id = MODEL_ID

    def __init__(self, *, n_draws: int = 2000, calendar: CalendarContract | None = None) -> None:
        self.n_draws = n_draws
        self.calendar = calendar or CalendarContract()

    def capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            model_id=self.model_id,
            supported=frozenset(
                {
                    Capability.OCCURRENCE_PROBABILITY,
                    Capability.COUNT_PMF,
                    Capability.DAILY_PATHS,
                }
            ),
            unresolved={
                str(Capability.GEOGRAPHIC_JOINT): (
                    "cells share a prior but their draws are independent; "
                    "shared shrinkage is not modelled dependence"
                ),
                str(Capability.COUNT_LOG_PROB): "sample-based; no exact tail probability",
                str(Capability.FATALITIES): "no severity head",
            },
            daily_construction=DAILY_CONSTRUCTION,
        )

    # rng is unused at fit time: the prior is moment-matched, not sampled.
    def fit(self, panel: pl.DataFrame, *, ctx: FitContext, rng: RandomStreams) -> ModelArtifact:  # noqa: ARG002
        history = build_history(panel)
        by_family: dict[str, list[tuple[str, float, float, int]]] = {}
        for (district, family), item in sorted(history.items()):
            exposure = item.windows * item.window_days
            by_family.setdefault(family, []).append(
                (district, item.rate_per_day, exposure, item.total_events)
            )

        shrunk: dict[str, float] = {}
        priors: dict[str, list[float]] = {}
        for family, cells in sorted(by_family.items()):
            shape, rate = fit_gamma_prior([cell[1] for cell in cells], [cell[2] for cell in cells])
            priors[family] = [shape, rate]
            for district, _, exposure, events in cells:
                # Gamma-Poisson posterior mean: (a + events) / (b + exposure).
                shrunk[f"{district}|{family}"] = (shape + events) / (rate + exposure)

        return ModelArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            parameters={"rate_per_day": shrunk, "prior": priors},
            training_rows=panel.height,
            fit_context=ctx.identity(),
        )

    def predict(
        self,
        issue_rows: pl.DataFrame,
        *,
        model: ModelArtifact,
        ctx: ForecastContext,
        rng: RandomStreams,
    ) -> ForecastArtifact:
        keys = issue_keys(issue_rows)
        start, end = issue_window(issue_rows)
        edges = self.calendar.daily_edges(Window(start, end))  # type: ignore[arg-type]
        table = model.parameters.get("rate_per_day", {})
        rates = np.array(
            [table.get(f"{key.district_id}|{key.family}", 0.0) for key in keys], dtype=float
        )
        counts = daily_paths(
            rates,
            edges=edges,
            n_draws=self.n_draws,
            rng=rng,
            stream_name=(
                "predict",
                self.model_id,
                utc_isoformat(ctx.issue_time),
                model.parameter_identity(),
            ),
        )
        return ForecastArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            context_identity=ctx.identity(),
            model_identity=model.identity(),
            paths=PathSamples(keys=keys, edges=edges, counts=counts),
        )
