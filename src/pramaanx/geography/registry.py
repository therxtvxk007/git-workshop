"""Effective-dated district registry with LGD as the identity spine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from itertools import pairwise

from pydantic import field_validator, model_validator

from pramaanx.schemas.base import VersionedModel
from pramaanx.schemas.geography import DistrictRef


def district_id_from_lgd(code: str | int) -> str:
    """Return the stable internal ID for one official LGD district code."""
    normalised = str(code).strip()
    if not normalised or not normalised.isdigit():
        raise ValueError(f"LGD district code must be numeric, got {code!r}")
    return f"IND-D-{normalised}"


class DistrictRegistryEntry(VersionedModel):
    """One district identity during one effective boundary interval."""

    district: DistrictRef
    lgd_district_code: str
    valid_from: date
    valid_to: date | None = None
    source_hash: str

    @field_validator("lgd_district_code")
    @classmethod
    def _normalise_lgd_code(cls, value: str) -> str:
        district_id_from_lgd(value)
        return value.strip()

    @field_validator("source_hash")
    @classmethod
    def _require_source_hash(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_hash cannot be blank")
        return value

    @model_validator(mode="after")
    def _check_identity_and_interval(self) -> DistrictRegistryEntry:
        expected_id = district_id_from_lgd(self.lgd_district_code)
        if self.district.district_id != expected_id:
            raise ValueError(
                f"district_id {self.district.district_id!r} does not match LGD code; "
                f"expected {expected_id!r}"
            )
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot precede valid_from")
        return self

    def active_on(self, as_of: date) -> bool:
        return self.valid_from <= as_of and (self.valid_to is None or as_of <= self.valid_to)


class LgdColumnMap(VersionedModel):
    """Explicit column contract for an LGD export.

    LGD exports have changed headings over time. Callers must record the exact
    mapping used instead of relying on fuzzy header guesses.
    """

    district_code: str
    district_name: str
    state_code: str
    state_name: str


def entries_from_lgd_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    columns: LgdColumnMap,
    boundary_version: str,
    valid_from: date,
    source_hash: str,
    valid_to: date | None = None,
) -> list[DistrictRegistryEntry]:
    """Normalize an explicitly mapped LGD export into versioned entries."""
    required = {
        columns.district_code,
        columns.district_name,
        columns.state_code,
        columns.state_name,
    }
    entries: list[DistrictRegistryEntry] = []
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"LGD row {index} is missing columns: {sorted(missing)}")
        code = str(row[columns.district_code]).strip()
        state_code = str(row[columns.state_code]).strip()
        entry = DistrictRegistryEntry(
            district=DistrictRef(
                district_id=district_id_from_lgd(code),
                district_name=str(row[columns.district_name]),
                state_id=f"IND-S-{state_code}",
                state_name=str(row[columns.state_name]),
                boundary_version=boundary_version,
            ),
            lgd_district_code=code,
            valid_from=valid_from,
            valid_to=valid_to,
            source_hash=source_hash,
        )
        entries.append(entry)
    return entries


class DistrictRegistry:
    """Validated effective-dated lookup over immutable registry entries."""

    def __init__(self, entries: Iterable[DistrictRegistryEntry]) -> None:
        self._entries = tuple(
            sorted(entries, key=lambda item: (item.district.district_id, item.valid_from))
        )
        if not self._entries:
            raise ValueError("district registry cannot be empty")
        self._validate_non_overlapping()

    @property
    def entries(self) -> tuple[DistrictRegistryEntry, ...]:
        return self._entries

    def _validate_non_overlapping(self) -> None:
        by_id: dict[str, list[DistrictRegistryEntry]] = {}
        for entry in self._entries:
            by_id.setdefault(entry.district.district_id, []).append(entry)
        for district_id, versions in by_id.items():
            for previous, current in pairwise(versions):
                if previous.valid_to is None or current.valid_from <= previous.valid_to:
                    raise ValueError(f"overlapping registry intervals for {district_id}")

    def as_of(self, as_of: date) -> tuple[DistrictRef, ...]:
        """Return exactly the district universe that existed on ``as_of``."""
        active = [entry.district for entry in self._entries if entry.active_on(as_of)]
        ids = [district.district_id for district in active]
        if len(ids) != len(set(ids)):
            raise AssertionError("registry validation failed to enforce one active version per ID")
        return tuple(sorted(active, key=lambda district: district.district_id))

    def get(self, district_id: str, *, as_of: date) -> DistrictRef:
        matches = [
            entry.district
            for entry in self._entries
            if entry.district.district_id == district_id and entry.active_on(as_of)
        ]
        if not matches:
            raise KeyError(f"district {district_id!r} does not exist at {as_of.isoformat()}")
        if len(matches) > 1:
            raise AssertionError("multiple active district versions survived validation")
        return matches[0]
