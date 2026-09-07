"""Chronology contexts: who may read what, and under which claim.

The repository already had one admission rule -- ``first_observed_at <=
cutoff`` in :mod:`pramaanx.timeguard.cutoff`. That rule is necessary and it is
not sufficient, for three reasons the revision plan sets out (S27.1, S29):

1. A batch-level availability stamp can overwrite per-row history, so
   availability has to travel with the revision, not with the write call.
2. "Available" means different things depending on the claim being made. A
   forecast that says *this system had this evidence* is a weaker and more
   defensible statement than *this evidence existed then*, and only the second
   needs archival proof.
3. The forecaster and the scorer both read the store, and only one of them may
   see matured outcomes. A single ``read()`` that both call cannot express
   that, so the difference is carried in the context type.

A context is a capability token. :class:`ForecastContext` cannot be handed to a
reference reader because the reference reader asks for :class:`ScoreContext`
and there is no conversion between them. That is a guard against accident, not
against malice: arbitrary Python with filesystem access defeats it, which is
why the store also logs every read (S29.3).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field, model_validator

from pramaanx.core.errors import ContractViolationError
from pramaanx.hashing import hash_object, utc_isoformat
from pramaanx.schemas.base import PramaanModel, UtcDatetime


class InformationProfile(StrEnum):
    """What claim a run is entitled to make about its inputs (S29.2)."""

    #: Inputs this system actually captured before the cutoff. Supports "what
    #: we had", never "what existed". Eligibility uses
    #: ``max(available_time, retrieved_time)``, because a record retrieved
    #: after the cutoff was not in our hands at the cutoff regardless of when
    #: it was published.
    PROSPECTIVE_OBSERVED = "prospective_observed"

    #: Exact historical versions whose pre-cutoff availability is evidenced.
    #: Supports an information-set replay. Requires an availability basis
    #: stronger than a page that currently says it is old.
    STRICT_HISTORICAL = "strict_historical"

    #: Reconstructed data or later tooling, declared as such. Useful, and
    #: excluded from strict historical comparison.
    ENGINEERING_REPLAY = "engineering_replay"


class AvailabilityBasis(StrEnum):
    """How the availability of one revision is evidenced (S29.1)."""

    #: We fetched it ourselves and hold the receipt.
    OBSERVED_RETRIEVAL = "observed_retrieval"
    #: A versioned release whose publication is itself an artefact.
    VERSIONED_RELEASE = "versioned_release"
    #: A third-party archive capture with a capture timestamp.
    VERIFIED_ARCHIVE_CAPTURE = "verified_archive_capture"
    #: The source asserts a date and nothing corroborates it.
    UNRESOLVED = "unresolved"


#: Bases that a strict historical claim accepts. A live page that currently
#: says "2019" is not evidence that its 2019 contents were these bytes, so
#: ``UNRESOLVED`` is absent on purpose and ``OBSERVED_RETRIEVAL`` only counts
#: when the retrieval itself predates the cutoff -- which the store checks.
STRICT_BASES: frozenset[AvailabilityBasis] = frozenset(
    {
        AvailabilityBasis.OBSERVED_RETRIEVAL,
        AvailabilityBasis.VERSIONED_RELEASE,
        AvailabilityBasis.VERIFIED_ARCHIVE_CAPTURE,
    }
)


class OriginRole(StrEnum):
    """The one role an origin plays in the prequential protocol (S33.1)."""

    TRAIN = "train"
    SELECT = "select"
    CALIBRATE = "calibrate"
    RETRO_TEST = "retro_test"
    PROSPECTIVE = "prospective"


class _BaseContext(PramaanModel):
    """Fields every context carries, so a ledger row is comparable across them."""

    model_config = PramaanModel.model_config | {"frozen": True}

    #: The instant the run is issued from. Origin identity for the protocol.
    issue_time: UtcDatetime
    #: The information boundary. Never later than ``issue_time``; usually equal.
    cutoff_at: UtcDatetime
    #: The pinned input manifest. A context without one cannot be served,
    #: because "the current contents of the data directory" is not a snapshot.
    input_manifest: str
    profile: InformationProfile
    role: OriginRole
    #: Hash of the registry and gate policy in force. A source whose tier
    #: changed produces a different context, and therefore a different cache
    #: key, even over identical bytes.
    policy_hash: str
    #: The district boundary version this run's geography is expressed in.
    boundary_version: str
    #: Hash of the feature contract; empty when the run builds no features.
    feature_contract: str = ""

    @model_validator(mode="after")
    def _cutoff_not_after_issue(self) -> _BaseContext:
        if self.cutoff_at > self.issue_time:
            raise ContractViolationError(
                "cutoff_at is after issue_time",
                cutoff_at=utc_isoformat(self.cutoff_at),
                issue_time=utc_isoformat(self.issue_time),
            )
        return self

    def eligibility_instant(self, available_time: datetime, retrieved_time: datetime) -> datetime:
        """The instant a revision's eligibility is judged at, under this profile.

        Prospective runs take the later of availability and retrieval: evidence
        published in January but fetched in March was not ours in February.
        Historical and engineering replays take availability, because the point
        of a replay is to ask what was knowable, not what we happened to hold.
        """
        if self.profile is InformationProfile.PROSPECTIVE_OBSERVED:
            return max(available_time, retrieved_time)
        return available_time

    def identity(self) -> str:
        """Stable hash of everything that makes this context a distinct read."""
        return hash_object(self.canonical_dict())


class ForecastContext(_BaseContext):
    """Read capability for predictors. Carries no way to reach an outcome.

    There is deliberately no ``as_score_context()``. A forecaster that wants
    labels has to be handed a different object by the runtime, and that hand-off
    is the thing a reviewer can look for.
    """

    def horizon_end(self, days: int) -> datetime:
        return self.issue_time + timedelta(days=days)


class FitContext(_BaseContext):
    """Read capability for fitting: predictors plus *matured* training labels.

    ``fit_cutoff`` is not a duplicate of ``cutoff_at``. Features for a training
    row are built at that row's own origin, which is earlier; the label must be
    mature and its exact revision available by the time the fit runs. Two
    boundaries, two fields (S33.1).
    """

    fit_cutoff: UtcDatetime
    label_manifest: str
    training_origins: tuple[UtcDatetime, ...] = Field(default_factory=tuple)
    maturation_days: int = Field(ge=0)

    @model_validator(mode="after")
    def _training_origins_precede_fit(self) -> FitContext:
        if self.fit_cutoff > self.issue_time:
            raise ContractViolationError(
                "fit_cutoff is after issue_time",
                fit_cutoff=utc_isoformat(self.fit_cutoff),
                issue_time=utc_isoformat(self.issue_time),
            )
        late = [utc_isoformat(o) for o in self.training_origins if o > self.fit_cutoff]
        if late:
            raise ContractViolationError(
                "training origin is after the fit cutoff",
                origins=late,
                fit_cutoff=utc_isoformat(self.fit_cutoff),
            )
        return self

    def forecast_context(self, *, issue_time: datetime | None = None) -> ForecastContext:
        """The narrower predictor-only view, for building features at an origin.

        Widening is impossible in the other direction, which is the point.
        """
        origin = (issue_time or self.issue_time).astimezone(UTC)
        return ForecastContext(
            issue_time=origin,
            cutoff_at=min(self.cutoff_at, origin),
            input_manifest=self.input_manifest,
            profile=self.profile,
            role=self.role,
            policy_hash=self.policy_hash,
            boundary_version=self.boundary_version,
            feature_contract=self.feature_contract,
        )


class ScoreContext(_BaseContext):
    """Read capability for scoring an *already frozen* forecast.

    Holding this is the only way to reach matured reference labels, and it
    names the forecast it may score. An evaluator that regenerates predictions
    while holding it is scoring something other than what was committed, so
    the forecast reference is required rather than optional (S29.3).
    """

    forecast_artifact: str
    reference_manifest: str
    maturation_days: int = Field(ge=0)
    #: Hash of the frozen evaluation contract: metrics, weights, eligibility.
    evaluation_contract: str

    @model_validator(mode="after")
    def _scoring_looks_backwards(self) -> ScoreContext:
        if self.role is OriginRole.PROSPECTIVE and self.reference_manifest == self.input_manifest:
            raise ContractViolationError(
                "a prospective score reuses the forecast's own input manifest as "
                "its reference; matured outcomes cannot be in it",
                manifest=self.input_manifest,
            )
        return self


class ForecastReader(Protocol):
    """The only read path a predictor gets."""

    def read(
        self, table: str, *, ctx: ForecastContext, columns: tuple[str, ...] | None = None
    ) -> Any: ...


class TrainingLabelReader(Protocol):
    """Matured labels for fitting, gated on the fit cutoff."""

    def read_mature(self, table: str, *, ctx: FitContext) -> Any: ...


class ReferenceReader(Protocol):
    """Matured labels for scoring a frozen forecast. Never given to a model."""

    def read_reference(self, table: str, *, ctx: ScoreContext) -> Any: ...
