"""Optional GLiNER-assisted actor and location candidate generation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from pramaanx.extraction.cascade import BaseStage, MentionCandidate
from pramaanx.extraction.prose import detect_event_types, detect_modality, split_sentences
from pramaanx.schemas.base import PramaanModel
from pramaanx.schemas.observation import Observation

ENTITY_LABELS = (
    "armed group",
    "security force",
    "political organization",
    "person",
    "district",
    "city",
    "state",
    "target",
)
ACTOR_LABELS = frozenset({"armed group", "security force", "political organization", "person"})
LOCATION_LABELS = frozenset({"district", "city", "state"})


class SpanEntity(PramaanModel):
    text: str
    label: str
    score: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class GLiNERBackend(Protocol):
    model_version: str

    def predict(self, text: str, labels: Sequence[str]) -> Sequence[SpanEntity]: ...


class LiveGLiNERBackend:
    """Lazy model loader; importing PRAMAAN-X never downloads model weights."""

    def __init__(self, model_name: str) -> None:
        self.model_version = model_name
        self._model: Any = None

    def predict(self, text: str, labels: Sequence[str]) -> Sequence[SpanEntity]:
        if self._model is None:
            try:
                from gliner import GLiNER
            except ImportError as error:  # pragma: no cover - optional live dependency
                raise RuntimeError("GLiNER extraction requires the 'nlp' project extra") from error
            self._model = GLiNER.from_pretrained(self.model_version)
        raw = self._model.predict_entities(text, list(labels))
        return [
            SpanEntity(text=item["text"], label=item["label"], score=float(item["score"]))
            for item in raw
        ]


class GLiNERStage(BaseStage):
    """Use GLiNER for spans and deterministic rules for event types."""

    name = "gliner"
    VERSION = "0.1.0"

    def __init__(self, backend: GLiNERBackend, *, min_score: float = 0.35) -> None:
        super().__init__(min_score=min_score)
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score must be between zero and one")
        self.backend = backend
        self.min_score = min_score

    @property
    def version(self) -> str:
        return f"{self.name}@{self.VERSION}:{self.backend.model_version}"

    def propose(self, observation: Observation, text: str) -> Sequence[MentionCandidate]:
        del observation
        entities = [
            entity
            for entity in self.backend.predict(text, ENTITY_LABELS)
            if entity.score >= self.min_score
        ]
        candidates: list[MentionCandidate] = []
        for sentence in split_sentences(text):
            event_types = detect_event_types(sentence)
            if not event_types:
                continue
            sentence_entities = [
                entity for entity in entities if entity.text.casefold() in sentence.casefold()
            ]
            actors = [entity for entity in sentence_entities if entity.label in ACTOR_LABELS]
            locations = [entity for entity in sentence_entities if entity.label in LOCATION_LABELS]
            targets = [entity for entity in sentence_entities if entity.label == "target"]
            confidence_values = [entity.score for entity in sentence_entities]
            confidence = (
                sum(confidence_values) / len(confidence_values) if confidence_values else 0.35
            )
            explicit = {"event_type"}
            if actors:
                explicit.add("subject")
            if locations:
                explicit.add("location")
            if targets:
                explicit.add("object")
            for event_type in event_types:
                candidates.append(
                    MentionCandidate(
                        stage_name=self.name,
                        span=sentence[:512],
                        event_type=event_type,
                        subject=actors[0].text if actors else None,
                        object=targets[0].text if targets else None,
                        location_text=locations[0].text if locations else None,
                        modality=detect_modality(sentence),
                        confidence=confidence,
                        explicit_fields=explicit,
                    )
                )
        return candidates
