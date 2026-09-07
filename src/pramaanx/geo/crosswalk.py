"""Mapping districts between boundary versions, with the gaps left visible.

A crosswalk is where a boundary change becomes a number, so it is where a
boundary change becomes a silent error. Four rules from the plan (S31.2):

**Unresolved mass stays unresolved.** If 0.85 of a district's population is
accounted for and nobody knows where the rest went, the honest output is 0.85
plus a recorded 0.15 gap. Forcing the remainder into a neighbour to make the
row sum to one manufactures evidence, and the sum-to-one check then passes on
a number that was invented to make it pass.

**A rename is not a split.** They have the same shape -- one code in, one code
out -- and completely different meanings for a time series. Naming the kind
keeps a rename from being reported as a boundary change.

**Kinds are not interchangeable.** A transfer moves a district between states
and therefore needs a district-to-state mapping for the target version; a merge
needs every source to land in the same target.

**Counts are not weights.** Multiplying an integer incident count by an area
share and reporting the result as a count is the one thing this module will not
do. :func:`allocate_counts` returns a weighted aggregate and says so in its
name and its type.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.core.errors import ContractViolationError
from pramaanx.schemas.base import PramaanModel, VersionedModel

#: Shares are floats; exact equality to 1.0 is not available. The tolerance is
#: a contract value rather than a magic number so a report can state it.
DEFAULT_TOLERANCE = 1e-6


class ChangeKind(StrEnum):
    """What actually happened to the district."""

    #: Same territory, new name or new code.
    RENAME = "rename"
    #: One district became several.
    SPLIT = "split"
    #: Several became one.
    MERGE = "merge"
    #: The district moved between states, territory unchanged.
    TRANSFER = "transfer"
    #: Unchanged; carried so a full crosswalk lists every code.
    IDENTITY = "identity"


class WeightBasis(StrEnum):
    """What the share is a share *of*. Reported, never assumed."""

    POPULATION = "population"
    AREA = "area"
    #: A whole-district move, so the share is 1 by construction.
    WHOLE = "whole"


class CrosswalkEdge(PramaanModel):
    """One district's contribution to one district in the target version."""

    model_config = PramaanModel.model_config | {"frozen": True}

    from_id: str
    to_id: str
    share: float = Field(ge=0.0, le=1.0)
    kind: ChangeKind
    basis: WeightBasis = WeightBasis.WHOLE

    @model_validator(mode="after")
    def _whole_moves_are_whole(self) -> CrosswalkEdge:
        if self.kind in {ChangeKind.RENAME, ChangeKind.IDENTITY, ChangeKind.TRANSFER}:
            if abs(self.share - 1.0) > DEFAULT_TOLERANCE:
                raise ContractViolationError(
                    "a rename, transfer or identity moves the whole district; a "
                    "partial share means the change is a split and should say so",
                    kind=str(self.kind),
                    share=self.share,
                )
            if self.basis is not WeightBasis.WHOLE:
                raise ContractViolationError(
                    "a whole-district move has no weighting basis",
                    kind=str(self.kind),
                    basis=str(self.basis),
                )
        return self


class Crosswalk(VersionedModel):
    """Edges from one boundary version to another, plus what is unaccounted for."""

    from_version: str
    to_version: str
    effective_from: date
    edges: tuple[CrosswalkEdge, ...] = Field(default_factory=tuple)
    #: Where the shares came from. A crosswalk whose weights nobody can trace
    #: is a table of opinions.
    source_ref: str = ""
    #: Whether this crosswalk claims to cover every code in the source version.
    #: Only then does sum-to-one apply as a completeness check.
    exhaustive: bool = True

    @model_validator(mode="after")
    def _no_duplicate_edges(self) -> Crosswalk:
        pairs = [(edge.from_id, edge.to_id) for edge in self.edges]
        duplicates = sorted({pair for pair in pairs if pairs.count(pair) > 1})
        if duplicates:
            raise ContractViolationError(
                "the same district pair appears twice in one crosswalk",
                pairs=[list(pair) for pair in duplicates],
            )
        return self

    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({edge.from_id for edge in self.edges}))

    def weights_for(self, district_id: str) -> dict[str, float]:
        """Target shares for one source district, ordered for determinism."""
        return {
            edge.to_id: edge.share
            for edge in sorted(self.edges, key=lambda e: e.to_id)
            if edge.from_id == district_id
        }

    def unresolved_mass(self, district_id: str) -> float:
        """The share of this district nobody has accounted for.

        Zero when the mapping is complete. Positive when a notification is
        partial or a shapefile leaves a gap, and that number belongs in the
        report rather than in a neighbouring district.
        """
        total = sum(self.weights_for(district_id).values())
        return max(0.0, 1.0 - total)

    def check_mass(self, *, tolerance: float = DEFAULT_TOLERANCE) -> dict[str, float]:
        """Return every source district whose shares do not sum to one.

        Over-allocation is always an error: a district cannot contribute more
        than itself. Under-allocation is an error only when the crosswalk
        claims to be exhaustive; otherwise it is reported as unresolved mass.
        """
        problems: dict[str, float] = {}
        for district_id in self.sources():
            total = sum(self.weights_for(district_id).values())
            if total > 1.0 + tolerance or (self.exhaustive and total < 1.0 - tolerance):
                problems[district_id] = total
        if problems:
            raise ContractViolationError(
                "crosswalk shares do not sum to one",
                from_version=self.from_version,
                to_version=self.to_version,
                offenders=dict(sorted(problems.items())),
                exhaustive=self.exhaustive,
            )
        return {district_id: self.unresolved_mass(district_id) for district_id in self.sources()}

    def kinds_for(self, district_id: str) -> tuple[ChangeKind, ...]:
        return tuple(sorted({edge.kind for edge in self.edges if edge.from_id == district_id}))


class WeightedAggregate(PramaanModel):
    """A share-weighted total, with the mass it could not place.

    Not a count. The name and the extra field exist so that a fractional value
    cannot be printed in a column labelled "incidents" without the reader
    seeing what produced it (S31.2).
    """

    model_config = PramaanModel.model_config | {"frozen": True}

    district_id: str
    value: float
    unresolved: float = 0.0
    basis: WeightBasis = WeightBasis.WHOLE


def allocate_counts(
    counts: Mapping[str, int],
    crosswalk: Crosswalk,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> tuple[WeightedAggregate, ...]:
    """Push counts through a crosswalk as weighted aggregates, never as counts.

    Whole-district moves keep integer values exactly. Splits produce fractions,
    which is the honest answer to "how many incidents happened in the half of
    a district that became a new one" when the incidents were not located
    individually. A caller that needs integers has to allocate draws, which
    needs the location contract, not this function.
    """
    crosswalk.check_mass(tolerance=tolerance)
    totals: dict[str, float] = {}
    bases: dict[str, set[WeightBasis]] = {}
    unresolved: dict[str, float] = {}

    for source, count in sorted(counts.items()):
        weights = crosswalk.weights_for(source)
        if not weights:
            raise ContractViolationError(
                "no crosswalk edge for this district; a missing mapping must not "
                "be treated as a district that disappeared",
                district_id=source,
                from_version=crosswalk.from_version,
            )
        gap = crosswalk.unresolved_mass(source)
        for target, share in weights.items():
            totals[target] = totals.get(target, 0.0) + count * share
            bases.setdefault(target, set()).add(
                next(
                    edge.basis
                    for edge in crosswalk.edges
                    if edge.from_id == source and edge.to_id == target
                )
            )
            if gap:
                unresolved[target] = unresolved.get(target, 0.0) + count * gap * share

    return tuple(
        WeightedAggregate(
            district_id=target,
            value=round(value, 12),
            unresolved=round(unresolved.get(target, 0.0), 12),
            basis=(
                next(iter(bases[target])) if len(bases[target]) == 1 else WeightBasis.POPULATION
            ),
        )
        for target, value in sorted(totals.items())
    )


def identity_crosswalk(
    codes: Iterable[str], *, from_version: str, to_version: str, effective_from: date
) -> Crosswalk:
    """An unchanged mapping. Useful as the base case and as a test control."""
    return Crosswalk(
        from_version=from_version,
        to_version=to_version,
        effective_from=effective_from,
        edges=tuple(
            CrosswalkEdge(from_id=code, to_id=code, share=1.0, kind=ChangeKind.IDENTITY)
            for code in sorted(codes)
        ),
    )
