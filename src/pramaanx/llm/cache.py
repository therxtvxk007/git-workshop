"""Deterministic in-process cache for validated structured responses."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredResponseCache:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, object]] = {}

    def get(self, request_hash: str, schema: type[T]) -> T | None:
        record = self._records.get(request_hash)
        return None if record is None else schema.model_validate(record)

    def put(self, request_hash: str, value: BaseModel) -> None:
        self._records[request_hash] = value.model_dump(mode="json")
