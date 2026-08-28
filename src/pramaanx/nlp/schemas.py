"""The typed vocabulary of deterministic multilingual preprocessing.

Every model here exists to keep one promise: **an evidence span resolves to
exact original characters.** Not similar characters, not the same word found
again by searching, not a normalised approximation. Exactly
``original_text[span.start:span.end]``.

That promise is what makes an LLM verifiable later. A model that reports
"the article says a blast occurred in Kishtwar" is unfalsifiable unless the
claim carries offsets into text nobody rewrote. Once normalisation is allowed
to silently shift an offset by one character, every downstream span check
becomes a guess, and the adjudication layer's ability to reject invented
evidence quietly stops working -- while still passing its own tests.

So this package never mutates original text. It produces *views* alongside it,
each carrying an explicit character-level alignment back to the original, and
every span that leaves the pipeline is a span over the original.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict, Field, model_validator

from pramaanx.hashing import hash_object
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel

PIPELINE_VERSION = "nlp-deterministic/1.0.0"
"""Bumped whenever the pipeline's output could change for unchanged input.

Recorded on every result. Two results produced by different pipeline versions
are not comparable, and a backtest that mixes them is measuring the pipeline
as much as the model.
"""


class ResolutionStatus(StrEnum):
    """How far a mention got towards a definite referent.

    Three states, never two. Collapsing ``AMBIGUOUS`` into ``UNRESOLVED`` would
    throw away the candidate list a human or a later stage needs; collapsing it
    into ``RESOLVED`` by picking the first candidate is the single most common
    way a geocoding pipeline invents facts.
    """

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class TextSpan(PramaanModel):
    """A half-open character range over the original article text.

    Carries its own text so that a consumer holding only the span can be
    checked against the source without re-deriving anything. Whenever both are
    available, :meth:`verify_against` is the assertion that matters.
    """

    #: Whitespace stripping is switched off for this model alone.
    #: :class:`~pramaanx.schemas.base.PramaanModel` sets
    #: ``str_strip_whitespace=True``, which is right for names and identifiers
    #: and catastrophic here: a span ending in a space would silently lose it,
    #: the text would then be shorter than the offsets claim, and a span that is
    #: *wrong by one character* still looks like a citation. The validator below
    #: would catch it -- but only because this config stops it happening.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, validate_assignment=True)

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str

    @model_validator(mode="after")
    def _check_range(self) -> TextSpan:
        if self.end <= self.start:
            raise ValueError(
                f"empty or inverted span [{self.start}, {self.end}). A zero-width evidence "
                "span points at nothing while looking like a citation."
            )
        if self.end - self.start != len(self.text):
            raise ValueError(
                f"span [{self.start}, {self.end}) covers {self.end - self.start} characters "
                f"but carries {len(self.text)}. The offsets and the text disagree, which "
                "means one of them was computed against different text."
            )
        return self

    def verify_against(self, original_text: str) -> bool:
        """Whether this span really slices ``original_text`` to its own text."""
        return original_text[self.start : self.end] == self.text

    @classmethod
    def over(cls, original_text: str, start: int, end: int) -> TextSpan:
        """Build a span by slicing, so the text can never disagree with offsets."""
        if not 0 <= start < end <= len(original_text):
            raise ValueError(
                f"span [{start}, {end}) does not fit text of length {len(original_text)}"
            )
        return cls(start=start, end=end, text=original_text[start:end])


class AlignedTextView(PramaanModel):
    """A transformed view of text, plus the map back to where it came from.

    ``transformed_to_original`` gives, for each character of
    ``transformed_text``, the index in ``original_text`` it derives from;
    ``transformed_to_original_end`` gives the exclusive upper bound of that
    derivation. Both are needed, and the second is the reason this model is
    wider than a naive design.

    One index is not enough because transformations are not one-to-one. Unicode
    composition turns two original characters into one transformed character;
    decomposition does the reverse. With only a start index, mapping a span
    back would silently truncate the composed pair to its first character --
    producing a span that still validates, still looks like a citation, and
    quotes half a grapheme.

    ``removed_spans`` records what was dropped. Deleting a zero-width character
    without recording it is exactly how offsets shift unnoticed, so deletion is
    never silent here.
    """

    #: Whitespace stripping off, for the same reason as :class:`TextSpan`: these
    #: two strings are indexed by the alignment arrays, and silently trimming
    #: either one shifts every index that follows it.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, validate_assignment=True)

    original_text: str
    transformed_text: str
    transformed_to_original: tuple[int | None, ...]
    transformed_to_original_end: tuple[int | None, ...]
    transformation: str
    transformation_version: str
    removed_spans: tuple[TextSpan, ...] = ()

    @model_validator(mode="after")
    def _check_alignment(self) -> AlignedTextView:
        if len(self.transformed_to_original) != len(self.transformed_text):
            raise ValueError(
                f"alignment has {len(self.transformed_to_original)} entries for "
                f"{len(self.transformed_text)} transformed characters. An alignment that "
                "does not cover the text it describes cannot map anything back safely."
            )
        if len(self.transformed_to_original_end) != len(self.transformed_to_original):
            raise ValueError("start and end alignment arrays must be the same length")
        for index, (start, end) in enumerate(
            zip(self.transformed_to_original, self.transformed_to_original_end, strict=True)
        ):
            if (start is None) != (end is None):
                raise ValueError(
                    f"alignment entry {index} has a start but no end, or the reverse; "
                    "a half-known origin is not a known origin"
                )
            if (
                start is not None
                and end is not None
                and not (0 <= start < end <= len(self.original_text))
            ):
                raise ValueError(
                    f"alignment entry {index} points at [{start}, {end}), outside the "
                    f"original text of length {len(self.original_text)}"
                )
        return self

    def to_original_span(self, start: int, end: int) -> TextSpan | None:
        """Map a range in the transformed text back to the original.

        Returns ``None`` when the range covers only characters with no origin
        (inserted, not derived). Returning ``None`` rather than a best guess is
        the point: a span that cannot be grounded must not be citable.
        """
        if not 0 <= start < end <= len(self.transformed_text):
            raise ValueError(
                f"range [{start}, {end}) does not fit transformed text of length "
                f"{len(self.transformed_text)}"
            )
        origins = [
            (low, high)
            for low, high in zip(
                self.transformed_to_original[start:end],
                self.transformed_to_original_end[start:end],
                strict=True,
            )
            if low is not None and high is not None
        ]
        if not origins:
            return None
        return TextSpan.over(
            self.original_text,
            min(low for low, _ in origins),
            max(high for _, high in origins),
        )


class LanguageAssessment(PramaanModel):
    """What is believed about the language of a document, and how firmly.

    ``script_codes`` are ISO 15924 (``Deva``, ``Beng``, ``Taml`` ...) and are
    observations. ``language_code`` is ISO 639-1 and is an inference, which is
    why it may be ``None`` while scripts are known.

    The distinction is not pedantry. Devanagari carries Hindi, Marathi, Nepali,
    Konkani and Sanskrit; Bengali script carries Bengali and Assamese. A
    pipeline that reads script identity as language certainty will label every
    Marathi article Hindi, and every downstream per-language metric will then
    report excellent Hindi coverage of a state that does not speak it.
    """

    language_code: str | None = None
    script_codes: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ambiguous: bool = False
    #: Every language this assessment could not rule out. Non-empty exactly
    #: when ``ambiguous`` is true.
    candidate_language_codes: tuple[str, ...] = ()
    backend: str
    backend_version: str

    @model_validator(mode="after")
    def _check_ambiguity_is_explicit(self) -> LanguageAssessment:
        if self.ambiguous and not self.candidate_language_codes:
            raise ValueError(
                "an ambiguous assessment must name its candidates; 'ambiguous' with no "
                "alternatives is indistinguishable from 'unknown' and loses the "
                "information a reviewer would act on"
            )
        if not self.ambiguous and len(self.candidate_language_codes) > 1:
            raise ValueError(
                "several candidate languages were recorded but the assessment claims to be "
                "unambiguous; one of the two is wrong"
            )
        return self


class TemporalKind(StrEnum):
    """The shape of a time expression, kept for auditing and for features."""

    ISO_DATE = "iso_date"
    NUMERIC_DATE = "numeric_date"
    MONTH_NAME_DATE = "month_name_date"
    DATE_RANGE = "date_range"
    RELATIVE_DAY = "relative_day"
    RELATIVE_WEEK = "relative_week"
    WEEKDAY = "weekday"
    OFFSET_AGO = "offset_ago"
    OFFSET_AHEAD = "offset_ahead"
    YEAR = "year"
    VAGUE_PAST = "vague_past"


class TemporalMention(PramaanModel):
    """A time expression, resolved against the article's own publication time.

    ``anchor_time`` is recorded on every mention rather than assumed, because
    "yesterday" means nothing without it and because the anchor is a *linguistic*
    reference point -- not the cutoff. Admissibility is decided elsewhere, by
    ``first_resolvable_at``; a mention that points into the future is a normal
    thing for an article to contain, not a leak.
    """

    span: TextSpan
    kind: TemporalKind
    normalized_start: UtcDatetime | None = None
    normalized_end: UtcDatetime | None = None
    resolution_status: ResolutionStatus
    anchor_time: UtcDatetime
    is_future_claim: bool = False
    is_retrospective: bool = False
    #: Every reading an ambiguous expression admits, as ISO-8601 intervals.
    #: ``01/03/2026`` is 1 March under one convention and 3 January under
    #: another, and this is where both survive instead of one being chosen.
    candidate_interpretations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _ambiguity_is_not_silently_resolved(self) -> TemporalMention:
        if self.resolution_status is ResolutionStatus.AMBIGUOUS:
            if self.normalized_start is not None or self.normalized_end is not None:
                raise ValueError(
                    f"{self.span.text!r} is ambiguous but carries a single normalised "
                    "interval. Picking one reading of an ambiguous date is how a pipeline "
                    "quietly asserts a fact nobody wrote."
                )
            if len(self.candidate_interpretations) < 2:
                raise ValueError(
                    f"{self.span.text!r} is ambiguous but lists fewer than two readings"
                )
        if self.resolution_status is ResolutionStatus.RESOLVED and self.normalized_start is None:
            raise ValueError(f"{self.span.text!r} claims resolution but normalises to nothing")
        if (
            self.normalized_start is not None
            and self.normalized_end is not None
            and self.normalized_end < self.normalized_start
        ):
            raise ValueError(f"{self.span.text!r} normalises to an inverted interval")
        return self


class LocationMention(PramaanModel):
    """A place name, and how far resolution actually got.

    ``search_widened`` is the flag that keeps an unknown state honest. Resolving
    "Bijapur" with no state context means searching all of India, where it
    matches districts in both Karnataka and Chhattisgarh. That search is
    permitted; doing it silently is not.
    """

    span: TextSpan
    normalized_name: str
    candidate_district_ids: tuple[str, ...] = ()
    status: ResolutionStatus
    state_context: str | None = None
    search_widened: bool = False
    resolver: str = "none"

    @model_validator(mode="after")
    def _status_matches_candidates(self) -> LocationMention:
        count = len(self.candidate_district_ids)
        if self.status is ResolutionStatus.RESOLVED and count != 1:
            raise ValueError(
                f"{self.normalized_name!r} is marked resolved with {count} candidates; "
                "resolution means exactly one"
            )
        if self.status is ResolutionStatus.AMBIGUOUS and count < 2:
            raise ValueError(
                f"{self.normalized_name!r} is marked ambiguous with {count} candidates; "
                "ambiguity means more than one"
            )
        if self.status is ResolutionStatus.UNRESOLVED and count:
            raise ValueError(
                f"{self.normalized_name!r} is unresolved but carries candidates; that is "
                "ambiguity wearing the wrong label"
            )
        return self


class ActorMention(PramaanModel):
    """A named actor, matched against an effective-dated alias registry.

    ``canonical_actor_id`` is deliberately not the display name. Organisations
    rename, split and are proscribed under new names; a pipeline keyed on the
    string in the article loses the connection between them, and one keyed on a
    display name silently rewrites history when the display name changes.
    """

    span: TextSpan
    canonical_actor_id: str | None = None
    matched_alias: str
    alias_version: str
    status: ResolutionStatus
    candidate_actor_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _status_matches_candidates(self) -> ActorMention:
        if self.status is ResolutionStatus.RESOLVED and self.canonical_actor_id is None:
            raise ValueError(f"{self.matched_alias!r} is marked resolved with no actor id")
        if self.status is ResolutionStatus.AMBIGUOUS:
            if self.canonical_actor_id is not None:
                raise ValueError(
                    f"{self.matched_alias!r} is ambiguous but names one actor anyway; "
                    "choosing among alias collisions is the caller's decision to make "
                    "explicitly, not this layer's to make quietly"
                )
            if len(self.candidate_actor_ids) < 2:
                raise ValueError(f"{self.matched_alias!r} is ambiguous with fewer than two ids")
        return self


class AttributionStatus(StrEnum):
    """Whether a quotation says who said it."""

    ATTRIBUTED = "attributed"
    UNATTRIBUTED = "unattributed"


class QuotedStatement(PramaanModel):
    """A quotation, and the attribution actually present in the text.

    An unattributed quote stays unattributed. Guessing the nearest named person
    is the mechanism by which "police said" becomes a specific officer, and by
    which a claim acquires an authority the article never gave it.
    """

    quote_span: TextSpan
    attribution_span: TextSpan | None = None
    attributed_actor_id: str | None = None
    attribution_text: str | None = None
    status: AttributionStatus = AttributionStatus.UNATTRIBUTED

    @model_validator(mode="after")
    def _no_speaker_without_evidence(self) -> QuotedStatement:
        if self.status is AttributionStatus.UNATTRIBUTED and (
            self.attribution_span is not None or self.attributed_actor_id is not None
        ):
            raise ValueError(
                "an unattributed quotation carries no speaker; a speaker with no attribution "
                "span in the text is invented"
            )
        if self.status is AttributionStatus.ATTRIBUTED and self.attribution_span is None:
            raise ValueError("an attributed quotation must point at the attribution it found")
        return self


class CrimeVerdict(StrEnum):
    """The ordinary-crime screen's three answers.

    Deliberately not a boolean. The screen exists to save LLM budget, and the
    cost of its two error directions is wildly asymmetric: wrongly keeping a
    burglary report wastes a few tokens, wrongly discarding an IED recovery
    loses the event entirely. ``INSUFFICIENT_EVIDENCE`` is where an honest
    "I cannot tell" goes, and it is retained rather than dropped.
    """

    LIKELY_ORDINARY_CRIME = "likely_ordinary_crime"
    POTENTIALLY_RELEVANT = "potentially_relevant"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class OrdinaryCrimeAssessment(PramaanModel):
    """Why the screen answered as it did, in spans rather than in prose."""

    verdict: CrimeVerdict
    ordinary_crime_spans: tuple[TextSpan, ...] = ()
    target_family_spans: tuple[TextSpan, ...] = ()
    reason: str

    @model_validator(mode="after")
    def _rejection_requires_positive_evidence(self) -> OrdinaryCrimeAssessment:
        """A rejection needs evidence *for* it, and none against.

        The rule this enforces is the whole safety property of the screen: an
        article is only called ordinary crime when something in it says so and
        nothing in it points at the target families. Absence of terrorism
        vocabulary is not evidence of a burglary.
        """
        if self.verdict is CrimeVerdict.LIKELY_ORDINARY_CRIME:
            if not self.ordinary_crime_spans:
                raise ValueError(
                    "an article was called ordinary crime with no ordinary-crime evidence; "
                    "that is a rejection based on the absence of other vocabulary"
                )
            if self.target_family_spans:
                raise ValueError(
                    "an article carrying a terrorism, insurgency or LWE indicator was called "
                    "ordinary crime. Any credible target-family indicator keeps the article."
                )
        return self


class DeterministicNlpResult(VersionedModel):
    """Everything the deterministic stage found, grounded in original offsets.

    This is what an LLM stage is given and what its output is checked against.
    It contains no probability, and it must not: a deterministic preprocessor
    that scored articles would be a model nobody trained, evaluated or
    calibrated, sitting upstream of the one that was.
    """

    observation_id: str
    source_id: str
    cutoff_at: UtcDatetime
    first_resolvable_at: UtcDatetime
    published_at: UtcDatetime | None = None
    modified_at: UtcDatetime | None = None
    retrieved_at: UtcDatetime

    #: False when the article's licence retained no readable text. The record is
    #: still processed and still returned -- a hash-only article is evidence
    #: that something was published, and dropping it would bias coverage
    #: towards permissively licensed sources.
    text_available: bool = True
    original_text_hash: str
    language: LanguageAssessment
    normalized_view: AlignedTextView | None = None
    transliterated_view: AlignedTextView | None = None

    #: Where the headline and body sit inside the assembled document. A span
    #: alone cannot say which field it came from, and the distinction matters:
    #: a claim supported only by a headline is weaker evidence than one
    #: supported by the body, and a licence that retained only the headline
    #: should be visible as such downstream.
    headline_span: TextSpan | None = None
    body_span: TextSpan | None = None

    sentence_spans: tuple[TextSpan, ...] = ()
    temporal_mentions: tuple[TemporalMention, ...] = ()
    location_mentions: tuple[LocationMention, ...] = ()
    actor_mentions: tuple[ActorMention, ...] = ()
    quoted_statements: tuple[QuotedStatement, ...] = ()
    retrospective_spans: tuple[TextSpan, ...] = ()
    ordinary_crime_assessment: OrdinaryCrimeAssessment

    candidate_spans: tuple[TextSpan, ...] = ()
    pipeline_version: str = PIPELINE_VERSION
    alias_version: str = "none"
    source_snapshot_hash: str | None = None

    @property
    def output_hash(self) -> str:
        """Deterministic hash of the whole result.

        Two runs over the same article with the same versions produce the same
        hash. A metamorphic test asserts exactly that, which is what turns
        "deterministic" from a design intention into a checked property.
        """
        return hash_object(self.model_dump(mode="json"))

    def verify_spans(self, original_text: str) -> tuple[str, ...]:
        """Names of every span family that fails to slice ``original_text``.

        Returns the failures rather than raising, so a caller can report all of
        them at once. The pipeline calls this before returning and refuses to
        emit a result with any entry.
        """
        failures: list[str] = []

        def check(name: str, spans: tuple[TextSpan, ...]) -> None:
            for index, span in enumerate(spans):
                if not span.verify_against(original_text):
                    failures.append(f"{name}[{index}]")

        check("sentence_spans", self.sentence_spans)
        check("retrospective_spans", self.retrospective_spans)
        check("candidate_spans", self.candidate_spans)
        check("temporal", tuple(mention.span for mention in self.temporal_mentions))
        check("location", tuple(mention.span for mention in self.location_mentions))
        check("actor", tuple(mention.span for mention in self.actor_mentions))
        check("quote", tuple(quote.quote_span for quote in self.quoted_statements))
        check(
            "attribution",
            tuple(
                quote.attribution_span
                for quote in self.quoted_statements
                if quote.attribution_span is not None
            ),
        )
        check("ordinary_crime", self.ordinary_crime_assessment.ordinary_crime_spans)
        check("target_family", self.ordinary_crime_assessment.target_family_spans)
        return tuple(failures)
