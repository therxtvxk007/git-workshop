"""Turning place names into district identities, or refusing to.

Source feeds name districts in prose: ACLED gives ``admin1``/``admin2``
strings, UCDP gives ``adm_1``/``adm_2``, news gives whatever the reporter
wrote. None of them carry LGD codes.

The resolver normalises aggressively (case, diacritics, the endless
``Dist.``/``District``/``Zilla`` suffixes) but decides conservatively. When a
name matches two districts in different states and no state was supplied, the
answer is :class:`Unresolved`, not the first match. An unresolved location is a
labelled state the panel carries through to the end; a wrong location is a row
that scores a real incident against the wrong place and quietly rewards the
model for it.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from pramaanx.geography.registry import DistrictRegistry
from pramaanx.schemas.geography import DistrictRef

#: Trailing words that carry no identifying information. Stripped only when
#: they trail: "District" in "District Council" is part of a name.
_SUFFIXES = ("district", "dist", "zilla", "zila", "jilla", "jila", "division")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalise_place_name(name: str) -> str:
    """Case-, accent- and suffix-insensitive form of a place name."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = _PUNCTUATION.sub(" ", stripped.lower())
    tokens = [token for token in _WHITESPACE.split(cleaned) if token]
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


@dataclass(frozen=True)
class Unresolved:
    """A name that could not be turned into exactly one district."""

    #: ``unknown`` (no match) or ``ambiguous`` (several).
    reason: str
    query: str
    candidates: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return False


@dataclass(frozen=True)
class Resolution:
    """Exactly one district, with the record that was in effect."""

    district: DistrictRef
    matched_on: str

    @property
    def district_id(self) -> str:
        return self.district.district_id

    def __bool__(self) -> bool:
        return True


class DistrictResolver:
    """Name -> district lookup, always as of a moment.

    ``aliases`` maps an alternate spelling to a district id; it is how known
    historical names and regional-language forms are supplied. It is data the
    operator provides, never something this class infers.
    """

    def __init__(
        self,
        registry: DistrictRegistry,
        *,
        aliases: Iterable[tuple[str, str]] = (),
    ) -> None:
        self._registry = registry
        self._aliases: dict[str, set[str]] = defaultdict(set)
        for alias, district_id in aliases:
            self._aliases[normalise_place_name(alias)].add(district_id)

    def resolve(
        self,
        district_name: str,
        *,
        moment: datetime,
        state_name: str | None = None,
    ) -> Resolution | Unresolved:
        """Resolve one district name in the universe in effect at ``moment``."""
        query = normalise_place_name(district_name)
        if not query:
            return Unresolved(reason="unknown", query=district_name)

        universe = self._registry.as_of(moment)
        state_filter = normalise_place_name(state_name) if state_name else None
        if state_filter:
            in_state = [
                record
                for record in universe
                if normalise_place_name(record.state_name) == state_filter
            ]
            # A state name that matches nothing is itself a resolution failure:
            # narrowing to an empty set and then searching the whole country
            # would turn a typo'd state into a nationwide guess.
            if not in_state:
                return Unresolved(reason="unknown", query=f"{district_name}, {state_name}")
            universe = in_state

        matches = [
            record for record in universe if normalise_place_name(record.district_name) == query
        ]
        matched_on = "name"
        if not matches:
            alias_targets = self._aliases.get(query, set())
            matches = [record for record in universe if record.district_id in alias_targets]
            matched_on = "alias"

        if not matches:
            return Unresolved(reason="unknown", query=district_name)
        if len(matches) > 1:
            return Unresolved(
                reason="ambiguous",
                query=district_name,
                candidates=tuple(sorted(record.district_id for record in matches)),
            )
        return Resolution(district=matches[0], matched_on=matched_on)
