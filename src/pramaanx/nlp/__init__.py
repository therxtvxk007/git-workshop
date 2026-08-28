"""Deterministic multilingual preprocessing, ahead of anything statistical.

The package answers one question about an article -- *what does it literally
say, and where exactly does it say it* -- and refuses to answer any other. It
assigns no probability, ranks nothing, and makes no judgement about whether an
event will occur. Those belong to models that were trained, evaluated and
calibrated; a preprocessor that scored articles would be an unevaluated model
sitting upstream of the evaluated one, and its influence would never appear in
any metric.

What it produces is the ground an LLM stage can be checked against: spans that
slice the original text exactly, timestamps kept apart from one another, and
explicit ``ambiguous`` and ``unresolved`` states wherever the text does not
determine an answer.

Importing this package loads no model, opens no socket and reads no data file.
Every backend -- a statistical language detector, WP0's district resolver, an
actor alias table -- is injected by the caller through
:class:`~pramaanx.nlp.pipeline.NlpOptions`. That is what keeps the offline test
suite offline, and it is asserted rather than assumed: see
``tests/unit/test_nlp_pipeline.py``.

Scope note. Thirteen languages are *represented*: their scripts are detected,
their text is normalised without damage, segmented, carried through intact and
hashed. Extraction quality is a different claim and a much narrower one. The
temporal, actor, location and ordinary-crime lexicons are English-first, have
been measured on no Indian-language corpus, and must not be described as
working equally across those languages until somebody measures them. See
``docs/integration/wp02_multilingual_nlp.md``.
"""

from __future__ import annotations

from pramaanx.nlp.actors import (
    EMPTY_REGISTRY,
    ActorAlias,
    ActorAliasRegistry,
    AliasKind,
    extract_actor_mentions,
)
from pramaanx.nlp.alignment import AlignmentBuilder, AlignmentError, identity_view
from pramaanx.nlp.language import (
    SUPPORTED_LANGUAGES,
    LanguageDetector,
    ScriptHeuristicDetector,
    assess_language,
)
from pramaanx.nlp.locations import (
    STATES,
    DistrictResolver,
    LocationQuery,
    LocationResolution,
    NullDistrictResolver,
    extract_location_mentions,
)
from pramaanx.nlp.normalize import NORMALIZATION_VERSION, normalise, original_text_hash
from pramaanx.nlp.ordinary_crime import assess_ordinary_crime
from pramaanx.nlp.pipeline import (
    CutoffViolationError,
    NlpOptions,
    SpanIntegrityError,
    batch_hash,
    document_text,
    run_batch,
    run_deterministic_nlp,
)
from pramaanx.nlp.quotes import extract_quotations
from pramaanx.nlp.retrospective import find_retrospective_spans, retrospective_kinds
from pramaanx.nlp.schemas import (
    PIPELINE_VERSION,
    ActorMention,
    AlignedTextView,
    AttributionStatus,
    CrimeVerdict,
    DeterministicNlpResult,
    LanguageAssessment,
    LocationMention,
    OrdinaryCrimeAssessment,
    QuotedStatement,
    ResolutionStatus,
    TemporalKind,
    TemporalMention,
    TextSpan,
)
from pramaanx.nlp.script import SCRIPT_UNKNOWN, detect_scripts, dominant_script
from pramaanx.nlp.sentence import segment_sentences
from pramaanx.nlp.temporal import anchor_for, extract_temporal_mentions
from pramaanx.nlp.transliterate import can_transliterate, transliterate

__all__ = [
    "EMPTY_REGISTRY",
    "NORMALIZATION_VERSION",
    "PIPELINE_VERSION",
    "SCRIPT_UNKNOWN",
    "STATES",
    "SUPPORTED_LANGUAGES",
    "ActorAlias",
    "ActorAliasRegistry",
    "ActorMention",
    "AliasKind",
    "AlignedTextView",
    "AlignmentBuilder",
    "AlignmentError",
    "AttributionStatus",
    "CrimeVerdict",
    "CutoffViolationError",
    "DeterministicNlpResult",
    "DistrictResolver",
    "LanguageAssessment",
    "LanguageDetector",
    "LocationMention",
    "LocationQuery",
    "LocationResolution",
    "NlpOptions",
    "NullDistrictResolver",
    "OrdinaryCrimeAssessment",
    "QuotedStatement",
    "ResolutionStatus",
    "ScriptHeuristicDetector",
    "SpanIntegrityError",
    "TemporalKind",
    "TemporalMention",
    "TextSpan",
    "anchor_for",
    "assess_language",
    "assess_ordinary_crime",
    "batch_hash",
    "can_transliterate",
    "detect_scripts",
    "document_text",
    "dominant_script",
    "extract_actor_mentions",
    "extract_location_mentions",
    "extract_quotations",
    "extract_temporal_mentions",
    "find_retrospective_spans",
    "identity_view",
    "normalise",
    "original_text_hash",
    "retrospective_kinds",
    "run_batch",
    "run_deterministic_nlp",
    "segment_sentences",
    "transliterate",
]
