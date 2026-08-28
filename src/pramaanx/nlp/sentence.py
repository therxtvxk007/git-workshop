"""Sentence boundaries, as spans over the original text.

Segmentation runs on the **original** string, not on the normalised view. That
is a deliberate inversion of the obvious design, and the reason is exactness: a
span produced by slicing the original cannot disagree with the original. Had
segmentation run on the normalised text and mapped back, every boundary would
depend on the alignment being right, and a bug in normalisation would surface
here as slightly wrong sentences rather than as a normalisation failure.

The rules are conservative. Where a boundary is genuinely uncertain -- an
abbreviation that might end a sentence, an ellipsis mid-thought -- the segmenter
does not split. An over-long sentence costs a slightly wider evidence span; an
over-eager split cuts a quotation in half and can strand an attribution in a
different sentence from the words it attributes.
"""

from __future__ import annotations

import re
import unicodedata

from pramaanx.nlp.schemas import TextSpan

SEGMENTER_VERSION = "nlp-sentence/1.0.0"

#: Characters that can end a sentence. The danda and double danda are the
#: primary terminators in Devanagari, Bengali, Gujarati and Oriya prose, and
#: their absence from a Latin-only terminator set is the single most common way
#: an Indic segmenter returns one enormous "sentence" per paragraph.
TERMINATORS = frozenset(
    {
        ".",
        "!",
        "?",
        "\u0964",  # danda
        "\u0965",  # double danda
        "\u061f",  # Arabic question mark, used in Urdu
        "\u06d4",  # Arabic full stop, used in Urdu
        "\u2026",  # horizontal ellipsis
    }
)

#: Closing characters that belong to the sentence they follow. A terminator
#: inside a quotation ends the sentence *after* the closing quote, or the quote
#: mark is orphaned onto the next sentence.
_CLOSERS = frozenset({'"', "'", ")", "]", "}", "\u201d", "\u2019", "\u00bb", "\u203a"})

#: Abbreviations after which a full stop is usually not a sentence end.
#: Indian-English honorifics and ranks are included because they are dense in
#: exactly the reporting this project reads.
ABBREVIATIONS = frozenset(
    {
        "adv",
        "addl",
        "asst",
        "brig",
        "capt",
        "col",
        "cst",
        "dr",
        "dy",
        "dept",
        "dg",
        "dgp",
        "dig",
        "dsp",
        "etc",
        "eg",
        "fig",
        "gen",
        "govt",
        "hon",
        "ie",
        "insp",
        "inst",
        "jr",
        "kum",
        "lt",
        "maj",
        "messrs",
        "mr",
        "mrs",
        "ms",
        "mt",
        "no",
        "nos",
        "pvt",
        "prof",
        "rs",
        "rev",
        "sgt",
        "sh",
        "shri",
        "smt",
        "sp",
        "sr",
        "st",
        "supdt",
        "vs",
        "viz",
    }
)

_WORD_BEFORE = re.compile(r"([A-Za-z]+)\.$")
_INITIAL = re.compile(r"(?:^|[\s(\[])([A-Z])\.$")
_DIGIT_AROUND = re.compile(r"\d\.\d")
#: A letter immediately followed by a full stop, right after the one being
#: considered: the shape of a dotted abbreviation still in progress. In
#: "4.30 p.m. Everyone left", the stop after "p" is followed by "m.", so it is
#: internal; the stop after "m" is followed by a word, so it may end the
#: sentence. Looking ahead is what separates those two, and it is why "p.m."
#: neither splits in the middle nor swallows the sentence that follows it.
_ABBREV_CONTINUES = re.compile(r"^\s*[A-Za-z]\.")


def _is_paragraph_break(text: str, index: int) -> bool:
    return text[index] in {"\n", "\r", "\u2028", "\u2029"}


def _blocks_split(text: str, terminator_index: int) -> bool:
    """Whether the full stop at ``terminator_index`` is not a sentence end."""
    char = text[terminator_index]
    if char != ".":
        # Only the full stop is ambiguous. A danda or an exclamation mark is
        # never an abbreviation marker.
        return False

    prefix = text[: terminator_index + 1]

    if _INITIAL.search(prefix):
        return True

    if _ABBREV_CONTINUES.match(text[terminator_index + 1 :]):
        return True

    match = _WORD_BEFORE.search(prefix)
    if match and match.group(1).casefold() in ABBREVIATIONS:
        return True

    # A decimal point or a dotted numeric date: 3.5, 01.03.2026.
    if terminator_index > 0 and terminator_index + 1 < len(text):
        window = text[terminator_index - 1 : terminator_index + 2]
        if _DIGIT_AROUND.search(window):
            return True

    return False


def _ellipsis_continues(text: str, end: int) -> bool:
    """Whether an ellipsis is mid-sentence rather than terminal.

    An ellipsis followed by a lower-case letter is a trailing thought inside one
    sentence; followed by a capital or by nothing, it ends one.
    """
    for index in range(end, len(text)):
        char = text[index]
        if char.isspace():
            continue
        return not (char.isupper() or unicodedata.category(char) == "Lo")
    return False


def _trimmed_span(text: str, start: int, end: int) -> TextSpan | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end <= start:
        return None
    return TextSpan.over(text, start, end)


def segment_sentences(text: str) -> tuple[TextSpan, ...]:
    """Split ``text`` into sentence spans over itself.

    Deterministic and total: concatenating the returned spans in order, with
    the whitespace between them, reconstructs the input. Empty and
    whitespace-only regions produce no span rather than an empty one.
    """
    if not text.strip():
        return ()

    spans: list[TextSpan] = []
    start = 0
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if _is_paragraph_break(text, index):
            # A line break is a boundary that no abbreviation rule overrides:
            # feed-supplied text uses them where a human would use a full stop.
            span = _trimmed_span(text, start, index)
            if span is not None:
                spans.append(span)
            start = index + 1
            index += 1
            continue

        if char not in TERMINATORS:
            index += 1
            continue

        run_end = index + 1
        while run_end < length and text[run_end] in TERMINATORS and text[run_end] == char:
            run_end += 1

        if char == "…" or (char == "." and run_end - index >= 3):
            if _ellipsis_continues(text, run_end):
                index = run_end
                continue
        elif _blocks_split(text, index):
            index += 1
            continue

        while run_end < length and text[run_end] in _CLOSERS:
            run_end += 1

        span = _trimmed_span(text, start, run_end)
        if span is not None:
            spans.append(span)
        start = run_end
        index = run_end

    tail = _trimmed_span(text, start, length)
    if tail is not None:
        spans.append(tail)

    return tuple(spans)


def sentence_containing(spans: tuple[TextSpan, ...], offset: int) -> TextSpan | None:
    """The sentence span covering ``offset``, if any.

    Used to give a mention its sentence context without re-segmenting, and to
    keep an attribution and its quotation in the same unit.
    """
    for span in spans:
        if span.start <= offset < span.end:
            return span
    return None
