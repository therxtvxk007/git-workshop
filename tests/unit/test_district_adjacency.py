from __future__ import annotations

import pytest

from pramaanx.geography import AdjacencyEdge, DistrictAdjacencyGraph


def test_edges_are_canonical_and_hops_are_deterministic() -> None:
    graph = DistrictAdjacencyGraph(
        [
            AdjacencyEdge(left_district_id="B", right_district_id="A", boundary_version="v1"),
            AdjacencyEdge(left_district_id="B", right_district_id="C", boundary_version="v1"),
            AdjacencyEdge(left_district_id="C", right_district_id="D", boundary_version="v2"),
        ]
    )
    assert graph.edges[0].left_district_id == "A"
    assert graph.neighbours("A", boundary_version="v1") == ("B",)
    assert graph.neighbours("A", boundary_version="v1", hops=2) == ("B", "C")
    assert graph.neighbours("A", boundary_version="v2", hops=2) == ()


def test_duplicate_and_self_edges_fail() -> None:
    edge = AdjacencyEdge(left_district_id="A", right_district_id="B", boundary_version="v1")
    with pytest.raises(ValueError, match="duplicate"):
        DistrictAdjacencyGraph([edge, edge])
    with pytest.raises(ValueError, match="itself"):
        AdjacencyEdge(left_district_id="A", right_district_id="A", boundary_version="v1")
