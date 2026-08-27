"""The frozen prediction contract: what is being forecast, and what counts.

Everything downstream is defined by this file. The rate denominator, the target
numerator, the geographic unit and the evaluation all follow from it, which is
why it is frozen before the geography layer rather than after: a gazetteer built
against an undefined unit is a gazetteer built to the wrong specification.

The contract exists mainly to make one class of mistake impossible. It is very
easy to build a system that appears to forecast terrorism and is in fact
counting newspaper articles about protests. Every rule here is a barrier
between an article and a target outcome, and most of them are refusals.

Three refusals matter more than the rest.

*Motivation is never inferred from wording.* A CAMEO code, a headline verb or
a reporter's adjective cannot establish that an act was politically motivated.
Only a claim of responsibility, an official attribution, or a judicial finding
can, and in their absence the incident is :attr:`Resolution.ADJUDICATION_REQUIRED`
rather than a positive or a negative.

*An explosion is not a bombing.* Gas cylinders, quarry accidents, ordnance
disposal and military training all produce explosions. Treating an unresolved
explosive incident as a positive target would inflate the base rate with events
that are not the phenomenon, in a way no calibration can correct.

*Reports are not incidents.* Twenty articles about one bombing are one target.
The outcome is a deduplicated real-world incident carrying a stable
``incident_id``, and every report attaches to it rather than incrementing it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.hashing import hash_object, stable_id
from pramaanx.schemas.base import PramaanModel, Probability, UtcDatetime, VersionedModel

CONTRACT_VERSION = "1.0.0"
"""Bumped by hand when any rule below changes. Pinned by a contract test, so an
unannounced change to what counts as a target fails the build."""


# --------------------------------------------------------------------------
# Target classes and exclusions
# --------------------------------------------------------------------------


class TargetClass(StrEnum):
    """The event classes a positive outcome may belong to.

    Deliberately narrow. Each requires the motivation evidence in
    :class:`MotivationEvidence` before it can be positive; the class alone never
    establishes the target.
    """

    #: An attack against civilians or civilian infrastructure intended to
    #: coerce or intimidate, attributed by claim, official finding or judgment.
    TERRORISM = "terrorism"
    #: An armed attack by a recognised insurgent group against state forces,
    #: state infrastructure or civilians.
    ARMED_INSURGENT_ATTACK = "armed_insurgent_attack"
    #: An attack using an improvised explosive device, where motivation has been
    #: established. An unattributed explosion is NOT this class -- see
    #: :class:`ExplosiveCause`.
    IED_ATTACK = "ied_attack"
    #: An attack attributed to a Left-Wing Extremist group.
    LWE_ATTACK = "lwe_attack"
    #: An armed assault whose political motivation is established but which does
    #: not fit the classes above.
    POLITICALLY_MOTIVATED_ARMED_ASSAULT = "politically_motivated_armed_assault"


class Completion(StrEnum):
    """Whether the attack occurred, was attempted, or was prevented.

    A separate axis from :class:`TargetClass`, and never collapsed into it. A
    foiled plot and a completed bombing are different outcomes with different
    base rates, and a forecast scored against their union is scored against a
    quantity nobody asked about.
    """

    COMPLETED = "completed"
    #: Initiated and failed on its own terms -- a device that did not detonate,
    #: an assault repelled.
    ATTEMPTED = "attempted"
    #: Prevented before initiation by intervention. Recorded, never a positive
    #: target: counting foiled plots as attacks would score a forecaster on
    #: police success.
    FOILED = "foiled"


class ExclusionReason(StrEnum):
    """Why a candidate incident is not a target outcome.

    Named rather than collapsed into a boolean so that a rejected incident can
    be audited, and so an evaluation can report what the corpus was mostly made
    of. Most reporting that mentions violence falls into one of these.
    """

    PROTEST = "protest"
    ORDINARY_CRIME = "ordinary_crime"
    ARREST = "arrest"
    ARMS_RECOVERY = "arms_recovery"
    #: Rhetoric, threats and inflammatory speech without an act.
    RHETORIC_OR_THREAT = "rhetoric_or_threat"
    ACCIDENTAL_EXPLOSION = "accidental_explosion"
    MILITARY_TRAINING_OR_DISPOSAL = "military_training_or_disposal"
    #: An armed clash between state forces and an insurgent group initiated by
    #: the state. Recorded as context, not as an attack outcome.
    SECURITY_OPERATION = "security_operation"
    COURT_OR_INVESTIGATION_UPDATE = "court_or_investigation_update"
    #: Outside India, or outside the forecast horizon.
    OUT_OF_SCOPE = "out_of_scope"


class MotivationEvidence(StrEnum):
    """What may establish political motivation. Nothing else does."""

    #: A group claimed responsibility.
    CLAIM_OF_RESPONSIBILITY = "claim_of_responsibility"
    #: NIA, state police or a government body attributed the act.
    OFFICIAL_ATTRIBUTION = "official_attribution"
    #: A court judgment or charge sheet.
    JUDICIAL_FINDING = "judicial_finding"
    #: None of the above. Reporting alone, however confident its wording.
    NONE = "none"


class ExplosiveCause(StrEnum):
    """Why something exploded. An IED attack requires ``ATTRIBUTED_DEVICE``."""

    ATTRIBUTED_DEVICE = "attributed_device"
    ACCIDENTAL = "accidental"
    CRIMINAL_NON_POLITICAL = "criminal_non_political"
    MILITARY_TRAINING_OR_DISPOSAL = "military_training_or_disposal"
    #: Cause not established by any admissible evidence.
    UNRESOLVED = "unresolved"


class Resolution(StrEnum):
    """The label state of a candidate incident."""

    #: A target outcome. Counts toward the positive class.
    POSITIVE = "positive"
    #: Established not to be a target outcome. Counts toward the negative class.
    NEGATIVE = "negative"
    #: Admissible evidence does not settle it. Counts toward NEITHER class and
    #: is excluded from scoring rather than defaulted either way. Defaulting is
    #: how an ambiguous corpus silently becomes a confident one.
    ADJUDICATION_REQUIRED = "adjudication_required"


# --------------------------------------------------------------------------
# Forecast unit, horizon and cutoff
# --------------------------------------------------------------------------

FORECAST_UNIT = "district"
"""The geographic unit. An Indian district, by stable identifier -- never by
name, because names are reused, renamed and split."""

HORIZON_DAYS = 30
"""Rolling: the window is ``(cutoff, cutoff + 30 days]``, recomputed at every
cutoff. Not a fixed calendar month, and not an ambiguous "within 30 days"."""

PRIMARY_OUTPUT = "binary_occurrence"
"""P(at least one qualifying incident in the district during the window).

Binary rather than a count because the count distribution over districts is
dominated by zeros and a handful of heavy districts, so a count model's apparent
skill comes almost entirely from predicting zero. Counts and severity are
recorded as secondary outputs and are not the scored quantity."""


class ForecastWindow(PramaanModel):
    """The exact interval a forecast covers, half-open on the cutoff side."""

    cutoff_at: UtcDatetime
    horizon_days: int = Field(default=HORIZON_DAYS, gt=0)

    @property
    def start(self) -> datetime:
        return self.cutoff_at

    @property
    def end(self) -> datetime:
        return self.cutoff_at + timedelta(days=self.horizon_days)

    def contains(self, moment: datetime) -> bool:
        """``(cutoff, cutoff + horizon]``.

        Open at the cutoff: an incident at exactly the cutoff instant has
        already happened and is evidence, not outcome.
        """
        return self.start < moment <= self.end


CUTOFF_SEMANTICS = (
    "A forecast at cutoff T may use evidence whose availability instant is <= T, "
    "and nothing else. Availability is first_observed_at, not publication time and "
    "not event time: a document published before T but not retrievable until after "
    "it could not have informed a forecast made at T. Outcomes are read only after "
    "forecasts for T are committed and hashed."
)


# --------------------------------------------------------------------------
# Incident identity
# --------------------------------------------------------------------------

INCIDENT_DATE_TOLERANCE_DAYS = 1
"""Two reports of the same class in the same district within this many days are
the same incident unless an adjudicator splits them. One day, not three: attacks
in a district on consecutive days are usually distinct, and merging them would
suppress the very clustering the model is meant to detect."""


class IncidentKey(PramaanModel):
    """The tuple that decides incident identity before adjudication."""

    target_class: TargetClass
    completion: Completion
    district_id: str
    occurred_on: date

    def same_incident_as(self, other: IncidentKey) -> bool:
        """Whether two keys denote one real-world incident.

        Class, completion and district must match exactly; dates may differ by
        :data:`INCIDENT_DATE_TOLERANCE_DAYS` because reports disagree about when
        something happened, especially across midnight and across time zones.
        """
        if (self.target_class, self.completion, self.district_id) != (
            other.target_class,
            other.completion,
            other.district_id,
        ):
            return False
        gap = abs((self.occurred_on - other.occurred_on).days)
        return gap <= INCIDENT_DATE_TOLERANCE_DAYS

    def incident_id(self) -> str:
        """Stable, content-derived identity for one real-world incident."""
        return stable_id(
            "inc",
            self.target_class.value,
            self.completion.value,
            self.district_id,
            self.occurred_on.isoformat(),
        )


class IncidentReport(PramaanModel):
    """One source's account of an incident. Never itself an outcome."""

    report_id: str
    observation_id: str
    source_id: str
    #: When this account became available. Used for cutoff enforcement.
    first_observed_at: UtcDatetime


class Incident(VersionedModel):
    """One deduplicated real-world incident: the unit a target outcome is.

    ``reports`` may hold twenty accounts of one bombing. They attach here; they
    do not increment anything. ``supporting_report_count`` is descriptive and is
    never the outcome.
    """

    incident_id: str
    key: IncidentKey
    resolution: Resolution
    motivation_evidence: MotivationEvidence = MotivationEvidence.NONE
    explosive_cause: ExplosiveCause | None = None
    exclusion: ExclusionReason | None = None
    reports: tuple[IncidentReport, ...] = ()
    #: Free text from the adjudicator. Never parsed by anything.
    rationale: str = ""

    @model_validator(mode="after")
    def _resolution_is_consistent(self) -> Incident:
        if self.resolution is Resolution.NEGATIVE and self.exclusion is None:
            raise ValueError(
                f"{self.incident_id} is negative but names no exclusion reason. "
                "A rejection nobody can audit is indistinguishable from an oversight."
            )
        if self.resolution is Resolution.POSITIVE:
            if self.exclusion is not None:
                raise ValueError(
                    f"{self.incident_id} is positive and also excluded as "
                    f"{self.exclusion.value}; one of the two is wrong"
                )
            if self.motivation_evidence is MotivationEvidence.NONE:
                raise ValueError(
                    f"{self.incident_id} is a positive target with no motivation "
                    "evidence. Political motivation is established by a claim, an "
                    "official attribution or a judicial finding -- never by reporting "
                    "language or an event code."
                )
        return self

    @property
    def supporting_report_count(self) -> int:
        """Descriptive only. Twenty reports of one bombing is still one target."""
        return len(self.reports)

    @property
    def counts_as_outcome(self) -> bool:
        return self.resolution is Resolution.POSITIVE

    @property
    def scoreable(self) -> bool:
        """Adjudication-required incidents are excluded from scoring entirely."""
        return self.resolution is not Resolution.ADJUDICATION_REQUIRED


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


class ClassificationInput(PramaanModel):
    """What a classifier may look at. Deliberately not free text."""

    proposed_class: TargetClass | None = None
    completion: Completion = Completion.COMPLETED
    motivation_evidence: MotivationEvidence = MotivationEvidence.NONE
    explosive_cause: ExplosiveCause | None = None
    #: Set when the reporting describes something in the exclusion list.
    observed_exclusion: ExclusionReason | None = None


class ClassificationResult(PramaanModel):
    resolution: Resolution
    target_class: TargetClass | None = None
    exclusion: ExclusionReason | None = None
    reason: str


def classify(candidate: ClassificationInput) -> ClassificationResult:
    """Apply the contract to one candidate incident.

    The order of the checks is the contract. Exclusions are applied before
    motivation, so an arrest with an official attribution is still an arrest.
    """
    if candidate.observed_exclusion is not None:
        return ClassificationResult(
            resolution=Resolution.NEGATIVE,
            exclusion=candidate.observed_exclusion,
            reason=(
                f"excluded as {candidate.observed_exclusion.value}: this is not an "
                "attack outcome regardless of how it was reported or attributed"
            ),
        )

    if candidate.proposed_class is None:
        return ClassificationResult(
            resolution=Resolution.ADJUDICATION_REQUIRED,
            reason="no target class proposed; a human must decide what this is",
        )

    if candidate.completion is Completion.FOILED:
        return ClassificationResult(
            resolution=Resolution.NEGATIVE,
            exclusion=ExclusionReason.ARREST,
            reason=(
                "prevented before initiation. Recorded, but never a positive target: "
                "counting foiled plots would score the forecaster on police success"
            ),
        )

    if candidate.proposed_class is TargetClass.IED_ATTACK:
        cause = candidate.explosive_cause
        if cause is None or cause is ExplosiveCause.UNRESOLVED:
            return ClassificationResult(
                resolution=Resolution.ADJUDICATION_REQUIRED,
                reason=(
                    "explosive incident with unresolved cause. Gas cylinders, quarry "
                    "accidents and ordnance disposal all explode; an unresolved "
                    "explosion is neither a positive nor a negative until adjudicated"
                ),
            )
        if cause is not ExplosiveCause.ATTRIBUTED_DEVICE:
            return ClassificationResult(
                resolution=Resolution.NEGATIVE,
                exclusion=(
                    ExclusionReason.ACCIDENTAL_EXPLOSION
                    if cause is ExplosiveCause.ACCIDENTAL
                    else ExclusionReason.MILITARY_TRAINING_OR_DISPOSAL
                    if cause is ExplosiveCause.MILITARY_TRAINING_OR_DISPOSAL
                    else ExclusionReason.ORDINARY_CRIME
                ),
                reason=f"explosive cause established as {cause.value}",
            )

    if candidate.motivation_evidence is MotivationEvidence.NONE:
        return ClassificationResult(
            resolution=Resolution.ADJUDICATION_REQUIRED,
            reason=(
                "no claim of responsibility, official attribution or judicial finding. "
                "Political motivation is not inferable from an event code or from how "
                "an article is worded"
            ),
        )

    return ClassificationResult(
        resolution=Resolution.POSITIVE,
        target_class=candidate.proposed_class,
        reason=(
            f"{candidate.proposed_class.value}, {candidate.completion.value}, "
            f"motivation established by {candidate.motivation_evidence.value}"
        ),
    )


# --------------------------------------------------------------------------
# Forecast output
# --------------------------------------------------------------------------


class AbstentionReason(StrEnum):
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_CONFORMING_LABELS = "no_conforming_labels"
    UNCALIBRATED = "uncalibrated"


class DistrictForecast(VersionedModel):
    """The contract's output for one district, one class, one window."""

    district_id: str
    target_class: TargetClass
    window: ForecastWindow
    #: The scored quantity: P(>= 1 qualifying incident in the window).
    probability: Probability | None = None
    interval_lower: Probability | None = None
    interval_upper: Probability | None = None
    #: Secondary, recorded but never scored as the primary metric.
    expected_incident_count: float | None = Field(default=None, ge=0.0)
    abstained: bool = False
    abstention_reason: AbstentionReason | None = None
    contract_version: str = CONTRACT_VERSION

    @model_validator(mode="after")
    def _abstention_carries_no_number(self) -> DistrictForecast:
        if self.abstained:
            if self.abstention_reason is None:
                raise ValueError(f"{self.district_id} abstained without naming a reason")
            if self.probability is not None:
                raise ValueError(
                    f"{self.district_id} abstained but still returned a probability. "
                    "An abstention with a number attached is a forecast."
                )
        elif self.probability is None:
            raise ValueError(f"{self.district_id} neither abstained nor produced a probability")
        return self


# --------------------------------------------------------------------------
# Gold labels: what two human verifiers will verify
# --------------------------------------------------------------------------


class VerifierDecision(PramaanModel):
    """One human verifier's independent judgement of one candidate incident.

    Recorded before the verifiers see each other's work. The schema is frozen
    now, ahead of annotation, so that the questions asked of the two verifiers
    cannot drift once labelling starts.
    """

    verifier_id: str
    decided_at: UtcDatetime
    resolution: Resolution
    target_class: TargetClass | None = None
    completion: Completion | None = None
    motivation_evidence: MotivationEvidence = MotivationEvidence.NONE
    explosive_cause: ExplosiveCause | None = None
    exclusion: ExclusionReason | None = None
    district_id: str | None = None
    occurred_on: date | None = None
    rationale: str = ""
    #: True when the verifier could not decide from the evidence shown. Not a
    #: failure: it is the answer the adjudication state exists to record.
    could_not_decide: bool = False


class DualAdjudication(VersionedModel):
    """Two independent decisions and their reconciliation.

    Agreement is computed per field rather than overall, because two verifiers
    who agree an incident is positive but disagree on its district disagree
    about something that matters to a district-level forecast.
    """

    incident_id: str
    first: VerifierDecision
    second: VerifierDecision
    #: Set only by a third adjudicator, and only where the two disagreed.
    final: VerifierDecision | None = None

    @model_validator(mode="after")
    def _verifiers_are_distinct(self) -> DualAdjudication:
        if self.first.verifier_id == self.second.verifier_id:
            raise ValueError(
                f"{self.incident_id} was verified twice by {self.first.verifier_id}. "
                "Two independent decisions require two people."
            )
        return self

    def disagreements(self) -> tuple[str, ...]:
        """Fields on which the two verifiers differ."""
        fields = (
            "resolution",
            "target_class",
            "completion",
            "motivation_evidence",
            "explosive_cause",
            "exclusion",
            "district_id",
            "occurred_on",
        )
        return tuple(
            name for name in fields if getattr(self.first, name) != getattr(self.second, name)
        )

    @property
    def agreed(self) -> bool:
        return not self.disagreements()

    @property
    def resolved(self) -> bool:
        """Whether this incident has a usable label."""
        return self.agreed or self.final is not None


# --------------------------------------------------------------------------
# Conformance
# --------------------------------------------------------------------------

NON_CONFORMING_PATHS: dict[str, str] = {
    "base_rate/event_mention": (
        "The base-rate generator counts EventMention rows derived one-to-one from "
        "GDELT CAMEO codes. Those are undeduplicated article-derived mentions over a "
        "protest/demand/coerce/assault ontology, not deduplicated incidents over the "
        "target classes. Twenty articles about one incident become twenty counted "
        "events. This path may not issue contract forecasts, and its counts must not "
        "be relabelled as incidents to make it conform."
    ),
}
"""Paths that exist and work but may not issue a contract forecast.

Listed rather than deleted: the base-rate generator is still the M0 floor and
still runs in the synthetic demo, which is a mechanism exercise and not a
contract forecast. What it may not do is produce a number that claims to be a
probability of a terrorist incident.
"""


class NonConformingPathError(RuntimeError):
    """Raised when a non-conforming path is asked for a contract forecast."""


def assert_conforming(path: str) -> None:
    """Refuse a contract forecast from a path the contract does not admit."""
    reason = NON_CONFORMING_PATHS.get(path)
    if reason is not None:
        raise NonConformingPathError(f"{path} may not issue a contract forecast. {reason}")


def contract_fingerprint() -> dict[str, object]:
    """Everything a change to which changes what is being predicted."""
    return {
        "contract_version": CONTRACT_VERSION,
        "target_classes": sorted(item.value for item in TargetClass),
        "completions": sorted(item.value for item in Completion),
        "exclusions": sorted(item.value for item in ExclusionReason),
        "motivation_evidence": sorted(item.value for item in MotivationEvidence),
        "explosive_causes": sorted(item.value for item in ExplosiveCause),
        "resolutions": sorted(item.value for item in Resolution),
        "forecast_unit": FORECAST_UNIT,
        "horizon_days": HORIZON_DAYS,
        "primary_output": PRIMARY_OUTPUT,
        "incident_date_tolerance_days": INCIDENT_DATE_TOLERANCE_DAYS,
        "cutoff_semantics": CUTOFF_SEMANTICS,
        "non_conforming_paths": sorted(NON_CONFORMING_PATHS),
    }


def contract_hash() -> str:
    return hash_object(contract_fingerprint())


def build_incident(
    key: IncidentKey,
    candidate: ClassificationInput,
    reports: Sequence[IncidentReport] = (),
    *,
    rationale: str = "",
) -> Incident:
    """Classify a candidate and assemble the incident it resolves to."""
    result = classify(candidate)
    return Incident(
        incident_id=key.incident_id(),
        key=key,
        resolution=result.resolution,
        motivation_evidence=candidate.motivation_evidence,
        explosive_cause=candidate.explosive_cause,
        exclusion=result.exclusion,
        reports=tuple(reports),
        rationale=rationale or result.reason,
    )
