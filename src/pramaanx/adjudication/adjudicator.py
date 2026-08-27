"""The adjudication loop: candidates and evidence in, belief states out.

Deterministic by construction. Every trial is seeded, every update is recorded
with the amount it moved the belief and why, and the resulting probability is
reproducible by replaying those updates from the prior. Nothing here calls a
language model; the loop is the part that has to be auditable, and a structure
that only works when a model is available cannot be tested.

An LLM adjudicator plugs in as another :class:`Adjudicator` when one exists,
and is held to the same contract: it may propose updates, it may not write a
field. That asymmetry is the point. Reasoning text is allowed to argue and not
to decide, because a reasoning step that can quietly overwrite a structured
field turns every downstream metric into a description of prose.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from pramaanx.adjudication.base import (
    AdjudicationReport,
    BeliefState,
    BeliefUpdate,
    UpdateKind,
    Verdict,
    independence_counts,
)
from pramaanx.adjudication.math import logit, logit_mean, logit_spread, sigmoid
from pramaanx.generators.base import CandidateProposal
from pramaanx.logging import get_logger
from pramaanx.schemas.evidence import EvidenceRef

log = get_logger(__name__)

#: Log-odds contributed by one independent supporting cluster. Deliberately
#: modest: this is a corroboration bonus, not the estimate itself, and a large
#: value would let three retellings of a rumour outvote the base rate.
SUPPORT_WEIGHT = 0.55
#: Contradiction weighs more than support, because a report that an event did
#: not happen is usually written by someone who checked, while a report that it
#: did is often written by someone who heard.
CONTRADICTION_WEIGHT = 0.8
#: Below this many independent supporting clusters, the loop abstains rather
#: than returning a number the evidence cannot carry.
MIN_INDEPENDENT_SUPPORT = 2


@runtime_checkable
class Adjudicator(Protocol):
    """Structural contract, so an LLM adjudicator needs no inheritance."""

    name: str

    @property
    def version(self) -> str: ...

    def adjudicate(
        self,
        proposal: CandidateProposal,
        evidence: Sequence[EvidenceRef],
        *,
        as_of: datetime,
    ) -> BeliefState: ...


class EvidenceWeightAdjudicator:
    """Weighs independent corroboration against contradiction.

    The non-LLM control arm. Any reasoning adjudicator has to beat *this* to
    justify its cost and its opacity, and having it in the repository from the
    start is what stops "the model said so" becoming the baseline by default.
    """

    name = "evidence_weight"
    VERSION = "0.1.0"

    def __init__(
        self,
        *,
        trials: int = 3,
        support_weight: float = SUPPORT_WEIGHT,
        contradiction_weight: float = CONTRADICTION_WEIGHT,
        min_independent_support: int = MIN_INDEPENDENT_SUPPORT,
    ) -> None:
        if trials < 1:
            raise ValueError("trials must be at least 1")
        self.trials = trials
        self.support_weight = support_weight
        self.contradiction_weight = contradiction_weight
        self.min_independent_support = min_independent_support

    @property
    def version(self) -> str:
        return (
            f"{self.name}@{self.VERSION}"
            f"/t{self.trials}/s{self.support_weight}/c{self.contradiction_weight}"
        )

    def _seed(self, candidate_id: str, trial: int) -> float:
        """A deterministic per-trial perturbation in [-1, 1].

        Trials exist to expose sensitivity, so they must differ; they must also
        be reproducible, so the difference cannot come from a random source.
        Hashing the candidate id with the trial index gives both.
        """
        digest = hashlib.sha256(f"{candidate_id}:{trial}".encode()).digest()
        return (int.from_bytes(digest[:8], "big") / (2**64 - 1)) * 2.0 - 1.0

    def adjudicate(
        self,
        proposal: CandidateProposal,
        evidence: Sequence[EvidenceRef],
        *,
        as_of: datetime,
    ) -> BeliefState:
        candidate_id = proposal.candidate_key
        prior = proposal.generator_score
        support, contra, repeated = independence_counts(evidence)

        updates: list[BeliefUpdate] = [
            BeliefUpdate(
                kind=UpdateKind.PRIOR,
                delta_logit=0.0,
                rationale=f"generator {proposal.generator_name} proposed {prior:.4f}",
            )
        ]

        if repeated:
            updates.append(
                BeliefUpdate(
                    kind=UpdateKind.REPETITION_DISCOUNT,
                    delta_logit=0.0,
                    rationale=(
                        f"{repeated} item(s) discarded as repetition within an already "
                        "counted independence cluster; they contribute nothing"
                    ),
                )
            )

        # Abstain before weighing. A belief assembled from one source and then
        # labelled insufficient has already done the arithmetic it is claiming
        # not to trust.
        if support < self.min_independent_support and contra == 0:
            updates.append(
                BeliefUpdate(
                    kind=UpdateKind.ABSTENTION,
                    delta_logit=0.0,
                    rationale=(
                        f"{support} independent supporting cluster(s), below the "
                        f"minimum of {self.min_independent_support}; the evidence does "
                        "not settle this and the prior is returned unchanged"
                    ),
                )
            )
            return BeliefState(
                candidate_id=candidate_id,
                adjudicator_version=self.version,
                verdict=Verdict.INSUFFICIENT,
                probability=prior,
                prior=prior,
                independent_support=support,
                independent_contradiction=contra,
                repeated_items=repeated,
                unresolved_fields=self._unresolved(proposal),
                updates=tuple(updates),
                decided_at=as_of,
            )

        jitters = [self._seed(candidate_id, trial) * 0.05 for trial in range(self.trials)]
        trial_probabilities = [
            sigmoid(
                logit(prior)
                + support * self.support_weight * (1.0 + jitter)
                - contra * self.contradiction_weight * (1.0 + jitter)
            )
            for jitter in jitters
        ]

        probability = logit_mean(trial_probabilities)
        disagreement = logit_spread(trial_probabilities)

        # The recorded deltas must be what *actually* moved the belief, not the
        # nominal weights. Aggregation is a mean in logit space and each trial
        # is linear in its jitter, so the ensemble's effect is the nominal
        # weight scaled by the mean jitter. Recording the unscaled weight would
        # make the audit trail replay to a different number than the one
        # stored, which is precisely the failure this trail exists to expose.
        ensemble = 1.0 + (sum(jitters) / len(jitters))

        if support:
            updates.append(
                BeliefUpdate(
                    kind=UpdateKind.INDEPENDENT_SUPPORT,
                    delta_logit=support * self.support_weight * ensemble,
                    rationale=f"{support} independent supporting cluster(s)",
                    evidence_ids=tuple(
                        sorted({ref.cluster_key for ref in evidence if ref.stance == "supports"})
                    ),
                )
            )
        if contra:
            updates.append(
                BeliefUpdate(
                    kind=UpdateKind.CONTRADICTION,
                    delta_logit=-contra * self.contradiction_weight * ensemble,
                    rationale=f"{contra} independent contradicting cluster(s)",
                    evidence_ids=tuple(
                        sorted({ref.cluster_key for ref in evidence if ref.stance == "contradicts"})
                    ),
                )
            )

        if support and contra:
            verdict = Verdict.DISPUTED
        elif contra > support:
            verdict = Verdict.CONTRADICTED
        else:
            verdict = Verdict.SUPPORTED

        return BeliefState(
            candidate_id=candidate_id,
            adjudicator_version=self.version,
            verdict=verdict,
            probability=probability,
            prior=prior,
            independent_support=support,
            independent_contradiction=contra,
            repeated_items=repeated,
            unresolved_fields=self._unresolved(proposal),
            updates=tuple(updates),
            trial_disagreement=disagreement,
            decided_at=as_of,
        )

    @staticmethod
    def _unresolved(proposal: CandidateProposal) -> tuple[str, ...]:
        """Fields the candidate never pinned down. Named, never guessed."""
        hypothesis = proposal.hypothesis
        missing = []
        if not hypothesis.actor_ids:
            missing.append("actor_ids")
        if not hypothesis.location_cells:
            missing.append("location_cells")
        if not hypothesis.time_bucket_probabilities:
            missing.append("time_bucket_probabilities")
        return tuple(missing)


def adjudicate_all(
    adjudicator: Adjudicator,
    proposals: Sequence[CandidateProposal],
    *,
    as_of: datetime,
    evidence_for: Callable[[CandidateProposal], Sequence[EvidenceRef]] | None = None,
) -> tuple[list[BeliefState], AdjudicationReport]:
    """Adjudicate every proposal, in a stable order.

    ``evidence_for`` may be a callable taking a proposal and returning evidence;
    by default a proposal's own attached evidence is used, which is what the
    generators already populate through retrieval.
    """
    beliefs: list[BeliefState] = []
    for proposal in sorted(proposals, key=lambda item: item.candidate_key):
        refs = evidence_for(proposal) if evidence_for is not None else proposal.hypothesis.evidence
        beliefs.append(adjudicator.adjudicate(proposal, refs, as_of=as_of))

    abstentions = sum(1 for belief in beliefs if belief.is_abstention)
    disputed = sum(1 for belief in beliefs if belief.verdict is Verdict.DISPUTED)
    spread = [belief.trial_disagreement for belief in beliefs]
    report = AdjudicationReport(
        adjudicator_version=adjudicator.version,
        trials=getattr(adjudicator, "trials", 1),
        candidates=len(beliefs),
        abstentions=abstentions,
        disputed=disputed,
        mean_disagreement=sum(spread) / len(spread) if spread else 0.0,
    )
    log.info(
        "adjudication.complete",
        candidates=report.candidates,
        abstentions=report.abstentions,
        disputed=report.disputed,
    )
    return beliefs, report
