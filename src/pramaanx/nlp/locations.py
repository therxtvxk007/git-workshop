"""Finding place names, and refusing to resolve them without authority.

This module does exactly half of the location problem, and the division is the
important part.

**WP2 finds candidates.** Where in the text does a place name appear, what is
its surface form, and what state context surrounds it. That is a text problem,
and it belongs here.

**WP0 resolves them.** Which district identifier a name refers to, under which
boundary vintage, is a geography problem with a versioned registry behind it.
This package therefore defines :class:`DistrictResolver` as a seam and ships a
resolver that resolves nothing. Building a second district registry here --
even a small one, even "temporarily" -- would create exactly the duplicate
authority the work-package split exists to prevent, and the two would disagree
first about the districts that split in 2022.

The default is :class:`NullDistrictResolver`, which returns ``UNRESOLVED`` for
everything. That is a deliberately useless default, and a useless default is
correct here: a pipeline running without geography wired in should produce
visibly unresolved locations rather than plausible wrong ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from pramaanx.nlp.schemas import LocationMention, ResolutionStatus, TextSpan

LOCATIONS_VERSION = "nlp-locations/1.0.0"

#: The states and union territories of India. A small, closed, slow-changing
#: set, which is why it is safe to hold here while districts are not: there are
#: twenty-eight of them, they are not ambiguous with each other, and they
#: provide the context that disambiguates districts.
STATES: tuple[str, ...] = (
    "Andaman and Nicobar Islands",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Dadra and Nagar Haveli",
    "Daman and Diu",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu and Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Ladakh",
    "Lakshadweep",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Puducherry",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
)

_STATE_KEYS = {state.casefold(): state for state in STATES}

#: Words that mark the token before them as an administrative place. "Kishtwar
#: district" is a far stronger candidate than a bare capitalised word, and the
#: Devanagari and Bengali equivalents are included so the cue is not
#: English-only.
_PLACE_CUES = ("district", "tehsil", "taluka", "block", "subdivision", "जिला", "জেলা", "ജില്ല")

_CAPITALISED = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
_CUE = re.compile(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+(" + "|".join(_PLACE_CUES) + r")\b")
_IN_PREPOSITION = re.compile(r"\b(?:in|at|near|from|of)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")

#: Capitalised words that are common sentence openers or institutional names,
#: not places. Keeps the candidate list from being mostly noise without
#: pretending to be a gazetteer.
_STOP_CANDIDATES = frozenset(
    {
        "the",
        "police",
        "security",
        "forces",
        "government",
        "ministry",
        "court",
        "high",
        "supreme",
        "chief",
        "minister",
        "district",
        "state",
        "central",
        "india",
        "indian",
        "according",
        "officials",
        "official",
        "sources",
        # Pronouns and sentence openers: frequent, always capitalised at the
        # start of a quotation, and never a place.
        "we",
        "he",
        "she",
        "they",
        "it",
        "this",
        "that",
        "there",
        "these",
        "those",
        # Ranks and honorifics. "Superintendent of Police Ravi Kumar" is a
        # person; leaving these in made every named officer a place candidate.
        "superintendent",
        "inspector",
        "commissioner",
        "constable",
        "sub",
        "deputy",
        "additional",
        "director",
        "general",
        "colonel",
        "major",
        "captain",
        "brigadier",
        "shri",
        "smt",
        "dr",
        "mr",
        "mrs",
        "ms",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)


@dataclass(frozen=True)
class LocationQuery:
    """Everything a resolver is told, so nothing is inferred behind its back."""

    place_text: str
    state_context: str | None
    as_of: datetime
    language: str | None
    #: True when no state context was found and the search must cover all of
    #: India. Passed explicitly so a resolver can decline, and so the widening
    #: is recorded on the mention rather than being invisible.
    widened: bool


@dataclass(frozen=True)
class LocationResolution:
    """A resolver's answer. Candidates are always plural or absent."""

    status: ResolutionStatus
    candidate_district_ids: tuple[str, ...] = ()
    normalized_name: str | None = None
    resolver: str = "none"


@runtime_checkable
class DistrictResolver(Protocol):
    """The seam WP0's registry plugs into.

    ``as_of`` is required, not optional. A district that split in 2022 has two
    correct answers depending on the date being asked about, and a resolver
    signature that lets the caller omit the date guarantees that half the
    callers will.
    """

    name: str
    version: str

    def resolve(self, query: LocationQuery) -> LocationResolution: ...


class NullDistrictResolver:
    """Resolves nothing, on purpose.

    The default when geography is not wired in. Every location comes back
    ``UNRESOLVED``, which is honest and visibly incomplete -- as opposed to a
    "helpful" fallback matching on name similarity, which would be invisibly
    wrong and would silently attribute incidents to the wrong district.
    """

    name = "null"
    version = LOCATIONS_VERSION

    def resolve(self, query: LocationQuery) -> LocationResolution:
        return LocationResolution(
            status=ResolutionStatus.UNRESOLVED,
            normalized_name=query.place_text,
            resolver=self.name,
        )


def find_state_context(text: str) -> str | None:
    """The state named in ``text``, or ``None`` if it names none or several.

    Returning ``None`` for several is the conservative reading: an article
    mentioning both Karnataka and Chhattisgarh gives no single context, and
    picking the first would resolve "Bijapur" to whichever state the sub-editor
    happened to mention earlier.
    """
    found = {
        canonical
        for key, canonical in _STATE_KEYS.items()
        if re.search(rf"\b{re.escape(key)}\b", text.casefold())
    }
    if len(found) == 1:
        return found.pop()
    return None


def find_place_candidates(text: str) -> tuple[TextSpan, ...]:
    """Spans that plausibly name a place, longest and most-cued first.

    Three signals, in descending confidence: an explicit administrative cue
    ("X district"), a locative preposition ("in X"), and a bare capitalised
    sequence. All three are candidates only -- resolution decides what is real,
    and an over-inclusive candidate list costs a resolver lookup while a
    missing one loses the district entirely.
    """
    spans: dict[tuple[int, int], TextSpan] = {}

    def add(start: int, end: int) -> None:
        surface = text[start:end].strip()
        if not surface or surface.casefold() in _STOP_CANDIDATES:
            return
        if all(word.casefold() in _STOP_CANDIDATES for word in surface.split()):
            return
        trimmed_start = start + (len(text[start:end]) - len(text[start:end].lstrip()))
        trimmed_end = trimmed_start + len(surface)
        spans[(trimmed_start, trimmed_end)] = TextSpan.over(text, trimmed_start, trimmed_end)

    for match in _CUE.finditer(text):
        add(match.start(1), match.end(1))
    for match in _IN_PREPOSITION.finditer(text):
        add(match.start(1), match.end(1))
    for match in _CAPITALISED.finditer(text):
        add(match.start(1), match.end(1))

    ordered = sorted(spans.values(), key=lambda span: (span.start, -(span.end - span.start)))
    kept: list[TextSpan] = []
    for span in ordered:
        if any(span.start < existing.end and existing.start < span.end for existing in kept):
            continue
        kept.append(span)
    return tuple(kept)


def extract_location_mentions(
    text: str,
    *,
    as_of: datetime,
    resolver: DistrictResolver | None = None,
    language: str | None = None,
) -> tuple[LocationMention, ...]:
    """Candidate places, each passed to ``resolver`` with full context.

    The state context is computed once for the whole document and given to every
    query. When there is none, ``widened`` is set and travels onto the mention
    as ``search_widened`` -- so a national-scope match is always visible as one,
    and a reviewer can tell "Bijapur, Karnataka" from "Bijapur, somewhere".
    """
    if as_of.tzinfo is None:
        raise ValueError("location extraction requires a timezone-aware as_of")
    backend = resolver or NullDistrictResolver()
    state = find_state_context(text)
    mentions: list[LocationMention] = []

    for span in find_place_candidates(text):
        if span.text.casefold() in _STATE_KEYS:
            continue
        query = LocationQuery(
            place_text=span.text,
            state_context=state,
            as_of=as_of,
            language=language,
            widened=state is None,
        )
        resolution = backend.resolve(query)
        mentions.append(
            LocationMention(
                span=span,
                normalized_name=resolution.normalized_name or span.text,
                candidate_district_ids=resolution.candidate_district_ids,
                status=resolution.status,
                state_context=state,
                search_widened=query.widened,
                resolver=resolution.resolver,
            )
        )
    return tuple(mentions)
