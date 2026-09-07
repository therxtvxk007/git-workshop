"""What a forecaster actually produces, declared rather than assumed.

The plan keeps the daily-path requirement for every full forecaster, and adds
the thing that requirement needs to be honest (S32.1, S42): a model does not
acquire daily count paths by satisfying a Python signature.

Persistence predicts a window total. hist12 predicts a distribution over window
totals. Neither has a daily process. Scattering a window total uniformly across
thirty days would produce an array of the right shape and a statement nobody
made -- that incidents are uniform in time within a window -- and that
statement would then be scored as if the model had asserted it.

So capability is declared, an unsupported request raises, and the run records
the gap. The alternative is a table of numbers where the reader cannot tell
which came from a model and which came from an adapter's convenience.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from pramaanx.core.errors import CapabilityUnsupportedError
from pramaanx.schemas.base import PramaanModel


class Capability(StrEnum):
    """One output contract a forecaster may claim."""

    #: P(N > 0) for a contracted window.
    OCCURRENCE_PROBABILITY = "occurrence_probability"
    #: A distribution over window totals: 0..K plus tail mass.
    COUNT_PMF = "count_pmf"
    #: Exact log probability of an observed count, tail included. Stronger than
    #: COUNT_PMF: a bucketed tail cannot score an observation beyond K.
    COUNT_LOG_PROB = "count_log_prob"
    #: Draws of daily counts, from which any window follows by summation.
    DAILY_PATHS = "daily_paths"
    #: Per-incident severity, so a fatality distribution is reachable.
    FATALITIES = "fatalities"
    #: Draws that are jointly valid across districts, so a state total is a
    #: sum of draws rather than a sum of probabilities.
    GEOGRAPHIC_JOINT = "geographic_joint"
    #: Incident-level family membership, so a union forecast is defined.
    FAMILY_UNION = "family_union"


class CapabilityManifest(PramaanModel):
    """What one adapter claims, and why it does not claim the rest."""

    model_config = PramaanModel.model_config | {"frozen": True}

    model_id: str
    supported: frozenset[Capability] = Field(default_factory=frozenset)
    #: Capability -> the missing model-specific construction. Recorded so the
    #: run manifest can say what would have to be specified, rather than
    #: leaving a blank where a number should be.
    unresolved: dict[str, str] = Field(default_factory=dict)
    #: Named where a daily construction *is* claimed, so the assumption is on
    #: the record and not inside the adapter.
    daily_construction: str = ""
    #: The declared exception to the no-hard-zero lint (S32.2). Ladder rung 1
    #: predicts exactly zero, and that is the control the whole ladder is
    #: measured against -- so the lint is scoped rather than the comparator
    #: replaced by an epsilon, which would make it a different model.
    diagnostic_zero_baseline: bool = False

    def supports(self, capability: Capability) -> bool:
        return capability in self.supported

    def require(self, capability: Capability) -> None:
        if self.supports(capability):
            return
        raise CapabilityUnsupportedError(
            "this model does not produce that output",
            model_id=self.model_id,
            capability=str(capability),
            reason=self.unresolved.get(
                str(capability), "not declared by the adapter's capability manifest"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "supported": sorted(str(item) for item in self.supported),
            "unresolved": dict(sorted(self.unresolved.items())),
            "daily_construction": self.daily_construction,
            "diagnostic_zero_baseline": self.diagnostic_zero_baseline,
        }
