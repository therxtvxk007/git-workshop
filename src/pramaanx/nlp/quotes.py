"""Quotations, and the attribution the text actually contains.

A quotation matters to this project because it separates what somebody claimed
from what a newspaper asserts. "Police said three militants were killed" and
"three militants were killed" are different evidential objects, and an
adjudication layer that cannot tell them apart will treat a single official
statement, repeated by five outlets, as five independent observations of an
event.

The one rule that governs everything here: **an unattributed quote stays
unattributed.** The tempting behaviour -- when a quotation has no "said X",
look for the nearest named person and use them -- produces attributions that
are right often enough to be trusted and wrong often enough to matter. A quote
in a paragraph that happens to mention a Superintendent of Police becomes that
officer's statement, and a claim acquires an authority the article never gave
it.
"""

from __future__ import annotations

import re

from pramaanx.nlp.schemas import (
    ActorMention,
    AttributionStatus,
    QuotedStatement,
    ResolutionStatus,
    TextSpan,
)

QUOTES_VERSION = "nlp-quotes/1.0.0"

#: Opening-to-closing quotation mark pairs. Indian English uses both single and
#: double marks, and feeds deliver curly and straight forms interchangeably, so
#: all four are recognised rather than assuming a house style.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("\u201c", "\u201d"),  # left/right double quotation mark
    ("'", "'"),
    ("\u2018", "\u2019"),  # left/right single quotation mark
)

#: Verbs that introduce or follow a quotation. Reporting verbs only: "added",
#: "claimed" and "alleged" carry evidential weight and are kept, while "argued"
#: and "explained" are not present because they rarely appear in the wire copy
#: this reads and would widen the false-match surface for no gain.
_REPORTING_VERBS = (
    "said",
    "says",
    "added",
    "told",
    "stated",
    "claimed",
    "alleged",
    "asserted",
    "confirmed",
    "denied",
    "noted",
    "reported",
    "observed",
)

_VERB_ALT = "|".join(_REPORTING_VERBS)

#: A speaker: capitalised words, optionally joined by the lowercase connectives
#: that Indian designations use. Without them, "Superintendent of Police Ravi
#: Kumar" captures only the rank, and the attribution names an office rather
#: than the person the article actually credited.
_SPEAKER = r"[A-Z][\w.]*(?:\s+(?:of|for|in|at|the|and)\s+[A-Z][\w.]*|\s+[A-Z][\w.]*){0,5}"

#: "..., said Superintendent of Police Ravi Kumar" -- verb then speaker.
_TRAILING_ATTRIBUTION = re.compile(rf"^[\s,]*(?:{_VERB_ALT})\s+({_SPEAKER})")
#: "Ravi Kumar said, ..." -- speaker then verb, before the quotation.
_LEADING_ATTRIBUTION = re.compile(rf"({_SPEAKER})\s+(?:{_VERB_ALT})[\s,:]*$")
#: "according to police sources" -- an attribution with no named person, which
#: is still an attribution and must not be turned into one.
_IMPERSONAL = re.compile(
    r"^[\s,]*(?:according to|as per)\s+([a-z][\w]*(?:\s+[\w]*){0,3})",
    re.IGNORECASE,
)

#: How far either side of a quotation to look for its attribution. Beyond about
#: this, an apparent attribution usually belongs to a different sentence.
_WINDOW = 120

#: Shortest run of characters treated as a quotation. Below this, a pair of
#: apostrophes is almost always possessive or an abbreviation, not a quote.
_MIN_QUOTE_CHARS = 12


def _opens_a_quote(text: str, index: int) -> bool:
    """Whether the mark at ``index`` can open a quotation.

    An opening mark is preceded by nothing, by whitespace, or by punctuation.
    The rule exists for the straight apostrophe: in "the officer's car and the
    driver's seat", the two apostrophes are possessive, and a naive pair-finder
    reads everything between them as a twenty-character quotation that nobody
    said.
    """
    if index == 0:
        return True
    previous = text[index - 1]
    return previous.isspace() or not previous.isalnum()


def _closes_a_quote(text: str, index: int) -> bool:
    """Whether the mark at ``index`` can close a quotation.

    A closing mark is followed by nothing, whitespace or punctuation -- never
    by a letter, which is what a contraction or a possessive looks like.
    """
    if index + 1 >= len(text):
        return True
    following = text[index + 1]
    return following.isspace() or not following.isalnum()


def _find_quote_spans(text: str) -> list[TextSpan]:
    spans: list[TextSpan] = []
    claimed: list[tuple[int, int]] = []

    for opener, closer in _QUOTE_PAIRS:
        index = 0
        while index < len(text):
            start = text.find(opener, index)
            if start == -1:
                break
            if not _opens_a_quote(text, start):
                index = start + 1
                continue
            end = start + 1
            while (end := text.find(closer, end)) != -1 and not _closes_a_quote(text, end):
                end += 1
            if end == -1:
                break
            inner_start, inner_end = start + 1, end
            index = end + 1
            if inner_end - inner_start < _MIN_QUOTE_CHARS:
                continue
            if any(
                start < taken_end and taken_start < end + 1 for taken_start, taken_end in claimed
            ):
                continue
            claimed.append((start, end + 1))
            spans.append(TextSpan.over(text, inner_start, inner_end))

    return sorted(spans, key=lambda span: span.start)


def _trimmed(text: str, start: int, raw: str) -> tuple[TextSpan, str]:
    """Drop the sentence's own full stop from the end of a speaker match.

    "said Ravi Kumar." captures the terminating stop along with the name. The
    stop belongs to the sentence, not to the person, and leaving it in makes
    every attribution string differ from the same name written mid-sentence.
    """
    trimmed = raw.rstrip(". \t")
    if not trimmed:
        trimmed = raw
    return TextSpan.over(text, start, start + len(trimmed)), trimmed


def _attribution_for(
    text: str, quote: TextSpan
) -> tuple[TextSpan | None, str | None, AttributionStatus]:
    """The attribution adjacent to ``quote``, or an explicit absence."""
    after = text[quote.end + 1 : quote.end + 1 + _WINDOW]
    for pattern in (_TRAILING_ATTRIBUTION, _IMPERSONAL):
        match = pattern.match(after)
        if match:
            span, value = _trimmed(text, quote.end + 1 + match.start(1), match.group(1))
            return span, value, AttributionStatus.ATTRIBUTED

    window_start = max(0, quote.start - 1 - _WINDOW)
    before = text[window_start : max(window_start, quote.start - 1)]
    leading = _LEADING_ATTRIBUTION.search(before)
    if leading:
        span, value = _trimmed(text, window_start + leading.start(1), leading.group(1))
        return span, value, AttributionStatus.ATTRIBUTED

    # Nothing adjacent said who spoke. That is the answer.
    return None, None, AttributionStatus.UNATTRIBUTED


def extract_quotations(
    text: str, *, actor_mentions: tuple[ActorMention, ...] = ()
) -> tuple[QuotedStatement, ...]:
    """Quotations with their attributions, and no invented speakers.

    ``actor_mentions`` links an attribution to a canonical actor only when the
    attribution span *overlaps* a resolved actor mention. Overlap, not
    proximity: the actor must literally be the words the article used to say who
    spoke. An actor mentioned elsewhere in the same sentence does not qualify,
    because that is the nearest-named-person heuristic wearing a different hat.
    """
    statements: list[QuotedStatement] = []

    for quote in _find_quote_spans(text):
        span, attribution_text, status = _attribution_for(text, quote)
        actor_id: str | None = None
        if span is not None:
            for mention in actor_mentions:
                overlaps = mention.span.start < span.end and span.start < mention.span.end
                if overlaps and mention.status is ResolutionStatus.RESOLVED:
                    actor_id = mention.canonical_actor_id
                    break
        statements.append(
            QuotedStatement(
                quote_span=quote,
                attribution_span=span,
                attributed_actor_id=actor_id,
                attribution_text=attribution_text,
                status=status,
            )
        )

    return tuple(statements)
