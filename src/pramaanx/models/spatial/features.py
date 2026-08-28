"""As-of feature construction from historically resolvable incidents."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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


def _season_code(month: int) -> int:
    """Meteorological season, 0-3, on the Indian calendar."""
    if month in {12, 1, 2}:
        return 0  # winter
    if month in {3, 4, 5}:
        return 1  # pre-monsoon
    if month in {6, 7, 8, 9}:
        return 2  # monsoon
    return 3  # post-monsoon


def build_extended_spatial_features(
    *,
    registry: DistrictRegistry,
    incidents: Iterable[NormalizedIncident],
    cutoffs: Iterable[datetime],
    event_families: Iterable[str],
    history_windows_days: Iterable[int],
    adjacency: DistrictAdjacencyGraph | None = None,
    neighbour_hops: int = 1,
    horizon_days: int = 30,
    decay_half_life_days: float = 30.0,
    completion_status: Mapping[str, str] | None = None,
) -> list[SpatialFeatureRow]:
    """The WP5 feature set, built on top of the foundation's history counts.

    `build_spatial_features` is called unchanged and its output enriched, so the
    windowed counts the foundation already tests keep exactly the semantics
    those tests pin down. Everything added here obeys the same availability
    rule: an incident contributes only when ``occurred_at <= cutoff`` and
    ``first_resolvable_at <= cutoff``.

    Two absences are represented as absences rather than as zeros:

    * A district with no resolvable history gets ``district_history_observed =
      0`` and no ``days_since_last`` value at all. Imputing a large number
      there would tell every model that quiet districts are old districts.
    * Attempted/completed splits are emitted only when `completion_status`
      supplies them. The foundation's `NormalizedIncident` carries no
      completion field, so this package cannot invent one -- see
      docs/integration/wp05_spatial.md.
    """
    base_rows = build_spatial_features(
        registry=registry,
        incidents=incidents,
        cutoffs=cutoffs,
        event_families=event_families,
        history_windows_days=history_windows_days,
        adjacency=adjacency,
        neighbour_hops=neighbour_hops,
    )
    incident_list = tuple(incidents)
    windows = tuple(sorted(set(history_windows_days)))
    enriched: list[SpatialFeatureRow] = []

    # Previous-cutoff district rates, filled in as the cutoffs are walked in
    # order. The first cutoff has no predecessor and is left without the
    # feature rather than seeded with a guess.
    previous_rate: dict[tuple[str, str], float] = {}
    rows_by_cutoff: dict[datetime, list[SpatialFeatureRow]] = {}
    for row in base_rows:
        rows_by_cutoff.setdefault(row.cutoff_at, []).append(row)

    for cutoff in sorted(rows_by_cutoff):
        available = [
            incident
            for incident in incident_list
            if incident.occurred_at <= cutoff and incident.first_resolvable_at <= cutoff
        ]
        this_cutoff_rate: dict[tuple[str, str], float] = {}

        for row in sorted(rows_by_cutoff[cutoff], key=lambda item: item.district_id):
            district = registry.get(row.district_id, as_of=cutoff.date())
            family_incidents = [
                incident for incident in available if incident.event_family == row.event_family
            ]
            district_incidents = [
                incident for incident in family_incidents if incident.district_id == row.district_id
            ]
            state_ids = {
                candidate.district_id
                for candidate in registry.as_of(cutoff.date())
                if candidate.state_id == district.state_id
            }
            neighbour_ids = (
                set(
                    adjacency.neighbours(
                        row.district_id,
                        boundary_version=row.boundary_version,
                        hops=neighbour_hops,
                    )
                )
                if adjacency is not None
                else set()
            )
            weights = _neighbour_weights(adjacency, row.district_id, row.boundary_version)

            features = dict(row.features)
            features["calendar_month"] = float(cutoff.month)
            features["calendar_season"] = float(_season_code(cutoff.month))
            features["horizon_days"] = float(horizon_days)
            features["district_history_observed"] = float(bool(district_incidents))

            if district_incidents:
                latest = max(incident.occurred_at for incident in district_incidents)
                features["district_days_since_last_event"] = float(
                    (cutoff - latest).total_seconds() / 86400.0
                )
            # Absent when there is no history: see the docstring.

            features["district_decayed_count"] = float(
                sum(
                    0.5
                    ** (
                        ((cutoff - incident.occurred_at).total_seconds() / 86400.0)
                        / decay_half_life_days
                    )
                    for incident in district_incidents
                )
            )

            state_year = [
                incident
                for incident in family_incidents
                if incident.district_id in state_ids
                and (cutoff - incident.occurred_at) <= timedelta(days=365)
            ]
            features["state_event_rate_365d"] = float(len(state_year) / max(len(state_ids), 1))
            features["state_trend_90d_over_365d"] = _trend(
                short=features.get("state_count_90d", 0.0),
                long=features.get("state_count_365d", 0.0),
                short_days=90,
                long_days=365,
            )

            neighbour_year = [
                incident
                for incident in family_incidents
                if incident.district_id in neighbour_ids
                and (cutoff - incident.occurred_at) <= timedelta(days=365)
            ]
            # Every incident here matched a neighbour id, so its district is
            # resolved; narrowing it explicitly keeps that fact checkable.
            neighbour_year_ids = [
                incident.district_id
                for incident in neighbour_year
                if incident.district_id is not None
            ]
            features["neighbour_active_count_365d"] = float(len(set(neighbour_year_ids)))
            features["neighbour_weighted_count_365d"] = float(
                sum((weights.get(district, 0.0) for district in neighbour_year_ids), 0.0)
            )
            features["neighbour_trend_90d_over_365d"] = _trend(
                short=features.get("neighbour_count_90d", 0.0),
                long=features.get("neighbour_count_365d", 0.0),
                short_days=90,
                long_days=365,
            )

            if completion_status is not None:
                recent_year = [
                    incident
                    for incident in district_incidents
                    if (cutoff - incident.occurred_at) <= timedelta(days=365)
                ]
                statuses = [
                    completion_status.get(incident.incident_id, "") for incident in recent_year
                ]
                attempted = sum(1 for status in statuses if status == "attempted")
                completed = sum(1 for status in statuses if status == "completed")
                features["district_attempted_count_365d"] = float(attempted)
                features["district_completed_count_365d"] = float(completed)
                total = attempted + completed
                if total:
                    features["district_attempted_completed_ratio"] = float(attempted / total)

            key = (row.district_id, row.event_family)
            if key in previous_rate:
                features["district_previous_cutoff_rate"] = previous_rate[key]
            longest = max(windows) if windows else 365
            this_cutoff_rate[key] = float(
                features.get(f"district_count_{longest}d", 0.0) / max(longest, 1)
            )

            enriched.append(
                SpatialFeatureRow(
                    district_id=row.district_id,
                    cutoff_at=row.cutoff_at,
                    event_family=row.event_family,
                    boundary_version=row.boundary_version,
                    features=features,
                )
            )
        previous_rate.update(this_cutoff_rate)

    return enriched


def _trend(*, short: float, long: float, short_days: int, long_days: int) -> float:
    """Short-window rate over the annualised long-window rate.

    Returns 0.0 when the long window is empty. That is a measured zero, not a
    missing value: the long window was looked at and contained nothing.
    """
    if long <= 0.0:
        return 0.0
    return float((short / short_days) / (long / long_days))


def _neighbour_weights(
    adjacency: DistrictAdjacencyGraph | None, district_id: str, boundary_version: str
) -> dict[str, float]:
    if adjacency is None:
        return {}
    weights: dict[str, float] = {}
    for edge in adjacency.edges:
        if edge.boundary_version != boundary_version:
            continue
        if edge.left_district_id == district_id:
            weights[edge.right_district_id] = edge.weight
        elif edge.right_district_id == district_id:
            weights[edge.left_district_id] = edge.weight
    return weights
