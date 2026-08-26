"""Shared schema machinery.

Two rules hold across every record in this project:

* timestamps are timezone-aware UTC, always;
* schemas are versioned, and a field is never silently reinterpreted.

When a field's meaning changes, add a new field and bump ``SCHEMA_VERSION``.
Old records keep the version they were written with, so a migration can tell
what a given value actually meant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from pramaanx.hashing import canonical_bytes, hash_object

SCHEMA_VERSION = 2
"""Bump on any change to persisted field meaning.

See ``docs/schema_changelog.md``. Version 2 added ``EventMention.observed_at``.
"""

Probability = Annotated[float, Field(ge=0.0, le=1.0)]

T = TypeVar("T", bound="PramaanModel")


def _require_aware_utc(value: Any) -> Any:
    """Reject naive datetimes; normalise aware ones to UTC."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime rejected: every timestamp must be timezone-aware. "
                "A guessed timezone is a cutoff bug waiting to happen."
            )
        return value.astimezone(UTC)
    return value


UtcDatetime = Annotated[datetime, BeforeValidator(_require_aware_utc)]


class PramaanModel(BaseModel):
    """Base model: strict fields, canonical hashing, deterministic dumps."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=False,
    )

    def canonical_dict(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude=exclude)

    def canonical_bytes(self, *, exclude: set[str] | None = None) -> bytes:
        return canonical_bytes(self.canonical_dict(exclude=exclude))

    def content_hash(self, *, exclude: set[str] | None = None) -> str:
        return hash_object(self.canonical_dict(exclude=exclude))


class VersionedModel(PramaanModel):
    """A record that is written to disk and therefore needs a schema version."""

    schema_version: int = SCHEMA_VERSION


def normalised_distribution(
    values: dict[str, float],
    *,
    field_name: str,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    """Validate a categorical distribution.

    An empty mapping means "no opinion" and is allowed. A non-empty one must be
    non-negative and sum to 1 within tolerance: a distribution that quietly sums
    to 0.6 turns into a silently deflated probability three stages downstream.
    """
    if not values:
        return {}
    for key, value in values.items():
        if value < 0.0:
            raise ValueError(f"{field_name}[{key!r}] is negative: {value}")
    total = sum(values.values())
    if abs(total - 1.0) > tolerance:
        raise ValueError(f"{field_name} must sum to 1.0, got {total:.9f}")
    return dict(sorted(values.items()))
