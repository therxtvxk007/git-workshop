import json
import httpx
import pytest
from pydantic import BaseModel
from pramaanx.llm import GeminiProvider, GeminiValidationError

class Item(BaseModel):
    evidence_refs: list[str]
    quoted_spans: list[str]

class Batch(BaseModel):
    items: list[Item]

class FakeClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
    def post(self, *args: object, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", "https://example.invalid")
        body = json.dumps(self.payload)
        return httpx.Response(200, request=request, json={
            "candidates": [{"content": {"parts": [{"text": body}]}}]
        })

def test_nested_evidence_and_quotes_are_validated() -> None:
    provider = GeminiProvider(api_key="test", client=FakeClient({
        "items": [{"evidence_refs": ["obs-1"], "quoted_spans": ["verbatim"]}]
    }))
    result = provider.generate_structured("prompt", Batch, {"obs-1": "a verbatim span"})
    assert result.items[0].evidence_refs == ["obs-1"]

def test_unknown_nested_evidence_is_rejected() -> None:
    provider = GeminiProvider(api_key="test", client=FakeClient({
        "items": [{"evidence_refs": ["invented"], "quoted_spans": ["verbatim"]}]
    }))
    with pytest.raises(GeminiValidationError, match="unknown evidence"):
        provider.generate_structured("prompt", Batch, {"obs-1": "a verbatim span"})
