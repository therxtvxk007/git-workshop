"""Explicit normalization for ACLED/UCDP-style incident rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from pydantic import field_validator

from pramaanx.hashing import stable_id
from pramaanx.outcomes.models import LocationStatus, NormalizedIncident
from pramaanx.schemas.base import VersionedModel


class IncidentColumnMap(VersionedModel):
    """Recorded mapping for one pinned source version.

    ``first_resolvable_at`` is mandatory. A current ACLED/UCDP download cannot
    truthfully reconstruct when each historical event first became available;
    callers must use a vintage snapshot or ingestion ledger carrying that time.
    """

    source_record_id: str
    event_family: str
    occurred_at: str
    first_resolvable_at: str
    district_id: str | None = None
    correction_version: str | None = None

    @field_validator("source_record_id", "event_family", "occurred_at", "first_resolvable_at")
    @classmethod
    def _require_column(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("column names cannot be blank")
        return value


def _moment(value: object, *, field: str, row_index: int) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"row {row_index} field {field!r} must be an ISO datetime")
    if parsed.tzinfo is None:
        raise ValueError(f"row {row_index} field {field!r} is timezone-naive")
    return parsed


def normalize_incident_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    source: str,
    source_version: str,
    columns: IncidentColumnMap,
) -> list[NormalizedIncident]:
    """Normalize pinned source rows while rejecting guessed availability."""
    required = {
        columns.source_record_id,
        columns.event_family,
        columns.occurred_at,
        columns.first_resolvable_at,
    }
    if columns.district_id:
        required.add(columns.district_id)

    incidents: list[NormalizedIncident] = []
    for index, row in enumerate(rows):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"incident row {index} is missing columns: {sorted(missing)}")
        record_id = str(row[columns.source_record_id])
        district_value = row.get(columns.district_id) if columns.district_id else None
        district_id = str(district_value).strip() if district_value is not None else None
        if district_id == "":
            district_id = None
        correction = (
            str(row.get(columns.correction_version, "original"))
            if columns.correction_version
            else "original"
        )
        incidents.append(
            NormalizedIncident(
                incident_id=stable_id("inc", source, source_version, record_id, correction),
                source=source,
                source_version=source_version,
                event_family=str(row[columns.event_family]),
                occurred_at=_moment(
                    row[columns.occurred_at], field=columns.occurred_at, row_index=index
                ),
                first_resolvable_at=_moment(
                    row[columns.first_resolvable_at],
                    field=columns.first_resolvable_at,
                    row_index=index,
                ),
                district_id=district_id,
                location_status=(
                    LocationStatus.RESOLVED if district_id else LocationStatus.UNRESOLVED
                ),
                correction_version=correction,
                source_record_id=record_id,
            )
        )
    return incidents
