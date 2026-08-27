"""Gemini, Claude, and OpenAI through one schema-constrained adapter."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel

from pramaanx.llm.base import ProviderResponse

T = TypeVar("T", bound=BaseModel)


class LiteLLMStructuredProvider:
    """Provider portability without placing credentials in configuration.

    LiteLLM reads the provider's standard environment variable. Use a model
    string such as ``gemini/<exact-model-id>``, ``anthropic/<exact-model-id>``,
    or ``openai/<exact-model-id>``. The exact string is recorded on every call.
    """

    def __init__(self, model: str) -> None:
        if not model.strip() or "/" not in model:
            raise ValueError("LiteLLM model must include a provider prefix")
        self.model = model
        self.name = model.split("/", 1)[0]

    def generate_structured(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        request_id: str,
        temperature: float,
    ) -> ProviderResponse[T]:
        try:
            import litellm
        except ImportError as error:  # pragma: no cover - optional live dependency
            raise RuntimeError("live LLM calls require the 'llm' project extra") from error

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": output_schema.__name__,
                "strict": True,
                "schema": output_schema.model_json_schema(),
            },
        }
        response: Any = litellm.completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format=response_format,
            temperature=temperature,
            metadata={"request_id": request_id},
        )
        content = response.choices[0].message.content
        payload = json.loads(content) if isinstance(content, str) else content
        usage = getattr(response, "usage", None)
        return ProviderResponse(
            parsed=output_schema.model_validate(payload),
            model_version=str(getattr(response, "model", self.model)),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )
