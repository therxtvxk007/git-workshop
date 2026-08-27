"""Comparing a generator against the preregistered base-rate floor.

The preregistration names G0 as the floor every later branch has to clear. This
module makes that comparison a computation rather than an assertion in a
report, and it separates two questions that get conflated whenever a new
generator looks good:

*Did it find different candidates?* A set-level question about discovery,
answered here by :func:`compare_discovery`. A generator whose candidate set is
a subset of the floor's has added nothing, however much better its scores look.

*Did it forecast better?* A question about scoring, answered by the evaluation
harness. This module deliberately does not compute it. Handing a generator the
job of grading itself is how a floor comparison quietly becomes a formality --
so :class:`FloorVerdict` takes the metrics as inputs and refuses to guess them.

The margin is preregistered too. Beating the floor by less than the margin is
recorded as *not cleared*, because a generator that wins by a hair on one
backtest has demonstrated variance, not skill.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field, model_validator

from pramaanx.generators.base import CandidateProposal
from pramaanx.schemas.base import PramaanModel

#: Preregistered floor generator. Named here so a comparison cannot quietly be
#: run against something weaker.
FLOOR_GENERATOR = "base_rate"

#: Minimum improvement over the floor that counts as clearing it.
DEFAULT_MARGIN = 0.02


class DiscoveryComparison(PramaanModel):
    """Set-level comparison of two generators' candidate pools."""

    floor_name: str
    challenger_name: str
    floor_only: list[str] = Field(default_factory=list)
    challenger_only: list[str] = Field(default_factory=list)
    shared: list[str] = Field(default_factory=list)

    @property
    def floor_count(self) -> int:
        return len(self.floor_only) + len(self.shared)

    @property
    def challenger_count(self) -> int:
        return len(self.challenger_only) + len(self.shared)

    @property
    def union_count(self) -> int:
        return len(self.floor_only) + len(self.challenger_only) + len(self.shared)

    @property
    def novel_fraction(self) -> float:
        """Share of the challenger's pool the floor never proposed."""
        return len(self.challenger_only) / self.challenger_count if self.challenger_count else 0.0

    @property
    def coverage_of_floor(self) -> float:
        """Share of the floor's pool the challenger also found.

        Low coverage is not automatically bad -- a specialised branch is allowed
        to be narrow -- but it must be visible, because a union stage that drops
        the floor's candidates loses the one pool with a known hit rate.
        """
        return len(self.shared) / self.floor_count if self.floor_count else 0.0

    @property
    def adds_discovery(self) -> bool:
        return bool(self.challenger_only)


def compare_discovery(
    floor: Sequence[CandidateProposal],
    challenger: Sequence[CandidateProposal],
    *,
    floor_name: str = FLOOR_GENERATOR,
) -> DiscoveryComparison:
    """Compare two candidate pools by structured identity.

    Comparison is on ``candidate_key``, the hypothesis identity, not on object
    equality: two generators proposing the same event with different scores have
    proposed the same candidate, and that is exactly what the union stage will
    treat them as.
    """
    challenger_names = sorted({proposal.generator_name for proposal in challenger})
    floor_keys = {proposal.candidate_key for proposal in floor}
    challenger_keys = {proposal.candidate_key for proposal in challenger}
    return DiscoveryComparison(
        floor_name=floor_name,
        challenger_name="|".join(challenger_names) or "<empty>",
        floor_only=sorted(floor_keys - challenger_keys),
        challenger_only=sorted(challenger_keys - floor_keys),
        shared=sorted(floor_keys & challenger_keys),
    )


class FloorVerdict(PramaanModel):
    """Whether a challenger cleared the preregistered floor.

    Metrics are inputs. The harness that computed them owns their definition;
    this type owns only the comparison and the margin, so that "cleared the
    floor" means the same thing in every report that says it.
    """

    challenger_name: str
    metric_name: str
    floor_value: float
    challenger_value: float
    margin: float = Field(default=DEFAULT_MARGIN, ge=0.0)
    #: True when a larger value is worse -- Brier score, for instance.
    lower_is_better: bool = False
    discovery: DiscoveryComparison | None = None

    @model_validator(mode="after")
    def _check_metric(self) -> FloorVerdict:
        if not self.metric_name.strip():
            raise ValueError("a floor verdict must name the metric it compares")
        return self

    @property
    def improvement(self) -> float:
        """Signed improvement, always positive-is-better."""
        if self.lower_is_better:
            return self.floor_value - self.challenger_value
        return self.challenger_value - self.floor_value

    @property
    def cleared(self) -> bool:
        return self.improvement >= self.margin

    @property
    def summary(self) -> str:
        """One line for a report, phrased so it cannot overclaim.

        Deliberately says "did not clear" rather than "failed": a branch that
        adds discovery while matching the floor on score is useful, and language
        that calls it a failure encourages deleting it.
        """
        verdict = "cleared" if self.cleared else "did not clear"
        direction = "lower" if self.lower_is_better else "higher"
        detail = (
            f"{self.challenger_name} {verdict} the {FLOOR_GENERATOR} floor on "
            f"{self.metric_name} ({direction} is better): "
            f"{self.challenger_value:.6f} against {self.floor_value:.6f}, "
            f"margin {self.margin:.6f}"
        )
        if self.discovery is not None and self.discovery.adds_discovery:
            detail += (
                f"; it proposed {len(self.discovery.challenger_only)} candidates the floor did not"
            )
        return detail
