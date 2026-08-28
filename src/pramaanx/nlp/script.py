"""Which writing systems a document uses, decided by character, not by guess.

Script detection is the one part of language processing that can be done
exactly. A codepoint belongs to a Unicode block, the block belongs to a script,
and no statistics are involved. So this module is deterministic, needs no model,
and never returns a confidence -- it returns what is there.

The reason to keep it strictly separate from language detection is that the two
questions have different answers. ``Deva`` is a fact about the bytes; Hindi is
an inference about the writer. See :mod:`pramaanx.nlp.language`, which is
allowed to be uncertain, and is.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

SCRIPT_VERSION = "nlp-script/1.0.0"

#: ISO 15924 code for "nothing identifiable". Never spelled ``Latn``: a string
#: of digits and punctuation is not English, and defaulting it to Latin is how
#: a coverage report acquires phantom English documents.
SCRIPT_UNKNOWN = "Zyyy"

#: Unicode ranges for the scripts WP2 must represent, as ISO 15924 codes.
#: Ordered so that ties break deterministically, most-specific first.
SCRIPT_RANGES: tuple[tuple[str, int, int], ...] = (
    ("Latn", 0x0041, 0x005A),
    ("Latn", 0x0061, 0x007A),
    ("Latn", 0x00C0, 0x024F),
    ("Arab", 0x0600, 0x06FF),
    ("Arab", 0x0750, 0x077F),
    ("Arab", 0xFB50, 0xFDFF),
    ("Arab", 0xFE70, 0xFEFF),
    ("Deva", 0x0900, 0x097F),
    ("Deva", 0xA8E0, 0xA8FF),
    ("Beng", 0x0980, 0x09FF),
    ("Guru", 0x0A00, 0x0A7F),
    ("Gujr", 0x0A80, 0x0AFF),
    ("Orya", 0x0B00, 0x0B7F),
    ("Taml", 0x0B80, 0x0BFF),
    ("Telu", 0x0C00, 0x0C7F),
    ("Knda", 0x0C80, 0x0CFF),
    ("Mlym", 0x0D00, 0x0D7F),
)

#: Human-readable names, for reports and error messages only. Nothing branches
#: on these.
SCRIPT_NAMES: dict[str, str] = {
    "Latn": "Latin",
    "Arab": "Arabic",
    "Deva": "Devanagari",
    "Beng": "Bengali",
    "Guru": "Gurmukhi",
    "Gujr": "Gujarati",
    "Orya": "Oriya",
    "Taml": "Tamil",
    "Telu": "Telugu",
    "Knda": "Kannada",
    "Mlym": "Malayalam",
    SCRIPT_UNKNOWN: "Unknown",
}

_ORDER = {code: index for index, (code, _, _) in enumerate(SCRIPT_RANGES)}

#: Codepoints that carry no script identity of their own and must not vote.
#: Zero-width joiners are orthographically meaningful inside Indic clusters but
#: say nothing about *which* Indic script, so they are excluded from counting
#: rather than removed from the text.
_NEUTRAL = frozenset({0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD})


def script_of_char(char: str) -> str | None:
    """The ISO 15924 code for one character, or ``None`` if it has no script.

    Digits, punctuation, spaces and joiners return ``None``. They are shared by
    every writing system, so letting them vote would make a Hindi article
    containing a phone number look partly Latin.
    """
    code = ord(char)
    if code in _NEUTRAL:
        return None
    category = unicodedata.category(char)
    if not (category.startswith("L") or category.startswith("M")):
        return None
    for name, low, high in SCRIPT_RANGES:
        if low <= code <= high:
            return name
    return None


def script_counts(text: str) -> dict[str, int]:
    """How many characters of each script appear, sorted for determinism."""
    counts: dict[str, int] = {}
    for char in text:
        code = script_of_char(char)
        if code is not None:
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], _ORDER.get(item[0], 99))))


def detect_scripts(text: str, *, minimum_share: float = 0.05) -> tuple[str, ...]:
    """Every script with a meaningful share of the letters, strongest first.

    ``minimum_share`` exists so that one stray Latin abbreviation in a Malayalam
    article does not report the article as bilingual, while a genuinely
    code-mixed document still reports both. It is a share of *letters*, not of
    characters, so punctuation density cannot move it.

    Returns ``()`` for text with no identifiable letters -- not ``("Latn",)``.
    """
    if not 0.0 <= minimum_share <= 1.0:
        raise ValueError(f"minimum_share must be in [0, 1], got {minimum_share}")
    counts = script_counts(text)
    total = sum(counts.values())
    if not total:
        return ()
    return tuple(code for code, count in counts.items() if count / total >= minimum_share)


def dominant_script(text: str) -> str:
    """The single script most letters belong to, or :data:`SCRIPT_UNKNOWN`.

    Ties break by the order of :data:`SCRIPT_RANGES` rather than by dictionary
    order, so the answer does not depend on the insertion history of a dict.
    """
    counts = script_counts(text)
    if not counts:
        return SCRIPT_UNKNOWN
    return min(counts, key=lambda code: (-counts[code], _ORDER.get(code, 99)))


def is_mixed_script(text: str, *, minimum_share: float = 0.05) -> bool:
    """Whether the text meaningfully uses more than one writing system."""
    return len(detect_scripts(text, minimum_share=minimum_share)) > 1


def describe(codes: Iterable[str]) -> str:
    """Human-readable script list, for messages and reports."""
    names = [SCRIPT_NAMES.get(code, code) for code in codes]
    return ", ".join(names) if names else SCRIPT_NAMES[SCRIPT_UNKNOWN]
