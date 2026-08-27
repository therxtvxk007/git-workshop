"""Leakage-safe construction of the dense district-cutoff outcome panel."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from pramaanx.geography.registry import DistrictRegistry
from pramaanx.isolation import guard_outcome_access
from pramaanx.outcomes.models import DistrictOutcomeRow, LabelStatus, NormalizedIncident


def build_district_outcome_panel(
    *,
    registry: DistrictRegistry,
    incidents: Iterable[NormalizedIncident],
    cutoffs: Iterable[datetime],
    event_families: Iterable[str],
    horizon_days: int,
    observation_end: datetime,
    reporting_delay_days: int = 0,
) -> list[DistrictOutcomeRow]:
    """Build all positive and negative rows; callable only outside forecasting."""
    guard_outcome_access("build_district_outcome_panel")
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if reporting_delay_days < 0:
        raise ValueError("reporting_delay_days cannot be negative")
    incident_list = tuple(incidents)
    families = tuple(sorted(set(event_families)))
    if not families:
        raise ValueError("at least one event family is required")

    rows: list[DistrictOutcomeRow] = []
    for cutoff in sorted(set(cutoffs)):
        horizon_end = cutoff + timedelta(days=horizon_days)
        districts = registry.as_of(cutoff.date())
        for family in families:
            window_incidents = [
                incident
                for incident in incident_list
                if incident.event_family == family and cutoff < incident.occurred_at <= horizon_end
            ]
            right_censored = observation_end < horizon_end + timedelta(days=reporting_delay_days)
            hidden_reports = any(
                incident.first_resolvable_at > observation_end for incident in window_incidents
            )
            unresolved = any(incident.district_id is None for incident in window_incidents)

            for district in districts:
                district_incidents = sorted(
                    (
                        incident
                        for incident in window_incidents
                        if incident.district_id == district.district_id
                        and incident.first_resolvable_at <= observation_end
                    ),
                    key=lambda incident: (incident.occurred_at, incident.incident_id),
                )
                if right_censored or hidden_reports:
                    status = LabelStatus.RIGHT_CENSORED
                elif unresolved:
                    # One unlocated qualifying incident means zero labels for
                    # every district would assert knowledge the registry lacks.
                    status = LabelStatus.UNRESOLVED_LOCATION
                elif district_incidents:
                    status = LabelStatus.OBSERVED
                else:
                    status = LabelStatus.ZERO
                rows.append(
                    DistrictOutcomeRow(
                        district_id=district.district_id,
                        cutoff_at=cutoff,
                        horizon_end=horizon_end,
                        event_family=family,
                        incident_occurred=bool(district_incidents),
                        incident_count=len(district_incidents),
                        first_incident_at=(
                            district_incidents[0].occurred_at if district_incidents else None
                        ),
                        first_resolvable_at=(
                            min(incident.first_resolvable_at for incident in district_incidents)
                            if district_incidents
                            else None
                        ),
                        label_status=status,
                        boundary_version=district.boundary_version,
                        incident_ids=[incident.incident_id for incident in district_incidents],
                    )
                )
    validate_panel(rows)
    return rows


def validate_panel(rows: Iterable[DistrictOutcomeRow]) -> None:
    """Reject duplicate keys and incomplete district universes."""
    guard_outcome_access("validate_district_outcome_panel")
    keys: list[tuple[str, datetime, str]] = []
    universes: dict[tuple[datetime, str], set[str]] = {}
    for row in rows:
        key = (row.district_id, row.cutoff_at, row.event_family)
        keys.append(key)
        universes.setdefault((row.cutoff_at, row.event_family), set()).add(row.district_id)
    if len(keys) != len(set(keys)):
        raise ValueError("district outcome panel contains duplicate district-cutoff-family rows")
    if not universes:
        raise ValueError("district outcome panel cannot be empty")

    expected_by_cutoff: dict[datetime, set[str]] = {}
    for (cutoff, _family), district_ids in universes.items():
        expected = expected_by_cutoff.setdefault(cutoff, district_ids)
        if district_ids != expected:
            raise ValueError(
                f"event families use different district universes at {cutoff.isoformat()}"
            )
