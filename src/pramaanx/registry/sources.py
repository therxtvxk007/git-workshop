"""Source tiers, collection approval, and the gates that read them.

Table 4 of the paper gives every source one of four tiers, and the tiers are
not a quality label -- they are a statement about what a source is allowed to
*do*. A monitoring-only source may not move a probability. A discovery-only
source may put a candidate into the pool and may not adjudicate it. That
distinction has to be enforced somewhere a feature builder cannot forget, so
it is enforced here and read through :mod:`pramaanx.registry.policy`.

Approval is a separate axis and it is not a name in a file. The plan's legal
gate (S24.5, S34.1) asks for status, scope, effective dates and evidence, and
``may_collect`` refuses without them. An approval owner's name alone was the
failure mode: it looks like a decision and records none.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.core.errors import ContractViolationError
from pramaanx.schemas.base import PramaanModel, VersionedModel


class SourceTier(StrEnum):
    """What a source is licensed to do, in the paper's Table 4 vocabulary."""

    #: Field-level precision and recall measured against gold. May move a
    #: probability.
    VALIDATED = "validated"
    #: May surface a candidate for review. May not move a probability, because
    #: nothing has measured how often it is right.
    DISCOVERY_ONLY = "discovery_only"
    #: Watched for situational awareness. Feeds coverage and health features,
    #: never the event record.
    MONITORING_ONLY = "monitoring_only"
    #: Provenance, controller, history or legal status unrecorded. Collect
    #: nothing until they are (S19).
    QUARANTINED = "quarantined"


class ApprovalStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    REFUSED = "refused"
    EXPIRED = "expired"


class CollectionApproval(PramaanModel):
    """A recorded decision, with the evidence and dates that make it one."""

    status: ApprovalStatus = ApprovalStatus.PENDING
    owner: str = ""
    #: What was approved: which endpoints, which rate, which retention.
    scope: str = ""
    effective_from: date | None = None
    effective_to: date | None = None
    #: Where the decision is written down.
    evidence_ref: str = ""

    @model_validator(mode="after")
    def _an_approval_carries_its_evidence(self) -> CollectionApproval:
        if self.status is ApprovalStatus.APPROVED and not (
            self.owner and self.scope and self.evidence_ref and self.effective_from
        ):
            raise ContractViolationError(
                "an approval needs an owner, a scope, an effective date and an "
                "evidence reference; a name on its own is not a decision",
                owner=self.owner,
                scope=self.scope,
            )
        return self

    def active_on(self, day: date) -> bool:
        if self.status is not ApprovalStatus.APPROVED:
            return False
        if self.effective_from is not None and day < self.effective_from:
            return False
        return not (self.effective_to is not None and day > self.effective_to)


class SourceEntry(VersionedModel):
    """One evidence source, with the S11.1 legal fields and its tier."""

    source_id: str
    owner: str = ""
    jurisdiction: str = ""
    terms_version: str = ""
    permitted_collection_method: str = ""
    retention: str = ""
    training_permitted: bool | None = None
    redistribution_permitted: bool | None = None
    attribution_rule: str = ""
    personal_data: bool | None = None
    deletion_procedure: str = ""
    review_date: date | None = None
    tier: SourceTier = SourceTier.QUARANTINED
    approval: CollectionApproval = Field(default_factory=CollectionApproval)
    #: Withheld from forecasting for a shadow-stream audit (S9). Orthogonal to
    #: tier: a validated source can be in shadow, and that is the point.
    shadow: bool = False


def may_collect(source: SourceEntry, *, on: date | datetime | None = None) -> bool:
    """Whether a collector may run against this source today.

    A quarantined source is refused whatever its approval says, and an
    unapproved source is refused whatever its tier says. Both gates, not either.
    """
    if source.tier is SourceTier.QUARANTINED:
        return False
    day = on.date() if isinstance(on, datetime) else on
    return source.approval.active_on(day) if day is not None else False


def may_create_candidate(source: SourceEntry) -> bool:
    """Whether this source may put an event candidate into the pool."""
    return source.tier in {SourceTier.VALIDATED, SourceTier.DISCOVERY_ONLY}


def may_alter_probability(source: SourceEntry) -> bool:
    """Whether evidence from this source may move a forecast probability.

    Only a validated source. A discovery-only source that could also move the
    number would make measured extraction accuracy optional, which is the
    thing the tiers exist to prevent.
    """
    return source.tier is SourceTier.VALIDATED


def may_inform_coverage(source: SourceEntry) -> bool:
    """Whether this source counts towards coverage and source-health features.

    Monitoring-only sources exist for exactly this. An outage at a source that
    may not move a probability still has to raise coverage uncertainty.
    """
    return source.tier is not SourceTier.QUARANTINED


class SourceRegistry(VersionedModel):
    """The registered sources, with the gates applied by id."""

    entries: tuple[SourceEntry, ...] = Field(default_factory=tuple)

    def get(self, source_id: str) -> SourceEntry:
        for entry in self.entries:
            if entry.source_id == source_id:
                return entry
        raise ContractViolationError(
            "source is not registered; an unregistered source is quarantined by "
            "default and may not be collected or read",
            source_id=source_id,
        )

    def tier(self, source_id: str) -> SourceTier:
        return self.get(source_id).tier

    def shadow_sources(self) -> frozenset[str]:
        return frozenset(entry.source_id for entry in self.entries if entry.shadow)

    def collectable(self, *, on: date | datetime) -> tuple[str, ...]:
        return tuple(sorted(entry.source_id for entry in self.entries if may_collect(entry, on=on)))
