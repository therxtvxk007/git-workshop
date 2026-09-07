"""Rung 4: the rolling 12-month empirical distribution.

The paper's primary count reference, and the anchor the VIEWS result says is
hard to beat. It resamples the last N observed window counts for a cell, so its
distribution is exactly the cell's recent history and nothing else.

Like persistence, it is a window-total model. Its draws are a bootstrap over
observed totals, and there is no daily process behind them, so it declares no
daily paths. Unlike persistence it is genuinely distributional, which is what
makes it a usable count reference rather than a point forecast.

A cell with no observed history gets no forecast rather than a zero. "We have
never observed this district" and "this district has no events" are different
statements, and only the second is a prediction.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from pramaanx.core.contexts import FitContext, ForecastContext
from pramaanx.core.errors import ContractViolationError
from pramaanx.core.rng import RandomStreams
from pramaanx.hashing import utc_isoformat
from pramaanx.models.base import ForecastArtifact, ModelArtifact
from pramaanx.models.capabilities import Capability, CapabilityManifest
from pramaanx.models.ladder._history import build_history, issue_keys, issue_window
from pramaanx.models.samples import WindowSamples

MODEL_ID = "ladder.hist12"
DEFAULT_LOOKBACK = 12


class Hist12:
    """Resample the last ``lookback`` observed window counts for each cell."""

    model_id = MODEL_ID

    def __init__(self, *, lookback: int = DEFAULT_LOOKBACK, n_draws: int = 2000) -> None:
        if lookback <= 0:
            raise ContractViolationError("lookback must be positive")
        self.lookback = lookback
        self.n_draws = n_draws

    def capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            model_id=self.model_id,
            supported=frozenset({Capability.OCCURRENCE_PROBABILITY, Capability.COUNT_PMF}),
            unresolved={
                str(Capability.DAILY_PATHS): (
                    "an empirical distribution over window totals carries no within-window process"
                ),
                str(Capability.COUNT_LOG_PROB): (
                    "empirical support only; a count never observed in the "
                    "lookback has zero mass under this model"
                ),
                str(Capability.GEOGRAPHIC_JOINT): "cells are resampled independently",
                str(Capability.FATALITIES): "no severity head",
            },
        )

    # rng is unused at fit time: the fit is a lookup table of recent counts.
    def fit(self, panel: pl.DataFrame, *, ctx: FitContext, rng: RandomStreams) -> ModelArtifact:  # noqa: ARG002
        history = build_history(panel)
        return ModelArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            parameters={
                "lookback": self.lookback,
                "recent_counts": {
                    f"{district}|{family}": list(item.counts[-self.lookback :])
                    for (district, family), item in sorted(history.items())
                },
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
        rng: RandomStreams,
    ) -> ForecastArtifact:
        keys = issue_keys(issue_rows)
        window = issue_window(issue_rows)
        table = model.parameters.get("recent_counts", {})

        missing = [
            key.as_tuple() for key in keys if not table.get(f"{key.district_id}|{key.family}")
        ]
        if missing:
            raise ContractViolationError(
                "no observed history for these cells; an empirical distribution "
                "over nothing is not a forecast of zero",
                cells=[list(cell) for cell in missing[:10]],
                total=len(missing),
            )

        generator = rng.stream(
            "predict", self.model_id, utc_isoformat(ctx.issue_time), model.parameter_identity()
        )
        columns = []
        for key in keys:
            observed = np.asarray(table[f"{key.district_id}|{key.family}"], dtype=np.int64)
            columns.append(generator.choice(observed, size=self.n_draws, replace=True))

        return ForecastArtifact(
            model_id=self.model_id,
            capabilities=self.capabilities(),
            context_identity=ctx.identity(),
            model_identity=model.identity(),
            windows=WindowSamples(
                keys=keys,
                window=window,
                counts=np.stack(columns, axis=1).astype(np.int64),
            ),
        )
