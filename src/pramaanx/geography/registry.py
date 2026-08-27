"""The effective-dated district registry.

Every question this module answers is asked *as of* a moment. There is no
``districts()`` accessor and no notion of the current list, because the two
mistakes this layer exists to prevent are both mistakes of tense:

* scoring a 2014 event against the district that replaced its district in 2022;
* letting a 2025 split change what the 2024 panel thought the universe was.

``as_of`` is the whole interface. A registry loaded with records covering forty
years of boundary changes returns a different, internally consistent universe
for each date, and the same date always returns the same answer.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from itertools import pairwise

from pramaanx.schemas.geography import DistrictRef


class GeographyError(ValueError):
    """The district records supplied are not internally consistent."""


class DistrictRegistry:
    """Effective-dated lookup over a set of :class:`DistrictRef` records."""

    def __init__(self, records: Iterable[DistrictRef]) -> None:
        by_id: dict[str, list[DistrictRef]] = defaultdict(list)
        for record in records:
            by_id[record.district_id].append(record)
        for district_id, versions in by_id.items():
            versions.sort(key=lambda item: item.valid_from)
            _reject_overlaps(district_id, versions)
        self._by_id: dict[str, list[DistrictRef]] = dict(sorted(by_id.items()))

    @classmethod
    def empty(cls) -> DistrictRegistry:
        return cls([])

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, district_id: object) -> bool:
        return district_id in self._by_id

    # -- point-in-time queries -------------------------------------------
    def at(self, district_id: str, moment: datetime) -> DistrictRef | None:
        """The record for one district in effect at ``moment``, if any."""
        _require_aware(moment)
        for record in self._by_id.get(district_id, ()):
            if record.covers(moment):
                return record
        return None

    def require_at(self, district_id: str, moment: datetime) -> DistrictRef:
        record = self.at(district_id, moment)
        if record is None:
            raise GeographyError(
                f"{district_id} was not in effect at {moment.isoformat()}; "
                "resolve it through the crosswalk rather than assuming it existed"
            )
        return record

    def as_of(self, moment: datetime) -> list[DistrictRef]:
        """The whole district universe in effect at ``moment``, sorted by id."""
        _require_aware(moment)
        return sorted(
            (
                record
                for versions in self._by_id.values()
                for record in versions
                if record.covers(moment)
            ),
            key=lambda item: item.district_id,
        )

    def universe_ids(self, moment: datetime) -> list[str]:
        return [record.district_id for record in self.as_of(moment)]

    def states_as_of(self, moment: datetime) -> dict[str, list[str]]:
        """State id -> its districts, for the universe in effect at ``moment``.

        Each district appears under exactly one state; the registry rejects
        overlapping records precisely so this stays true.
        """
        grouped: dict[str, list[str]] = defaultdict(list)
        for record in self.as_of(moment):
            grouped[record.state_id].append(record.district_id)
        return {state: sorted(ids) for state, ids in sorted(grouped.items())}

    def boundary_version_at(self, moment: datetime) -> str:
        """The single boundary vintage the universe at ``moment`` belongs to."""
        versions = {record.boundary_version for record in self.as_of(moment)}
        if not versions:
            raise GeographyError(f"no districts are in effect at {moment.isoformat()}")
        if len(versions) > 1:
            raise GeographyError(
                f"the universe at {moment.isoformat()} mixes boundary versions "
                f"{sorted(versions)}; adjacency and crosswalks would be ambiguous"
            )
        return versions.pop()

    def history(self, district_id: str) -> Sequence[DistrictRef]:
        """Every record for one district, oldest first."""
        return tuple(self._by_id.get(district_id, ()))


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None:
        raise GeographyError("registry queries need a timezone-aware moment")


def _reject_overlaps(district_id: str, versions: list[DistrictRef]) -> None:
    for earlier, later in pairwise(versions):
        if earlier.valid_until is None:
            raise GeographyError(
                f"{district_id} has an open-ended record starting "
                f"{earlier.valid_from.isoformat()} followed by another starting "
                f"{later.valid_from.isoformat()}: close the earlier one"
            )
        if earlier.valid_until > later.valid_from:
            raise GeographyError(
                f"{district_id} has overlapping validity intervals "
                f"({earlier.valid_from.isoformat()}..{earlier.valid_until.isoformat()} and "
                f"{later.valid_from.isoformat()}..): one district would resolve twice"
            )
