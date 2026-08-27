"""As-of feature construction from historically resolvable incidents."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from pramaanx.geography import DistrictAdjacencyGraph, DistrictRegistry
from pramaanx.models.spatial.dataset import SpatialFeatureRow
from pramaanx.outcomes.models import NormalizedIncident


def build_spatial_features(
    *,
    registry: DistrictRegistry,
    incidents: Iterable[NormalizedIncident],
    cutoffs: Iterable[datetime],
    event_families: Iterable[str],
    history_windows_days: Iterable[int],
    adjacency: DistrictAdjacencyGraph | None = None,
    neighbour_hops: int = 1,
) -> list[SpatialFeatureRow]:
    """Build deterministic features using only information available at cutoff."""
    windows = tuple(sorted(set(history_windows_days)))
    if not windows or any(window <= 0 for window in windows):
        raise ValueError("history windows must be positive")
    if neighbour_hops < 0:
        raise ValueError("neighbour_hops cannot be negative")
    incident_list = tuple(incidents)
    rows: list[SpatialFeatureRow] = []

    for cutoff in sorted(set(cutoffs)):
        districts = registry.as_of(cutoff.date())
        by_id = {district.district_id: district for district in districts}
        historically_available = [
            incident
            for incident in incident_list
            if incident.occurred_at <= cutoff and incident.first_resolvable_at <= cutoff
        ]
        for family in sorted(set(event_families)):
            family_incidents = [
                incident for incident in historically_available if incident.event_family == family
            ]
            for district in districts:
                features: dict[str, float] = {}
                neighbour_ids = (
                    set(
                        adjacency.neighbours(
                            district.district_id,
                            boundary_version=district.boundary_version,
                            hops=neighbour_hops,
                        )
                    )
                    if adjacency is not None
                    else set()
                )
                state_ids = {
                    candidate.district_id
                    for candidate in by_id.values()
                    if candidate.state_id == district.state_id
                }
                for window in windows:
                    start = cutoff - timedelta(days=window)
                    recent = [
                        incident
                        for incident in family_incidents
                        if start < incident.occurred_at <= cutoff
                    ]
                    features[f"district_count_{window}d"] = float(
                        sum(incident.district_id == district.district_id for incident in recent)
                    )
                    features[f"state_count_{window}d"] = float(
                        sum(incident.district_id in state_ids for incident in recent)
                    )
                    features[f"neighbour_count_{window}d"] = float(
                        sum(incident.district_id in neighbour_ids for incident in recent)
                    )
                features["district_missing_location_count"] = float(
                    sum(incident.district_id is None for incident in family_incidents)
                )
                rows.append(
                    SpatialFeatureRow(
                        district_id=district.district_id,
                        cutoff_at=cutoff,
                        event_family=family,
                        boundary_version=district.boundary_version,
                        features=features,
                    )
                )
    return rows
