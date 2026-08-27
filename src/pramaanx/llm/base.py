"""Typed structured-output engine with complete call provenance."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from time import monotonic
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field, field_validator

from pramaanx.hashing import hash_object
from pramaanx.llm.budget import LLMBudget
from pramaanx.llm.cache import StructuredResponseCache
from pramaanx.schemas.base import UtcDatetime, VersionedModel

T = TypeVar("T", bound=BaseModel)


class ProviderResponse[T: BaseModel](BaseModel):
    parsed: T
    model_version: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0)


@runtime_checkable
class StructuredLLMProvider(Protocol):
    name: str
    model: str

    def generate_structured(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        request_id: str,
        temperature: float,
    ) -> ProviderResponse[T]: ...


class LLMCallRecord(VersionedModel):
    request_id: str
    provider: str
    model: str
    model_version: str
    prompt_version: str
    output_schema: str
    temperature: float = Field(ge=0.0)
    request_hash: str
    response_hash: str
    evidence_ids: list[str]
    cutoff_at: UtcDatetime
    called_at: UtcDatetime
    latency_ms: float = Field(ge=0.0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    retry_count: int = Field(ge=0)
    cache_hit: bool = False

    @field_validator("evidence_ids")
    @classmethod
    def _canonical_evidence(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence IDs must be unique")
        return sorted(value)


class StructuredLLMEngine:
    """Validate, budget, cache, and record every structured provider call."""

    def __init__(
        self,
        provider: StructuredLLMProvider,
        *,
        budget: LLMBudget | None = None,
        cache: StructuredResponseCache | None = None,
    ) -> None:
        self.provider = provider
        self.budget = budget or LLMBudget()
        self.cache = cache or StructuredResponseCache()
        self.calls: list[LLMCallRecord] = []

    def generate(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        request_id: str,
        prompt_version: str,
        evidence_ids: Sequence[str],
        cutoff_at: datetime,
        temperature: float = 0.0,
    ) -> T:
        request_payload = {
            "provider": self.provider.name,
            "model": self.provider.model,
            "prompt": prompt,
            "prompt_version": prompt_version,
            "schema": output_schema.model_json_schema(),
            "temperature": temperature,
            "evidence_ids": sorted(evidence_ids),
            "cutoff_at": cutoff_at,
        }
        request_hash = hash_object(request_payload)
        cached = self.cache.get(request_hash, output_schema)
        started = monotonic()
        if cached is not None:
            parsed = cached
            provider_response = ProviderResponse(
                parsed=parsed,
                model_version=self.provider.model,
            )
            cache_hit = True
        else:
            self.budget.consume(input_chars=len(prompt))
            provider_response = self.provider.generate_structured(
                prompt=prompt,
                output_schema=output_schema,
                request_id=request_id,
                temperature=temperature,
            )
            # Validate again even when the SDK claims schema conformance.
            parsed = output_schema.model_validate(provider_response.parsed)
            self.cache.put(request_hash, parsed)
            cache_hit = False
        latency_ms = (monotonic() - started) * 1_000.0
        self.calls.append(
            LLMCallRecord(
                request_id=request_id,
                provider=self.provider.name,
                model=self.provider.model,
                model_version=provider_response.model_version,
                prompt_version=prompt_version,
                output_schema=output_schema.__name__,
                temperature=temperature,
                request_hash=request_hash,
                response_hash=hash_object(parsed.model_dump(mode="json")),
                evidence_ids=list(evidence_ids),
                cutoff_at=cutoff_at,
                called_at=datetime.now(UTC),
                latency_ms=latency_ms,
                input_tokens=provider_response.input_tokens,
                output_tokens=provider_response.output_tokens,
                retry_count=provider_response.retry_count,
                cache_hit=cache_hit,
            )
        )
        return parsed
