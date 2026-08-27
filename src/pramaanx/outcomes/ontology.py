"""What counts as a qualifying incident, stated once.

Two datasets, two taxonomies, one target. ACLED classifies by
``disorder_type``/``event_type``/``sub_event_type``; UCDP by ``type_of_violence``
plus actor identity. Neither has a category called "terrorism", and inventing
one by keyword search over event descriptions is how a research target turns
into whatever the keywords happened to match.

So the mapping is an explicit table, and anything not in it is *excluded* --
returned as ``None``, counted, and reported. An unmapped category is a visible
gap in coverage. A category silently swept into the nearest family is a
redefinition of the outcome that no metric will ever reveal.

Every entry says which family it feeds and why. Changing an entry changes the
research target, so it changes ``ONTOLOGY_VERSION`` too, and a panel built
under one version cannot be mixed with a panel built under another.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

ONTOLOGY_VERSION = "families-2026-08-27"


class EventFamily(StrEnum):
    """The families this project forecasts. Deliberately few and separable."""

    TERRORISM = "terrorism"
    LEFT_WING_EXTREMISM = "left_wing_extremism"
    INSURGENCY = "insurgency"


#: ACLED ``(event_type, sub_event_type)`` -> family. Sub-event granularity is
#: needed because ``Violence against civilians`` covers both a Maoist ambush and
#: a communal lynching, and only one of those is this project's target.
#:
#: An empty sub-event means "every sub-event of this event type".
ACLED_EVENT_MAP: Mapping[tuple[str, str], EventFamily] = {
    # Battles between a state force and a non-state armed group. Which family it
    # belongs to is decided by the actor, not the tactic, so these route through
    # ACLED_ACTOR_FAMILIES below and are only a *candidate* here.
    ("Battles", "Armed clash"): EventFamily.INSURGENCY,
    ("Battles", "Government regains territory"): EventFamily.INSURGENCY,
    ("Battles", "Non-state actor overtakes territory"): EventFamily.INSURGENCY,
    ("Explosions/Remote violence", "Remote explosive/landmine/IED"): EventFamily.TERRORISM,
    ("Explosions/Remote violence", "Grenade"): EventFamily.TERRORISM,
    ("Explosions/Remote violence", "Suicide bomb"): EventFamily.TERRORISM,
    ("Explosions/Remote violence", "Shelling/artillery/missile attack"): EventFamily.INSURGENCY,
    ("Violence against civilians", "Attack"): EventFamily.TERRORISM,
    ("Violence against civilians", "Abduction/forced disappearance"): EventFamily.INSURGENCY,
}

#: Actor-name fragments that override the tactic-based family. Matched
#: case-insensitively against ACLED's ``actor1``/``actor2``. The list is short
#: and named on purpose: an actor list that tries to be exhaustive becomes a
#: political claim, and a long one drifts out of date silently.
ACLED_ACTOR_FAMILIES: Mapping[str, EventFamily] = {
    "cpi-maoist": EventFamily.LEFT_WING_EXTREMISM,
    "communist party of india (maoist)": EventFamily.LEFT_WING_EXTREMISM,
    "naxal": EventFamily.LEFT_WING_EXTREMISM,
    "plfi": EventFamily.LEFT_WING_EXTREMISM,
    "ulfa": EventFamily.INSURGENCY,
    "nscn": EventFamily.INSURGENCY,
    "nlft": EventFamily.INSURGENCY,
    "pla (india)": EventFamily.INSURGENCY,
}

#: UCDP GED ``type_of_violence`` -> family. UCDP's three-way split is coarser
#: than the target, so only one-sided violence and non-state conflict map at
#: all, and state-based conflict routes through the actor test as well.
UCDP_VIOLENCE_MAP: Mapping[int, EventFamily] = {
    1: EventFamily.INSURGENCY,  # state-based armed conflict
    2: EventFamily.INSURGENCY,  # non-state conflict
    3: EventFamily.TERRORISM,  # one-sided violence against civilians
}

#: Excluded outright, with the reason. Ordinary crime and protest policing are
#: the two categories most likely to be swept in by a keyword approach and most
#: likely to swamp the base rate if they are.
EXCLUDED_REASONS: Mapping[str, str] = {
    "Protests": "protest and its policing are a different phenomenon and a different base rate",
    "Riots": "communal and mob violence is out of scope for this target",
    "Strategic developments": "not an incident; ACLED uses it for context records",
}


class OntologyError(ValueError):
    """A row could not be classified and was not explicitly excluded."""


def _actor_family(actors: tuple[str, ...]) -> EventFamily | None:
    for actor in actors:
        lowered = actor.lower()
        for fragment, family in ACLED_ACTOR_FAMILIES.items():
            if fragment in lowered:
                return family
    return None


def classify_acled(
    *,
    event_type: str,
    sub_event_type: str,
    actors: tuple[str, ...] = (),
) -> EventFamily | None:
    """Family for one ACLED row, or ``None`` if it does not qualify.

    Actor identity wins over tactic where both apply: an IED laid by a Maoist
    unit is left-wing extremism, not generic terrorism, and putting it in the
    wrong family makes both families' base rates wrong at once.
    """
    if event_type in EXCLUDED_REASONS:
        return None
    candidate = ACLED_EVENT_MAP.get((event_type, sub_event_type))
    if candidate is None:
        candidate = ACLED_EVENT_MAP.get((event_type, ""))
    if candidate is None:
        return None
    return _actor_family(actors) or candidate


def classify_ucdp(
    *,
    type_of_violence: int,
    actors: tuple[str, ...] = (),
) -> EventFamily | None:
    """Family for one UCDP GED row, or ``None`` if it does not qualify."""
    candidate = UCDP_VIOLENCE_MAP.get(type_of_violence)
    if candidate is None:
        return None
    return _actor_family(actors) or candidate


def known_families() -> list[str]:
    return [family.value for family in EventFamily]
