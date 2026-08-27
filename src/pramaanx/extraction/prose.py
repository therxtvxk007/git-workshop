"""Deterministic linguistic analysis of running text.

This module does the unglamorous half of extraction: splitting prose into
sentences, spotting the words that name an event, deciding whether the sentence
asserts or denies it, and turning "last Tuesday" into a timestamp.

It is rule-based on purpose, and the rules are visible. A learned extractor
belongs in the cascade as a *stage* with a measured error rate against a gold
set; until that gold set exists, a rule you can read and argue with beats a
model whose failure modes nobody has characterised. Being deterministic also
means the reproducibility test measures the pipeline rather than a sampling
temperature.

The one rule everything else here depends on: relative dates resolve against
the *observation's availability instant*, never against a wall clock. "Yesterday"
in a document that became available in March 2024 means March 2024, whatever
day the extractor happens to run.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

#: Coarse event vocabulary. Each key is an event type; each value holds the
#: stems that trigger it. Stems are matched on word boundaries after casefolding,
#: so "shelling" fires "shell" but "seashell" does not fire on a bare "shell".
#:
#: Deliberately conflict- and humanitarian-shaped, because that is what the
#: connectors feed it. Extending this table is a data decision and should come
#: with gold-set evidence that the new trigger earns its false positives.
EVENT_TRIGGERS: dict[str, tuple[str, ...]] = {
    "armed_clash": ("clash", "firefight", "gun battle", "gunbattle", "skirmish", "exchange of fire"),
    "armed_assault": ("attack", "assault", "raid", "ambush", "storm"),
    "bombing": ("bomb", "ied", "explosion", "blast", "detonat", "landmine"),
    "shelling": ("shell", "artillery", "mortar", "rocket", "airstrike", "air strike"),
    "abduction": ("abduct", "kidnap", "hostage", "seize", "captur"),
    "arrest": ("arrest", "detain", "custody", "apprehend"),
    "killing": ("kill", "murder", "assassinat", "execut", "shot dead", "death toll"),
    "protest": ("protest", "demonstrat", "rally", "march", "sit-in", "strike"),
    "riot": ("riot", "unrest", "clashes with police", "vandal", "arson"),
    "displacement": ("displac", "flee", "fled", "refugee", "evacuat", "exodus"),
    "aid_delivery": ("aid convoy", "relief", "humanitarian assistance", "food distribution"),
    "flood": ("flood", "inundat", "deluge", "torrential"),
    "drought": ("drought", "crop failure", "famine", "food insecurity"),
    "earthquake": ("earthquake", "tremor", "seismic", "aftershock"),
    "cyclone": ("cyclone", "hurricane", "typhoon", "storm surge"),
    "disease_outbreak": ("outbreak", "epidemic", "cholera", "measles", "infection"),
    "election": ("election", "poll", "ballot", "referendum"),
    "ceasefire": ("ceasefire", "cease-fire", "truce", "peace deal", "peace accord"),
}

#: Cues that the sentence denies the event rather than asserting it. Checked
#: before the planned/possible cues, because "denied plans to" is a denial.
DENIAL_CUES: tuple[str, ...] = (
    "denied",
    "denies",
    "no reports of",
    "no evidence of",
    "did not take place",
    "did not occur",
    "never happened",
    "rejected claims",
    "dismissed reports",
    "false report",
    "unfounded",
)

#: Cues that the event is scheduled or intended rather than accomplished.
PLANNED_CUES: tuple[str, ...] = (
    "planned",
    "plans to",
    "scheduled",
    "will hold",
    "is set to",
    "due to begin",
    "announced it would",
    "intends to",
    "to be held",
    "upcoming",
)

#: Cues that the claim is hedged.
POSSIBLE_CUES: tuple[str, ...] = (
    "may ",
    "might ",
    "could ",
    "reportedly",
    "allegedly",
    "unconfirmed",
    "feared",
    "suspected",
    "believed to",
    "risk of",
    "warned of",
    "threatened to",
)

_MONTHS: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_WEEKDAYS: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

#: Abbreviations that end in a period without ending a sentence.
_ABBREVIATIONS = frozenset(
    {
        "mr", "mrs", "ms", "dr", "prof", "gen", "col", "lt", "sgt", "capt",
        "st", "no", "vs", "etc", "inc", "ltd", "govt", "dept", "approx",
        "u.s", "u.n", "u.k",
    }
)

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE = re.compile(r"\s+")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?(?:\s+(\d{4}))?\b",
)
_MDY = re.compile(
    r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
)
_RELATIVE_DAYS = re.compile(r"\b(today|yesterday|last night|overnight)\b", re.IGNORECASE)
_RELATIVE_UNITS = re.compile(
    r"\b(?:(\d{1,3})|a|an)\s+(day|days|week|weeks|month|months)\s+ago\b", re.IGNORECASE
)
_LAST_WEEKDAY = re.compile(
    r"\b(?:last|this past|on)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_PROPER_RUN = re.compile(r"\b([A-Z][\w'-]*(?:\s+(?:of|the|de|al|bin)?\s*[A-Z][\w'-]*)*)")

#: Capitalised words that are not names. Sentence-initial capitalisation makes
#: these unavoidable without a tagger, so they are listed rather than guessed at.
_NON_NAMES = frozenset(
    {
        "a", "after", "an", "and", "as", "at", "but", "during", "following", "for",
        "from", "he", "however", "in", "it", "meanwhile", "on", "one", "she",
        "since", "the", "their", "there", "they", "this", "to", "two", "we",
        "when", "while", "with", "several", "many", "some", "at least", "more",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    }
)

#: Prepositions that introduce a place. Order matters: the longest match wins,
#: so "in the outskirts of" beats a bare "in".
_LOCATION_MARKERS: tuple[str, ...] = (
    "on the outskirts of",
    "in the district of",
    "in the province of",
    "in the town of",
    "in the city of",
    "in the village of",
    "near the town of",
    "across",
    "throughout",
    "outside",
    "near",
    "in",
    "at",
)


def split_sentences(text: str) -> list[str]:
    """Split running text into sentences.

    Regex rather than a parser, with an abbreviation guard. The failure mode of
    over-splitting is a truncated span, which the gold set can see; the failure
    mode of a heavyweight dependency is a model download at import time, which
    the reproducibility test cannot tolerate.
    """
    collapsed = _WHITESPACE.sub(" ", text or "").strip()
    if not collapsed:
        return []
    pieces = _SENTENCE_BREAK.split(collapsed)
    sentences: list[str] = []
    for piece in pieces:
        stripped = piece.strip()
        if not stripped:
            continue
        if sentences:
            previous = sentences[-1]
            tail = previous.rstrip(".").rsplit(" ", 1)[-1].casefold()
            # Re-join when the previous fragment ended on a known abbreviation
            # or on a single initial ("J." in "J. Smith").
            if tail in _ABBREVIATIONS or (len(tail) == 1 and previous.endswith(".")):
                sentences[-1] = f"{previous} {stripped}"
                continue
        sentences.append(stripped)
    return sentences


def detect_event_types(sentence: str) -> list[str]:
    """Every event type triggered by this sentence, in deterministic order.

    Returns all matches rather than the best one. A sentence describing an
    airstrike that killed twelve people is genuinely two mentions, and picking
    one would discard a real claim. The cascade decides what to do with the
    ambiguity; the trigger layer does not get to hide it.
    """
    lowered = sentence.casefold()
    found: set[str] = set()
    for event_type, stems in EVENT_TRIGGERS.items():
        for stem in stems:
            if " " in stem:
                if stem in lowered:
                    found.add(event_type)
                    break
            elif re.search(rf"\b{re.escape(stem)}", lowered):
                found.add(event_type)
                break
    return sorted(found)


def detect_modality(sentence: str) -> str:
    """Classify what the sentence claims about the event's status.

    Checked in precedence order -- denial, then planned, then hedged -- because
    the cues co-occur and the outermost one governs. "Officials denied plans to
    withdraw" is a denial, not a plan.
    """
    lowered = sentence.casefold()
    if any(cue in lowered for cue in DENIAL_CUES):
        return "denied"
    if any(cue in lowered for cue in PLANNED_CUES):
        return "planned"
    if any(cue in lowered for cue in POSSIBLE_CUES):
        return "possible"
    return "asserted"


def _clamp_day(year: int, month: int, day: int) -> datetime | None:
    try:
        return datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None


def extract_date(sentence: str, *, reference: datetime, allow_future: bool) -> datetime | None:
    """Resolve the first date expression in ``sentence`` against ``reference``.

    ``reference`` is the observation's availability instant, never a wall clock.
    ``allow_future`` is set only for planned or hedged sentences: an asserted
    event dated to a bare "12 March" resolves to the most recent March that has
    already happened, because a document cannot assert an event that has not
    occurred yet.
    """
    if reference.tzinfo is None:
        raise ValueError("reference instant must be timezone-aware")

    iso = _ISO_DATE.search(sentence)
    if iso:
        parsed = _clamp_day(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if parsed is not None:
            return parsed

    relative = _RELATIVE_DAYS.search(sentence)
    if relative:
        token = relative.group(1).casefold()
        offset = 0 if token == "today" else 1
        return (reference - timedelta(days=offset)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    units = _RELATIVE_UNITS.search(sentence)
    if units:
        count = int(units.group(1)) if units.group(1) else 1
        unit = units.group(2).casefold().rstrip("s")
        days = {"day": 1, "week": 7, "month": 30}[unit] * count
        return (reference - timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    weekday = _LAST_WEEKDAY.search(sentence)
    if weekday:
        target = _WEEKDAYS[weekday.group(1).casefold()]
        delta = (reference.weekday() - target) % 7 or 7
        return (reference - timedelta(days=delta)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    for pattern, order in ((_DMY, "dmy"), (_MDY, "mdy")):
        match = pattern.search(sentence)
        if not match:
            continue
        if order == "dmy":
            day_text, month_text, year_text = match.group(1), match.group(2), match.group(3)
        else:
            month_text, day_text, year_text = match.group(1), match.group(2), match.group(3)
        month = _MONTHS.get(month_text.casefold().rstrip("."))
        if month is None:
            continue
        day = int(day_text)
        if year_text:
            return _clamp_day(int(year_text), month, day)
        return _resolve_bare_date(
            month, day, reference=reference, allow_future=allow_future
        )
    return None


def _resolve_bare_date(
    month: int, day: int, *, reference: datetime, allow_future: bool
) -> datetime | None:
    """Pick the year for a date written without one.

    Backwards by default. A document asserting an event on "12 March" is
    talking about a March that has happened; resolving it forward would invent
    a future event and, worse, one dated after the cutoff that produced it.
    """
    candidate = _clamp_day(reference.year, month, day)
    if candidate is None:
        return None
    if allow_future:
        # Scheduled events may legitimately sit ahead of the reference, but only
        # within a year -- beyond that the bare date is more likely a typo than
        # a plan.
        if candidate < reference:
            forward = _clamp_day(reference.year + 1, month, day)
            if forward is not None and (forward - reference) <= timedelta(days=365):
                return forward
        return candidate
    if candidate > reference:
        return _clamp_day(reference.year - 1, month, day)
    return candidate


def extract_location(sentence: str) -> str | None:
    """Pull a place name out of a prepositional phrase.

    Only fires on an explicit marker. Any capitalised run in a sentence *could*
    be a place, and guessing produces location noise that entity resolution then
    dutifully turns into confident-looking entities.
    """
    for marker in _LOCATION_MARKERS:
        pattern = re.compile(rf"\b{re.escape(marker)}\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)")
        match = pattern.search(sentence)
        if match:
            candidate = match.group(1).strip(" ,.;:")
            if candidate and candidate.casefold() not in _NON_NAMES:
                return candidate
    return None


def extract_proper_names(sentence: str, *, skip: str | None = None) -> list[str]:
    """Capitalised runs that plausibly name somebody, in order of appearance.

    Sentence-initial words are dropped when they are ordinary vocabulary, which
    is the cheapest correction for the one systematic error this heuristic makes.
    """
    found: list[str] = []
    for match in _PROPER_RUN.finditer(sentence):
        candidate = _WHITESPACE.sub(" ", match.group(1)).strip(" ,.;:")
        if not candidate or candidate.casefold() in _NON_NAMES:
            continue
        if skip and candidate.casefold() == skip.casefold():
            continue
        if match.start() == 0 and len(candidate.split()) == 1:
            # A single capitalised word opening a sentence is not evidence.
            continue
        if candidate not in found:
            found.append(candidate)
    return found
