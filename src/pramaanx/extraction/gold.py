"""Gold sets and the extraction error taxonomy.

A learned extraction stage cannot be justified by looking at its output and
finding it plausible. It needs a manually audited gold set and an error
taxonomy, so that "the cascade improved" is a statement about a measured
quantity and "it got worse at dates" is a thing anybody can check.

This module ships the machinery, not the data. A gold set is human labour with
provenance -- who annotated it, against which guidelines, on which corpus -- and
:class:`GoldSet` refuses to be constructed without that provenance. An
unattributed gold set is indistinguishable from model output somebody forgot
was model output, and once it enters the loop every score computed against it
is circular.

The taxonomy is deliberately field-level. "Precision 0.71" tells you nothing
actionable; "dates are wrong in a third of planned-modality sentences" tells you
what to fix.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel
from pramaanx.schemas.event import EventMention

#: How far a predicted event date may sit from the gold date and still count.
#: Reporting drifts by a day across timezones; two days is generous without
#: being meaningless.
DATE_TOLERANCE = timedelta(days=2)


class DefectKind(StrEnum):
    """What went wrong with one prediction, or one thing that was missed."""

    MISSED = "missed"
    SPURIOUS = "spurious"
    WRONG_EVENT_TYPE = "wrong_event_type"
    WRONG_SUBJECT = "wrong_subject"
    WRONG_OBJECT = "wrong_object"
    WRONG_LOCATION = "wrong_location"
    WRONG_DATE = "wrong_date"
    WRONG_MODALITY = "wrong_modality"


#: Field-level defects, as opposed to the two whole-mention ones. Kept as a set
#: so that a report can separate "we found the claim but read it wrong" from
#: "we never found the claim", which are different engineering problems.
FIELD_DEFECTS: frozenset[DefectKind] = frozenset(
    {
        DefectKind.WRONG_EVENT_TYPE,
        DefectKind.WRONG_SUBJECT,
        DefectKind.WRONG_OBJECT,
        DefectKind.WRONG_LOCATION,
        DefectKind.WRONG_DATE,
        DefectKind.WRONG_MODALITY,
    }
)


class GoldMention(PramaanModel):
    """One human-audited claim in one observation."""

    observation_id: str
    span: str
    event_type: str
    subject: str | None = None
    object: str | None = None
    location_text: str | None = None
    event_time_start: UtcDatetime | None = None
    modality: str
    #: Set when annotators disagreed and the adjudicator kept the disagreement
    #: rather than forcing a label. Scoring skips the disputed fields, because
    #: an extractor cannot be marked wrong against a truth that does not exist.
    disputed_fields: set[str] = Field(default_factory=set)

    @property
    def key(self) -> tuple[str, str]:
        return (self.observation_id, self.event_type)


class GoldSet(VersionedModel):
    """An audited corpus slice, with the provenance that makes it usable."""

    gold_set_id: str
    #: Free text naming the annotators or the annotating team. Required.
    annotated_by: str
    annotated_at: UtcDatetime
    #: Version of the annotation guidelines these labels follow.
    guidelines_version: str
    #: Observations that were annotated, including those with no mentions --
    #: without them, recall cannot be computed and every empty document looks
    #: like a document nobody checked.
    observation_ids: list[str] = Field(default_factory=list)
    mentions: list[GoldMention] = Field(default_factory=list)
    #: Inter-annotator agreement, when it was measured. ``None`` means it was
    #: not, which is a fact worth carrying rather than a zero to invent.
    agreement: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_provenance(self) -> GoldSet:
        if not self.annotated_by.strip():
            raise ValueError("a gold set must record who annotated it")
        if not self.guidelines_version.strip():
            raise ValueError("a gold set must record its guidelines version")
        known = set(self.observation_ids)
        orphans = sorted({m.observation_id for m in self.mentions} - known)
        if orphans:
            raise ValueError(f"gold mentions reference unannotated observations: {orphans[:5]}")
        return self

    def for_observation(self, observation_id: str) -> list[GoldMention]:
        return [m for m in self.mentions if m.observation_id == observation_id]


class Defect(PramaanModel):
    """One scored discrepancy, kept individually so errors can be read."""

    kind: DefectKind
    observation_id: str
    event_type: str
    span: str
    expected: str | None = None
    predicted: str | None = None


class ExtractionScore(PramaanModel):
    """The result of scoring one prediction set against one gold set."""

    gold_set_id: str
    predicted_count: int = Field(ge=0)
    gold_count: int = Field(ge=0)
    matched: int = Field(ge=0)
    defects: list[Defect] = Field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.matched / self.predicted_count if self.predicted_count else 0.0

    @property
    def recall(self) -> float:
        return self.matched / self.gold_count if self.gold_count else 0.0

    @property
    def f1(self) -> float:
        precision, recall = self.precision, self.recall
        if precision + recall <= 0.0:
            return 0.0
        return 2.0 * precision * recall / (precision + recall)

    def defect_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {kind.value: 0 for kind in DefectKind}
        for defect in self.defects:
            counts[defect.kind.value] += 1
        return dict(sorted(counts.items()))

    def field_accuracy(self) -> dict[str, float]:
        """Per-field accuracy over the mentions that were found at all.

        Conditioned on a match on purpose: a field cannot be scored on a claim
        the extractor never located, and folding those in would confound a
        detection failure with a reading failure.
        """
        if not self.matched:
            return {kind.value: 0.0 for kind in sorted(FIELD_DEFECTS, key=lambda k: k.value)}
        counts = self.defect_counts()
        return {
            kind.value: 1.0 - (counts[kind.value] / self.matched)
            for kind in sorted(FIELD_DEFECTS, key=lambda k: k.value)
        }


def _normalise(value: str | None) -> str:
    return (value or "").strip().casefold()


def score_extraction(
    predicted: Sequence[EventMention],
    gold: GoldSet,
    *,
    date_tolerance: timedelta = DATE_TOLERANCE,
) -> ExtractionScore:
    """Score ``predicted`` against ``gold``.

    Matching is on (observation, event type) with a one-to-one greedy pairing in
    deterministic order. Span text is not required to match exactly: two
    extractors can select different sentence boundaries around the same claim,
    and penalising that would measure the sentence splitter rather than the
    extractor.

    Predictions for observations outside the gold set are ignored rather than
    counted as spurious. The gold set makes no claim about what it did not
    annotate, and counting against it would let a small gold set punish an
    extractor for working on documents nobody audited.
    """
    scope = set(gold.observation_ids)
    in_scope = sorted(
        (mention for mention in predicted if mention.observation_id in scope),
        key=lambda item: item.mention_id,
    )

    remaining: dict[tuple[str, str], list[GoldMention]] = {}
    for mention in sorted(gold.mentions, key=lambda item: (item.observation_id, item.span)):
        remaining.setdefault(mention.key, []).append(mention)

    defects: list[Defect] = []
    matched = 0
    for mention in in_scope:
        pool = remaining.get((mention.observation_id, mention.event_type))
        if not pool:
            defects.append(
                Defect(
                    kind=DefectKind.SPURIOUS,
                    observation_id=mention.observation_id,
                    event_type=mention.event_type,
                    span=mention.supporting_span,
                    predicted=mention.event_type,
                )
            )
            continue
        truth = pool.pop(0)
        matched += 1
        defects.extend(_field_defects(mention, truth, date_tolerance=date_tolerance))

    for pool in remaining.values():
        for truth in pool:
            defects.append(
                Defect(
                    kind=DefectKind.MISSED,
                    observation_id=truth.observation_id,
                    event_type=truth.event_type,
                    span=truth.span,
                    expected=truth.event_type,
                )
            )

    defects.sort(key=lambda item: (item.observation_id, item.kind.value, item.span))
    return ExtractionScore(
        gold_set_id=gold.gold_set_id,
        predicted_count=len(in_scope),
        gold_count=len(gold.mentions),
        matched=matched,
        defects=defects,
    )


def _field_defects(
    mention: EventMention, truth: GoldMention, *, date_tolerance: timedelta
) -> list[Defect]:
    """Compare the fields of a matched pair, skipping disputed ones."""
    defects: list[Defect] = []

    def record(kind: DefectKind, expected: str | None, predicted: str | None) -> None:
        defects.append(
            Defect(
                kind=kind,
                observation_id=truth.observation_id,
                event_type=truth.event_type,
                span=truth.span,
                expected=expected,
                predicted=predicted,
            )
        )

    comparisons: tuple[tuple[str, DefectKind, str | None, str | None], ...] = (
        ("subject", DefectKind.WRONG_SUBJECT, truth.subject, mention.subject),
        ("object", DefectKind.WRONG_OBJECT, truth.object, mention.object),
        ("location", DefectKind.WRONG_LOCATION, truth.location_text, mention.location_text),
        ("modality", DefectKind.WRONG_MODALITY, truth.modality, mention.modality),
    )
    for field, kind, expected, predicted in comparisons:
        if field in truth.disputed_fields:
            continue
        if _normalise(expected) != _normalise(predicted):
            record(kind, expected, predicted)

    if "event_time" not in truth.disputed_fields:
        expected_at, predicted_at = truth.event_time_start, mention.event_time_start
        if expected_at is None and predicted_at is not None:
            record(DefectKind.WRONG_DATE, None, predicted_at.isoformat())
        elif expected_at is not None and predicted_at is None:
            record(DefectKind.WRONG_DATE, expected_at.isoformat(), None)
        elif (
            expected_at is not None
            and predicted_at is not None
            and abs(predicted_at - expected_at) > date_tolerance
        ):
            record(DefectKind.WRONG_DATE, expected_at.isoformat(), predicted_at.isoformat())

    return defects
