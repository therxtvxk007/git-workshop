"""Versioned India district geography.

The identity spine is the Local Government Directory: official district codes,
official state hierarchy, official effective dates. Polygons (geoBoundaries
ADM2) and derived Queen contiguity are optional inputs that produce a *declared*
adjacency table, which is what the pipeline actually reads -- so a run in CI
needs no geospatial stack and still gets byte-identical neighbours.

Nothing here maintains a "current" district list. Every answer is as of a
moment, so a boundary change in 2025 cannot alter what a 2024 cutoff saw.
"""

from __future__ import annotations

from pramaanx.geography.adjacency import (
    AdjacencyError,
    DistrictAdjacency,
    queen_adjacency_from,
)
from pramaanx.geography.crosswalk import CrosswalkError, DistrictCrosswalk
from pramaanx.geography.lgd import LgdContractError, normalise_lgd_rows
from pramaanx.geography.registry import DistrictRegistry, GeographyError
from pramaanx.geography.resolver import (
    DistrictResolver,
    Resolution,
    Unresolved,
    normalise_place_name,
)

__all__ = [
    "AdjacencyError",
    "CrosswalkError",
    "DistrictAdjacency",
    "DistrictCrosswalk",
    "DistrictRegistry",
    "DistrictResolver",
    "GeographyError",
    "LgdContractError",
    "Resolution",
    "Unresolved",
    "normalise_lgd_rows",
    "normalise_place_name",
    "queen_adjacency_from",
]
