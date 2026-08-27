"""Gemini verifier that plugs into the independent extraction cascade."""
from __future__ import annotations
from collections.abc import Sequence
from pydantic import BaseModel, Field
from pramaanx.extraction.cascade import BaseStage, MentionCandidate
from pramaanx.llm.gemini import GeminiProvider
from pramaanx.schemas.observation import Observation

class GeminiMention(BaseModel):
    span: str
    event_type: str
    subject: str | None = None
    object: str | None = None
    location_text: str | None = None
    modality: str = "unknown"
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str]
    quoted_spans: list[str]

class GeminiMentionBatch(BaseModel):
    mentions: list[GeminiMention]
    evidence_refs: list[str] = Field(default_factory=list)
    quoted_spans: list[str] = Field(default_factory=list)

class GeminiVerificationStage(BaseStage):
    name = "gemini_verifier"
    VERSION = "0.1.0"
    def __init__(self, provider: GeminiProvider) -> None:
        super().__init__()
        self.provider = provider
    def propose(self, observation: Observation, text: str) -> Sequence[MentionCandidate]:
        prompt = ("Extract only terrorism, insurgency or left-wing-extremism event claims. "
                  "Return strict JSON. Every quoted span must occur verbatim in the supplied text.\n"
                  f"EVIDENCE_ID={observation.observation_id}\nTEXT={text}")
        result = self.provider.generate_structured(prompt, GeminiMentionBatch,
                                                   {observation.observation_id: text})
        return [MentionCandidate(stage_name=self.name, span=item.span, event_type=item.event_type,
            subject=item.subject, object=item.object, location_text=item.location_text,
            modality=item.modality, confidence=item.confidence,
            explicit_fields={"event_type"} | ({"subject"} if item.subject else set()) |
            ({"location"} if item.location_text else set())) for item in result.mentions]
