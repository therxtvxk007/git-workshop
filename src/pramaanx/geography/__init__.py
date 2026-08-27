"""Versioned India district geography built from official/open source inputs."""

from pramaanx.geography.adjacency import AdjacencyEdge, DistrictAdjacencyGraph
from pramaanx.geography.boundaries import derive_queen_adjacency
from pramaanx.geography.crosswalk import CrosswalkEdge, DistrictCrosswalk
from pramaanx.geography.registry import (
    DistrictRegistry,
    DistrictRegistryEntry,
    LgdColumnMap,
    district_id_from_lgd,
    entries_from_lgd_rows,
)
from pramaanx.geography.resolver import DistrictNameResolver, ResolutionResult

__all__ = [
    "AdjacencyEdge",
    "CrosswalkEdge",
    "DistrictAdjacencyGraph",
    "DistrictCrosswalk",
    "DistrictNameResolver",
    "DistrictRegistry",
    "DistrictRegistryEntry",
    "LgdColumnMap",
    "ResolutionResult",
    "derive_queen_adjacency",
    "district_id_from_lgd",
    "entries_from_lgd_rows",
]
