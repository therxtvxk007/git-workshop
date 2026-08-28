"""Canonical text, produced without ever losing the original.

Normalisation exists so that two spellings of the same string compare equal:
NFC composition, one kind of space, one kind of quote. It is also the stage
with the highest chance of quietly corrupting evidence, because every operation
here changes character counts and therefore offsets.

Three rules keep it honest.

**The original is immutable.** Nothing in this module returns a modified
string. It returns an :class:`~pramaanx.nlp.schemas.AlignedTextView` beside the
original, and the original is what every span is measured against.

**No character is removed without a record.** Removals go through
``AlignmentBuilder.drop``, so a dropped zero-width space appears in
``removed_spans`` rather than as an unexplained gap in the offsets.

**Nothing is translated.** Normalisation is a spelling operation. Converting
Devanagari digits to ASCII digits would be a semantic edit, and it is not done
here; :mod:`pramaanx.nlp.transliterate` produces a separate, clearly auxiliary
view for that kind of change.
"""

from __future__ import annotations

import unicodedata

from pramaanx.hashing import hash_text
from pramaanx.nlp.alignment import AlignmentBuilder, combining_clusters
from pramaanx.nlp.schemas import AlignedTextView

NORMALIZATION_VERSION = "nlp-normalize/1.0.0"
TRANSFORMATION = "nfc-canonical"

#: Zero-width and formatting characters that carry no orthographic meaning and
#: are removed. Every one of these can be pasted invisibly into a headline and
#: shift every offset after it.
_STRIPPED_INVISIBLES = frozenset(
    {
        "\u200b",  # zero-width space
        "\u2060",  # word joiner
        "\ufeff",  # zero-width no-break space / BOM
        "\u00ad",  # soft hyphen
        "\u180e",  # Mongolian vowel separator
    }
)

#: Zero-width joiners are **kept**. In Devanagari, Bengali and the southern
#: scripts, ZWNJ and ZWJ decide whether a consonant cluster renders as a
#: conjunct or as separate letters -- they change the word, not its appearance.
#: Stripping them would be the "punctuation normalisation" that quietly edits
#: Indic text, so they are listed here to make the decision explicit rather
#: than accidental.
_PRESERVED_JOINERS = frozenset({"\u200c", "\u200d"})  # ZWNJ, ZWJ

#: Quotation marks folded to their ASCII equivalents. All one-to-one, so
#: alignment is unaffected and quote extraction does not need four variants of
#: every pattern.
#: Written as escapes rather than as the characters themselves. In a table
#: whose entire subject is characters that look like other characters, the
#: codepoint is the readable form and the glyph is the ambiguous one.
_QUOTE_FOLDING = {
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u201a": "'",  # single low-9 quotation mark
    "\u201b": "'",  # single high-reversed-9 quotation mark
    "\u201c": '"',  # left double quotation mark
    "\u201d": '"',  # right double quotation mark
    "\u201e": '"',  # double low-9 quotation mark
    "\u201f": '"',  # double high-reversed-9 quotation mark
    "\u2039": "'",  # single left-pointing angle quotation mark
    "\u203a": "'",  # single right-pointing angle quotation mark
    "\u00ab": '"',  # left double angle quotation mark
    "\u00bb": '"',  # right double angle quotation mark
}

#: Dashes folded to a plain hyphen, again one-to-one.
_DASH_FOLDING = {
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
}

#: Line separators mapped to a plain newline. Line breaks are preserved rather
#: than collapsed into spaces, because they are the most reliable sentence
#: boundary in feed-supplied text and losing them makes segmentation worse.
_LINE_BREAKS = frozenset(
    {"\n", "\r", "\u2028", "\u2029", "\v", "\f"}  # \u2028/9: line, paragraph separator
)

_PUNCTUATION_FOLDING = {**_QUOTE_FOLDING, **_DASH_FOLDING}


def _is_space(char: str) -> bool:
    return char not in _LINE_BREAKS and (char.isspace() or unicodedata.category(char) == "Zs")


def _is_removable_control(char: str) -> bool:
    """Control characters that are not line breaks and not tabs."""
    if char in _LINE_BREAKS or char == "\t":
        return False
    return unicodedata.category(char) in {"Cc", "Cf"} and char not in _PRESERVED_JOINERS


def normalise(text: str) -> AlignedTextView:
    """Produce the canonical view of ``text``, aligned back to it.

    The sequence, in order, is: cluster-wise NFC; invisible and control removal;
    punctuation folding; whitespace canonicalisation with line breaks kept.

    NFC runs per combining cluster rather than over the whole string. Whole-string
    normalisation would be one call and would make alignment impossible to
    recover, because composition changes lengths in ways that cannot be
    attributed to particular input characters after the fact. Per-cluster
    normalisation is closed -- a cluster's normal form never reaches outside the
    cluster -- so each output maps to exactly the range it came from.
    """
    builder = AlignmentBuilder(text, transformation=TRANSFORMATION, version=NORMALIZATION_VERSION)
    run_start: int | None = None
    run_end = 0
    run_has_break = False
    emitted_any = False

    def flush_whitespace() -> None:
        """Emit one character for a whole run of whitespace.

        A run containing any line break becomes ``"\\n"``; otherwise ``" "``.
        Collapsing the run rather than each character is what makes ``\\r\\n``
        one break instead of two, and it keeps a run of blank lines from
        multiplying into boundaries the writer did not intend. The whole run is
        the source range, so nothing is unaccounted for.

        Leading and trailing whitespace is dropped rather than emitted: a
        canonical form should not begin or end with a character that came from
        a feed's indentation.
        """
        nonlocal run_start, run_has_break
        if run_start is None:
            return
        if emitted_any:
            builder.emit("\n" if run_has_break else " ", run_start, run_end)
        else:
            builder.drop(run_start, run_end)
        run_start = None
        run_has_break = False

    for start, end, cluster in combining_clusters(text):
        composed = unicodedata.normalize("NFC", cluster)

        if len(composed) == 1 and (_is_space(composed) or composed in _LINE_BREAKS):
            if run_start is None:
                run_start = start
            run_end = end
            run_has_break = run_has_break or composed in _LINE_BREAKS
            continue

        flush_whitespace()

        kept = "".join(
            char
            for char in composed
            if char not in _STRIPPED_INVISIBLES and not _is_removable_control(char)
        )
        if not kept:
            builder.drop(start, end)
            continue

        folded = "".join(_PUNCTUATION_FOLDING.get(char, char) for char in kept)
        builder.emit(folded, start, end)
        emitted_any = True

    if run_start is not None:
        builder.drop(run_start, run_end)

    return builder.build()


def original_text_hash(text: str) -> str:
    """Hash of the untouched original.

    Recorded on every result so that a later stage can prove it is reasoning
    about the same characters the spans were measured against. A normalised
    hash would not do: it would match for two documents that differ only in the
    invisible characters this module removes, which is precisely the difference
    worth detecting.
    """
    return hash_text(text)


def normalised_key(text: str) -> str:
    """A case-folded canonical key, for lexicon lookup only.

    Never used to produce a span. Case folding is not alignment-safe in general
    -- some case mappings change length -- so this exists strictly for comparing
    a candidate string against a dictionary, and the span always comes from the
    original offsets that produced the candidate.
    """
    return normalise(text).transformed_text.casefold()
