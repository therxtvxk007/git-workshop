"""Event families, and the counting rule for incidents that carry several.

The paper's three families are not disjoint. One incident can be insurgent and
terrorist at once, and LWE incidents are routinely coded as both. The plan
records that the panel never defined a counting rule for this, and chooses
multi-label with union counting (S4, defect 4):

* an incident carries a *set* of family labels;
* a per-family count is the number of distinct incidents carrying that label;
* the "any family" count is the union, and it is never the sum.

A mutually exclusive scheme was rejected because it forces an arbitrary
priority order, and because a comparator that used a different order could then
never be reproduced.

The forecasting side of this is deliberately unfinished. Family *marginals* do
not identify the union: two families each expecting one incident could be the
same incident or two. Deriving a union forecast from marginals means assuming
something about their joint membership, and an adapter may not choose that
assumption (S31.3, S42). So :func:`union_forecast` raises, and per-family
forecasting stays available.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum

from pydantic import field_validator

from pramaanx.core.errors import ContractViolationError, UnresolvedContractError
from pramaanx.schemas.base import PramaanModel


class Family(StrEnum):
    """The three forecast families. Overlapping by design, not by accident."""

    TERRORISM = "terrorism"
    LWE = "lwe"
    INSURGENCY = "insurgency"


ALL_FAMILIES: tuple[Family, ...] = (Family.TERRORISM, Family.LWE, Family.INSURGENCY)


class IncidentLabels(PramaanModel):
    """One incident and every family it belongs to."""

    model_config = PramaanModel.model_config | {"frozen": True}

    incident_id: str
    district_id: str
    #: Required, not defaulted. An incident with no family is invisible to
    #: every family count and present in the union, so it has no consistent
    #: place in the panel at all.
    families: frozenset[Family]

    @field_validator("families", mode="after")
    @classmethod
    def _at_least_one(cls, value: frozenset[Family]) -> frozenset[Family]:
        if not value:
            raise ContractViolationError(
                "an incident with no family label cannot be counted in any family "
                "or in the union; label it or exclude it"
            )
        return value


def family_counts(incidents: Iterable[IncidentLabels]) -> dict[Family, int]:
    """Distinct incidents per family. Deduplicated *within* a family."""
    counts = dict.fromkeys(ALL_FAMILIES, 0)
    seen: dict[Family, set[str]] = {family: set() for family in ALL_FAMILIES}
    for incident in incidents:
        for family in incident.families:
            if incident.incident_id not in seen[family]:
                seen[family].add(incident.incident_id)
                counts[family] += 1
    return counts


def union_count(incidents: Iterable[IncidentLabels]) -> int:
    """Distinct incidents in any family. Deduplicated *across* families."""
    return len({incident.incident_id for incident in incidents if incident.families})


def check_union_invariant(counts: Mapping[Family, int], union: int) -> None:
    """The invariant every panel build asserts (S4).

    Equality means nothing overlapped, which is possible. Exceeding the sum is
    impossible and means an incident was double-counted inside one family.
    """
    total = sum(counts.values())
    if union > total:
        raise ContractViolationError(
            "union count exceeds the sum of family counts, so an incident was "
            "counted twice within a family",
            union=union,
            sum_of_families=total,
        )


def observed_counts(incidents: Iterable[IncidentLabels]) -> tuple[dict[Family, int], int]:
    """Per-family counts and the union, checked against each other."""
    materialised = list(incidents)
    counts = family_counts(materialised)
    union = union_count(materialised)
    check_union_invariant(counts, union)
    return counts, union


def union_forecast(_marginals: Mapping[Family, object]) -> int:
    """Refused. Family marginals do not identify the union.

    Summing them double-counts every shared incident, taking the maximum
    assumes total containment, and multiplying assumes independence. All three
    are statistical assumptions about joint family membership, and the model
    contract has not stated one. A forecast artifact that carries incident-level
    membership per draw can answer this; marginals cannot (S31.3).
    """
    raise UnresolvedContractError(
        "a union forecast needs joint family membership per incident or per "
        "scenario; it cannot be derived from per-family marginals",
        families=sorted(str(family) for family in _marginals),
    )
