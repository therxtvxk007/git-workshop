"""Rung 3: last window's observation, repeated.

This rung is where the plan's capability rule earns its keep (S42, first row).
Persistence predicts a *window total*. It has no daily process, and inventing
one -- scattering the total uniformly across thirty days -- would produce an
array of the right shape carrying a claim nobody made. So the adapter declares
no daily paths, says why, and refuses any window other than the contracted one.

The consequence is visible rather than hidden: this rung cannot enter a
7-versus-30-day horizon comparison, and the run manifest says so instead of the
comparison quietly including a uniform-in-time assumption attributed to it.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from pramaanx.core.contexts import FitContext, ForecastContext
from pramaanx.core.rng import RandomStreams
from pramaanx.models.base import ForecastArtifact, ModelArtifact
from pramaanx.models.capabilities import Capability, CapabilityManifest
from pramaanx.models.ladder._history import build_history, issue_keys, issue_window
from pramaanx.models.samples import ProbabilityMethod, WindowSamples

MODEL_ID = "ladder.persistence"

NO_DAILY_PROCESS = (
    "persistence predicts one window total; its within-window daily process is "
    "not specified, and a uniform scatter would be an added assumption"
)


class Persistence:
    """The most recent observed window count for each district-family."""

    model_id = MODEL_ID

    def capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            model_id=self.model_id,
            supported=frozenset({Capability.OCCURRENCE_PROBABILITY, Capability.COUNT_PMF}),
            unresolved={
                str(Capability.DAILY_PATHS): NO_DAILY_PROCESS,
                str(Capability.COUNT_LOG_PROB): (
                    "degenerate at one value; any other observed count has zero "
                    "mass and an infinite log score, which is a real result and "
                    "not one to be clipped away"
                ),
                str(Capability.GEOGRAPHIC_JOINT): "no cross-district dependence",
                str(Capability.FATALITIES): "no severity head",
            },
        )

    # rng is unused: the forecast is a lookup, not a draw.
    def fit(self, panel: pl.DataFrame, *, ctx: FitContext, rng: RandomStreams) -> ModelArtifact:  # noqa: ARG002
        history = build_history(panel)
        return ModelArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            parameters={
                "last_count": {
                    f"{district}|{family}": (item.counts[-1] if item.counts else 0)
                    for (district, family), item in sorted(history.items())
                }
            },
            training_rows=panel.height,
            fit_context=ctx.identity(),
        )

    def predict(
        self,
        issue_rows: pl.DataFrame,
        *,
        model: ModelArtifact,
        ctx: ForecastContext,
        rng: RandomStreams,  # noqa: ARG002 -- deterministic
    ) -> ForecastArtifact:
        keys = issue_keys(issue_rows)
        window = issue_window(issue_rows)
        table = model.parameters.get("last_count", {})
        counts = np.array(
            [[table.get(f"{key.district_id}|{key.family}", 0) for key in keys]], dtype=np.int64
        )
        return ForecastArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            context_identity=ctx.identity(),
            model_identity=model.identity(),
            windows=WindowSamples(
                keys=keys,
                window=window,
                counts=counts,
                method=ProbabilityMethod.ANALYTIC,
            ),
        )
