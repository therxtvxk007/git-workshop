"""Turning observations into event mentions.

Two paths, because the sources are two kinds of thing.

:mod:`pramaanx.extraction.structured`
    Sources that arrive already coded -- the synthetic world's JSON, GDELT's
    event rows. A deterministic mapping, no model, no ambiguity.

:mod:`pramaanx.extraction.cascade`
    Running text. Independent stages behind one protocol, joined by a consensus
    step that marks contested fields unresolved instead of voting them away.
    :class:`~pramaanx.extraction.cascade.PatternStage` ships and works; the
    learned stages (a span tagger, an event-type classifier, a constrained LLM
    verifier) implement the same protocol and are deliberately absent until they
    can be scored against a gold set.

:mod:`pramaanx.extraction.gold`
    What makes that scoring possible: audited gold sets that refuse to exist
    without provenance, and a field-level error taxonomy so that "worse at
    dates" is a measurement rather than an impression.
"""

from __future__ import annotations

from pramaanx.extraction.cascade import (
    FUTURE_CAPABLE_MODALITIES,
    MIN_CANDIDATE_CONFIDENCE,
    BaseStage,
    ExtractionCascade,
    ExtractionStage,
    MentionCandidate,
    PatternStage,
    prose_extractor,
    register_prose_source,
    resolve_text,
)
from pramaanx.extraction.gold import (
    DATE_TOLERANCE,
    FIELD_DEFECTS,
    Defect,
    DefectKind,
    ExtractionScore,
    GoldMention,
    GoldSet,
    score_extraction,
)
from pramaanx.extraction.prose import (
    DENIAL_CUES,
    EVENT_TRIGGERS,
    PLANNED_CUES,
    POSSIBLE_CUES,
    detect_event_types,
    detect_modality,
    extract_date,
    extract_location,
    extract_proper_names,
    split_sentences,
)
from pramaanx.extraction.structured import (
    CAMEO_ROOT_TYPES,
    EXTRACTORS,
    ExtractionError,
    extract_mentions,
    mentions_for_cutoff,
)

__all__ = [
    "CAMEO_ROOT_TYPES",
    "DATE_TOLERANCE",
    "DENIAL_CUES",
    "EVENT_TRIGGERS",
    "EXTRACTORS",
    "FIELD_DEFECTS",
    "FUTURE_CAPABLE_MODALITIES",
    "MIN_CANDIDATE_CONFIDENCE",
    "PLANNED_CUES",
    "POSSIBLE_CUES",
    "BaseStage",
    "Defect",
    "DefectKind",
    "ExtractionCascade",
    "ExtractionError",
    "ExtractionScore",
    "ExtractionStage",
    "GoldMention",
    "GoldSet",
    "MentionCandidate",
    "PatternStage",
    "detect_event_types",
    "detect_modality",
    "extract_date",
    "extract_location",
    "extract_mentions",
    "extract_proper_names",
    "mentions_for_cutoff",
    "prose_extractor",
    "register_prose_source",
    "resolve_text",
    "score_extraction",
    "split_sentences",
]
