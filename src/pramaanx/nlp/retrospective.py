"""Marking articles that are recalling an event rather than reporting one.

An anniversary piece about the 2008 Mumbai attacks, a verdict in a decade-old
trial, a documentary review: these contain every keyword a terrorism-detection
pipeline looks for, describe events in vivid detail, and refer to nothing that
is about to happen. Fed to a district risk model unmarked, they produce a
spike in "evidence" for a district on the anniversary of an old attack, every
year, forever.

The spans here are **features, not filters**. Nothing is discarded for being
retrospective, and the reason is that the same article often does both jobs --
"on the anniversary of the 2008 attacks, security was tightened across the
city" is a retrospective frame around a current, forecast-relevant fact.
Rejecting it would lose the fact; ignoring the frame would date the fact to
2008. Marking it lets a later stage weigh both.
"""

from __future__ import annotations

import re

from pramaanx.nlp.schemas import TextSpan

RETROSPECTIVE_VERSION = "nlp-retrospective/1.0.0"


class RetrospectiveCue:
    """A marker phrase and what kind of recollection it signals."""

    __slots__ = ("kind", "pattern")

    def __init__(self, kind: str, pattern: str) -> None:
        self.kind = kind
        self.pattern = re.compile(pattern, re.IGNORECASE)


#: Grouped by the kind of retrospection, because they are not equally strong.
#: A judicial cue ("chargesheet", "acquitted") almost always means an old case;
#: a memorial cue can equally introduce present-day security measures.
CUES: tuple[RetrospectiveCue, ...] = (
    RetrospectiveCue("anniversary", r"\b\d+(?:st|nd|rd|th)?\s+anniversary\b"),
    RetrospectiveCue("anniversary", r"\banniversary of the\b"),
    RetrospectiveCue("anniversary", r"\bmarking\s+\d+\s+years\b"),
    RetrospectiveCue(
        "memorial", r"\b(?:commemorat\w*|remembrance|memorial service|paid tribute)\b"
    ),
    RetrospectiveCue("judicial", r"\b(?:chargesheet|charge sheet|charge-sheet)\b"),
    RetrospectiveCue("judicial", r"\b(?:convicted|acquitted|sentenced|verdict|life term)\b"),
    RetrospectiveCue("judicial", r"\b(?:trial court|special court|nia court|tada court)\b"),
    RetrospectiveCue("judicial", r"\b(?:appeal|appellant|bail plea)\s+(?:against|in)\b"),
    RetrospectiveCue("investigation", r"\b(?:probe into the|investigation into the)\b"),
    RetrospectiveCue("investigation", r"\b(?:reopened|cold case)\b"),
    RetrospectiveCue("recall", r"\b(?:looking back|in hindsight|recalled|recalling|revisit\w*)\b"),
    RetrospectiveCue("recall", r"\b(?:years (?:ago|later)|decades (?:ago|later))\b"),
    RetrospectiveCue("recall", r"\b(?:back in (?:19|20)\d{2})\b"),
    RetrospectiveCue("summary", r"\b(?:a look at|timeline of|what happened (?:in|on))\b"),
    RetrospectiveCue("summary", r"\b(?:the aftermath of|in the aftermath)\b"),
    RetrospectiveCue("documentary", r"\b(?:documentary|docuseries|film based on|biopic)\b"),
    RetrospectiveCue("documentary", r"\b(?:book on the|memoir)\b"),
    RetrospectiveCue("later_reporting", r"\b(?:it (?:later )?emerged|was later confirmed)\b"),
    RetrospectiveCue("later_reporting", r"\b(?:the death toll (?:rose|climbed))\b"),
    RetrospectiveCue("later_reporting", r"\b(?:as it turned out|it transpired)\b"),
)


def find_retrospective_spans(text: str) -> tuple[TextSpan, ...]:
    """Every retrospective marker in ``text``, non-overlapping and in order.

    Overlaps are resolved longest-first so that "10th anniversary of the" yields
    one span rather than two nested ones, keeping the output a function of the
    text rather than of the cue ordering.
    """
    matches: list[tuple[int, int]] = []
    for cue in CUES:
        matches.extend((match.start(), match.end()) for match in cue.pattern.finditer(text))

    ordered = sorted(matches, key=lambda pair: (pair[0], -(pair[1] - pair[0])))
    kept: list[TextSpan] = []
    for start, end in ordered:
        if any(start < span.end and span.start < end for span in kept):
            continue
        kept.append(TextSpan.over(text, start, end))
    return tuple(kept)


def retrospective_kinds(text: str) -> tuple[str, ...]:
    """The distinct kinds of retrospection present, sorted.

    Useful as a feature: a judicial cue and an anniversary cue mean different
    things about how an article should be weighted, and collapsing them into a
    single boolean throws that away.
    """
    return tuple(sorted({cue.kind for cue in CUES if cue.pattern.search(text)}))


def is_probably_retrospective(text: str, *, minimum_cues: int = 2) -> bool:
    """Whether enough independent cues fire to call the article retrospective.

    Two by default. One cue is routinely present in ordinary current reporting
    -- "the aftermath of the blast" appears in same-day coverage -- so a single
    marker is a signal, not a verdict. This helper exists for reporting and for
    features; the pipeline records the spans regardless of what it returns.
    """
    return len(retrospective_kinds(text)) >= minimum_cues
