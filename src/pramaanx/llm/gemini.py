"""Gemini REST provider with strict schema and evidence validation."""
from __future__ import annotations
import os
from typing import TypeVar
import httpx
from pydantic import BaseModel, ValidationError
T = TypeVar("T", bound=BaseModel)

class GeminiValidationError(ValueError):
    pass

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
        data = parsed.model_dump()
        for ref in data.get("evidence_refs", []):
            if ref not in allowed_evidence:
                raise GeminiValidationError(f"unknown evidence reference: {ref}")
        for quote in data.get("quoted_spans", []):
            if not any(quote in body for body in allowed_evidence.values()):
                raise GeminiValidationError("quoted span is not present in supplied evidence")
        return parsed
