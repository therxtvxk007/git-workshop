"""The training-row contract for the classical spatial baseline ladder.

One row is always exactly one ``district x cutoff x event_family``. Every model
in the ladder consumes rows built by this module, which is the mechanism that
makes B0 and B12 comparable: they cannot disagree about which districts exist,
which cutoffs are eligible, or which labels are safe to train on, because they
are handed the same rows.

The construction is deliberately strict and refuses rather than repairs. A
dataset builder that quietly drops a censored row, or silently fills a missing
district, produces a training set nobody can reconstruct later -- and the
resulting model looks better than it is, because the rows it found hardest
were the ones that disappeared.

This module adapts the foundation's ``DistrictOutcomeRow`` and
``SpatialFeatureRow`` through a narrow interface. It does not redefine either,
and it introduces no parallel outcome schema.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from pramaanx.geography.registry import DistrictRegistry
from pramaanx.hashing import hash_object
from pramaanx.models.spatial.dataset import SpatialFeatureRow
from pramaanx.outcomes.models import DistrictOutcomeRow, LabelStatus
from pramaanx.schemas.base import UtcDatetime, VersionedModel

__all__ = [
    "ContractViolationError",
    "ReportingDelayPolicy",
    "SpatialTrainingRow",
    "TrainingRowSet",
    "build_training_rows",
]

#: Label states a model may train on. `UNRESOLVED_LOCATION` and
#: `RIGHT_CENSORED` are excluded by construction, not by a downstream filter
#: that a future caller could forget to apply.
TRAINABLE_LABEL_STATUSES = frozenset({LabelStatus.OBSERVED, LabelStatus.ZERO})


class ContractViolationError(ValueError):
    """A candidate training row broke the input contract."""


class ReportingDelayPolicy(VersionedModel):
    """The delay assumptions a row set was built under.

    Carried on the row set and hashed into every artefact. Two runs that used
    different delays are not comparable, and without this they would look
    identical: the rows have the same keys and the labels differ silently.
    """

    #: Days after `horizon_end` before a label is considered fully reported.
    #: Mirrors `build_district_outcome_panel(reporting_delay_days=...)`.
    reporting_delay_days: int = Field(ge=0)
    #: The observation boundary the panel was built against.
    observation_end: UtcDatetime
    #: Forecast horizon in days, so a row set states its own target definition.
    horizon_days: int = Field(gt=0)
    policy_version: str = "district-reporting-delay@1"

    @field_validator("policy_version")
    @classmethod
    def _require_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy_version cannot be blank")
        return value


class SpatialTrainingRow(VersionedModel):
    """One fully-specified supervised row, safe to train on."""

    district_id: str
    state_id: str
    boundary_version: str
    cutoff_at: UtcDatetime
    event_family: str
    feature_set_version: str
    features: dict[str, float] = Field(default_factory=dict)
    #: Per-feature availability. Every value must be at or before `cutoff_at`;
    #: this is what makes "no post-cutoff features" checkable rather than
    #: merely intended.
    feature_available_at: dict[str, UtcDatetime] = Field(default_factory=dict)
    occurrence_target: int = Field(ge=0, le=1)
    count_target: int = Field(ge=0)
    label_status: LabelStatus
    #: When the target first became knowable. `None` only for true zero rows,
    #: which have no incident to resolve.
    target_first_resolvable_at: UtcDatetime | None = None
    snapshot_hash: str
    #: Optional coverage/evidence signals injected by other work packages.
    #: Absent is not zero: a district with no coverage record is distinguishable
    #: from one with measured zero coverage.
    source_coverage: dict[str, float] = Field(default_factory=dict)

    @field_validator("district_id", "state_id", "boundary_version", "event_family", "snapshot_hash")
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("training row identifiers and provenance cannot be blank")
        return value

    @model_validator(mode="after")
    def _check_row(self) -> SpatialTrainingRow:
        if self.label_status not in TRAINABLE_LABEL_STATUSES:
            raise ContractViolationError(
                f"label_status {self.label_status.value!r} is not trainable; "
                "censored and unresolved rows must never reach a model"
            )
        if self.occurrence_target != int(self.count_target > 0):
            raise ContractViolationError("occurrence_target must equal count_target > 0")
        late = sorted(
            name for name, seen in self.feature_available_at.items() if seen > self.cutoff_at
        )
        if late:
            raise ContractViolationError(
                f"features available only after the cutoff: {late}. A feature the model "
                "could not have seen is leakage regardless of how small its effect is."
            )
        unknown = sorted(set(self.feature_available_at) - set(self.features))
        if unknown:
            raise ContractViolationError(f"availability recorded for absent features: {unknown}")
        return self

    @property
    def key(self) -> tuple[str, datetime, str]:
        return (self.district_id, self.cutoff_at, self.event_family)


@dataclass(frozen=True)
class TrainingRowSet:
    """An immutable, validated set of rows plus the policy that produced it.

    A dataclass rather than a pydantic model on purpose. Pydantic wraps every
    exception raised inside a validator in a `ValidationError`, so a caller
    could not catch `ContractViolationError` and act on the specific violation
    -- and "the row set was rejected" is exactly the thing callers need to
    branch on. `SpatialTrainingRow` stays a pydantic model because it is a
    persisted record; this is a container.
    """

    rows: tuple[SpatialTrainingRow, ...]
    feature_set_version: str
    reporting_delay: ReportingDelayPolicy
    snapshot_hash: str

    def __init__(
        self,
        rows: Sequence[SpatialTrainingRow],
        feature_set_version: str,
        reporting_delay: ReportingDelayPolicy,
        snapshot_hash: str,
    ) -> None:
        materialised = tuple(rows)
        if not materialised:
            raise ContractViolationError("training row set cannot be empty")
        _reject_duplicates(materialised)
        _reject_mixed_snapshots(materialised, snapshot_hash)
        _reject_incomplete_universe(materialised)
        _reject_mixed_boundaries(materialised)
        versions = {row.feature_set_version for row in materialised}
        if versions != {feature_set_version}:
            raise ContractViolationError(
                f"row set declares feature_set_version {feature_set_version!r} "
                f"but contains {sorted(versions)}"
            )
        object.__setattr__(self, "rows", materialised)
        object.__setattr__(self, "feature_set_version", feature_set_version)
        object.__setattr__(self, "reporting_delay", reporting_delay)
        object.__setattr__(self, "snapshot_hash", snapshot_hash)

    @property
    def cutoffs(self) -> tuple[datetime, ...]:
        return tuple(sorted({row.cutoff_at for row in self.rows}))

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(sorted({name for row in self.rows for name in row.features}))

    def rows_hash(self) -> str:
        """Content hash over the rows, independent of wall-clock time."""
        return hash_object(
            [
                {
                    "district_id": row.district_id,
                    "cutoff_at": row.cutoff_at,
                    "event_family": row.event_family,
                    "boundary_version": row.boundary_version,
                    "features": row.features,
                    "occurrence_target": row.occurrence_target,
                    "count_target": row.count_target,
                }
                for row in sorted(self.rows, key=lambda item: item.key)
            ]
        )


def _reject_duplicates(rows: Sequence[SpatialTrainingRow]) -> None:
    keys = [row.key for row in rows]
    if len(keys) != len(set(keys)):
        duplicated = sorted({key for key in keys if keys.count(key) > 1})[:5]
        raise ContractViolationError(
            f"duplicate district/cutoff/family rows, e.g. {duplicated}. A duplicated row "
            "silently doubles that district's weight in every fitted model."
        )


def _reject_mixed_snapshots(rows: Sequence[SpatialTrainingRow], expected: str) -> None:
    mismatched = sorted({row.snapshot_hash for row in rows} - {expected})
    if mismatched:
        raise ContractViolationError(
            f"rows carry snapshot hashes other than {expected!r}: {mismatched}. Mixing "
            "snapshots means the feature values and the labels came from different worlds."
        )


def _reject_incomplete_universe(rows: Sequence[SpatialTrainingRow]) -> None:
    """Every family at a cutoff must cover the same districts.

    A family that is missing districts is not merely smaller: the models that
    can predict it and the models that cannot are then being scored on
    different populations.
    """
    universes: dict[tuple[datetime, str], set[str]] = {}
    for row in rows:
        universes.setdefault((row.cutoff_at, row.event_family), set()).add(row.district_id)
    by_cutoff: dict[datetime, set[str]] = {}
    for (cutoff, family), districts in sorted(universes.items()):
        expected = by_cutoff.setdefault(cutoff, districts)
        if districts != expected:
            missing = sorted(expected - districts)[:5]
            extra = sorted(districts - expected)[:5]
            raise ContractViolationError(
                f"incomplete district universe at {cutoff.isoformat()} for {family!r}: "
                f"missing {missing}, unexpected {extra}"
            )


def _reject_mixed_boundaries(rows: Sequence[SpatialTrainingRow]) -> None:
    """One boundary version per cutoff, unless a mapping was supplied.

    Two boundary versions inside one cutoff means two different definitions of
    "district" are being averaged. `build_training_rows` accepts an explicit
    crosswalk to allow it deliberately; without one it is refused.
    """
    by_cutoff: dict[datetime, set[str]] = {}
    for row in rows:
        by_cutoff.setdefault(row.cutoff_at, set()).add(row.boundary_version)
    for cutoff, versions in sorted(by_cutoff.items()):
        if len(versions) > 1:
            raise ContractViolationError(
                f"cutoff {cutoff.isoformat()} mixes boundary versions {sorted(versions)} "
                "without an explicit boundary mapping"
            )


def build_training_rows(
    *,
    feature_rows: Iterable[SpatialFeatureRow],
    outcome_rows: Iterable[DistrictOutcomeRow],
    registry: DistrictRegistry,
    feature_set_version: str,
    snapshot_hash: str,
    reporting_delay: ReportingDelayPolicy,
    feature_available_at: Mapping[str, datetime] | None = None,
    source_coverage: Mapping[tuple[str, datetime, str], Mapping[str, float]] | None = None,
    boundary_mapping: Mapping[str, str] | None = None,
) -> TrainingRowSet:
    """Join features to labels, refusing anything a model must not learn from.

    `feature_available_at` maps a feature name to the moment it becomes
    available *relative to a cutoff*; it is supplied per-cutoff by the caller
    when a feature has a publication lag. Features without an entry are
    assumed available at their cutoff, which is the correct default for the
    history features this package builds from already-resolvable incidents.
    """
    features = list(feature_rows)
    outcomes = {(row.district_id, row.cutoff_at, row.event_family): row for row in outcome_rows}

    prepared: list[SpatialTrainingRow] = []
    pending: list[tuple[str, datetime, str]] = []
    excluded: dict[LabelStatus, int] = {}

    for row in sorted(features, key=lambda item: item.key):
        outcome = outcomes.get(row.key)
        if outcome is None:
            # A feature row with no label is *pending*, not negative. Treating
            # it as a zero is the single most damaging silent default here.
            pending.append(row.key)
            continue
        if outcome.label_status not in TRAINABLE_LABEL_STATUSES:
            excluded[outcome.label_status] = excluded.get(outcome.label_status, 0) + 1
            continue

        district = registry.get(row.district_id, as_of=row.cutoff_at.date())
        boundary = row.boundary_version
        if boundary_mapping is not None:
            boundary = boundary_mapping.get(boundary, boundary)

        availability = {
            name: _resolve_availability(name, row.cutoff_at, feature_available_at)
            for name in row.features
        }
        coverage = dict((source_coverage or {}).get(row.key, {}))

        prepared.append(
            SpatialTrainingRow(
                district_id=row.district_id,
                state_id=district.state_id,
                boundary_version=boundary,
                cutoff_at=row.cutoff_at,
                event_family=row.event_family,
                feature_set_version=feature_set_version,
                features=dict(row.features),
                feature_available_at=availability,
                occurrence_target=int(outcome.incident_occurred),
                count_target=outcome.incident_count,
                label_status=outcome.label_status,
                target_first_resolvable_at=outcome.first_resolvable_at,
                snapshot_hash=snapshot_hash,
                source_coverage=coverage,
            )
        )

    if pending:
        raise ContractViolationError(
            f"{len(pending)} feature rows have no resolved label, e.g. {pending[:3]}. "
            "A pending label is not a negative outcome."
        )
    if not prepared:
        raise ContractViolationError(
            "every candidate row was excluded as censored or unresolved: "
            f"{ {status.value: count for status, count in excluded.items()} }"
        )

    return TrainingRowSet(
        rows=prepared,
        feature_set_version=feature_set_version,
        reporting_delay=reporting_delay,
        snapshot_hash=snapshot_hash,
    )


def _resolve_availability(
    name: str, cutoff: datetime, overrides: Mapping[str, datetime] | None
) -> datetime:
    if overrides is not None and name in overrides:
        return overrides[name]
    return cutoff
