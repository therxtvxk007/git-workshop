"""One revision of one source entity.

The unit the as-of store holds is not "a row" but "a statement a source made
about an entity at a point in its own revision history". That distinction is
what lets the same store answer three different questions -- what did the
source say in March, what does it say now, and what has it since retracted --
without any of the three overwriting the others.

Four rules are enforced here rather than at the call site, because a call site
can be forgotten:

* availability travels with the revision, so a batch write cannot restamp it;
* how availability is *evidenced* is a field, not a comment;
* a deletion is a revision, not an absence;
* ordering inside a source is the source's own, normalised at collection.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from pramaanx.core.contexts import AvailabilityBasis
from pramaanx.core.errors import ContractViolationError
from pramaanx.hashing import canonical_json, hash_object, stable_id, utc_isoformat
from pramaanx.schemas.base import UtcDatetime, VersionedModel


class RevisionOperation(StrEnum):
    """What this revision asserts about the entity."""

    UPSERT = "upsert"
    #: A tombstone. The entity was withdrawn or corrected out of existence.
    #: Reads before this revision's availability still see the old state; that
    #: is the whole reason a deletion is stored rather than applied.
    DELETE = "delete"


class Revision(VersionedModel):
    """One immutable statement about one entity, with its own availability."""

    table: str
    source_id: str
    entity_id: str
    #: Deterministic and unique. Two revisions of the same entity that claim the
    #: same order are a collector bug, and the store refuses to guess between
    #: them rather than break the tie on hash order (S28.1).
    revision_id: str = ""
    source_revision_order: int = Field(ge=0)
    operation: RevisionOperation = RevisionOperation.UPSERT

    #: When the reported fact applies. Half-open: ``[start, end)``.
    valid_time_start: UtcDatetime | None = None
    valid_time_end: UtcDatetime | None = None
    #: What the source says about its own publication.
    publish_time: UtcDatetime | None = None
    #: Earliest defensible availability of *these bytes*, under the basis below.
    available_time: UtcDatetime
    #: When this system obtained these bytes.
    retrieved_time: UtcDatetime
    #: Local commit time. Separate from every claim above; useful for recovery.
    ingested_at: UtcDatetime

    availability_basis: AvailabilityBasis = AvailabilityBasis.UNRESOLVED
    #: Hash or reference for the release, capture or receipt that backs the
    #: basis. Required whenever the basis claims more than "the source says so".
    availability_evidence_ref: str | None = None

    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = ""

    @model_validator(mode="after")
    def _derive_and_check(self) -> Revision:
        if not self.payload_hash:
            object.__setattr__(self, "payload_hash", hash_object(self.payload))
        if not self.revision_id:
            object.__setattr__(
                self,
                "revision_id",
                stable_id(
                    "rev",
                    self.table,
                    self.source_id,
                    self.entity_id,
                    self.source_revision_order,
                    str(self.operation),
                    self.payload_hash,
                    utc_isoformat(self.available_time),
                ),
            )

        if self.retrieved_time < self.available_time:
            raise ContractViolationError(
                "retrieved_time precedes available_time; a revision cannot be "
                "in hand before it exists",
                entity_id=self.entity_id,
                available_time=utc_isoformat(self.available_time),
                retrieved_time=utc_isoformat(self.retrieved_time),
            )
        if self.ingested_at < self.retrieved_time:
            raise ContractViolationError(
                "ingested_at precedes retrieved_time",
                entity_id=self.entity_id,
                retrieved_time=utc_isoformat(self.retrieved_time),
                ingested_at=utc_isoformat(self.ingested_at),
            )
        if (
            self.valid_time_start is not None
            and self.valid_time_end is not None
            and self.valid_time_end < self.valid_time_start
        ):
            raise ContractViolationError(
                "valid_time_end precedes valid_time_start",
                entity_id=self.entity_id,
            )
        if (
            self.availability_basis is not AvailabilityBasis.UNRESOLVED
            and not self.availability_evidence_ref
        ):
            raise ContractViolationError(
                "availability_basis claims evidence but no reference was given; "
                "an unbacked claim must be recorded as unresolved instead",
                entity_id=self.entity_id,
                basis=str(self.availability_basis),
            )
        return self

    @property
    def key(self) -> tuple[str, str]:
        """The identity a revision supersedes: source *and* entity.

        Two sources reporting the same incident stay two entities. Collapsing
        them here would make one source's correction silently overwrite the
        other's independent observation.
        """
        return (self.source_id, self.entity_id)

    def to_row(self) -> dict[str, Any]:
        """Flatten to the column layout the store's parquet parts use."""
        return {
            "table": self.table,
            "source_id": self.source_id,
            "entity_id": self.entity_id,
            "revision_id": self.revision_id,
            "source_revision_order": self.source_revision_order,
            "operation": str(self.operation),
            "valid_time_start": self.valid_time_start,
            "valid_time_end": self.valid_time_end,
            "publish_time": self.publish_time,
            "available_time": self.available_time,
            "retrieved_time": self.retrieved_time,
            "ingested_at": self.ingested_at,
            "availability_basis": str(self.availability_basis),
            "availability_evidence_ref": self.availability_evidence_ref,
            "payload_json": self.payload_json(),
            "payload_hash": self.payload_hash,
            "schema_version": self.schema_version,
        }

    def payload_json(self) -> str:
        return canonical_json(self.payload)


#: The column order every revision part is written with. Fixed so two writes of
#: the same rows produce the same bytes.
REVISION_COLUMNS: tuple[str, ...] = (
    "table",
    "source_id",
    "entity_id",
    "revision_id",
    "source_revision_order",
    "operation",
    "valid_time_start",
    "valid_time_end",
    "publish_time",
    "available_time",
    "retrieved_time",
    "ingested_at",
    "availability_basis",
    "availability_evidence_ref",
    "payload_json",
    "payload_hash",
    "schema_version",
)


def check_order_collisions(revisions: list[Revision]) -> None:
    """Reject two different revisions claiming the same place in one history.

    The store's read picks the highest ``source_revision_order`` per entity. If
    two rows tie, "latest" is undefined, and any tie-break the store invented --
    hash order, file order, insertion order -- would be a silent choice about
    which correction won. So this is an ingestion-time failure (S30.1).
    """
    seen: dict[tuple[str, str, str, int], str] = {}
    for revision in revisions:
        slot = (
            revision.table,
            revision.source_id,
            revision.entity_id,
            revision.source_revision_order,
        )
        previous = seen.get(slot)
        if previous is not None and previous != revision.revision_id:
            raise ContractViolationError(
                "two revisions claim the same source_revision_order for one entity",
                table=revision.table,
                source_id=revision.source_id,
                entity_id=revision.entity_id,
                source_revision_order=revision.source_revision_order,
                revision_ids=sorted([previous, revision.revision_id]),
            )
        seen[slot] = revision.revision_id
