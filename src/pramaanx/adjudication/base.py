"""Belief state: what is believed about one candidate, and on what evidence.

A generator proposes; it does not decide. The gap between "a rule fired" and
"this is likely" is where corroboration is weighed against contradiction, where
repetition is told apart from independent confirmation, and where the honest
answer is sometimes that the evidence does not settle it. That gap is this
package.

Three rules shape everything here.

*Reasoning may not silently move a number.* A belief state changes only through
a recorded :class:`BeliefUpdate` naming what moved it and by how much. Free text
is allowed to argue; it is not allowed to write. This is the single most
important property, because a reasoning step that can quietly overwrite a
structured field turns every downstream metric into a description of prose.

*Repetition is not corroboration.* Support is counted over independence
clusters, never over items. Ten outlets rewriting one wire story raise the
count by one, and the difference between those two ways of counting is most of
the distance between a calibrated system and a confident one.

*Insufficient is an answer.* :class:`Verdict.INSUFFICIENT` exists so that thin
evidence produces an abstention rather than a number produced by the prior with
extra steps.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.schemas.base import PramaanModel, Probability, UtcDatetime, VersionedModel
from pramaanx.schemas.evidence import EvidenceRef

#: Recorded on a belief nothing has adjudicated. Mirrors the calibration and
#: alert-policy labels: a default that says so is safer than a silent one.
UNADJUDICATED = "unadjudicated@none"


class Verdict(StrEnum):
    """What the evidence supports, once weighed."""

    #: Independent support, and contradiction accounted for.
    SUPPORTED = "supported"
    #: Contradicting evidence outweighs the support.
    CONTRADICTED = "contradicted"
    #: Both sides are represented and neither dominates. Not a middle score --
    #: a statement that the corpus itself disagrees.
    DISPUTED = "disputed"
    #: Too little independent evidence to say anything. An abstention.
    INSUFFICIENT = "insufficient"


class UpdateKind(StrEnum):
    """Why a belief moved. Every movement has exactly one of these."""

    PRIOR = "prior"
    INDEPENDENT_SUPPORT = "independent_support"
    CONTRADICTION = "contradiction"
    REPETITION_DISCOUNT = "repetition_discount"
    RECENCY = "recency"
    SOURCE_RELIABILITY = "source_reliability"
    ABSTENTION = "abstention"


class BeliefUpdate(PramaanModel):
    """One recorded movement of a belief, and its justification.

    ``delta`` is in log-odds, not probability. Probability deltas are not
    additive -- +0.1 means something different at 0.5 than at 0.9 -- so a log
    of probability steps cannot be replayed or audited. Log-odds add.
    """

    kind: UpdateKind
    delta_logit: float
    rationale: str
    #: The evidence this update rests on. Empty for a prior or an abstention.
    evidence_ids: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.delta_logit:+.4f} ({self.rationale})"


class BeliefState(VersionedModel):
    """What is believed about one candidate, and everything that moved it."""

    candidate_id: str
    adjudicator_version: str = UNADJUDICATED
    verdict: Verdict = Verdict.INSUFFICIENT
    probability: Probability = 0.5
    prior: Probability = 0.5
    #: Independence clusters supporting and contradicting, not item counts.
    independent_support: int = Field(default=0, ge=0)
    independent_contradiction: int = Field(default=0, ge=0)
    #: Items dropped as repetition of an already-counted cluster. Kept because
    #: "we saw this fifty times from one source" is itself a finding.
    repeated_items: int = Field(default=0, ge=0)
    #: Fields the evidence did not settle. Named, never guessed.
    unresolved_fields: tuple[str, ...] = ()
    updates: tuple[BeliefUpdate, ...] = ()
    #: Spread across reasoning trials. High disagreement means the answer is an
    #: artefact of the seed, whatever the mean says.
    trial_disagreement: float = Field(default=0.0, ge=0.0)
    decided_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _abstention_is_not_a_confident_number(self) -> BeliefState:
        if self.verdict is Verdict.INSUFFICIENT and self.probability != self.prior:
            raise ValueError(
                f"{self.candidate_id} abstained but moved its probability from "
                f"{self.prior} to {self.probability}. An abstention that still "
                "returns an updated number is a confident answer wearing an "
                "abstention's label."
            )
        return self

    @property
    def is_abstention(self) -> bool:
        return self.verdict is Verdict.INSUFFICIENT

    @property
    def audit_trail(self) -> list[str]:
        return [str(update) for update in self.updates]

    def replay_probability(self) -> float:
        """Recompute the probability from the prior and the recorded updates.

        The check that makes the audit trail worth having: if replaying every
        recorded update does not reproduce the stored probability, something
        moved the number without recording why.
        """
        from pramaanx.adjudication.math import logit, sigmoid

        value = logit(self.prior)
        for update in self.updates:
            value += update.delta_logit
        return sigmoid(value)


class AdjudicationReport(PramaanModel):
    """Provenance for one adjudication pass over a set of candidates."""

    adjudicator_version: str
    trials: int = Field(ge=1)
    candidates: int = Field(ge=0)
    abstentions: int = Field(ge=0)
    disputed: int = Field(ge=0)
    mean_disagreement: float = Field(default=0.0, ge=0.0)

    @property
    def abstention_rate(self) -> float:
        return self.abstentions / self.candidates if self.candidates else 0.0


def independence_counts(refs: Sequence[EvidenceRef]) -> tuple[int, int, int]:
    """``(independent_support, independent_contradiction, repeated_items)``.

    Counting is over ``cluster_key``, so a hundred reprints of one wire story
    contribute one. The third value is what that discarded, which is a finding
    rather than noise: a candidate whose support is fifty items in one cluster
    is materially different from one with fifty clusters, and only this number
    tells them apart after the fact.
    """
    support: set[str] = set()
    contra: set[str] = set()
    repeated = 0
    for ref in refs:
        if ref.stance == "supports":
            if ref.cluster_key in support:
                repeated += 1
            support.add(ref.cluster_key)
        elif ref.stance == "contradicts":
            if ref.cluster_key in contra:
                repeated += 1
            contra.add(ref.cluster_key)
    return len(support), len(contra), repeated
