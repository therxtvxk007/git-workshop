"""Deterministic, boundary-versioned district adjacency."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from pydantic import Field, field_validator, model_validator

from pramaanx.schemas.base import VersionedModel


class AdjacencyEdge(VersionedModel):
    left_district_id: str
    right_district_id: str
    boundary_version: str
    weight: float = Field(default=1.0, gt=0.0)

    @field_validator("left_district_id", "right_district_id", "boundary_version")
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("adjacency identifiers and version cannot be blank")
        return value

    @model_validator(mode="after")
    def _canonicalise_pair(self) -> AdjacencyEdge:
        if self.left_district_id == self.right_district_id:
            raise ValueError("district cannot be adjacent to itself")
        if self.left_district_id > self.right_district_id:
            left, right = self.right_district_id, self.left_district_id
            # Assignment validation would recursively invoke this model
            # validator. Canonicalization is part of initial validation, so set
            # the already-validated strings directly.
            object.__setattr__(self, "left_district_id", left)
            object.__setattr__(self, "right_district_id", right)
        return self


class DistrictAdjacencyGraph:
    def __init__(self, edges: Iterable[AdjacencyEdge]) -> None:
        self._edges = tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.boundary_version,
                    edge.left_district_id,
                    edge.right_district_id,
                ),
            )
        )
        keys = [
            (edge.boundary_version, edge.left_district_id, edge.right_district_id)
            for edge in self._edges
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate adjacency edge")

    @property
    def edges(self) -> tuple[AdjacencyEdge, ...]:
        return self._edges

    def neighbours(
        self, district_id: str, *, boundary_version: str, hops: int = 1
    ) -> tuple[str, ...]:
        if hops < 0:
            raise ValueError("hops cannot be negative")
        graph: dict[str, set[str]] = {}
        for edge in self._edges:
            if edge.boundary_version != boundary_version:
                continue
            graph.setdefault(edge.left_district_id, set()).add(edge.right_district_id)
            graph.setdefault(edge.right_district_id, set()).add(edge.left_district_id)

        discovered = {district_id}
        result: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(district_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth == hops:
                continue
            for neighbour in sorted(graph.get(current, set())):
                if neighbour in discovered:
                    continue
                discovered.add(neighbour)
                result.add(neighbour)
                queue.append((neighbour, depth + 1))
        return tuple(sorted(result))
