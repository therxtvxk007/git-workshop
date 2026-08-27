"""Hard call and input budgets for LLM-assisted stages."""

from __future__ import annotations

from pydantic import BaseModel, Field, PrivateAttr


class LLMBudget(BaseModel):
    max_calls: int = Field(default=1_000, ge=0)
    max_input_chars: int = Field(default=10_000_000, ge=0)
    _calls: int = PrivateAttr(default=0)
    _input_chars: int = PrivateAttr(default=0)

    def consume(self, *, input_chars: int) -> None:
        if self._calls + 1 > self.max_calls:
            raise RuntimeError("LLM call budget exhausted")
        if self._input_chars + input_chars > self.max_input_chars:
            raise RuntimeError("LLM input-character budget exhausted")
        self._calls += 1
        self._input_chars += input_chars

    @property
    def calls_used(self) -> int:
        return self._calls

    @property
    def input_chars_used(self) -> int:
        return self._input_chars
