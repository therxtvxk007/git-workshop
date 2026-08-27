"""District identity, effective-dated.

A district is not a stable thing. India's districts are renamed, split and
merged, and the official Local Government Directory (LGD) assigns a fresh code
to each new unit rather than reusing the old one. A forecasting system that
stores ``"Palnadu"`` as a location therefore stores a fact with an expiry date,
and one that stores today's district list stores a fact that was false in 2014.

So identity here is a *code plus an interval*: ``IND-D-<lgd_code>`` is stable
for as long as the unit it names exists, and every record says when it came
into effect and, if it has since been superseded, when it stopped. Nothing in
this module maintains a "current" district truth; the current list is whatever
:meth:`~pramaanx.geography.registry.DistrictRegistry.as_of` returns for today.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator, model_validator

from pramaanx.schemas.base import UtcDatetime, VersionedModel

#: The one identity format. Built from the LGD district code, which is the
#: only district identifier the Indian state itself publishes and versions.
DISTRICT_ID_PATTERN = re.compile(r"^IND-D-\d{1,6}$")
STATE_ID_PATTERN = re.compile(r"^IND-S-\d{1,6}$")


def district_id_for(lgd_code: int | str) -> str:
    """Stable district identity from an LGD district code."""
    code = str(lgd_code).strip()
    if not code.isdigit():
        raise ValueError(f"LGD district code must be numeric, got {code!r}")
    return f"IND-D-{int(code)}"


def state_id_for(lgd_code: int | str) -> str:
    """Stable state identity from an LGD state code."""
    code = str(lgd_code).strip()
    if not code.isdigit():
        raise ValueError(f"LGD state code must be numeric, got {code!r}")
    return f"IND-S-{int(code)}"


class DistrictRef(VersionedModel):
    """One district as it existed over one interval of time.

    ``valid_until`` is exclusive and ``None`` means "still in effect". Two
    records for the same ``district_id`` may not overlap: an overlap would let
    one place resolve to two parent states on the same day, which is how a
    panel quietly acquires duplicate rows.
    """

    district_id: str
    district_name: str
    state_id: str
    state_name: str
    #: The boundary vintage this record belongs to, e.g. ``"lgd-2024-01-01"``.
    #: Adjacency and crosswalks are keyed by it, so a later vintage cannot
    #: reach back and change an earlier answer.
    boundary_version: str
    valid_from: UtcDatetime
    valid_until: UtcDatetime | None = None
    #: Population/area are carried only when the source supplies them; they are
    #: exposure variables, not identity, and are never used for matching.
    population: int | None = Field(default=None, ge=0)
    area_sq_km: float | None = Field(default=None, ge=0.0)

    @field_validator("district_id")
    @classmethod
    def _check_district_id(cls, value: str) -> str:
        if not DISTRICT_ID_PATTERN.match(value):
            raise ValueError(
                f"district_id {value!r} is not an LGD-derived identity; expected IND-D-<lgd code>"
            )
        return value

    @field_validator("state_id")
    @classmethod
    def _check_state_id(cls, value: str) -> str:
        if not STATE_ID_PATTERN.match(value):
            raise ValueError(f"state_id {value!r} is not IND-S-<lgd code>")
        return value

    @model_validator(mode="after")
    def _check_interval(self) -> DistrictRef:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError(f"{self.district_id}: valid_until must be strictly after valid_from")
        if not self.boundary_version:
            raise ValueError("boundary_version is required: an unversioned boundary is a guess")
        return self

    def covers(self, moment: Any) -> bool:
        """Was this record in effect at ``moment``? Half-open: ``[from, until)``."""
        if moment < self.valid_from:
            return False
        return self.valid_until is None or moment < self.valid_until


class CrosswalkEdge(VersionedModel):
    """A weighted mapping from a superseded district to a successor.

    A rename is one edge of weight 1. A split is several edges from one source
    whose weights sum to 1. A merge is several edges into one target. The weight
    says what share of the source's historical activity should be attributed to
    the target -- it is an apportionment rule, not a probability, and the caller
    decides whether apportioning is defensible for a given quantity.
    """

    source_district_id: str
    target_district_id: str
    #: The moment the successor takes effect. Before it, the source stands.
    effective_from: UtcDatetime
    weight: float = Field(default=1.0, gt=0.0, le=1.0)
    #: ``rename``, ``split``, ``merge`` -- recorded because the three have
    #: different consequences for whether a historical count may be apportioned.
    relation: str = "rename"
    basis: str = "unspecified"

    @model_validator(mode="after")
    def _check_edge(self) -> CrosswalkEdge:
        if self.source_district_id == self.target_district_id:
            raise ValueError(f"{self.source_district_id} cannot cross-walk to itself")
        if self.relation not in {"rename", "split", "merge"}:
            raise ValueError(f"unknown crosswalk relation {self.relation!r}")
        return self


class AdjacencyEdge(VersionedModel):
    """One undirected neighbour relation, pinned to a boundary vintage."""

    boundary_version: str
    district_id: str
    neighbour_id: str
    #: How the edge was derived: ``queen`` and ``rook`` come from polygon
    #: contiguity, ``declared`` from a hand-supplied table.
    method: str = "declared"
    shared_boundary_km: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _check_edge(self) -> AdjacencyEdge:
        if self.district_id == self.neighbour_id:
            raise ValueError(f"{self.district_id} cannot neighbour itself")
        if self.method not in {"queen", "rook", "declared"}:
            raise ValueError(f"unknown adjacency method {self.method!r}")
        return self
