"""Cutoff-safe district outcome panel construction."""
from __future__ import annotations
from datetime import datetime, timedelta
from pydantic import Field
from pramaanx.schemas.base import UtcDatetime, VersionedModel
from pramaanx.schemas.district import DistrictRef

class DistrictIncident(VersionedModel):
    incident_id: str
    district_id: str
    event_family: str
    occurred_at: UtcDatetime
    first_resolvable_at: UtcDatetime

class DistrictPanelRow(VersionedModel):
    district_id: str
    cutoff_at: UtcDatetime
    horizon_end: UtcDatetime
    event_family: str
    incident_occurred: int = Field(ge=0, le=1)
    incident_count: int = Field(ge=0)
    first_incident_at: UtcDatetime | None = None

def build_district_panel(districts: list[DistrictRef], incidents: list[DistrictIncident],
                         cutoffs: list[datetime], event_families: list[str],
                         horizon_days: int = 30) -> list[DistrictPanelRow]:
    rows: list[DistrictPanelRow] = []
    for cutoff in sorted(cutoffs):
        end = cutoff + timedelta(days=horizon_days)
        for district in sorted(districts, key=lambda d: d.district_id):
            for family in sorted(event_families):
                hits = sorted((x for x in incidents if x.district_id == district.district_id
                               and x.event_family == family and cutoff < x.occurred_at <= end),
                              key=lambda x: x.occurred_at)
                rows.append(DistrictPanelRow(district_id=district.district_id, cutoff_at=cutoff,
                    horizon_end=end, event_family=family, incident_occurred=int(bool(hits)),
                    incident_count=len(hits), first_incident_at=hits[0].occurred_at if hits else None))
    return rows
