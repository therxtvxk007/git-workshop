"""Rung 1: predict exactly zero.

The control the whole ladder is measured against. On a panel where most cells
are empty most of the time it is not a strawman, and a challenger that cannot
beat it on a proper score has not shown anything.

It is also the one model allowed to assert a hard zero probability. The plan's
review found that the no-hard-zero lint and this comparator contradict each
other (S27.1, S32.2), and resolved it by scoping the lint rather than replacing
this rung with an epsilon -- which would have made it a different model and its
score a different number.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from pramaanx.core.contexts import FitContext, ForecastContext
from pramaanx.core.rng import RandomStreams
from pramaanx.models.base import ForecastArtifact, ModelArtifact
from pramaanx.models.capabilities import Capability, CapabilityManifest
from pramaanx.models.ladder._history import issue_keys, issue_window
from pramaanx.models.samples import WindowSamples
from pramaanx.panel.windows import Window

MODEL_ID = "ladder.zero"


class ZeroBaseline:
    """Exactly zero, for every district, family and window."""

    model_id = MODEL_ID

    def __init__(self, n_draws: int = 1) -> None:
        # One draw is enough: the distribution is degenerate, and drawing a
        # thousand identical zeros would only make the Monte Carlo interval
        # look narrower than the model's actual claim.
        self.n_draws = n_draws

    def capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            model_id=self.model_id,
            supported=frozenset(
                {
                    Capability.OCCURRENCE_PROBABILITY,
                    Capability.COUNT_PMF,
                    Capability.COUNT_LOG_PROB,
                }
            ),
            unresolved={
                str(Capability.DAILY_PATHS): (
                    "a degenerate zero has no daily process to describe; the "
                    "window total is the whole model"
                ),
                str(Capability.FATALITIES): "no severity head",
            },
            diagnostic_zero_baseline=True,
        )

    # rng is unused: this rung learns nothing, and that is the whole point of it.
    def fit(self, panel: pl.DataFrame, *, ctx: FitContext, rng: RandomStreams) -> ModelArtifact:  # noqa: ARG002
        return ModelArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            parameters={},
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
        start, end = issue_window(issue_rows)
        return ForecastArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            context_identity=ctx.identity(),
            model_identity=model.identity(),
            windows=WindowSamples(
                keys=keys,
                window=Window(start, end),  # type: ignore[arg-type]
                counts=np.zeros((self.n_draws, len(keys)), dtype=np.int64),
            ),
        )
