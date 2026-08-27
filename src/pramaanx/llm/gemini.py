"""Gemini REST provider with strict schema and evidence validation."""
from __future__ import annotations
import os
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar
import httpx
from pydantic import BaseModel, ValidationError
T = TypeVar("T", bound=BaseModel)

class GeminiValidationError(ValueError):
    pass

def _walk(value: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.append((str(key), item))
            found.extend(_walk(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            found.extend(_walk(item))
    return found

class GeminiProvider:
    name = "gemini"
    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None,
                 client: httpx.Client | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("PRAMAANX_GEMINI_API_KEY")
        self.client = client or httpx.Client(timeout=60.0)
        if not self.api_key:
            raise ValueError("PRAMAANX_GEMINI_API_KEY is required")
    @property
    def version(self) -> str:
        return f"gemini:{self.model}"
    def generate_structured(self, prompt: str, output_schema: type[T], allowed_evidence: dict[str, str]) -> T:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        response = self.client.post(url, params={"key": self.api_key}, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json",
                "responseSchema": output_schema.model_json_schema(), "temperature": 0}})
        response.raise_for_status()
        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            parsed = output_schema.model_validate_json(text)
        except (KeyError, IndexError, ValidationError) as exc:
            raise GeminiValidationError("Gemini response failed strict schema validation") from exc
        for key, value in _walk(parsed.model_dump()):
            if key == "evidence_refs":
                for ref in value:
                    if ref not in allowed_evidence:
                        raise GeminiValidationError(f"unknown evidence reference: {ref}")
            elif key == "quoted_spans":
                for quote in value:
                    if not any(quote in body for body in allowed_evidence.values()):
                        raise GeminiValidationError("quoted span is not present in supplied evidence")
        return parsed
