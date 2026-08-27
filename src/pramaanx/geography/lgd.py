"""Normalising rows from the Local Government Directory.

The LGD is the identity spine: it is the Indian government's own district
register, it carries numeric codes for states and districts, and it versions
them when units change. This module turns its rows into
:class:`~pramaanx.schemas.geography.DistrictRef` records and nothing else --
no inference, no fuzzy matching, no filling in of a state from a district name.

The rule that matters is the last one in :func:`normalise_lgd_rows`: a row
missing an explicit code is rejected rather than guessed. A guessed district
code produces a district that looks real, joins cleanly to everything, and is
wrong -- the most expensive kind of wrong this project can produce.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from pramaanx.schemas.geography import DistrictRef, district_id_for, state_id_for

#: Column names accepted for each field. The LGD's own exports and the mirrors
#: people actually download from disagree on capitalisation and spacing, so the
#: alias list is explicit -- but it is a list of *known* spellings, not a
#: heuristic. An unrecognised header is an error, not a near match.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "district_code": ("district_code", "districtcode", "district code", "dist_code"),
    "district_name": ("district_name", "districtname", "district name", "district_name_english"),
    "state_code": ("state_code", "statecode", "state code"),
    "state_name": ("state_name", "statename", "state name", "state_name_english"),
    "valid_from": ("valid_from", "effective_from", "date_of_creation"),
    "valid_until": ("valid_until", "effective_to", "date_of_abolition"),
    "population": ("population", "population_2011"),
    "area_sq_km": ("area_sq_km", "area", "geographical_area_sq_km"),
}


class LgdContractError(ValueError):
    """An LGD row did not carry the columns this project requires."""


def _normalise_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace("  ", " ")


def _pick(row: Mapping[str, Any], field: str) -> Any:
    lowered = {_normalise_key(key): value for key, value in row.items()}
    for alias in COLUMN_ALIASES[field]:
        if alias in lowered:
            return lowered[alias]
        if alias.replace(" ", "_") in lowered:
            return lowered[alias.replace(" ", "_")]
    return None


def _required(row: Mapping[str, Any], field: str) -> Any:
    value = _pick(row, field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise LgdContractError(
            f"LGD row is missing {field!r}; accepted spellings are "
            f"{list(COLUMN_ALIASES[field])}. This column is not inferred: an inferred "
            "district code is indistinguishable from a correct one downstream."
        )
    return value


def _as_datetime(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise LgdContractError(f"{field} must be timezone-aware")
        return value.astimezone(UTC)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise LgdContractError(f"{field} is not an ISO-8601 date: {text!r}") from error
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _optional_number(value: Any, *, cast: type) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return cast(value)


def normalise_lgd_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    boundary_version: str,
    default_valid_from: datetime,
) -> list[DistrictRef]:
    """Turn LGD rows into effective-dated district records.

    ``default_valid_from`` applies only to rows whose own creation date the
    export omits -- most LGD mirrors carry no creation date for districts that
    predate the register. It is a parameter rather than a constant so the
    caller has to state, and record, the vintage they are asserting.
    """
    if not boundary_version:
        raise LgdContractError("boundary_version is required")
    if default_valid_from.tzinfo is None:
        raise LgdContractError("default_valid_from must be timezone-aware")

    records: list[DistrictRef] = []
    for index, row in enumerate(rows):
        try:
            district_code = _required(row, "district_code")
            state_code = _required(row, "state_code")
            raw_until = _pick(row, "valid_until")
            raw_from = _pick(row, "valid_from")
            records.append(
                DistrictRef(
                    district_id=district_id_for(district_code),
                    district_name=str(_required(row, "district_name")).strip(),
                    state_id=state_id_for(state_code),
                    state_name=str(_required(row, "state_name")).strip(),
                    boundary_version=boundary_version,
                    valid_from=(
                        _as_datetime(raw_from, field="valid_from")
                        if raw_from not in (None, "")
                        else default_valid_from.astimezone(UTC)
                    ),
                    valid_until=(
                        _as_datetime(raw_until, field="valid_until")
                        if raw_until not in (None, "")
                        else None
                    ),
                    population=_optional_number(_pick(row, "population"), cast=int),
                    area_sq_km=_optional_number(_pick(row, "area_sq_km"), cast=float),
                )
            )
        except (LgdContractError, ValueError) as error:
            raise LgdContractError(f"LGD row {index}: {error}") from error
    return sorted(records, key=lambda item: (item.district_id, item.valid_from))
