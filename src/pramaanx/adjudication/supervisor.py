"""Deterministic supervisor over independently produced assessments."""
from statistics import mean, pstdev
from pramaanx.adjudication.schemas import ExpertAssessment, SupervisorAssessment

EXPERT_ROLES = ("evidence_extractor", "temporal_analyst", "source_independence_analyst",
                "regional_analyst", "adversarial_sceptic", "supervisor")

def supervise(assessments: list[ExpertAssessment]) -> SupervisorAssessment:
    if len(assessments) < 5:
        raise ValueError("five independent expert assessments are required")
    ids = {item.candidate_id for item in assessments}
    if len(ids) != 1:
        raise ValueError("assessments refer to different candidates")
    supports = [x.support_strength for x in assessments]
    contradictions = [x.contradiction_strength for x in assessments]
    disagreement = min(1.0, pstdev(supports + contradictions))
    support, contradiction = mean(supports), mean(contradictions)
    semantic = max(0.0, min(1.0, support * (1.0 - contradiction)))
    unresolved = sorted({field for item in assessments for field in item.unresolved_fields})
    abstain = any(x.abstain for x in assessments) or disagreement >= 0.35
    return SupervisorAssessment(candidate_id=ids.pop(), support_strength=support,
        contradiction_strength=contradiction, disagreement=disagreement,
        semantic_score=semantic, abstain=abstain, unresolved_fields=unresolved)
