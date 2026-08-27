"""As-of district name resolution with explicit ambiguity."""

from __future__ import annotations

import unicodedata
from datetime import date
from enum import StrEnum

from pydantic import Field

from pramaanx.geography.registry import DistrictRegistry
from pramaanx.schemas.base import VersionedModel


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ResolutionResult(VersionedModel):
    query: str
    status: ResolutionStatus
    district_ids: list[str] = Field(default_factory=list)


def _normalise_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class DistrictNameResolver:
    def __init__(self, registry: DistrictRegistry) -> None:
        self._registry = registry

    def resolve(self, query: str, *, as_of: date) -> ResolutionResult:
        normalised = _normalise_name(query)
        matches = sorted(
            district.district_id
            for district in self._registry.as_of(as_of)
            if _normalise_name(district.district_name) == normalised
        )
        if not matches:
            status = ResolutionStatus.UNRESOLVED
        elif len(matches) == 1:
            status = ResolutionStatus.RESOLVED
        else:
            status = ResolutionStatus.AMBIGUOUS
        return ResolutionResult(query=query, status=status, district_ids=matches)
