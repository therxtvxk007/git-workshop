"""Nothing that happens after a cutoff may change a row built at that cutoff.

Each test mutates the future and asserts the past is byte-identical. These are
the checks that catch the failure mode nobody notices, because a leak does not
raise -- the run simply gets better.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures.spatial.synthetic import (
    BOUNDARY,
    FAMILY,
    build_adjacency,
    build_registry,
)
from pramaanx.geography.adjacency import AdjacencyEdge, DistrictAdjacencyGraph
from pramaanx.models.spatial.features import build_extended_spatial_features
from pramaanx.outcomes.models import LocationStatus, NormalizedIncident

CUTOFF = datetime(2026, 2, 1, tzinfo=UTC)
WINDOWS = [7, 30, 90, 365]


def incident(
    incident_id: str,
    *,
    occurred: datetime,
    resolvable: datetime,
    district: str = "IND-D-1",
    correction: str = "original",
) -> NormalizedIncident:
    return NormalizedIncident(
        incident_id=incident_id,
        source="synthetic",
        source_version="v1",
        event_family=FAMILY,
        occurred_at=occurred,
        first_resolvable_at=resolvable,
        district_id=district,
        location_status=LocationStatus.RESOLVED,
        correction_version=correction,
        source_record_id=incident_id,
    )


def build(incidents: list[NormalizedIncident], adjacency: DistrictAdjacencyGraph | None = None):
    return build_extended_spatial_features(
        registry=build_registry(3),
        incidents=incidents,
        cutoffs=[CUTOFF],
        event_families=[FAMILY],
        history_windows_days=WINDOWS,
        adjacency=adjacency if adjacency is not None else build_adjacency(3),
        horizon_days=30,
    )


BASE = [incident("a", occurred=CUTOFF - timedelta(days=10), resolvable=CUTOFF - timedelta(days=8))]


def test_a_future_incident_cannot_change_an_earlier_row() -> None:
    later = incident(
        "future", occurred=CUTOFF + timedelta(days=5), resolvable=CUTOFF + timedelta(days=6)
    )
    assert build(BASE) == build([*BASE, later])


def test_a_late_reported_incident_is_excluded_until_it_is_resolvable() -> None:
    # It happened before the cutoff, but nobody could have known.
    late = incident(
        "late", occurred=CUTOFF - timedelta(days=3), resolvable=CUTOFF + timedelta(days=4)
    )
    assert build(BASE) == build([*BASE, late])

    # Once resolvable before the cutoff, it must count.
    known = incident(
        "late", occurred=CUTOFF - timedelta(days=3), resolvable=CUTOFF - timedelta(days=1)
    )
    assert build([*BASE, known]) != build(BASE)


def test_a_later_revision_cannot_alter_an_earlier_row() -> None:
    revised = incident(
        "a",
        occurred=CUTOFF - timedelta(days=10),
        resolvable=CUTOFF + timedelta(days=20),
        correction="revision-2",
    )
    assert build(BASE) == build([*BASE, revised])


def test_a_later_neighbour_edge_cannot_alter_an_earlier_row() -> None:
    """An edge introduced under a later boundary version is not retroactive."""
    future_graph = DistrictAdjacencyGraph(
        [
            *build_adjacency(3).edges,
            AdjacencyEdge(
                left_district_id="IND-D-1",
                right_district_id="IND-D-3",
                boundary_version="v2-future",
                weight=1.0,
            ),
        ]
    )
    assert build(BASE, build_adjacency(3)) == build(BASE, future_graph)


def test_a_later_district_split_cannot_alter_an_earlier_row() -> None:
    """A district that only exists later must not appear in an earlier universe."""

    from fixtures.spatial.synthetic import district_ref
    from pramaanx.geography.registry import DistrictRegistry, DistrictRegistryEntry

    entries = list(build_registry(3).entries)
    entries.append(
        DistrictRegistryEntry(
            district=district_ref(99, 1),
            lgd_district_code="99",
            valid_from=(CUTOFF + timedelta(days=60)).date(),
            source_hash="sha256:synthetic-lgd",
        )
    )
    with_split = build_extended_spatial_features(
        registry=DistrictRegistry(entries),
        incidents=BASE,
        cutoffs=[CUTOFF],
        event_families=[FAMILY],
        history_windows_days=WINDOWS,
        adjacency=build_adjacency(3),
        horizon_days=30,
    )
    assert {row.district_id for row in with_split} == {row.district_id for row in build(BASE)}


def test_input_ordering_does_not_change_the_rows() -> None:
    incidents = [
        incident(
            f"i{index}",
            occurred=CUTOFF - timedelta(days=index + 1),
            resolvable=CUTOFF - timedelta(days=index),
        )
        for index in range(1, 12)
    ]
    forward = build(incidents)
    reverse = build(list(reversed(incidents)))
    assert forward == reverse
    assert [row.features for row in forward] == [row.features for row in reverse]


def test_boundary_versioned_adjacency_is_used() -> None:
    """Neighbour features must read the edges for this row's boundary version."""
    wrong_version = DistrictAdjacencyGraph(
        [
            AdjacencyEdge(
                left_district_id="IND-D-1",
                right_district_id="IND-D-2",
                boundary_version="some-other-version",
                weight=1.0,
            )
        ]
    )
    rows = build(BASE, wrong_version)
    target = next(row for row in rows if row.district_id == "IND-D-2")
    assert target.features["neighbour_count_365d"] == 0.0
    assert target.boundary_version == BOUNDARY
