"""An auxiliary Latin view of Indic text. Never a replacement for it.

Transliteration earns its place for one job: matching. "Naxal", "नक्सल" and
"നക്സൽ" are the same word, and an alias registry that has to enumerate every
script for every actor will always be missing one. A Latin view lets a single
alias match all three.

It is not, and must never become, evidence. Transliteration is lossy in both
directions: it discards the distinction between characters that share a Latin
rendering, and it invents inherent vowels that were never written. A quotation
taken from a transliterated view would be a quotation of something no
journalist wrote. So every span this package emits comes from the original,
:class:`~pramaanx.nlp.schemas.DeterministicNlpResult` keeps the transliterated
view clearly separate, and the pipeline never sources a quote from it.

The mapping exploits a property of the Unicode standard rather than duplicating
nine tables. The Indic blocks -- Devanagari, Bengali, Gurmukhi, Gujarati, Oriya,
Tamil, Telugu, Kannada, Malayalam -- inherit their layout from ISCII, so a
character's *offset within its block* has the same phonetic value across all of
them: offset 0x15 is ``ka`` in every one. One table indexed by offset therefore
covers all nine, and a script that lacks a letter simply has nothing at that
offset. Nine hand-maintained tables would drift apart; this one cannot.
"""

from __future__ import annotations

from dataclasses import dataclass

from pramaanx.nlp.alignment import AlignmentBuilder
from pramaanx.nlp.schemas import AlignedTextView

TRANSLITERATION_VERSION = "nlp-translit/1.0.0"
SCHEME = "iso15919-simplified"

#: Block start for each script this module can transliterate.
_SCRIPT_BASES: dict[str, int] = {
    "Deva": 0x0900,
    "Beng": 0x0980,
    "Guru": 0x0A00,
    "Gujr": 0x0A80,
    "Orya": 0x0B00,
    "Taml": 0x0B80,
    "Telu": 0x0C00,
    "Knda": 0x0C80,
    "Mlym": 0x0D00,
}

#: Scripts deliberately not transliterated, and why. Returning nothing is the
#: correct answer for these; a bad transliteration is worse than none, because
#: it would match aliases it should not.
UNSUPPORTED_SCRIPTS: dict[str, str] = {
    "Arab": (
        "Urdu omits short vowels in ordinary orthography, so romanisation "
        "requires a lexicon rather than a character mapping. A mechanical "
        "transliteration would produce consonant skeletons that collide with "
        "unrelated words."
    ),
    "Latn": "already Latin",
}

#: Independent vowels, by block offset.
_VOWELS: dict[int, str] = {
    0x05: "a",
    0x06: "aa",
    0x07: "i",
    0x08: "ii",
    0x09: "u",
    0x0A: "uu",
    0x0B: "ri",
    0x0C: "li",
    0x0E: "e",
    0x0F: "e",
    0x10: "ai",
    0x12: "o",
    0x13: "o",
    0x14: "au",
}

#: Consonant bases, by block offset. The inherent ``a`` is added separately so
#: that a following vowel sign can replace it and a virama can suppress it.
_CONSONANTS: dict[int, str] = {
    0x15: "k",
    0x16: "kh",
    0x17: "g",
    0x18: "gh",
    0x19: "ng",
    0x1A: "c",
    0x1B: "ch",
    0x1C: "j",
    0x1D: "jh",
    0x1E: "ny",
    0x1F: "t",
    0x20: "th",
    0x21: "d",
    0x22: "dh",
    0x23: "n",
    0x24: "t",
    0x25: "th",
    0x26: "d",
    0x27: "dh",
    0x28: "n",
    0x29: "n",
    0x2A: "p",
    0x2B: "ph",
    0x2C: "b",
    0x2D: "bh",
    0x2E: "m",
    0x2F: "y",
    0x30: "r",
    0x31: "r",
    0x32: "l",
    0x33: "l",
    0x34: "zh",
    0x35: "v",
    0x36: "sh",
    0x37: "sh",
    0x38: "s",
    0x39: "h",
}

#: Dependent vowel signs, by block offset. Each replaces the inherent ``a`` of
#: the consonant it follows.
_MATRAS: dict[int, str] = {
    0x3E: "aa",
    0x3F: "i",
    0x40: "ii",
    0x41: "u",
    0x42: "uu",
    0x43: "ri",
    0x44: "ri",
    0x46: "e",
    0x47: "e",
    0x48: "ai",
    0x4A: "o",
    0x4B: "o",
    0x4C: "au",
    0x62: "l",
    0x63: "l",
}

_VIRAMA = 0x4D
_ANUSVARA = 0x02
_CANDRABINDU = 0x01
_VISARGA = 0x03
_NUKTA = 0x3C
_DIGIT_START = 0x66
_DIGIT_END = 0x6F

_INHERENT = "a"


@dataclass
class _Token:
    """One transliterated unit, with the source range that produced it."""

    start: int
    end: int
    base: str
    vowel: str | None


def script_base(script_code: str) -> int | None:
    """The Unicode block start for a transliterable script, else ``None``."""
    return _SCRIPT_BASES.get(script_code)


def can_transliterate(script_code: str) -> bool:
    return script_code in _SCRIPT_BASES


def transliterate(text: str, *, script_code: str) -> AlignedTextView | None:
    """A Latin view of ``text``, or ``None`` when the script is not supported.

    Alignment is per *token*, not per character: a consonant and the vowel sign
    that modifies it form one token mapped to the range covering both. Mapping a
    Latin substring back therefore yields a complete Indic cluster rather than a
    consonant with its vowel severed.

    Characters with no mapping -- Latin words inside an Indic sentence, digits,
    punctuation -- pass through unchanged and stay aligned, so a code-mixed
    document transliterates without losing its English.
    """
    base = script_base(script_code)
    if base is None:
        return None

    tokens: list[_Token] = []
    for index, char in enumerate(text):
        offset = ord(char) - base
        in_block = 0 <= offset <= 0x7F

        if in_block and offset in _CONSONANTS:
            tokens.append(_Token(index, index + 1, _CONSONANTS[offset], _INHERENT))
            continue
        if in_block and offset in _MATRAS and tokens and tokens[-1].vowel is not None:
            # A vowel sign replaces the inherent vowel of the consonant before
            # it, and extends that token's source range to cover itself.
            tokens[-1].vowel = _MATRAS[offset]
            tokens[-1].end = index + 1
            continue
        if in_block and offset == _VIRAMA and tokens and tokens[-1].vowel is not None:
            tokens[-1].vowel = None
            tokens[-1].end = index + 1
            continue
        if in_block and offset == _NUKTA and tokens:
            # A nukta modifies the preceding consonant's articulation. This
            # simplified scheme does not distinguish the result, but the source
            # range must still cover it or the alignment would omit a character.
            tokens[-1].end = index + 1
            continue
        if in_block and offset in _VOWELS:
            tokens.append(_Token(index, index + 1, _VOWELS[offset], None))
            continue
        if in_block and offset in {_ANUSVARA, _CANDRABINDU}:
            tokens.append(_Token(index, index + 1, "n", None))
            continue
        if in_block and offset == _VISARGA:
            tokens.append(_Token(index, index + 1, "h", None))
            continue
        if in_block and _DIGIT_START <= offset <= _DIGIT_END:
            tokens.append(_Token(index, index + 1, str(offset - _DIGIT_START), None))
            continue
        tokens.append(_Token(index, index + 1, char, None))

    builder = AlignmentBuilder(text, transformation=SCHEME, version=TRANSLITERATION_VERSION)
    for token in tokens:
        rendered = token.base + (token.vowel or "")
        if rendered:
            builder.emit(rendered, token.start, token.end)
        else:
            builder.drop(token.start, token.end)
    return builder.build()


def transliteration_key(text: str, *, script_code: str) -> str:
    """A case-folded Latin key for lexicon matching, or the folded original.

    Falls back to the original when the script is not transliterable, so a
    caller matching aliases has one code path rather than a conditional that
    silently skips Urdu.
    """
    view = transliterate(text, script_code=script_code)
    return (view.transformed_text if view is not None else text).casefold()
