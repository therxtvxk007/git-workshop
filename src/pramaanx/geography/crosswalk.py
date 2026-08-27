"""Mapping superseded districts onto the units that replaced them.

Two directions matter and they are not symmetric:

* *forward* -- an old district's history, projected onto the current units, so
  a model trained on today's universe can use pre-split activity;
* *backward* -- a current district traced to the units it came from, so a
  feature builder knows which historical rows to read.

Both return weighted mappings. A split apportions; a rename does not. The
weights are apportionment shares, and :meth:`DistrictCrosswalk.project` will
only apply them to a quantity the caller declares divisible -- counts are, and
"did anything happen" is not, because half an incident is not an incident.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from pramaanx.schemas.geography import CrosswalkEdge

_WEIGHT_TOLERANCE = 1e-6


class CrosswalkError(ValueError):
    """The crosswalk edges supplied cannot be applied consistently."""


class DistrictCrosswalk:
    """Weighted rename/split/merge edges between district vintages."""

    def __init__(self, edges: Iterable[CrosswalkEdge]) -> None:
        forward: dict[str, list[CrosswalkEdge]] = defaultdict(list)
        backward: dict[str, list[CrosswalkEdge]] = defaultdict(list)
        for edge in edges:
            forward[edge.source_district_id].append(edge)
            backward[edge.target_district_id].append(edge)
        for source, group in forward.items():
            _check_weights(source, group)
        self._forward = {
            key: sorted(value, key=_edge_key) for key, value in sorted(forward.items())
        }
        self._backward = {
            key: sorted(value, key=_edge_key) for key, value in sorted(backward.items())
        }

    @classmethod
    def empty(cls) -> DistrictCrosswalk:
        return cls([])

    def successors(self, district_id: str, moment: datetime) -> dict[str, float]:
        """Where ``district_id``'s territory sits at ``moment``.

        Applied transitively: a district split in 2016 and one of its halves
        split again in 2022 resolves, for a 2024 moment, to all three surviving
        units with the product of the weights.
        """
        return self._walk(district_id, moment, self._forward, forward=True)

    def predecessors(self, district_id: str, moment: datetime) -> dict[str, float]:
        """Which historical units make up ``district_id`` as it stands at ``moment``."""
        return self._walk(district_id, moment, self._backward, forward=False)

    def project(
        self,
        values: dict[str, float],
        *,
        moment: datetime,
        divisible: bool,
    ) -> dict[str, float]:
        """Move per-district quantities onto the units in effect at ``moment``.

        ``divisible=False`` refuses to split a value across successors and
        raises instead. That is deliberate: silently giving each half of a split
        district a 0.5 "an incident occurred" label would manufacture two
        half-events out of one real one, and every calibration curve downstream
        would inherit the fiction.
        """
        projected: dict[str, float] = defaultdict(float)
        for district_id, value in sorted(values.items()):
            shares = self.successors(district_id, moment)
            if not shares:
                projected[district_id] += value
                continue
            if not divisible and len(shares) > 1:
                raise CrosswalkError(
                    f"{district_id} splits into {sorted(shares)} by {moment.isoformat()}; "
                    "an indivisible quantity cannot be apportioned across a split"
                )
            for target, weight in shares.items():
                projected[target] += value * weight
        return dict(sorted(projected.items()))

    def _walk(
        self,
        district_id: str,
        moment: datetime,
        index: dict[str, list[CrosswalkEdge]],
        *,
        forward: bool,
    ) -> dict[str, float]:
        if moment.tzinfo is None:
            raise CrosswalkError("crosswalk queries need a timezone-aware moment")
        resolved: dict[str, float] = defaultdict(float)
        stack: list[tuple[str, float, tuple[str, ...]]] = [(district_id, 1.0, (district_id,))]
        while stack:
            current, weight, path = stack.pop()
            edges = [
                edge
                for edge in index.get(current, ())
                # Forward: only changes that have already taken effect. Backward:
                # the same test, so both directions see one consistent vintage.
                if edge.effective_from <= moment
            ]
            if not edges:
                resolved[current] += weight
                continue
            for edge in edges:
                nxt = edge.target_district_id if forward else edge.source_district_id
                if nxt in path:
                    raise CrosswalkError(f"crosswalk cycle through {' -> '.join((*path, nxt))}")
                share = edge.weight if forward else 1.0
                stack.append((nxt, weight * share, (*path, nxt)))
        return {key: value for key, value in sorted(resolved.items()) if value > 0.0}


def _edge_key(edge: CrosswalkEdge) -> tuple[str, str, datetime]:
    return (edge.source_district_id, edge.target_district_id, edge.effective_from)


def _check_weights(source: str, edges: list[CrosswalkEdge]) -> None:
    by_moment: dict[datetime, list[CrosswalkEdge]] = defaultdict(list)
    for edge in edges:
        by_moment[edge.effective_from].append(edge)
    for moment, group in by_moment.items():
        total = sum(edge.weight for edge in group)
        if abs(total - 1.0) > _WEIGHT_TOLERANCE:
            raise CrosswalkError(
                f"crosswalk weights out of {source} at {moment.isoformat()} sum to "
                f"{total:.9f}, not 1.0; territory would be created or lost"
            )
        relations = {edge.relation for edge in group}
        if "rename" in relations and len(group) > 1:
            raise CrosswalkError(
                f"{source} at {moment.isoformat()} has {len(group)} successors but is "
                "labelled a rename; label it a split"
            )
