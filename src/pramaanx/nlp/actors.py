"""Named actors, matched against aliases that know what year it is.

Organisations rename, merge, split and get proscribed under new names. An alias
table without dates answers "who is this?" with today's answer, which
retroactively rewrites what an article from three years ago was about. So the
registry here is effective-dated on half-open intervals, exactly like WP1's news
source registry and for the same reason: the question is not "what is this
group called" but "what was this name attached to on the day this was written".

Two things this module deliberately will not do.

**It will not infer identity from ideology or geography.** An article about an
attack in Bastar does not thereby mention a Maoist group; an article using the
word "militant" does not name anyone. Matching is literal, against declared
aliases, and an unmatched name stays unmatched. Inferring the actor from the
district would make actor features a restatement of location features, and the
model would learn a circularity rather than a fact.

**It will not pick one actor when an alias is shared.** Ambiguous aliases return
every candidate. Choosing the more famous one is how a small local outfit's
activity gets attributed to a national organisation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import model_validator

from pramaanx.hashing import hash_object
from pramaanx.nlp.schemas import ActorMention, ResolutionStatus, TextSpan
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel

ACTORS_VERSION = "nlp-actors/1.0.0"


class AliasKind(StrEnum):
    """Why this string maps to this actor. Recorded for auditing, not branching."""

    OFFICIAL_NAME = "official_name"
    ABBREVIATION = "abbreviation"
    ALTERNATE_SPELLING = "alternate_spelling"
    TRANSLITERATION = "transliteration"
    ORGANISATION_ALIAS = "organisation_alias"
    FORMER_NAME = "former_name"


class ActorRegistryError(ValueError):
    """The alias registry is inconsistent, or would have to guess."""


class ActorAlias(VersionedModel):
    """One surface string, valid for one actor over one interval."""

    alias_text: str
    canonical_actor_id: str
    kind: AliasKind = AliasKind.OFFICIAL_NAME
    #: ISO 639-1 code of the alias, when it is language-specific. A Devanagari
    #: alias and its Latin transliteration are separate entries, so a match can
    #: say which one fired.
    language: str | None = None
    script: str | None = None
    effective_from: UtcDatetime
    #: Exclusive. ``None`` means still current.
    effective_to: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check_interval(self) -> ActorAlias:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ActorRegistryError(
                f"alias {self.alias_text!r} for {self.canonical_actor_id}: effective_to must "
                "be strictly after effective_from, or the alias can never match anything"
            )
        if not self.alias_text.strip():
            raise ActorRegistryError("an alias cannot be blank")
        return self

    def covers(self, moment: datetime) -> bool:
        if moment < self.effective_from:
            return False
        return self.effective_to is None or moment < self.effective_to

    @property
    def key(self) -> str:
        """The case-folded form used for lookup."""
        return self.alias_text.casefold()


class ActorResolution(PramaanModel):
    """What an alias lookup found."""

    status: ResolutionStatus
    canonical_actor_id: str | None = None
    candidate_actor_ids: tuple[str, ...] = ()


class ActorAliasRegistry(PramaanModel):
    """Every alias for every actor, resolvable as of a date.

    Unlike the news source registry, overlapping intervals are *allowed* here --
    an actor legitimately has several current aliases, and two actors can share
    one. What is not allowed is resolving a shared alias to a single actor; that
    surfaces as :attr:`ResolutionStatus.AMBIGUOUS`.
    """

    aliases: tuple[ActorAlias, ...] = ()
    display_names: dict[str, str] = {}

    @property
    def alias_version(self) -> str:
        """Content hash of the registry, recorded on every mention it produces.

        A mention carrying the registry version can be re-checked later against
        the exact alias table that produced it. Without it, "resolved to
        actor_17" is unfalsifiable once the table changes.
        """
        return f"{ACTORS_VERSION}+{hash_object([alias.model_dump(mode='json') for alias in sorted(self.aliases, key=lambda item: (item.alias_text, item.canonical_actor_id, item.effective_from))])[:24]}"

    def actors_for(self, alias_text: str, moment: datetime) -> tuple[str, ...]:
        """Every actor this alias could mean at ``moment``, sorted.

        Sorting is what makes the registry order-independent: two registries
        holding the same aliases in different order must resolve identically,
        because the order a YAML file happens to list aliases in is not a fact
        about the world.
        """
        if moment.tzinfo is None:
            raise ActorRegistryError("actor lookup requires a timezone-aware moment")
        instant = moment.astimezone(UTC)
        key = alias_text.casefold()
        return tuple(
            sorted(
                {
                    alias.canonical_actor_id
                    for alias in self.aliases
                    if alias.key == key and alias.covers(instant)
                }
            )
        )

    def resolve(self, alias_text: str, moment: datetime) -> ActorResolution:
        candidates = self.actors_for(alias_text, moment)
        if not candidates:
            return ActorResolution(status=ResolutionStatus.UNRESOLVED)
        if len(candidates) == 1:
            return ActorResolution(
                status=ResolutionStatus.RESOLVED, canonical_actor_id=candidates[0]
            )
        return ActorResolution(status=ResolutionStatus.AMBIGUOUS, candidate_actor_ids=candidates)

    def display_name(self, actor_id: str) -> str | None:
        """The human-readable name, kept apart from the identifier on purpose."""
        return self.display_names.get(actor_id)

    def active_aliases(self, moment: datetime) -> tuple[ActorAlias, ...]:
        instant = moment.astimezone(UTC)
        return tuple(
            sorted(
                (alias for alias in self.aliases if alias.covers(instant)),
                key=lambda alias: (-len(alias.alias_text), alias.key, alias.canonical_actor_id),
            )
        )

    @classmethod
    def from_entries(cls, entries: Iterable[ActorAlias], **names: str) -> ActorAliasRegistry:
        return cls(aliases=tuple(entries), display_names=dict(names))


def extract_actor_mentions(
    text: str,
    *,
    registry: ActorAliasRegistry,
    as_of: datetime,
) -> tuple[ActorMention, ...]:
    """Find every alias present in ``text``, at the length that matches longest.

    Longest-first matching means "Communist Party of India (Maoist)" is one
    mention rather than three overlapping ones, and it is why
    :meth:`ActorAliasRegistry.active_aliases` sorts by descending length. Matches
    are found on word boundaries so that an abbreviation does not fire inside an
    unrelated word.
    """
    if as_of.tzinfo is None:
        raise ActorRegistryError("actor extraction requires a timezone-aware as_of")
    version = registry.alias_version
    claimed: list[tuple[int, int]] = []
    mentions: list[ActorMention] = []

    for alias in registry.active_aliases(as_of):
        pattern = re.compile(rf"(?<!\w){re.escape(alias.alias_text)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            if any(start < taken_end and taken_start < end for taken_start, taken_end in claimed):
                continue
            resolution = registry.resolve(alias.alias_text, as_of)
            claimed.append((start, end))
            mentions.append(
                ActorMention(
                    span=TextSpan.over(text, start, end),
                    canonical_actor_id=resolution.canonical_actor_id,
                    matched_alias=alias.alias_text,
                    alias_version=version,
                    status=resolution.status,
                    candidate_actor_ids=resolution.candidate_actor_ids,
                )
            )

    return tuple(sorted(mentions, key=lambda mention: mention.span.start))


EMPTY_REGISTRY = ActorAliasRegistry()
"""The default. An empty registry resolves nothing, which is the correct
behaviour for a pipeline whose actor table has not been supplied: no actors are
found, rather than actors being guessed from context."""
