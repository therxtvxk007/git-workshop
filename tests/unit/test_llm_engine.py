from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeVar

import pytest
from pydantic import BaseModel

from pramaanx.llm import LLMBudget, ProviderResponse, StructuredLLMEngine

T = TypeVar("T", bound=BaseModel)
CUTOFF = datetime(2026, 1, 1, tzinfo=UTC)


class Answer(BaseModel):
    value: int


class FakeProvider:
    name = "fake"
    model = "fake/model-v1"

    def __init__(self) -> None:
        self.calls = 0

    def generate_structured(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        request_id: str,
        temperature: float,
    ) -> ProviderResponse[T]:
        del prompt, request_id, temperature
        self.calls += 1
        return ProviderResponse(
            parsed=output_schema.model_validate({"value": 7}),
            model_version="fake/model-v1-pinned",
            input_tokens=3,
            output_tokens=1,
        )


def test_engine_validates_caches_and_records_provenance() -> None:
    provider = FakeProvider()
    engine = StructuredLLMEngine(provider)
    arguments = {
        "prompt": "return seven",
        "output_schema": Answer,
        "request_id": "req-1",
        "prompt_version": "p@1",
        "evidence_ids": ["obs-1"],
        "cutoff_at": CUTOFF,
    }
    assert engine.generate(**arguments).value == 7  # type: ignore[arg-type]
    assert engine.generate(**arguments).value == 7  # type: ignore[arg-type]
    assert provider.calls == 1
    assert engine.calls[0].cache_hit is False
    assert engine.calls[1].cache_hit is True
    assert engine.calls[0].model_version == "fake/model-v1-pinned"
    assert engine.calls[0].request_hash == engine.calls[1].request_hash


def test_budget_fails_closed() -> None:
    engine = StructuredLLMEngine(FakeProvider(), budget=LLMBudget(max_calls=0))
    with pytest.raises(RuntimeError, match="budget"):
        engine.generate(
            prompt="x",
            output_schema=Answer,
            request_id="req",
            prompt_version="p@1",
            evidence_ids=[],
            cutoff_at=CUTOFF,
        )
