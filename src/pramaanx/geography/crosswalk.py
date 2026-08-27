"""Versioned district rename, split, and merge crosswalks."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from pydantic import Field, field_validator, model_validator

from pramaanx.schemas.base import VersionedModel


class CrosswalkEdge(VersionedModel):
    from_district_id: str
    to_district_id: str
    effective_on: date
    allocation_weight: float = Field(gt=0.0, le=1.0)
    source_hash: str

    @field_validator("from_district_id", "to_district_id", "source_hash")
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("crosswalk identifiers and source hash cannot be blank")
        return value

    @model_validator(mode="after")
    def _reject_self_edge(self) -> CrosswalkEdge:
        if self.from_district_id == self.to_district_id:
            raise ValueError("crosswalk self-edges are not meaningful")
        return self


class DistrictCrosswalk:
    """Translate district mass through all changes visible by an as-of date."""

    def __init__(self, edges: Iterable[CrosswalkEdge]) -> None:
        self._edges = tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.effective_on,
                    edge.from_district_id,
                    edge.to_district_id,
                ),
            )
        )
        self._validate_allocations()

    @property
    def edges(self) -> tuple[CrosswalkEdge, ...]:
        return self._edges

    def _validate_allocations(self) -> None:
        totals: dict[tuple[str, date], float] = {}
        for edge in self._edges:
            key = (edge.from_district_id, edge.effective_on)
            totals[key] = totals.get(key, 0.0) + edge.allocation_weight
        for key, total in totals.items():
            if abs(total - 1.0) > 1e-9:
                raise ValueError(f"crosswalk allocations for {key} sum to {total}, not 1.0")

    def translate(self, district_id: str, *, as_of: date) -> dict[str, float]:
        """Translate one historical identity through changes known by ``as_of``."""
        distribution = {district_id: 1.0}
        effective_dates = sorted(
            {edge.effective_on for edge in self._edges if edge.effective_on <= as_of}
        )
        for effective_on in effective_dates:
            replacements: dict[str, list[CrosswalkEdge]] = {}
            for edge in self._edges:
                if edge.effective_on == effective_on:
                    replacements.setdefault(edge.from_district_id, []).append(edge)
            next_distribution: dict[str, float] = {}
            for current_id, mass in distribution.items():
                outgoing = replacements.get(current_id)
                if not outgoing:
                    next_distribution[current_id] = next_distribution.get(current_id, 0.0) + mass
                    continue
                for edge in outgoing:
                    next_distribution[edge.to_district_id] = (
                        next_distribution.get(edge.to_district_id, 0.0)
                        + mass * edge.allocation_weight
                    )
            distribution = next_distribution
        return dict(sorted(distribution.items()))
