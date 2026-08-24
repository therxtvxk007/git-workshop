"""Boilerplate removal, language identification, source resolution.

All three are cheap and all three protect a later stage from a specific error:
boilerplate inflates BM25 term statistics, a misidentified language routes text
to the wrong extractor, and an unresolved source makes independence counting
meaningless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..types import Document

# Wire-service furniture, legal footers, subscription interstitials. Matched
# conservatively: over-eager stripping deletes the sentence carrying the signal.
BOILERPLATE_PATTERNS = (
    re.compile(r"\(Agency copy\.\)", re.IGNORECASE),
    re.compile(r"\(Reporting by [^)]{0,80}\)", re.IGNORECASE),
    re.compile(r"©\s?\d{4}[^.]{0,60}\.", re.IGNORECASE),
    re.compile(r"All rights reserved\.?", re.IGNORECASE),
    re.compile(r"Subscribe (?:now|today)[^.]{0,60}\.", re.IGNORECASE),
    re.compile(r"Click here to [^.]{0,60}\.", re.IGNORECASE),
    re.compile(r"This (?:article|story) (?:was|has been) (?:updated|corrected)[^.]{0,80}\.", re.IGNORECASE),
    re.compile(r"Follow us on \w+[^.]{0,40}\.", re.IGNORECASE),
    re.compile(r"\[\s*\d+\s*(?:min|minute)s? read\s*\]", re.IGNORECASE),
)

# \xa0 is a non-breaking space: common in scraped HTML and invisible in a
# character class, so it is spelled out rather than pasted.
_WS = re.compile("[ \t\u00a0]+")
_MULTI_NL = re.compile(r"\n{3,}")

# Script-range heuristics. Enough to route between extractors; a deployment
# with genuinely multilingual feeds should swap in fastText lid.176 here.
_SCRIPTS = {
    "hi": (0x0900, 0x097F),   # Devanagari
    "bn": (0x0980, 0x09FF),
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F),
    "gu": (0x0A80, 0x0AFF),
    "pa": (0x0A00, 0x0A7F),
    "ar": (0x0600, 0x06FF),
    "zh": (0x4E00, 0x9FFF),
    "ru": (0x0400, 0x04FF),
}


@dataclass
class CleanReport:
    n_input: int = 0
    n_stripped: int = 0
    n_too_short: int = 0
    chars_removed: int = 0
    languages: dict[str, int] | None = None

    def summary(self) -> dict:
        return {"input": self.n_input, "stripped": self.n_stripped,
                "too_short": self.n_too_short, "chars_removed": self.chars_removed,
                "languages": self.languages or {}}


def strip_boilerplate(text: str) -> tuple[str, int]:
    original = len(text)
    for pat in BOILERPLATE_PATTERNS:
        text = pat.sub(" ", text)
    text = _WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text).strip()
    return text, original - len(text)


def detect_language(text: str, sample: int = 600) -> str:
    """Script-frequency identification. Returns an ISO-639-1 code, defaulting to
    English when the sample is dominated by Latin characters."""
    head = text[:sample]
    if not head:
        return "und"
    counts: dict[str, int] = {}
    latin = 0
    for ch in head:
        cp = ord(ch)
        if 0x41 <= cp <= 0x7A:
            latin += 1
            continue
        for lang, (lo, hi) in _SCRIPTS.items():
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if counts:
        best = max(counts, key=counts.get)
        if counts[best] > latin * 0.25:
            return best
    return "en" if latin else "und"


def resolve_source(doc: Document, family_map: dict[str, str] | None = None) -> str:
    """Map a source id to its syndication family.

    Independence is counted over families. Two feeds owned by the same wire are
    one voice however many outlets republish them, and treating them as two is
    the single easiest way to manufacture false corroboration.
    """
    if family_map and doc.source_id in family_map:
        return family_map[doc.source_id]
    existing = doc.meta.get("source_family")
    if existing:
        return str(existing)
    # Fall back to the leading token of the source id, which is how most feed
    # naming conventions encode the owning organisation.
    return doc.source_id.split("_")[0] if "_" in doc.source_id else doc.source_id


def clean_documents(
    docs: list[Document],
    *,
    strip: bool = True,
    min_tokens: int = 12,
    family_map: dict[str, str] | None = None,
) -> tuple[list[Document], CleanReport]:
    rep = CleanReport(n_input=len(docs), languages={})
    kept: list[Document] = []
    for d in docs:
        if strip:
            text, removed = strip_boilerplate(d.text)
            if removed:
                rep.n_stripped += 1
                rep.chars_removed += removed
            d.text = text
            d.boilerplate_stripped = True
        if len(d.full_text.split()) < min_tokens:
            rep.n_too_short += 1
            continue
        d.language = detect_language(d.full_text)
        rep.languages[d.language] = rep.languages.get(d.language, 0) + 1
        d.meta["source_family"] = resolve_source(d, family_map)
        kept.append(d)
    return kept, rep
