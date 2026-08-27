"""The extraction cascade: running text to :class:`EventMention`.

:mod:`pramaanx.extraction.structured` handles sources that arrive already
coded. This module handles the ones that do not -- humanitarian situation
reports, news wires, prose of any kind -- which is the whole reason extraction
coverage on those sources was zero.

The design is a cascade of independent *stages* behind one protocol, joined by
a consensus step. Three properties are load-bearing:

*Stages are independent.* Each proposes candidates from the text alone. None of
them sees another stage's output, so agreement between two stages is real
corroboration rather than one stage echoing another.

*Consensus preserves disagreement.* When stages disagree about a field, the
field is marked unresolved and the confidence drops; it is never silently
resolved by majority vote. A field that two extractors read differently is a
field the pipeline does not actually know, and
:class:`~pramaanx.schemas.event.EventMention` already has the vocabulary --
``unresolved_fields`` -- to say so.

*The learned stages are absent, not faked.* A GLiNER-style span tagger, an
event-type classifier and a constrained LLM verifier all implement
:class:`ExtractionStage` and slot in without touching anything here. They are
not shipped, because a learned stage without a measured error rate against the
gold set in :mod:`pramaanx.extraction.gold` is an unquantified claim, and this
project's whole argument is that unquantified claims get labelled as such.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from pramaanx.extraction.prose import (
    detect_event_types,
    detect_modality,
    extract_date,
    extract_location,
    extract_proper_names,
    split_sentences,
)
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel
from pramaanx.schemas.event import EventMention
from pramaanx.schemas.observation import Observation

log = get_logger(__name__)

#: Modalities that permit an event date after the observation's availability.
FUTURE_CAPABLE_MODALITIES: frozenset[str] = frozenset({"planned", "possible"})

#: Confidence floor. A candidate below this is dropped rather than emitted as a
#: very uncertain mention: downstream stages weight by probability, and a flood
#: of near-zero mentions costs more in dilution than it gains in recall.
MIN_CANDIDATE_CONFIDENCE = 0.15


class MentionCandidate(PramaanModel):
    """One stage's proposal, before consensus.

    Deliberately not an :class:`EventMention`: a candidate has a stage and a
    confidence and may contradict its neighbours, none of which is true of a
    mention that has survived consensus.
    """

    stage_name: str
    span: str
    event_type: str
    subject: str | None = None
    object: str | None = None
    location_text: str | None = None
    event_time_start: datetime | None = None
    event_time_end: datetime | None = None
    modality: str = "unknown"
    confidence: float = Field(ge=0.0, le=1.0)
    explicit_fields: set[str] = Field(default_factory=set)

    @property
    def group_key(self) -> tuple[str, str]:
        """Candidates sharing this key are proposals about the same claim."""
        return (self.span, self.event_type)


@runtime_checkable
class ExtractionStage(Protocol):
    """Structural contract for a cascade stage."""

    name: str

    def propose(self, observation: Observation, text: str) -> Sequence[MentionCandidate]: ...


class BaseStage(ABC):
    """Convenience base: name and version, recorded on every run."""

    name: str = ""
    VERSION: str = "0.1.0"

    def __init__(self, **options: Any) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define a name")
        self.options = options

    @property
    def version(self) -> str:
        return f"{self.name}@{self.VERSION}"

    @abstractmethod
    def propose(self, observation: Observation, text: str) -> Sequence[MentionCandidate]:
        """Propose candidates from ``text`` alone."""


class PatternStage(BaseStage):
    """Rule-based extraction over sentences.

    One candidate per (sentence, triggered event type). A sentence that trips
    two triggers produces two candidates on purpose -- "the airstrike killed
    twelve" really is a shelling claim and a killing claim, and collapsing them
    would lose one of the two.
    """

    name = "pattern"
    VERSION = "0.1.0"

    def propose(self, observation: Observation, text: str) -> Sequence[MentionCandidate]:
        reference = observation.first_observed_at
        candidates: list[MentionCandidate] = []
        for sentence in split_sentences(text):
            event_types = detect_event_types(sentence)
            if not event_types:
                continue
            modality = detect_modality(sentence)
            allow_future = modality in FUTURE_CAPABLE_MODALITIES
            when = extract_date(sentence, reference=reference, allow_future=allow_future)
            location = extract_location(sentence)
            names = extract_proper_names(sentence, skip=location)
            subject = names[0] if names else None
            obj = names[1] if len(names) > 1 else None

            explicit = {"event_type"}
            if subject:
                explicit.add("subject")
            if location:
                explicit.add("location")
            if when:
                explicit.add("event_time")

            for event_type in event_types:
                candidates.append(
                    MentionCandidate(
                        stage_name=self.name,
                        span=sentence[:512],
                        event_type=event_type,
                        subject=subject,
                        object=obj,
                        location_text=location,
                        event_time_start=when,
                        event_time_end=when,
                        modality=modality,
                        confidence=self._confidence(
                            explicit=explicit,
                            modality=modality,
                            trigger_count=len(event_types),
                        ),
                        explicit_fields=explicit,
                    )
                )
        return candidates

    @staticmethod
    def _confidence(*, explicit: set[str], modality: str, trigger_count: int) -> float:
        """Confidence from how much of the frame was actually filled.

        Starts low and is earned back by resolved fields. A sentence that fired
        a trigger but yielded no actor, no place and no date is a weak claim and
        should score like one, whatever the trigger was.
        """
        score = 0.25
        score += 0.20 if "subject" in explicit else 0.0
        score += 0.15 if "location" in explicit else 0.0
        score += 0.20 if "event_time" in explicit else 0.0
        if modality == "possible":
            score *= 0.7
        elif modality == "denied":
            # A denial is a confident *claim* even though it asserts absence.
            score *= 0.9
        if trigger_count > 2:
            # Many triggers in one sentence usually means a summary paragraph
            # rather than a specific report.
            score *= 0.8
        return float(min(max(score, 0.0), 1.0))


class ExtractionCascade:
    """Runs stages and reconciles their proposals."""

    def __init__(self, stages: Sequence[ExtractionStage] | None = None) -> None:
        self.stages: tuple[ExtractionStage, ...] = tuple(stages or (PatternStage(),))
        if not self.stages:
            raise ValueError("an extraction cascade needs at least one stage")
        names = [stage.name for stage in self.stages]
        duplicates = sorted({name for name, count in Counter(names).items() if count > 1})
        if duplicates:
            raise ValueError(f"duplicate stage names in cascade: {duplicates}")

    @property
    def versions(self) -> dict[str, str]:
        """Stage versions, for the run manifest."""
        return {
            stage.name: getattr(stage, "version", f"{stage.name}@unknown")
            for stage in sorted(self.stages, key=lambda item: item.name)
        }

    def extract(self, observation: Observation, text: str) -> list[EventMention]:
        """Run every stage over ``text`` and reconcile into mentions."""
        if not text or not text.strip():
            return []
        candidates: list[MentionCandidate] = []
        for stage in self.stages:
            candidates.extend(stage.propose(observation, text))
        if not candidates:
            return []
        return _consensus(observation, candidates, stage_count=len(self.stages))


def _consensus(
    observation: Observation,
    candidates: Sequence[MentionCandidate],
    *,
    stage_count: int,
) -> list[EventMention]:
    """Reconcile candidates into mentions, preserving disagreement.

    Two kinds of disagreement are handled differently.

    *Type disagreement* -- stages triggered different event types on the same
    span -- yields one mention per type, each flagging ``event_type`` as
    unresolved. Dropping the minority reading would be a silent choice between
    two readings of the same sentence.

    *Field disagreement* -- stages agree on the type but not on the actor, place
    or date -- yields one mention whose disputed fields are unresolved. The
    surviving value is the most-proposed one, ties broken deterministically, and
    the fact that it was disputed travels with the record.
    """
    by_span: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        by_span[candidate.span].add(candidate.event_type)

    grouped: dict[tuple[str, str], list[MentionCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.group_key].append(candidate)

    mentions: list[EventMention] = []
    for (span, event_type), group in sorted(grouped.items()):
        agreeing_stages = {candidate.stage_name for candidate in group}
        subject, subject_disputed = _reconcile(group, "subject")
        obj, object_disputed = _reconcile(group, "object")
        location, location_disputed = _reconcile(group, "location_text")
        start, start_disputed = _reconcile(group, "event_time_start")
        end, _ = _reconcile(group, "event_time_end")
        modality, modality_disputed = _reconcile(group, "modality")

        explicit: set[str] = set()
        for candidate in group:
            explicit |= candidate.explicit_fields
        unresolved: set[str] = set()
        if subject is None:
            unresolved.add("subject")
        if location is None:
            unresolved.add("location")
        if start is None:
            unresolved.add("event_time")
        if subject_disputed:
            unresolved.add("subject")
        if object_disputed:
            unresolved.add("object")
        if location_disputed:
            unresolved.add("location")
        if start_disputed:
            unresolved.add("event_time")
        if modality_disputed:
            unresolved.add("modality")
        if len(by_span[span]) > 1 and stage_count > 1:
            unresolved.add("event_type")
        # A field cannot be both, and the schema enforces it. Disagreement wins:
        # one stage calling it explicit does not settle what another disputes.
        explicit -= unresolved

        probability = _combine_confidence(
            group, agreeing_stages=len(agreeing_stages), stage_count=stage_count
        )
        if probability < MIN_CANDIDATE_CONFIDENCE:
            continue

        relation = f"participates_in:{event_type}"
        mentions.append(
            EventMention(
                # The event type qualifies the relation so that one sentence
                # triggering two types yields two distinct mention ids. Without
                # the qualifier both would hash to the same id and one would be
                # silently lost on insert.
                mention_id=EventMention.build_id(observation.observation_id, relation, span),
                observation_id=observation.observation_id,
                observed_at=observation.first_observed_at,
                subject=subject,
                relation=relation,
                object=obj,
                event_type=event_type,
                location_text=location,
                event_time_start=start,
                event_time_end=end if end and start and end >= start else start,
                modality=modality or "unknown",
                extraction_probability=probability,
                supporting_span=span,
                explicit_fields=explicit,
                unresolved_fields=unresolved,
            )
        )
    mentions.sort(key=lambda item: item.mention_id)
    return mentions


def _reconcile(group: Sequence[MentionCandidate], field: str) -> tuple[Any, bool]:
    """Pick a field value across stages, reporting whether they disagreed.

    ``None`` is not a vote. A stage that failed to find a date has not
    contradicted a stage that found one; it has abstained, and treating
    abstention as disagreement would mark almost every field disputed the
    moment a second stage joined the cascade.
    """
    values = [getattr(candidate, field) for candidate in group]
    present = [value for value in values if value is not None]
    if not present:
        return None, False
    counts = Counter(present)
    disputed = len(counts) > 1
    chosen = min(sorted(counts, key=str), key=lambda value: (-counts[value], str(value)))
    return chosen, disputed


def _combine_confidence(
    group: Sequence[MentionCandidate], *, agreeing_stages: int, stage_count: int
) -> float:
    """Combine stage confidences into one extraction probability.

    The mean, lifted when independent stages agree. The lift is capped and
    applies only from the second stage onward, so a single-stage cascade cannot
    manufacture corroboration out of one opinion repeated.
    """
    mean = sum(candidate.confidence for candidate in group) / float(len(group))
    if stage_count < 2 or agreeing_stages < 2:
        return float(min(max(mean, 0.0), 1.0))
    lift = min(0.15 * (agreeing_stages - 1), 0.3)
    return float(min(mean + lift, 0.99))


def resolve_text(payload: dict[str, Any], fields: Sequence[str]) -> str:
    """Pull the prose out of a source payload.

    ``fields`` are dotted paths, tried in order and concatenated. Missing paths
    are skipped rather than raising: connectors legitimately omit a summary on
    some records, and a hard failure would take down a whole batch over one
    absent optional field.

    Lists of strings are joined; anything else is stringified only if it is a
    scalar. A dict reached at the end of a path is *not* flattened -- silently
    stringifying a nested object produces text full of braces that then trips
    every trigger in the lexicon.
    """
    chunks: list[str] = []
    for path in fields:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current is None:
            continue
        if isinstance(current, str):
            chunks.append(current)
        elif isinstance(current, list):
            chunks.extend(item for item in current if isinstance(item, str))
        elif isinstance(current, (int, float, bool)):
            chunks.append(str(current))
    return "\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())


def prose_extractor(fields: Sequence[str], cascade: ExtractionCascade | None = None) -> Any:
    """Build an extractor callable compatible with ``structured.EXTRACTORS``.

    Returned rather than registered so that a caller can hold several
    differently configured cascades -- one per source, with different stages --
    without a module-level singleton deciding for everybody.
    """
    engine = cascade or ExtractionCascade()
    resolved_fields = tuple(fields)

    def extract(observation: Observation, payload: dict[str, Any]) -> list[EventMention]:
        return engine.extract(observation, resolve_text(payload, resolved_fields))

    return extract


def register_prose_source(
    source_id: str,
    *,
    fields: Sequence[str],
    cascade: ExtractionCascade | None = None,
    overwrite: bool = False,
) -> None:
    """Register a prose source with the shared extractor table.

    Refuses to replace an existing registration unless ``overwrite`` is set. A
    source silently switching extractor is the kind of change that shows up
    three stages later as a metric moving for no visible reason.
    """
    from pramaanx.extraction import structured

    if source_id in structured.EXTRACTORS and not overwrite:
        raise ValueError(
            f"source {source_id!r} already has an extractor; pass overwrite=True to replace it"
        )
    structured.EXTRACTORS[source_id] = prose_extractor(fields, cascade)
    log.info("extraction.prose_source_registered", source_id=source_id, fields=list(fields))
