"""The deterministic stage, end to end: an article in, grounded spans out.

What this stage is *for* is worth stating plainly, because it is easy to
mistake for a weaker version of the LLM stage. It is not. It is the thing that
makes the LLM stage checkable.

An LLM asked to extract events from an article can invent a location, an actor,
a date, or a quotation, and its output will be well-formed and plausible either
way. The only defence is to require every claim to cite a span, and to check
those spans against text the model did not produce. That check is worth exactly
as much as the offsets are exact -- which is why this module refuses to emit a
result whose spans do not slice the original, rather than emitting one with a
warning.

Two admissibility rules, and they are different:

* the **article** is admissible only when ``first_resolvable_at <= cutoff``.
  Enforced here, on the record, before any text is read.
* the **content** may describe anything, including the future. Not enforced,
  because "forces will be deployed next week" is legitimate anticipatory
  reporting and discarding it would remove the most forecast-relevant sentences
  in the corpus.

Licence compliance needs no special handling here, which is the payoff from
WP1's design: the pipeline reads only ``headline`` and ``body_text``, and those
already contain exactly what the source's licence permitted to be retained. A
hash-only article therefore yields a result with no spans rather than a
licensing incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pramaanx.ingest.article_content import ArticleRecord
from pramaanx.nlp.actors import ActorAliasRegistry, extract_actor_mentions
from pramaanx.nlp.language import LanguageDetector, assess_language
from pramaanx.nlp.locations import DistrictResolver, extract_location_mentions
from pramaanx.nlp.normalize import normalise, original_text_hash
from pramaanx.nlp.ordinary_crime import assess_ordinary_crime
from pramaanx.nlp.quotes import extract_quotations
from pramaanx.nlp.retrospective import find_retrospective_spans
from pramaanx.nlp.schemas import (
    PIPELINE_VERSION,
    CrimeVerdict,
    DeterministicNlpResult,
    LanguageAssessment,
    OrdinaryCrimeAssessment,
    TextSpan,
)
from pramaanx.nlp.script import SCRIPT_UNKNOWN, dominant_script
from pramaanx.nlp.sentence import segment_sentences
from pramaanx.nlp.temporal import anchor_for, extract_temporal_mentions
from pramaanx.nlp.transliterate import can_transliterate, transliterate

#: Separator between headline and body in the assembled document. Two newlines,
#: so the sentence segmenter treats the headline as its own unit -- a headline
#: is not the first sentence of the body, and merging them produces a sentence
#: that no span can sensibly quote.
HEADLINE_SEPARATOR = "\n\n"


class CutoffViolationError(ValueError):
    """An article was submitted that the cutoff does not admit."""


class SpanIntegrityError(ValueError):
    """A produced span does not slice the original text it claims to."""


@dataclass(frozen=True)
class NlpOptions:
    """Everything injectable, so nothing is reached for implicitly.

    Each default is the inert one: no district resolver, no actor aliases, no
    statistical language backend. A pipeline run with defaults produces
    unresolved locations and no actors, which is visibly incomplete -- as
    opposed to quietly approximate.
    """

    resolver: DistrictResolver | None = None
    #: A factory rather than ``EMPTY_REGISTRY`` directly: a Pydantic model is
    #: mutable, and a shared default instance is one ``aliases`` assignment away
    #: from leaking one caller's actor table into every other caller's run.
    actor_registry: ActorAliasRegistry = field(default_factory=ActorAliasRegistry)
    language_detector: LanguageDetector | None = None
    transliterate_enabled: bool = True


def document_text(record: ArticleRecord) -> tuple[str, TextSpan | None, TextSpan | None]:
    """Assemble the readable text of ``record`` and locate its parts.

    Returns the document plus the spans of the headline and body within it, so
    a consumer can tell which field a piece of evidence came from. Both may be
    ``None``: a licence that retained neither leaves an empty document, and that
    is a legitimate state rather than an error.
    """
    parts: list[str] = []
    headline_span: TextSpan | None = None
    body_span: TextSpan | None = None

    if record.headline:
        parts.append(record.headline)
    if record.body_text:
        if parts:
            parts.append(HEADLINE_SEPARATOR)
        parts.append(record.body_text)

    text = "".join(parts)
    if record.headline:
        headline_span = TextSpan.over(text, 0, len(record.headline))
    if record.body_text:
        start = len(text) - len(record.body_text)
        body_span = TextSpan.over(text, start, len(text))
    return text, headline_span, body_span


def _empty_assessment(backend: str) -> LanguageAssessment:
    return LanguageAssessment(
        language_code=None,
        script_codes=(),
        confidence=None,
        ambiguous=False,
        backend=backend,
        backend_version=PIPELINE_VERSION,
    )


def _candidate_spans(
    sentences: tuple[TextSpan, ...],
    signal_offsets: tuple[int, ...],
) -> tuple[TextSpan, ...]:
    """Sentences carrying at least one extracted signal, in document order.

    These are what a downstream extractor -- GLiNER, or an LLM verification
    stage -- is asked to look at. Passing whole sentences rather than the
    matched fragments matters: a model asked to confirm "Kishtwar" in isolation
    has no way to tell an incident from a weather report, and one given the
    sentence does.
    """
    if not sentences:
        return ()
    chosen = [
        sentence
        for sentence in sentences
        if any(sentence.start <= offset < sentence.end for offset in signal_offsets)
    ]
    return tuple(chosen)


def run_deterministic_nlp(
    record: ArticleRecord,
    *,
    cutoff: datetime,
    options: NlpOptions | None = None,
) -> DeterministicNlpResult:
    """Process one article, or refuse it.

    Refuses when ``record.first_resolvable_at > cutoff``. That check is first,
    before any text is touched, so that a post-cutoff article cannot influence
    anything at all -- not a language statistic, not a cache entry, not a
    timing signal.
    """
    if cutoff.tzinfo is None:
        raise CutoffViolationError("run_deterministic_nlp requires a timezone-aware cutoff")
    moment = cutoff.astimezone(UTC)

    if not record.usable_at(moment):
        raise CutoffViolationError(
            f"{record.observation_id} first became resolvable at "
            f"{record.first_resolvable_at.isoformat()}, after the cutoff "
            f"{moment.isoformat()}. An article the forecaster could not have read must not "
            "reach the deterministic stage, however harmless the processing looks."
        )

    settings = options or NlpOptions()
    text, headline_span, body_span = document_text(record)
    anchor = anchor_for(record.published_at, record.first_resolvable_at)

    if not text.strip():
        # A hash-only or metadata-stripped article. Still a result: something
        # was published, and dropping it would bias coverage towards the
        # sources whose licences happen to be permissive.
        return DeterministicNlpResult(
            observation_id=record.observation_id,
            source_id=record.source_id,
            cutoff_at=moment,
            first_resolvable_at=record.first_resolvable_at,
            published_at=record.published_at,
            modified_at=record.modified_at,
            retrieved_at=record.retrieved_at,
            text_available=False,
            original_text_hash=original_text_hash(text),
            language=_empty_assessment("no_text"),
            ordinary_crime_assessment=OrdinaryCrimeAssessment(
                verdict=CrimeVerdict.INSUFFICIENT_EVIDENCE,
                reason=(
                    "the source's licence retained no readable text, so no screen could run. "
                    "Retained as evidence that an article was published."
                ),
            ),
            alias_version=settings.actor_registry.alias_version,
            source_snapshot_hash=record.snapshot_hash,
        )

    language = assess_language(
        text,
        detector=settings.language_detector,
        declared_language=record.original_language,
    )
    normalized_view = normalise(text)

    transliterated_view = None
    script = dominant_script(text)
    if settings.transliterate_enabled and script != SCRIPT_UNKNOWN and can_transliterate(script):
        transliterated_view = transliterate(text, script_code=script)

    sentences = segment_sentences(text)
    temporal = extract_temporal_mentions(text, anchor=anchor)
    locations = extract_location_mentions(
        text, as_of=moment, resolver=settings.resolver, language=language.language_code
    )
    actors = extract_actor_mentions(text, registry=settings.actor_registry, as_of=moment)
    quotes = extract_quotations(text, actor_mentions=actors)
    retrospective = find_retrospective_spans(text)
    crime = assess_ordinary_crime(text)

    signals = tuple(
        sorted(
            {mention.span.start for mention in temporal}
            | {mention.span.start for mention in locations}
            | {mention.span.start for mention in actors}
            | {span.start for span in crime.target_family_spans}
            | {quote.quote_span.start for quote in quotes}
        )
    )

    result = DeterministicNlpResult(
        observation_id=record.observation_id,
        source_id=record.source_id,
        cutoff_at=moment,
        first_resolvable_at=record.first_resolvable_at,
        published_at=record.published_at,
        modified_at=record.modified_at,
        retrieved_at=record.retrieved_at,
        text_available=True,
        original_text_hash=original_text_hash(text),
        language=language,
        normalized_view=normalized_view,
        transliterated_view=transliterated_view,
        headline_span=headline_span,
        body_span=body_span,
        sentence_spans=sentences,
        temporal_mentions=temporal,
        location_mentions=locations,
        actor_mentions=actors,
        quoted_statements=quotes,
        retrospective_spans=retrospective,
        ordinary_crime_assessment=crime,
        candidate_spans=_candidate_spans(sentences, signals),
        alias_version=settings.actor_registry.alias_version,
        source_snapshot_hash=record.snapshot_hash,
    )

    failures = result.verify_spans(text)
    if failures:
        raise SpanIntegrityError(
            f"{record.observation_id}: {len(failures)} span(s) do not slice the original "
            f"text: {', '.join(failures[:8])}. A span that does not resolve is not evidence, "
            "and emitting one would silently break every downstream verification that "
            "depends on it."
        )
    return result


def run_batch(
    records: tuple[ArticleRecord, ...],
    *,
    cutoff: datetime,
    options: NlpOptions | None = None,
    skip_inadmissible: bool = True,
) -> tuple[DeterministicNlpResult, ...]:
    """Process many articles, in an order that does not depend on the input's.

    Results are sorted by ``observation_id``, so shuffling the input produces a
    byte-identical batch. ``skip_inadmissible`` drops post-cutoff records rather
    than raising, which is what a backtest wants when replaying a mixed corpus;
    the strict single-record path still refuses them.
    """
    processed: dict[str, DeterministicNlpResult] = {}
    for record in sorted(records, key=lambda item: item.observation_id):
        if skip_inadmissible and not record.usable_at(cutoff.astimezone(UTC)):
            continue
        if record.observation_id in processed:
            # The same observation supplied twice is one observation. Article
            # ids are content-derived, so a repeat is a re-delivery of identical
            # bytes -- and letting it through twice would inflate every count
            # built on the batch, which is the wire-copy failure WP1 exists to
            # prevent reappearing one stage later.
            continue
        processed[record.observation_id] = run_deterministic_nlp(
            record, cutoff=cutoff, options=options
        )
    return tuple(sorted(processed.values(), key=lambda result: result.observation_id))


def batch_hash(results: tuple[DeterministicNlpResult, ...]) -> str:
    """One hash over a whole batch, for reproducibility assertions."""
    from pramaanx.hashing import hash_object

    return hash_object([result.output_hash for result in results])
