"""A recall-protective screen that keeps anything it cannot rule out.

Most crime reporting in India is not about terrorism, insurgency or left-wing
extremism. Sending all of it to an LLM is expensive, so a cheap deterministic
screen earns its place. But a screen in front of an event-detection system is a
recall filter, and its two errors are not symmetric:

* keeping a burglary report costs a few thousand tokens;
* dropping an IED recovery loses the event, and no downstream stage can
  recover it, because nothing downstream ever sees the article.

So the screen is built to be wrong in the cheap direction. It returns
``LIKELY_ORDINARY_CRIME`` only when the text contains positive ordinary-crime
evidence **and** contains no indicator from the target families. Everything
else -- including text it simply cannot read -- is retained.

Absence of terrorism vocabulary is never evidence of ordinary crime. That
asymmetry is enforced by :class:`~pramaanx.nlp.schemas.OrdinaryCrimeAssessment`
itself, which refuses to validate a rejection with no supporting span.

**Protected traits are not features here, in either direction.** No religion,
caste, community, ethnicity, language group or nationality term appears in any
lexicon below, and :data:`FORBIDDEN_FEATURE_TERMS` exists so a test can assert
that it never will. Such a term would be a proxy that raises or lowers the
score of an article for who is in it rather than what happened, and there is no
version of this system in which that is acceptable -- including the version
where it would improve a metric.
"""

from __future__ import annotations

import re

from pramaanx.nlp.schemas import CrimeVerdict, OrdinaryCrimeAssessment, TextSpan

ORDINARY_CRIME_VERSION = "nlp-ordinary-crime/1.0.0"

#: Terms that must never appear in any lexicon in this module, asserted by
#: ``tests/unit/test_nlp_ordinary_crime.py``. The list is about *categories of
#: person*, not about violence: a screen that reads community membership as a
#: threat indicator, or as an exculpatory one, is discriminatory whichever
#: direction it points.
FORBIDDEN_FEATURE_TERMS: frozenset[str] = frozenset(
    {
        "hindu",
        "muslim",
        "christian",
        "sikh",
        "buddhist",
        "jain",
        "parsi",
        "dalit",
        "adivasi",
        "tribal",
        "brahmin",
        "scheduled caste",
        "scheduled tribe",
        "obc",
        "upper caste",
        "lower caste",
        "minority community",
        "majority community",
        "bengali",
        "bihari",
        "tamil",
        "kashmiri",
        "punjabi",
        "gujarati",
        "marathi",
        "rohingya",
        "bangladeshi",
        "nepali",
        "pakistani",
        "immigrant",
        "migrant",
        "madrasa",
        "mosque",
        "temple",
        "church",
        "gurudwara",
    }
)

#: Positive evidence that an article is about ordinary crime. Every entry names
#: an offence or a circumstance, never a person or a group.
ORDINARY_CRIME_TERMS: tuple[str, ...] = (
    "chain snatching",
    "chain-snatching",
    "pickpocket",
    "shoplifting",
    "burglary",
    "burglars",
    "house break-in",
    "housebreaking",
    "robbery",
    "robbers",
    "mugging",
    "theft",
    "stolen vehicle",
    "vehicle theft",
    "bike theft",
    "car theft",
    "cattle theft",
    "road rage",
    "drunken brawl",
    "drunken driving",
    "drink driving",
    "hit-and-run",
    "hit and run",
    "road accident",
    "traffic accident",
    "domestic dispute",
    "family dispute",
    "property dispute",
    "land dispute",
    "dowry harassment",
    "cheating case",
    "fraud case",
    "forgery",
    "chit fund",
    "ponzi",
    "embezzlement",
    "bribery case",
    "illicit liquor",
    "hooch",
    "gambling den",
    "matka",
    "kidnapping for ransom",
    "extortion racket",
    "gang war",
    "gangster",
    "moneylender",
    "loan shark",
)

#: Indicators that an article touches terrorism, insurgency or left-wing
#: extremism. Any one of these keeps the article, whatever else it contains.
#: Deliberately over-inclusive: this list controls recall.
TARGET_FAMILY_TERMS: tuple[str, ...] = (
    # Devices and methods
    "ied",
    "improvised explosive",
    "explosive device",
    "pressure cooker bomb",
    "landmine",
    "land mine",
    "grenade",
    "rocket launcher",
    "under-barrel",
    "car bomb",
    "vbied",
    "suicide bomber",
    "suicide attack",
    "sticky bomb",
    "blast",
    "explosion",
    "detonator",
    "gelatin stick",
    "ammonium nitrate",
    "arms cache",
    "weapons cache",
    "ammunition dump",
    "arms haul",
    # Actors and organisation
    "militant",
    "militants",
    "insurgent",
    "insurgency",
    "terrorist",
    "terrorism",
    "terror module",
    "sleeper cell",
    "cadre",
    "overground worker",
    "ogw",
    "maoist",
    "naxal",
    "naxalite",
    "left wing extremism",
    "left-wing extremism",
    "lwe",
    "banned outfit",
    "proscribed organisation",
    "outlawed group",
    "extremist group",
    "armed group",
    "underground outfit",
    # Operations and law
    "encounter",
    "ambush",
    "counter-insurgency",
    "cordon and search",
    "search operation",
    "security forces",
    "paramilitary",
    "crpf",
    "assam rifles",
    "anti-terror",
    "uapa",
    "unlawful activities",
    "nia",
    "ats",
    "infiltration",
    "cross-border",
    "ceasefire violation",
    # Targets
    "attack on security",
    "convoy attack",
    "police post attack",
    "railway track blown",
    "tower blown",
    "school blown",
)

_ORDINARY = tuple(
    (term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE))
    for term in ORDINARY_CRIME_TERMS
)
_TARGET = tuple(
    (term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE))
    for term in TARGET_FAMILY_TERMS
)


def _matches(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> tuple[TextSpan, ...]:
    found: list[tuple[int, int]] = []
    for _, pattern in patterns:
        found.extend((match.start(), match.end()) for match in pattern.finditer(text))
    ordered = sorted(found, key=lambda pair: (pair[0], -(pair[1] - pair[0])))
    kept: list[TextSpan] = []
    for start, end in ordered:
        if any(start < span.end and span.start < end for span in kept):
            continue
        kept.append(TextSpan.over(text, start, end))
    return tuple(kept)


def assess_ordinary_crime(text: str) -> OrdinaryCrimeAssessment:
    """Screen ``text``, keeping anything that might belong to a target family.

    The three outcomes and exactly when each applies:

    ``POTENTIALLY_RELEVANT``
        any target-family indicator is present. Ordinary-crime vocabulary
        alongside it changes nothing -- an extortion racket run by a proscribed
        outfit is both, and the article is kept.
    ``LIKELY_ORDINARY_CRIME``
        ordinary-crime evidence present and no target-family indicator at all.
    ``INSUFFICIENT_EVIDENCE``
        neither fired. Retained, because "this screen could not read the
        article" is not a finding about the article -- and regional-language
        text, which these English lexicons do not cover, lands here.
    """
    target_spans = _matches(text, _TARGET)
    ordinary_spans = _matches(text, _ORDINARY)

    if target_spans:
        return OrdinaryCrimeAssessment(
            verdict=CrimeVerdict.POTENTIALLY_RELEVANT,
            ordinary_crime_spans=ordinary_spans,
            target_family_spans=target_spans,
            reason=(
                f"{len(target_spans)} target-family indicator(s) present; retained regardless "
                f"of the {len(ordinary_spans)} ordinary-crime indicator(s) also found"
            ),
        )

    if ordinary_spans:
        return OrdinaryCrimeAssessment(
            verdict=CrimeVerdict.LIKELY_ORDINARY_CRIME,
            ordinary_crime_spans=ordinary_spans,
            target_family_spans=(),
            reason=(
                f"{len(ordinary_spans)} ordinary-crime indicator(s) and no terrorism, "
                "insurgency or LWE indicator"
            ),
        )

    return OrdinaryCrimeAssessment(
        verdict=CrimeVerdict.INSUFFICIENT_EVIDENCE,
        reason=(
            "no indicator of either kind fired. The article is retained: this screen's "
            "lexicons are English-only, so silence here often means the text was not "
            "readable by it rather than that the article is irrelevant."
        ),
    )


def lexicon_terms() -> frozenset[str]:
    """Every term in every lexicon, for the protected-trait assertion."""
    return frozenset(term.casefold() for term in ORDINARY_CRIME_TERMS + TARGET_FAMILY_TERMS)
