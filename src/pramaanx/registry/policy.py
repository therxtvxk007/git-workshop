"""The read policy the as-of store applies at step 5, and its hash.

Two things the plan insists on meet here. The store's step 5 gate needs to know
which sources are withheld from a forecast run (S30.1). And every context
carries a ``policy_hash`` so that a source which changed tier produces a
different read -- and therefore a different cache key -- even over identical
bytes (S36.2).

Both come from the same registry, so they cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pramaanx.core.errors import ContractViolationError
from pramaanx.hashing import hash_object
from pramaanx.registry.sources import (
    SourceRegistry,
    may_alter_probability,
    may_create_candidate,
    may_inform_coverage,
)


class ReadPurpose(StrEnum):
    """What the reader intends to do with the rows, which decides the gate."""

    #: Move a probability. Validated sources only.
    ADJUDICATION = "adjudication"
    #: Put a candidate into the pool. Validated and discovery-only.
    DISCOVERY = "discovery"
    #: Coverage and source-health features. Everything but quarantined.
    COVERAGE = "coverage"
    #: The audit's own view, which is allowed to see withheld sources -- that
    #: is what a shadow stream is for (S9).
    AUDIT = "audit"


@dataclass(frozen=True)
class RegistryReadPolicy:
    """Denies a source when its tier, or its shadow status, says to.

    Withholding by source id is necessary and not sufficient: a translated or
    cached descendant of a withheld source is caught by lineage, not here. The
    two are complementary and the plan asks for both (S33.1).
    """

    registry: SourceRegistry
    purpose: ReadPurpose

    def deny_reason(self, source_id: str) -> str | None:
        try:
            entry = self.registry.get(source_id)
        except ContractViolationError:
            # An unregistered source is denied, not fatal. The store reports it
            # in ``denied_sources`` so the gap is visible in the run manifest.
            return "unregistered"

        if entry.shadow and self.purpose is not ReadPurpose.AUDIT:
            return "shadow_withheld"

        allowed = {
            ReadPurpose.ADJUDICATION: may_alter_probability,
            ReadPurpose.DISCOVERY: may_create_candidate,
            ReadPurpose.COVERAGE: may_inform_coverage,
            ReadPurpose.AUDIT: may_inform_coverage,
        }[self.purpose]
        return None if allowed(entry) else f"tier_{entry.tier}"

    def policy_hash(self) -> str:
        """The identity a context carries.

        Covers the purpose and every source's tier and shadow status -- the
        things that change what a read returns. Deliberately not the whole
        registry: a corrected attribution rule is not a different read.
        """
        return hash_object(
            {
                "purpose": str(self.purpose),
                "sources": {
                    entry.source_id: {"tier": str(entry.tier), "shadow": entry.shadow}
                    for entry in sorted(self.registry.entries, key=lambda e: e.source_id)
                },
            }
        )
