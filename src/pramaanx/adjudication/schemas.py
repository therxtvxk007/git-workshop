"""Typed outputs for six independent expert roles."""
from pydantic import Field
from pramaanx.schemas.base import PramaanModel

class ExpertAssessment(PramaanModel):
    role: str
    candidate_id: str
    support_strength: float = Field(ge=0.0, le=1.0)
    contradiction_strength: float = Field(ge=0.0, le=1.0)
    temporal_relevance: float = Field(ge=0.0, le=1.0)
    source_independence: float = Field(ge=0.0, le=1.0)
    coverage_completeness: float = Field(ge=0.0, le=1.0)
    unresolved_fields: list[str] = Field(default_factory=list)
    abstain: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    quoted_spans: list[str] = Field(default_factory=list)

class SupervisorAssessment(PramaanModel):
    candidate_id: str
    support_strength: float = Field(ge=0.0, le=1.0)
    contradiction_strength: float = Field(ge=0.0, le=1.0)
    disagreement: float = Field(ge=0.0, le=1.0)
    semantic_score: float = Field(ge=0.0, le=1.0)
    abstain: bool
    unresolved_fields: list[str] = Field(default_factory=list)
