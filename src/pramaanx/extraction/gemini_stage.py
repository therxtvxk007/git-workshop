"""Schema-constrained LLM verification over deterministic candidate spans."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from pramaanx.extraction.cascade import (
    FUTURE_CAPABLE_MODALITIES,
    BaseStage,
    MentionCandidate,
    PatternStage,
)
from pramaanx.hashing import stable_id
from pramaanx.llm.base import StructuredLLMEngine
from pramaanx.schemas.base import PramaanModel
from pramaanx.schemas.observation import Observation


class VerifiedMention(PramaanModel):
    observation_id: str
    span: str
    event_type: str
    subject: str | None = None
    object: str | None = None
    location_text: str | None = None
    event_time_start: datetime | None = None
    event_time_end: datetime | None = None
    modality: Literal["asserted", "planned", "possible", "denied", "unknown"] = "unknown"
    support: Literal["supported", "contradicted", "uncertain"]
    explicit_fields: set[str] = Field(default_factory=set)
    unresolved_fields: set[str] = Field(default_factory=set)

    @field_validator("observation_id", "span", "event_type")
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("verified mention identity, span, and event type cannot be blank")
        return value

    @model_validator(mode="after")
    def _disjoint_fields(self) -> VerifiedMention:
        overlap = self.explicit_fields & self.unresolved_fields
        if overlap:
            raise ValueError(f"fields cannot be explicit and unresolved: {sorted(overlap)}")
        return self


class VerificationBatch(PramaanModel):
    mentions: list[VerifiedMention] = Field(default_factory=list)


class GeminiVerificationStage(BaseStage):
    """Verify rule-generated spans using any structured LLM provider.

    The historical name is retained because Gemini is the default low-cost
    provider. The injected engine can point at Gemini, Claude, or OpenAI.
    """

    name = "llm-verification"
    VERSION = "0.1.0"
    PROMPT_VERSION = "district-event-verification@1"

    def __init__(
        self,
        engine: StructuredLLMEngine,
        *,
        candidate_stage: PatternStage | None = None,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.candidate_stage = candidate_stage or PatternStage()

    def propose(self, observation: Observation, text: str) -> Sequence[MentionCandidate]:
        seeds = list(self.candidate_stage.propose(observation, text))
        if not seeds:
            return []
        allowed_spans = sorted({candidate.span for candidate in seeds})
        prompt = self._prompt(observation, allowed_spans)
        batch = self.engine.generate(
            prompt=prompt,
            output_schema=VerificationBatch,
            request_id=stable_id("llmreq", observation.observation_id, self.PROMPT_VERSION),
            prompt_version=self.PROMPT_VERSION,
            evidence_ids=[observation.observation_id],
            cutoff_at=observation.first_observed_at,
            temperature=0.0,
        )
        candidates: list[MentionCandidate] = []
        for mention in batch.mentions:
            self._validate_grounding(mention, observation, text, allowed_spans)
            if mention.support == "contradicted":
                continue
            explicit = set(mention.explicit_fields)
            unresolved = set(mention.unresolved_fields)
            explicit -= unresolved
            resolved_fields = sum(
                value is not None
                for value in (
                    mention.subject,
                    mention.location_text,
                    mention.event_time_start,
                )
            )
            confidence = 0.45 + 0.08 * resolved_fields
            if mention.support == "uncertain":
                confidence *= 0.7
            candidates.append(
                MentionCandidate(
                    stage_name=self.name,
                    independence_group=self.candidate_stage.name,
                    span=mention.span,
                    event_type=mention.event_type,
                    subject=mention.subject,
                    object=mention.object,
                    location_text=mention.location_text,
                    event_time_start=mention.event_time_start,
                    event_time_end=mention.event_time_end,
                    modality=mention.modality,
                    confidence=confidence,
                    explicit_fields=explicit,
                )
            )
        return candidates

    @staticmethod
    def _prompt(observation: Observation, allowed_spans: list[str]) -> str:
        return (
            "Verify only the supplied candidate spans. Return schema-valid JSON. "
            "Do not provide a probability. Do not add evidence, locations, actors, or dates "
            "that the exact span does not support. Mark unresolved fields instead.\n"
            f"observation_id={observation.observation_id}\n"
            f"available_at={observation.first_observed_at.isoformat()}\n"
            f"candidate_spans={allowed_spans!r}"
        )

    @staticmethod
    def _validate_grounding(
        mention: VerifiedMention,
        observation: Observation,
        text: str,
        allowed_spans: list[str],
    ) -> None:
        if mention.observation_id != observation.observation_id:
            raise ValueError("LLM cited an unknown observation")
        if mention.span not in allowed_spans or mention.span not in text:
            raise ValueError("LLM cited a span outside the supplied evidence")
        span_folded = mention.span.casefold()
        for field_name, value in (
            ("subject", mention.subject),
            ("object", mention.object),
            ("location", mention.location_text),
        ):
            if value is not None and value.casefold() not in span_folded:
                raise ValueError(f"LLM supplied unsupported {field_name}")
        if (
            mention.event_time_start is not None
            and mention.event_time_start > observation.first_observed_at
            and mention.modality not in FUTURE_CAPABLE_MODALITIES
        ):
            raise ValueError("LLM introduced a post-cutoff event time for a non-future claim")
