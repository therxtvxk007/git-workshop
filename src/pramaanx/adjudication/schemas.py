"""Typed adjudication contracts; probabilities are deliberately absent."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from pramaanx.schemas.base import Probability, UtcDatetime, VersionedModel


class ExpertKind(StrEnum):
    EVIDENCE = "evidence"
    TEMPORAL = "temporal"
    INDEPENDENCE = "independence"
    REGIONAL = "regional"
    SCEPTIC = "sceptic"


WORKER_EXPERTS = tuple(ExpertKind)


class EvidencePack(VersionedModel):
    candidate_id: str
    cutoff_at: UtcDatetime
    snapshot_hash: str
    observation_ids: list[str]
    supporting_spans: dict[str, list[str]] = Field(default_factory=dict)
    contradiction_ids: list[str] = Field(default_factory=list)
    independence_clusters: dict[str, str] = Field(default_factory=dict)
    resolved_district_id: str | None = None
    coverage_completeness: Probability

    @field_validator("observation_ids", "contradiction_ids")
    @classmethod
    def _unique_refs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence pack references must be unique")
        return sorted(value)

    @model_validator(mode="after")
    def _check_pack_refs(self) -> EvidencePack:
        known = set(self.observation_ids)
        if not set(self.supporting_spans) <= known:
            raise ValueError("supporting spans cite observations outside the pack")
        if not set(self.contradiction_ids) <= known:
            raise ValueError("contradictions cite observations outside the pack")
        if not set(self.independence_clusters) <= known:
            raise ValueError("independence clusters cite observations outside the pack")
        return self


class ExpertAssessment(VersionedModel):
    candidate_id: str
    expert: ExpertKind
    supported_event_class: str | None = None
    support_score: Probability
    contradiction_score: Probability
    temporal_relevance: Probability
    source_independence: Probability
    location_resolution: Probability
    coverage_completeness: Probability
    ordinary_crime_risk: Probability
    retrospective_risk: Probability
    leakage_suspected: bool
    unresolved_fields: list[str] = Field(default_factory=list)
    abstention_recommended: bool
    evidence_refs: list[str] = Field(default_factory=list)
    contradiction_refs: list[str] = Field(default_factory=list)

    @field_validator("unresolved_fields", "evidence_refs", "contradiction_refs")
    @classmethod
    def _canonical_lists(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("assessment lists must be unique")
        return sorted(value)


class SupervisorAssessment(VersionedModel):
    candidate_id: str
    worker_hashes: dict[ExpertKind, str]
    mean_support: Probability
    mean_contradiction: Probability
    disagreement: Probability
    abstention_recommended: bool
    abstention_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    contradiction_refs: list[str] = Field(default_factory=list)

    @field_validator("abstention_reasons", "evidence_refs", "contradiction_refs")
    @classmethod
    def _canonical_lists(cls, value: list[str]) -> list[str]:
        return sorted(set(value))
