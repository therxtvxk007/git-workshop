"""Adapters for deriving district adjacency from open boundary polygons."""

from __future__ import annotations

from typing import Any

from pramaanx.geography.adjacency import AdjacencyEdge, DistrictAdjacencyGraph


def derive_queen_adjacency(
    frame: Any,
    *,
    district_id_column: str,
    boundary_version: str,
) -> DistrictAdjacencyGraph:
    """Derive Queen contiguity with GeoPandas + PySAL when installed.

    The heavy geospatial stack is optional because model-only deployments read
    the frozen adjacency parquet. Geography builders install the ``geography``
    project extra and invoke this function once per boundary version.
    """
    try:
        from libpysal.weights import Queen
    except ImportError as error:  # pragma: no cover - environment-specific dependency gate
        raise RuntimeError(
            "derive_queen_adjacency requires the 'geography' optional dependencies"
        ) from error

    if district_id_column not in frame.columns:
        raise ValueError(f"boundary frame is missing {district_id_column!r}")
    ids = [str(value) for value in frame[district_id_column].to_list()]
    if len(ids) != len(set(ids)):
        raise ValueError("boundary district IDs must be unique")

    weights = Queen.from_dataframe(frame, ids=ids, silence_warnings=True)
    pairs: set[tuple[str, str]] = set()
    for left, neighbours in weights.neighbors.items():
        for right in neighbours:
            pair_left, pair_right = sorted((str(left), str(right)))
            if pair_left != pair_right:
                pairs.add((pair_left, pair_right))
    return DistrictAdjacencyGraph(
        AdjacencyEdge(
            left_district_id=left,
            right_district_id=right,
            boundary_version=boundary_version,
        )
        for left, right in sorted(pairs)
    )
