"""The parameter-cutoff gate.

The plan's own review found this defect in itself (S26.1, defect 1): Appendix A
carried a ``parameter_cutoff`` field and nothing read it. A 2026 language model
reading a 2019 article may already know how 2019 turned out, through its
weights. The as-of store cannot see that leak, because the leak is not in the
input rows -- it is in the parameters, and no timestamp filter reaches it.

So a model is registered like a source, and the same question is asked of it:
what claim does using this support? Three answers, and the profile decides
which one is on offer:

* a strict historical replay needs the model to have existed, with evidence;
* a prospective run needs it to have existed, because the run claims to be
  what this system did at that time;
* an engineering replay may use anything, and says so in the ledger.

A missing cutoff is ``unknown``, never ``fine``. The plan is explicit that an
undocumented cutoff fails a strict run rather than being assumed benign.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.core.contexts import InformationProfile
from pramaanx.core.errors import ContractViolationError
from pramaanx.hashing import utc_isoformat
from pramaanx.schemas.base import UtcDatetime, VersionedModel


class IntendedUse(StrEnum):
    """What a run intends to do with a model's output.

    Separate from the science. TimesFM-3's weights are published for
    non-commercial, non-production use; a score win does not make it
    deployable in an operational system, and the licence field has to be able
    to say that before the score exists (S11, foundation rule 4).
    """

    RESEARCH = "research"
    COMMERCIAL = "commercial"
    OPERATIONAL = "operational"


class Verdict(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    #: The registry does not know enough to say. Strict runs treat this as
    #: blocked; engineering replays record it and continue.
    UNKNOWN = "unknown"


class ModelEntry(VersionedModel):
    """One pretrained artifact, with the evidence a strict claim would need.

    ``training_data_cutoff`` alone is necessary and not sufficient (S29.2). A
    model whose weights hash is unrecorded cannot be shown to be the model that
    existed then, and a model whose retrieval index was built last month has a
    later effective cutoff than its weights suggest.
    """

    model_id: str
    #: ``None`` means undocumented, which is not the same as "no cutoff".
    training_data_cutoff: UtcDatetime | None = None
    #: What the cutoff covers. A cutoff with no stated scope is a number
    #: without a claim attached.
    cutoff_scope: str = ""
    release_date: UtcDatetime | None = None
    weights_licence: str = ""
    commercial_use: bool | None = None
    operational_use: bool | None = None
    #: Exact identity of what would be loaded. Absent means a strict claim
    #: cannot be checked even when the dates look right.
    weights_hash: str = ""
    tokenizer_hash: str = ""
    config_hash: str = ""
    #: Later than the weights cutoff whenever a fine-tune, retrieval index,
    #: gazetteer or learned calibrator was built afterwards.
    derived_artifact_cutoff: UtcDatetime | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _cutoff_scope_accompanies_a_cutoff(self) -> ModelEntry:
        if self.training_data_cutoff is not None and not self.cutoff_scope:
            raise ContractViolationError(
                "a training cutoff without a stated scope is a number without a "
                "claim; say what it covers or leave it unknown",
                model_id=self.model_id,
            )
        return self

    @property
    def effective_cutoff(self) -> datetime | None:
        """The later of the weights cutoff and anything derived from it."""
        candidates = [
            value
            for value in (self.training_data_cutoff, self.derived_artifact_cutoff)
            if value is not None
        ]
        return max(candidates) if candidates else None

    def has_strict_identity(self) -> bool:
        """Whether the exact artifact is pinned well enough for a strict claim."""
        return bool(self.weights_hash and self.tokenizer_hash and self.config_hash)


class ModelDecision(VersionedModel):
    """A gate result that a ledger row can carry verbatim."""

    model_id: str
    verdict: Verdict
    reasons: tuple[str, ...] = ()
    profile: InformationProfile
    intended_use: IntendedUse
    issue_time: UtcDatetime

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOWED

    def raise_if_blocked(self) -> None:
        if self.allowed:
            return
        raise ContractViolationError(
            "model is not permitted for this run",
            model_id=self.model_id,
            verdict=str(self.verdict),
            reasons=list(self.reasons),
        )


def licence_reasons(model: ModelEntry, use: IntendedUse) -> list[str]:
    """Licence blocks, independent of any date."""
    reasons: list[str] = []
    if use is IntendedUse.COMMERCIAL and model.commercial_use is False:
        reasons.append("weights licence forbids commercial use")
    if use is IntendedUse.OPERATIONAL and model.operational_use is False:
        reasons.append("weights licence forbids operational or production use")
    return reasons


def licence_unknowns(model: ModelEntry, use: IntendedUse) -> list[str]:
    """Licence facts nobody has recorded. Unknown, not permitted."""
    unknowns: list[str] = []
    if not model.weights_licence:
        unknowns.append("weights licence is unrecorded")
    if use is IntendedUse.COMMERCIAL and model.commercial_use is None:
        unknowns.append("commercial use permission is unrecorded")
    if use is IntendedUse.OPERATIONAL and model.operational_use is None:
        unknowns.append("operational use permission is unrecorded")
    return unknowns


def may_use_model(
    model: ModelEntry,
    issue_time: datetime,
    *,
    profile: InformationProfile,
    intended_use: IntendedUse = IntendedUse.RESEARCH,
) -> ModelDecision:
    """Decide whether this model may run at this origin, under this claim."""
    reasons: list[str] = licence_reasons(model, intended_use)
    unknowns: list[str] = licence_unknowns(model, intended_use)

    cutoff = model.effective_cutoff
    if cutoff is None:
        unknowns.append("training data cutoff is undocumented")
    elif cutoff > issue_time:
        reasons.append(
            f"training data reaches {utc_isoformat(cutoff)}, past the "
            f"{utc_isoformat(issue_time)} origin"
        )

    if profile is InformationProfile.STRICT_HISTORICAL:
        if model.release_date is None:
            unknowns.append("release date is unrecorded, so historical availability is unproven")
        elif model.release_date > issue_time:
            reasons.append(
                f"released {utc_isoformat(model.release_date)}, after the origin; "
                "it could not have been used then"
            )
        if not model.has_strict_identity():
            unknowns.append(
                "weights, tokenizer or config hash is unrecorded, so the exact "
                "artifact cannot be shown to be the historical one"
            )

    def decide() -> tuple[Verdict, list[str]]:
        if reasons:
            return Verdict.BLOCKED, reasons + unknowns
        if not unknowns:
            return Verdict.ALLOWED, []
        # An engineering replay may proceed on an undocumented model, provided
        # the run is labelled as one. The other two profiles make claims that
        # the missing facts would have to support.
        if profile is InformationProfile.ENGINEERING_REPLAY:
            return Verdict.ALLOWED, unknowns
        return Verdict.UNKNOWN, unknowns

    verdict, notes = decide()
    return ModelDecision(
        model_id=model.model_id,
        verdict=verdict,
        reasons=tuple(notes),
        profile=profile,
        intended_use=intended_use,
        issue_time=issue_time,
    )


class ModelRegistry(VersionedModel):
    """The registered models, keyed by id."""

    entries: tuple[ModelEntry, ...] = Field(default_factory=tuple)

    def get(self, model_id: str) -> ModelEntry:
        for entry in self.entries:
            if entry.model_id == model_id:
                return entry
        raise ContractViolationError(
            "model is not registered; register it with its cutoff, licence and "
            "artifact hashes before a run may use it",
            model_id=model_id,
        )

    def decide(
        self,
        model_id: str,
        issue_time: datetime,
        *,
        profile: InformationProfile,
        intended_use: IntendedUse = IntendedUse.RESEARCH,
    ) -> ModelDecision:
        return may_use_model(
            self.get(model_id), issue_time, profile=profile, intended_use=intended_use
        )
