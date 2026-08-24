"""Structured output contracts.

Pydantic sits exactly here and nowhere hotter. An LLM asked for JSON will
eventually return prose, a trailing comma, or a confidently wrong field type,
and every one of those becomes a corrupted graph edge if it is not caught at the
boundary.

The schemas double as the constrained-decoding grammar: `json_schema()` feeds
vLLM's `guided_json` and SGLang's `response_format`, so malformed output is
prevented at generation rather than rejected afterwards.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

EVENT_TYPE = str


class ExtractedEvent(BaseModel):
    """One event tuple as the model is asked to emit it."""

    model_config = {"extra": "forbid"}

    subject: str = Field(min_length=1, max_length=200)
    relation: str = Field(min_length=1, max_length=80)
    object: str = Field(min_length=1, max_length=200)
    event_type: EVENT_TYPE = Field(min_length=1, max_length=60)
    event_time: datetime | None = None
    location: str = Field(default="unknown", max_length=120)
    extractor_confidence: float = Field(ge=0.0, le=1.0)
    supporting_span: str = Field(min_length=1, max_length=600)

    @field_validator("supporting_span")
    @classmethod
    def span_must_be_quotable(cls, v: str) -> str:
        """The span is shown to an analyst as the justification. An empty or
        whitespace-only span means the model asserted something it could not
        point at, which is precisely the output we must not store."""
        if not v.strip():
            raise ValueError("supporting_span must contain non-whitespace text")
        return v.strip()


class Hypothesis(BaseModel):
    """One candidate future, from the SCATTER-style sampler."""

    model_config = {"extra": "forbid"}

    location: str = Field(min_length=1, max_length=120)
    event_type: EVENT_TYPE = Field(min_length=1, max_length=60)
    horizon_days: int = Field(ge=1, le=365)
    plausibility: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=800)
    supporting_doc_ids: list[str] = Field(default_factory=list, max_length=32)


class HypothesisSet(BaseModel):
    model_config = {"extra": "forbid"}
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=32)


class Verdict(BaseModel):
    """Adjudication of an ambiguous extraction, or of contradictory evidence."""

    model_config = {"extra": "forbid"}

    supported: Literal["supports", "contradicts", "insufficient"]
    confidence: float = Field(ge=0.0, le=1.0)
    chosen_event_type: EVENT_TYPE | None = None
    reasoning: str = Field(min_length=1, max_length=1200)
    contradicting_doc_ids: list[str] = Field(default_factory=list, max_length=32)


class ExtractionBatch(BaseModel):
    model_config = {"extra": "forbid"}
    events: list[ExtractedEvent] = Field(default_factory=list, max_length=64)


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Schema for constrained decoding.

    `additionalProperties: false` is what actually stops the model inventing
    fields, and pydantic only emits it when the model forbids extras -- hence
    `extra: forbid` on every schema above.
    """
    return model.model_json_schema()


def parse_strict(model: type[BaseModel], payload: str | dict) -> tuple[BaseModel | None, str]:
    """Parse, returning (instance, error). Never raises.

    Stage 3 processes a batch; one malformed response must degrade that item to
    'no LLM opinion available' rather than abort the batch. The error string is
    logged and counted, because a rising parse-failure rate is the earliest
    signal that a served model has been changed underneath you.
    """
    try:
        if isinstance(payload, str):
            return model.model_validate_json(payload), ""
        return model.model_validate(payload), ""
    except ValidationError as exc:
        return None, "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
