"""LLM client.

One interface over vLLM, SGLang and any OpenAI-compatible endpoint, plus a
deterministic offline backend. The offline backend is not a mock in the testing
sense -- it is a real, if crude, rule-driven responder that produces
schema-valid output, so the whole cascade runs end to end on a machine with no
GPU and the stage-3 plumbing is exercised rather than skipped.

Three properties matter more than the provider choice:

  budget      stage 3 is the expensive stage, so calls are counted and capped.
              A run that would exceed the cap degrades to the offline responder
              rather than silently costing ten times the estimate.
  caching     keyed on (prompt, model, schema). Re-running an evaluation must
              not re-bill the same generations.
  validation  every response goes through the pydantic schema before it is
              returned. There is no path that returns unvalidated model output.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from ..util.cache import ContentCache
from ..util.hashing import content_hash
from ..util.logging import get_logger
from .schema import json_schema, parse_strict

log = get_logger("stage3.llm")


@dataclass
class LlmResponse:
    text: str
    parsed: BaseModel | None = None
    error: str = ""
    cached: bool = False
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider: str = ""

    @property
    def ok(self) -> bool:
        return self.parsed is not None


class LlmBackend(Protocol):
    name: str

    def generate(self, prompt: str, *, schema: type[BaseModel] | None,
                 temperature: float, max_tokens: int, n: int) -> list[str]: ...


class BudgetExceeded(RuntimeError):
    pass


# ------------------------------------------------------------ backends ---


@dataclass
class OpenAiCompatibleBackend:
    """vLLM, SGLang, and anything else speaking the OpenAI chat API.

    The only provider-specific part is how constrained decoding is requested:
    vLLM takes `guided_json` in `extra_body`, SGLang takes `response_format`
    with a json_schema. Both are sent; servers ignore the key they do not know.
    """

    base_url: str = "http://localhost:8000/v1"
    model: str = "Qwen/Qwen3.8-27B"
    api_key: str = "EMPTY"
    timeout_s: float = 60.0
    name: str = "openai-compatible"
    _client: Any = field(default=None, repr=False)

    def _http(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                base_url=self.base_url, timeout=self.timeout_s,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._client

    def generate(self, prompt: str, *, schema: type[BaseModel] | None,
                 temperature: float, max_tokens: int, n: int) -> list[str]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "You are an evidence analyst. Answer only with JSON "
                            "matching the requested schema. Never add commentary."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "n": n,
        }
        if schema is not None:
            js = json_schema(schema)
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": js, "strict": True},
            }
            body["extra_body"] = {"guided_json": js}
        r = self._http().post("/chat/completions", json=body)
        r.raise_for_status()
        payload = r.json()
        return [c["message"]["content"] for c in payload.get("choices", [])]

    def usage(self, payload: dict) -> tuple[int, int]:
        u = payload.get("usage", {})
        return int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))


@dataclass
class OfflineBackend:
    """Deterministic rule-driven responder.

    Emits schema-valid JSON derived from the prompt's own evidence block. It is
    weaker than a real model by design and never claims otherwise: its
    plausibility scores are a function of evidence count, not of reasoning. Its
    purpose is that stage 3 has a defined behaviour with no GPU, so the cascade,
    the budget accounting and the validation path are all exercised in CI.
    """

    name: str = "offline"
    seed: int = 20260824

    def generate(self, prompt: str, *, schema: type[BaseModel] | None,
                 temperature: float, max_tokens: int, n: int) -> list[str]:
        from .offline import respond

        return [respond(prompt, schema, i, self.seed) for i in range(max(n, 1))]


# -------------------------------------------------------------- client ---


@dataclass
class LlmClient:
    backend: LlmBackend
    cache: ContentCache | None = None
    max_calls: int = 0                 # 0 = unlimited
    fallback: LlmBackend | None = None
    calls_made: int = 0
    cache_hits: int = 0
    parse_failures: int = 0
    degraded: int = 0
    total_latency_ms: float = 0.0

    def complete(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 768,
        n: int = 1,
    ) -> list[LlmResponse]:
        key = content_hash(prompt, str(temperature), str(max_tokens), str(n),
                           schema.__name__ if schema else "-")
        model_id = f"{self.backend.name}:{getattr(self.backend, 'model', '-')}"

        if self.cache is not None:
            hit = self.cache.get("llm", key, model_id)
            if hit is not None:
                self.cache_hits += 1
                # Re-validate on the way out. The cache stores raw text, not the
                # parsed object: pickling a pydantic model would tie every cache
                # entry to the schema version that wrote it, and a schema change
                # would then return stale objects that no longer match the code
                # reading them.
                out: list[LlmResponse] = []
                for r in hit:
                    parsed, err = (parse_strict(schema, r["text"]) if schema else (None, ""))
                    out.append(LlmResponse(
                        text=r["text"], parsed=parsed,
                        error=err or r.get("error", ""), cached=True,
                        latency_ms=r.get("latency_ms", 0.0),
                        provider=r.get("provider", ""),
                    ))
                return out

        backend = self.backend
        if self.max_calls and self.calls_made >= self.max_calls:
            if self.fallback is None:
                raise BudgetExceeded(
                    f"stage-3 budget of {self.max_calls} calls exhausted and no "
                    f"fallback backend configured"
                )
            # Degrading is a recorded event, not a silent substitution: the run
            # summary reports how many items got the weaker responder.
            self.degraded += 1
            log.warning("llm budget exhausted, degrading to fallback",
                        extra={"limit": self.max_calls, "fallback": self.fallback.name})
            backend = self.fallback

        t0 = time.perf_counter()
        try:
            texts = backend.generate(prompt, schema=schema, temperature=temperature,
                                     max_tokens=max_tokens, n=n)
        except Exception as exc:
            log.warning("llm call failed", extra={"error": str(exc)[:200],
                                                  "backend": backend.name})
            if self.fallback is None or backend is self.fallback:
                return [LlmResponse(text="", error=str(exc)[:300], provider=backend.name)]
            self.degraded += 1
            texts = self.fallback.generate(prompt, schema=schema, temperature=temperature,
                                           max_tokens=max_tokens, n=n)
            backend = self.fallback
        latency = (time.perf_counter() - t0) * 1000
        self.total_latency_ms += latency
        if backend is self.backend:
            self.calls_made += 1

        out: list[LlmResponse] = []
        for text in texts:
            parsed, err = (parse_strict(schema, text) if schema else (None, ""))
            if schema is not None and parsed is None:
                self.parse_failures += 1
            out.append(LlmResponse(text=text, parsed=parsed, error=err,
                                   latency_ms=latency, provider=backend.name))

        if self.cache is not None and any(r.ok or schema is None for r in out):
            self.cache.put("llm", key, [
                {"text": r.text, "error": r.error, "latency_ms": r.latency_ms,
                 "provider": r.provider} for r in out
            ], model_id)
        return out

    def stats(self) -> dict[str, Any]:
        total = self.calls_made + self.cache_hits
        return {
            "calls": self.calls_made,
            "cache_hits": self.cache_hits,
            "cache_hit_rate": round(self.cache_hits / total, 4) if total else 0.0,
            "parse_failures": self.parse_failures,
            "degraded": self.degraded,
            "mean_latency_ms": round(self.total_latency_ms / max(self.calls_made, 1), 2),
            "budget": self.max_calls or None,
        }


def build_client(
    provider: str,
    *,
    base_url: str = "http://localhost:8000/v1",
    model: str = "Qwen/Qwen3.8-27B",
    max_calls: int = 0,
    cache_dir: str | None = ".cache/pramaan",
    timeout_s: float = 60.0,
) -> LlmClient:
    cache = ContentCache(cache_dir) if cache_dir else None
    offline = OfflineBackend()
    if provider in ("stub", "offline"):
        return LlmClient(backend=offline, cache=cache, max_calls=0)
    if provider in ("vllm", "sglang", "openai"):
        backend = OpenAiCompatibleBackend(base_url=base_url, model=model,
                                          timeout_s=timeout_s, name=provider)
        return LlmClient(backend=backend, cache=cache, max_calls=max_calls,
                         fallback=offline)
    raise ValueError(f"unknown LLM provider {provider!r}")
