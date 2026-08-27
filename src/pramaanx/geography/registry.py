"""Versioned district registry, crosswalks and adjacency."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pramaanx.schemas.district import DistrictRef

@dataclass(frozen=True)
class DistrictCrosswalk:
    source_district_id: str
    target_district_id: str
    valid_from: datetime
    weight: float = 1.0

class DistrictRegistry:
    def __init__(self, districts: list[DistrictRef], crosswalks: list[DistrictCrosswalk] | None = None,
                 adjacency: dict[str, set[str]] | None = None) -> None:
        self._districts = {d.district_id: d for d in districts}
        if len(self._districts) != len(districts):
            raise ValueError("duplicate district_id")
        self._crosswalks = list(crosswalks or [])
        self._adjacency = {k: set(v) for k, v in (adjacency or {}).items()}
        for district, neighbours in self._adjacency.items():
            if district not in self._districts:
                raise ValueError(f"unknown district in adjacency: {district}")
            for neighbour in neighbours:
                if neighbour not in self._districts:
                    raise ValueError(f"unknown neighbour: {neighbour}")
                if district not in self._adjacency.get(neighbour, set()):
                    raise ValueError(f"adjacency must be symmetric: {district}, {neighbour}")

    def as_of(self, at: datetime) -> list[DistrictRef]:
        return sorted((d for d in self._districts.values() if d.valid_from <= at and
                       (d.valid_until is None or at < d.valid_until)), key=lambda d: d.district_id)

    def get(self, district_id: str) -> DistrictRef:
        return self._districts[district_id]

    def resolve_historical(self, district_id: str, at: datetime) -> list[tuple[DistrictRef, float]]:
        district = self._districts[district_id]
        if district.valid_from <= at and (district.valid_until is None or at < district.valid_until):
            return [(district, 1.0)]
        matches = [x for x in self._crosswalks if x.source_district_id == district_id and x.valid_from <= at]
        if not matches:
            return []
        total = sum(x.weight for x in matches)
        if total <= 0:
            raise ValueError("crosswalk weights must be positive")
        return [(self._districts[x.target_district_id], x.weight / total) for x in matches]

    def neighbours(self, district_id: str, hops: int = 1) -> set[str]:
        if hops < 1:
            return set()
        seen = {district_id}
        frontier = deque([(district_id, 0)])
        result: set[str] = set()
        while frontier:
            node, depth = frontier.popleft()
            if depth == hops:
                continue
            for neighbour in sorted(self._adjacency.get(node, set())):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                result.add(neighbour)
                frontier.append((neighbour, depth + 1))
        return result
