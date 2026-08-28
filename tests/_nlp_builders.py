"""Builders and fixtures shared by the WP2 NLP tests.

Reuses ``_news_builders.record`` rather than constructing ``ArticleRecord`` a
second way. WP2's job is to consume exactly what WP1 produces, so a test that
built its own article shape could pass while the real integration was broken.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pramaanx.nlp.actors import ActorAlias, ActorAliasRegistry, AliasKind
from pramaanx.nlp.locations import LocationQuery, LocationResolution
from pramaanx.nlp.schemas import ResolutionStatus

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nlp"

CUTOFF = datetime(2026, 3, 5, tzinfo=UTC)
PUBLISHED = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
RESOLVABLE = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
#: A Sunday, so weekday arithmetic in the temporal tests has a fixed reference.
ANCHOR = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)


@lru_cache(maxsize=1)
def fixtures() -> dict[str, Any]:
    return json.loads((FIXTURES / "sentences.json").read_text(encoding="utf-8"))


def language_fixture(code: str) -> dict[str, Any]:
    return fixtures()["languages"][code]


def edge_case(name: str) -> str:
    return fixtures()["edge_cases"][name]["text"]


def language_codes() -> tuple[str, ...]:
    return tuple(sorted(fixtures()["languages"]))


class StubResolver:
    """A district resolver whose answers the test states outright.

    Exists so that WP2's tests exercise the *seam* without depending on WP0.
    Keyed on the surface form, so a test can say "Bijapur is ambiguous" and
    "Kishtwar resolves" without a geography package being present.
    """

    name = "stub"
    version = "test"

    def __init__(self, answers: dict[str, tuple[str, ...]] | None = None) -> None:
        self.answers = answers or {}
        self.queries: list[LocationQuery] = []

    def resolve(self, query: LocationQuery) -> LocationResolution:
        self.queries.append(query)
        candidates = self.answers.get(query.place_text, ())
        if not candidates:
            status = ResolutionStatus.UNRESOLVED
        elif len(candidates) == 1:
            status = ResolutionStatus.RESOLVED
        else:
            status = ResolutionStatus.AMBIGUOUS
        return LocationResolution(
            status=status,
            candidate_district_ids=candidates,
            normalized_name=query.place_text,
            resolver=self.name,
        )


def alias(
    text: str,
    actor_id: str,
    *,
    kind: AliasKind = AliasKind.OFFICIAL_NAME,
    effective_from: datetime = datetime(2020, 1, 1, tzinfo=UTC),
    effective_to: datetime | None = None,
    language: str | None = None,
) -> ActorAlias:
    return ActorAlias(
        alias_text=text,
        canonical_actor_id=actor_id,
        kind=kind,
        language=language,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def registry_of(*aliases: ActorAlias, **names: str) -> ActorAliasRegistry:
    return ActorAliasRegistry.from_entries(aliases, **names)
