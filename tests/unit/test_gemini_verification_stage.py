from __future__ import annotations

from typing import TypeVar

import pytest
from _phase2_builders import observation
from pydantic import BaseModel

from pramaanx.extraction import ExtractionCascade, GeminiVerificationStage, PatternStage
from pramaanx.llm import ProviderResponse, StructuredLLMEngine

T = TypeVar("T", bound=BaseModel)


class VerificationProvider:
    name = "fake-gemini"
    model = "gemini/test"

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def generate_structured(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        request_id: str,
        temperature: float,
    ) -> ProviderResponse[T]:
        del prompt, request_id, temperature
        return ProviderResponse(
            parsed=output_schema.model_validate(self.payload), model_version=self.model
        )


def payload(span: str, observation_id: str, **overrides: object) -> dict[str, object]:
    mention = {
        "observation_id": observation_id,
        "span": span,
        "event_type": "armed_clash",
        "subject": "Security forces",
        "object": "Maoist fighters",
        "location_text": "Bastar",
        "modality": "asserted",
        "support": "supported",
        "explicit_fields": ["event_type", "subject", "object", "location"],
        "unresolved_fields": ["event_time"],
    }
    mention.update(overrides)
    return {"mentions": [mention]}


def test_verification_stage_joins_cascade_without_fake_independence_lift() -> None:
    obs = observation(observed_days=100)
    text = "Security forces clashed with Maoist fighters in Bastar."
    engine = StructuredLLMEngine(VerificationProvider(payload(text, obs.observation_id)))
    llm_stage = GeminiVerificationStage(engine)
    candidates = llm_stage.propose(obs, text)
    assert candidates[0].independence_group == "pattern"

    pattern_only = ExtractionCascade([PatternStage()]).extract(obs, text)[0]
    combined = ExtractionCascade([PatternStage(), llm_stage]).extract(obs, text)[0]
    assert combined.extraction_probability <= max(
        pattern_only.extraction_probability, candidates[0].confidence
    )


def test_unknown_observation_and_unsupported_location_fail_closed() -> None:
    obs = observation(observed_days=100)
    text = "Security forces clashed with Maoist fighters in Bastar."
    unknown = GeminiVerificationStage(
        StructuredLLMEngine(VerificationProvider(payload(text, "obs-unknown")))
    )
    with pytest.raises(ValueError, match="unknown observation"):
        unknown.propose(obs, text)

    unsupported = GeminiVerificationStage(
        StructuredLLMEngine(
            VerificationProvider(payload(text, obs.observation_id, location_text="Delhi"))
        )
    )
    with pytest.raises(ValueError, match="unsupported location"):
        unsupported.propose(obs, text)


def test_probability_field_is_rejected_by_strict_schema() -> None:
    obs = observation(observed_days=100)
    text = "Security forces clashed with Maoist fighters in Bastar."
    stage = GeminiVerificationStage(
        StructuredLLMEngine(
            VerificationProvider(payload(text, obs.observation_id, probability=0.99))
        )
    )
    with pytest.raises(ValueError):
        stage.propose(obs, text)
