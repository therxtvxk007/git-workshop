"""Rung 2: the long-run rate per district-family.

The daily construction is declared, not assumed. A rate is events per unit
time; turning it into daily draws needs a process, and this rung uses a
homogeneous Poisson one. That is a real assumption -- it says incidents are
uniform in time within the window and independent of each other -- so it is
named in the capability manifest rather than buried in the sampler, which is
the distinction the plan draws between a stated construction and a smuggled one
(S32.1, S42).

Because the construction is genuinely daily, this rung answers any horizon the
contract asks for, and its nested windows are coherent by construction.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import polars as pl

from pramaanx.core.contexts import FitContext, ForecastContext
from pramaanx.core.errors import ContractViolationError
from pramaanx.core.rng import RandomStreams
from pramaanx.hashing import utc_isoformat
from pramaanx.models.base import ForecastArtifact, ModelArtifact
from pramaanx.models.capabilities import Capability, CapabilityManifest
from pramaanx.models.ladder._history import build_history, issue_keys, issue_window
from pramaanx.models.samples import PanelKey, PathSamples
from pramaanx.panel.windows import CalendarContract

MODEL_ID = "ladder.climatology"
DAILY_CONSTRUCTION = "homogeneous_poisson_from_long_run_rate"


def daily_paths(
    rates: np.ndarray,
    *,
    edges: tuple[datetime, ...],
    n_draws: int,
    rng: RandomStreams,
    stream_name: tuple[str, ...],
) -> np.ndarray:
    """Poisson daily counts, ``[draw, row, day]``, from per-row daily rates."""
    generator = rng.stream(*stream_name)
    n_days = len(edges) - 1
    lam = np.repeat(rates[np.newaxis, :, np.newaxis], n_days, axis=2)
    return generator.poisson(lam=np.broadcast_to(lam, (n_draws, rates.size, n_days))).astype(
        np.int64
    )


class Climatology:
    """Events per day, pooled over the whole observed history of a cell."""

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
                    "draws are independent across districts; independent "
                    "marginals are not a calibrated joint distribution"
                ),
                str(Capability.COUNT_LOG_PROB): (
                    "sample-based; an exact tail probability for an arbitrary "
                    "observed count is not available from the PMF bucket"
                ),
                str(Capability.FATALITIES): "no severity head",
            },
            daily_construction=DAILY_CONSTRUCTION,
        )

    def fit(self, panel: pl.DataFrame, *, ctx: FitContext, rng: RandomStreams) -> ModelArtifact:  # noqa: ARG002
        history = build_history(panel)
        return ModelArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            parameters={
                "rate_per_day": {
                    f"{district}|{family}": item.rate_per_day
                    for (district, family), item in sorted(history.items())
                }
            },
            training_rows=panel.height,
            fit_context=ctx.identity(),
        )

    def _rates(self, model: ModelArtifact, keys: tuple[PanelKey, ...]) -> np.ndarray:
        table = model.parameters.get("rate_per_day", {})
        return np.array(
            [table.get(f"{key.district_id}|{key.family}", 0.0) for key in keys], dtype=float
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
        window = issue_window(issue_rows)
        edges = self.calendar.daily_edges(window)
        if len(edges) < 2:
            raise ContractViolationError("window is shorter than one day")

        counts = daily_paths(
            self._rates(model, keys),
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
