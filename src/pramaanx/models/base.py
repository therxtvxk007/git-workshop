"""The forecaster interface and the artifact a fit returns.

Two things the plan asks for that a bare ``fit``/``predict`` pair does not give
(S32.1, S36.1):

* a fit returns a *serializable artifact*, and every fitted preprocessing step
  belongs to it. A transform fitted inside ``predict`` on the issue batch has
  seen data the protocol says it should not, and nothing in the signature would
  show that;
* the runtime, not the model, owns saving, loading and ledger publication. A
  model that writes its own outputs decides its own provenance.

The capability manifest travels with the artifact, so a scorer can tell which
metrics this forecast supports before it computes one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import polars as pl

from pramaanx.core.contexts import FitContext, ForecastContext
from pramaanx.core.errors import CapabilityUnsupportedError, ContractViolationError
from pramaanx.core.rng import RandomStreams
from pramaanx.hashing import hash_object
from pramaanx.models.capabilities import Capability, CapabilityManifest
from pramaanx.models.samples import PathSamples, WindowForecast, WindowSamples


@dataclass(frozen=True)
class ModelArtifact:
    """What a fit produced: parameters, and the identity that pins them."""

    model_id: str
    capabilities: CapabilityManifest
    parameters: dict[str, Any] = field(default_factory=dict)
    #: Training rows the fit actually used, after the protocol's filters. Part
    #: of the identity, because two fits over different eligible sets are two
    #: models even with identical hyperparameters.
    training_rows: int = 0
    fit_context: str = ""

    def identity(self) -> str:
        """The full identity, context included. What the ledger records."""
        return hash_object(
            {
                "model_id": self.model_id,
                "parameters": self.parameters,
                "training_rows": self.training_rows,
                "fit_context": self.fit_context,
                "capabilities": self.capabilities.to_dict(),
            }
        )

    def parameter_identity(self) -> str:
        """Only what determines the predictive distribution.

        This is what a predictive random stream is keyed on, and the exclusion
        of ``fit_context`` is deliberate. A context carries the input manifest,
        which changes whenever *anything* is appended to the store -- including
        rows dated after the cutoff, which by construction cannot reach this
        fit. Seeding on the full identity would let evidence from after the
        origin reseed the sampler and move a forecast it can never inform,
        which is exactly the invariance the plan requires (S38).
        """
        return hash_object(
            {
                "model_id": self.model_id,
                "parameters": self.parameters,
                "training_rows": self.training_rows,
            }
        )


@dataclass(frozen=True)
class ForecastArtifact:
    """A frozen forecast: samples, the panel it covers, and what it supports.

    Carries either daily paths or window totals. Which one is not a detail:
    a window-only artifact cannot answer a different window, and saying so is
    the point of having both (S42).
    """

    model_id: str
    capabilities: CapabilityManifest
    context_identity: str
    model_identity: str
    paths: PathSamples | None = None
    windows: WindowSamples | None = None

    def __post_init__(self) -> None:
        if (self.paths is None) == (self.windows is None):
            raise ContractViolationError(
                "a forecast artifact carries exactly one of daily paths or window totals",
                model_id=self.model_id,
            )
        if self.paths is not None and not self.capabilities.supports(Capability.DAILY_PATHS):
            raise ContractViolationError(
                "daily paths were produced by a model that does not declare them",
                model_id=self.model_id,
            )

    @property
    def n_draws(self) -> int:
        return (self.paths or self.windows).n_draws  # type: ignore[union-attr]

    def window(self, start: Any, end: Any) -> WindowSamples:
        """Totals for a window, if this artifact can honestly produce them."""
        if self.paths is not None:
            return self.paths.window(start, end)
        if self.windows is None:  # pragma: no cover -- __post_init__ forbids it
            raise ContractViolationError("forecast artifact carries no samples")
        if (self.windows.window.start, self.windows.window.end) != (start, end):
            raise CapabilityUnsupportedError(
                "this model forecasts one contracted window and has no daily "
                "process, so another window cannot be derived from it",
                model_id=self.model_id,
                contracted=self.windows.window.to_dict(),
                requested={"start": str(start), "end": str(end)},
                reason=self.capabilities.unresolved.get(
                    str(Capability.DAILY_PATHS), "no daily construction declared"
                ),
            )
        return self.windows

    def summarise(self, start: Any, end: Any) -> tuple[WindowForecast, ...]:
        return self.window(start, end).summarise()

    def to_frame(self, start: Any, end: Any) -> pl.DataFrame:
        """One row per panel row, in the layout the verifier and report read."""
        return pl.DataFrame([forecast.to_dict() for forecast in self.summarise(start, end)])


@runtime_checkable
class Forecaster(Protocol):
    """Fit returns an artifact; predict consumes one. Neither touches storage."""

    model_id: str

    def capabilities(self) -> CapabilityManifest: ...

    def fit(self, panel: pl.DataFrame, *, ctx: FitContext, rng: RandomStreams) -> ModelArtifact: ...

    def predict(
        self,
        issue_rows: pl.DataFrame,
        *,
        model: ModelArtifact,
        ctx: ForecastContext,
        rng: RandomStreams,
    ) -> ForecastArtifact: ...
