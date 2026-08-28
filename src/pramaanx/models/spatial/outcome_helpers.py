"""Small constructors shared by the spatial test suites and demos.

Kept in the package rather than duplicated across three test modules so that a
change to `NormalizedIncident` breaks one place instead of several.
"""

from __future__ import annotations

from datetime import datetime

from pramaanx.outcomes.models import LocationStatus, NormalizedIncident

__all__ = ["incident_at"]


def incident_at(
    incident_id: str,
    occurred_at: datetime,
    first_resolvable_at: datetime,
    *,
    district_id: str = "IND-D-1",
    event_family: str = "insurgency",
    correction_version: str = "original",
) -> NormalizedIncident:
    """One resolved incident with explicit occurrence and availability times."""
    return NormalizedIncident(
        incident_id=incident_id,
        source="synthetic",
        source_version="v1",
        event_family=event_family,
        occurred_at=occurred_at,
        first_resolvable_at=first_resolvable_at,
        district_id=district_id,
        location_status=LocationStatus.RESOLVED,
        correction_version=correction_version,
        source_record_id=incident_id,
    )
