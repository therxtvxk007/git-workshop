from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pramaanx.geography import AdjacencyEdge, DistrictAdjacencyGraph, DistrictRegistryEntry
from pramaanx.geography.registry import DistrictRegistry
from pramaanx.models.spatial import build_spatial_features
from pramaanx.outcomes import LocationStatus, NormalizedIncident
from pramaanx.schemas import DistrictRef

CUTOFF = datetime(2026, 2, 1, tzinfo=UTC)


def registry() -> DistrictRegistry:
    return DistrictRegistry(
        [
            DistrictRegistryEntry(
                district=DistrictRef(
                    district_id=f"IND-D-{code}",
                    district_name=f"District {code}",
                    state_id="IND-S-1",
                    state_name="State",
                    boundary_version="v1",
                ),
                lgd_district_code=code,
                valid_from=date(2020, 1, 1),
                source_hash="sha256:lgd",
            )
            for code in ["1", "2"]
        ]
    )


def incident(incident_id: str, occurred: datetime, resolved: datetime) -> NormalizedIncident:
    return NormalizedIncident(
        incident_id=incident_id,
        source="acled",
        source_version="v1",
        event_family="insurgency",
        occurred_at=occurred,
        first_resolvable_at=resolved,
        district_id="IND-D-1",
        location_status=LocationStatus.RESOLVED,
        correction_version="original",
        source_record_id=incident_id,
    )


def test_features_include_only_incidents_resolvable_by_cutoff() -> None:
    visible = incident("visible", CUTOFF - timedelta(days=2), CUTOFF - timedelta(days=1))
    future_event = incident("future-event", CUTOFF + timedelta(days=1), CUTOFF + timedelta(days=1))
    late_report = incident("late-report", CUTOFF - timedelta(days=3), CUTOFF + timedelta(days=1))
    adjacency = DistrictAdjacencyGraph(
        [
            AdjacencyEdge(
                left_district_id="IND-D-1", right_district_id="IND-D-2", boundary_version="v1"
            )
        ]
    )

    rows = build_spatial_features(
        registry=registry(),
        incidents=[visible, future_event, late_report],
        cutoffs=[CUTOFF],
        event_families=["insurgency"],
        history_windows_days=[7, 30],
        adjacency=adjacency,
    )
    first, second = rows
    assert first.features["district_count_7d"] == 1.0
    assert second.features["neighbour_count_7d"] == 1.0

    baseline_hashes = [row.content_hash() for row in rows]
    with_more_future = build_spatial_features(
        registry=registry(),
        incidents=[
            visible,
            future_event,
            late_report,
            incident("later", CUTOFF + timedelta(days=10), CUTOFF + timedelta(days=10)),
        ],
        cutoffs=[CUTOFF],
        event_families=["insurgency"],
        history_windows_days=[7, 30],
        adjacency=adjacency,
    )
    assert [row.content_hash() for row in with_more_future] == baseline_hashes
