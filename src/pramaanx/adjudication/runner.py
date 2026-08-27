"""Run blind worker experts through the structured LLM engine."""

from __future__ import annotations

from pramaanx.adjudication.schemas import (
    WORKER_EXPERTS,
    EvidencePack,
    ExpertAssessment,
    ExpertKind,
)
from pramaanx.hashing import stable_id
from pramaanx.llm import StructuredLLMEngine

EXPERT_INSTRUCTIONS: dict[ExpertKind, str] = {
    ExpertKind.EVIDENCE: "Assess direct support, contradictions, and whether claims are grounded.",
    ExpertKind.TEMPORAL: "Assess cutoff relevance, retrospective wording, and event-time consistency.",
    ExpertKind.INDEPENDENCE: "Assess syndication, copying, and the number of independent sources.",
    ExpertKind.REGIONAL: "Assess district resolution and regional actor/location plausibility.",
    ExpertKind.SCEPTIC: "Seek ordinary-crime confounds, missing evidence, and reasons to abstain.",
}


class ExpertRunner:
    PROMPT_VERSION = "blind-expert@1"

    def __init__(self, engine: StructuredLLMEngine) -> None:
        self.engine = engine

    def run(self, pack: EvidencePack) -> list[ExpertAssessment]:
        """Run each worker from the pack alone; no worker output enters another prompt."""
        assessments: list[ExpertAssessment] = []
        for expert in WORKER_EXPERTS:
            assessment = self.engine.generate(
                prompt=self._prompt(pack, expert),
                output_schema=ExpertAssessment,
                request_id=stable_id("expert", pack.snapshot_hash, pack.candidate_id, expert.value),
                prompt_version=self.PROMPT_VERSION,
                evidence_ids=pack.observation_ids,
                cutoff_at=pack.cutoff_at,
                temperature=0.0,
            )
            self._validate_assessment(pack, expert, assessment)
            assessments.append(assessment)
        return assessments

    @staticmethod
    def _prompt(pack: EvidencePack, expert: ExpertKind) -> str:
        return (
            f"expert={expert.value}\n"
            f"instruction={EXPERT_INSTRUCTIONS[expert]}\n"
            "Return only the ExpertAssessment schema. Do not estimate event probability. "
            "Cite only observation IDs in the evidence pack.\n"
            f"evidence_pack={pack.model_dump_json()}"
        )

    @staticmethod
    def _validate_assessment(
        pack: EvidencePack, expert: ExpertKind, assessment: ExpertAssessment
    ) -> None:
        if assessment.candidate_id != pack.candidate_id:
            raise ValueError("expert assessed a different candidate")
        if assessment.expert is not expert:
            raise ValueError("expert response has the wrong expert identity")
        known = set(pack.observation_ids)
        if not set(assessment.evidence_refs) <= known:
            raise ValueError("expert cited evidence outside the frozen pack")
        if not set(assessment.contradiction_refs) <= known:
            raise ValueError("expert cited contradictions outside the frozen pack")
