"""Deterministic supervisor that preserves worker disagreement."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from pramaanx.adjudication.schemas import (
    WORKER_EXPERTS,
    EvidencePack,
    ExpertAssessment,
    SupervisorAssessment,
)


class DeterministicSupervisor:
    version = "deterministic-supervisor@1"

    def __init__(self, *, disagreement_threshold: float = 0.25) -> None:
        if not 0.0 <= disagreement_threshold <= 1.0:
            raise ValueError("disagreement_threshold must be between zero and one")
        self.disagreement_threshold = disagreement_threshold

    def aggregate(
        self, pack: EvidencePack, assessments: Sequence[ExpertAssessment]
    ) -> SupervisorAssessment:
        if {assessment.expert for assessment in assessments} != set(WORKER_EXPERTS):
            raise ValueError("supervisor requires exactly one assessment from every worker")
        if any(assessment.candidate_id != pack.candidate_id for assessment in assessments):
            raise ValueError("supervisor cannot combine different candidates")

        supports = np.asarray([assessment.support_score for assessment in assessments])
        contradictions = np.asarray([assessment.contradiction_score for assessment in assessments])
        # Standard deviation of bounded scores is at most 0.5; scale to [0, 1].
        disagreement = min(float(max(supports.std(), contradictions.std()) * 2.0), 1.0)
        reasons: list[str] = []
        if disagreement >= self.disagreement_threshold:
            reasons.append("high_inter_expert_disagreement")
        if any(assessment.leakage_suspected for assessment in assessments):
            reasons.append("leakage_suspected")
        if any(assessment.abstention_recommended for assessment in assessments):
            reasons.append("worker_recommended_abstention")
        if pack.coverage_completeness < 0.5:
            reasons.append("inadequate_coverage")

        evidence_refs = sorted(
            {
                ref
                for assessment in assessments
                for ref in assessment.evidence_refs
                if ref in pack.observation_ids
            }
        )
        contradiction_refs = sorted(
            {
                ref
                for assessment in assessments
                for ref in assessment.contradiction_refs
                if ref in pack.contradiction_ids
            }
        )
        return SupervisorAssessment(
            candidate_id=pack.candidate_id,
            worker_hashes={
                assessment.expert: assessment.content_hash() for assessment in assessments
            },
            mean_support=float(supports.mean()),
            mean_contradiction=float(contradictions.mean()),
            disagreement=disagreement,
            abstention_recommended=bool(reasons),
            abstention_reasons=reasons,
            evidence_refs=evidence_refs,
            contradiction_refs=contradiction_refs,
        )
