"""Which districts existed, in which boundary version, on which day.

Districts change. A panel that treats the district list as a constant will
either lose a district that split or invent one that had not been notified yet,
and both look like a change in violence.

Two rules the plan makes explicit (S31.1, S31.2):

* the LGD code is the join key and it is a string. Names are display values;
  joining on a name joins two different districts that share one, and drops one
  that was transliterated differently;
* the roster is versioned by effective date. A run pins a boundary version in
  its context, and the roster it gets is the roster of that version -- never
  today's.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from pydantic import Field, field_validator, model_validator

from pramaanx.core.errors import ContractViolationError
from pramaanx.schemas.base import PramaanModel, VersionedModel


class District(PramaanModel):
    """One district in one boundary version."""

    model_config = PramaanModel.model_config | {"frozen": True}

    #: LGD code. String, always: leading zeros are meaningful and an integer
    #: cast silently merges "007" with "7".
    district_id: str
    state_id: str
    name: str = ""

    @field_validator("district_id", "state_id", mode="after")
    @classmethod
    def _codes_are_not_blank(cls, value: str) -> str:
        if not value:
            raise ContractViolationError("district and state codes must not be blank")
        return value


class BoundaryVersion(VersionedModel):
    """The complete district roster in force from a given date."""

    version: str
    effective_from: date
    districts: tuple[District, ...] = Field(default_factory=tuple)
    #: Where this roster came from: a notification, a census release, a
    #: shapefile. A version whose provenance is unrecorded cannot be defended
    #: as the roster that was in force.
    source_ref: str = ""

    @model_validator(mode="after")
    def _codes_are_unique(self) -> BoundaryVersion:
        codes = [district.district_id for district in self.districts]
        duplicates = sorted({code for code in codes if codes.count(code) > 1})
        if duplicates:
            raise ContractViolationError(
                "district codes repeat within one boundary version",
                version=self.version,
                duplicates=duplicates,
            )
        return self

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(district.district_id for district in self.districts))

    def state_of(self, district_id: str) -> str:
        for district in self.districts:
            if district.district_id == district_id:
                return district.state_id
        raise ContractViolationError(
            "district is not in this boundary version",
            version=self.version,
            district_id=district_id,
        )


class Roster(VersionedModel):
    """Every boundary version, and which one was in force on a day."""

    versions: tuple[BoundaryVersion, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _versions_are_distinct_and_ordered(self) -> Roster:
        names = [version.version for version in self.versions]
        if len(set(names)) != len(names):
            raise ContractViolationError("boundary version names repeat", versions=sorted(names))
        dates = [version.effective_from for version in self.versions]
        if dates != sorted(dates):
            raise ContractViolationError(
                "boundary versions must be given in effective-date order",
                versions=names,
            )
        return self

    def get(self, version: str) -> BoundaryVersion:
        for candidate in self.versions:
            if candidate.version == version:
                return candidate
        raise ContractViolationError("no such boundary version", version=version)

    def in_force_on(self, day: date) -> BoundaryVersion:
        """The version in force on ``day``.

        Chosen by effective date rather than by "the newest one we have",
        because a run replaying 2019 must not be handed a 2024 reorganisation.
        """
        candidates = [v for v in self.versions if v.effective_from <= day]
        if not candidates:
            raise ContractViolationError(
                "no boundary version was in force on this date; the roster does "
                "not reach back far enough for this origin",
                day=day.isoformat(),
                earliest=min((v.effective_from for v in self.versions), default=None),
            )
        return candidates[-1]

    def codes_on(self, day: date) -> tuple[str, ...]:
        return self.in_force_on(day).codes


def roster_from_districts(
    version: str, effective_from: date, districts: Iterable[tuple[str, str]]
) -> BoundaryVersion:
    """Build one version from ``(district_id, state_id)`` pairs."""
    return BoundaryVersion(
        version=version,
        effective_from=effective_from,
        districts=tuple(
            District(district_id=district, state_id=state) for district, state in districts
        ),
    )
