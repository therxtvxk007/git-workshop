"""Builders shared by the WP1 news tests.

Kept out of ``conftest.py`` deliberately. These are constructors, not fixtures:
a test that needs a record with one field changed should say so in one line at
the point of use, rather than through a fixture whose parameters have to be
read somewhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pramaanx.hashing import hash_object
from pramaanx.ingest.article_content import (
    ArticleRecord,
    LicenceClass,
    RedistributionPermission,
    apply_retention,
    canonical_url,
    canonical_url_hash,
    dominant_script,
)
from pramaanx.ingest.news_registry import (
    AcquisitionMethod,
    NewsSourceEntry,
    NewsSourceRegistry,
    ResolvabilityPolicy,
    StorableField,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "news"

WINDOW_START = datetime(2026, 3, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 3, 8, tzinfo=UTC)
RETRIEVED = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)

FULL_TEXT_FIELDS: tuple[StorableField, ...] = (
    StorableField.HEADLINE,
    StorableField.BODY,
    StorableField.BYLINE,
    StorableField.URL,
    StorableField.TIMESTAMPS,
    StorableField.HASHES,
)


def entry(
    source_id: str = "outlet_a",
    *,
    licence: LicenceClass = LicenceClass.FULL_TEXT_PERMITTED,
    acquisition: AcquisitionMethod = AcquisitionMethod.RSS,
    languages: tuple[str, ...] = ("en",),
    regions: tuple[str, ...] = (),
    permitted: tuple[StorableField, ...] | None = None,
    expected_items_per_day: float | None = 10.0,
    effective_from: datetime = datetime(2024, 1, 1, tzinfo=UTC),
    effective_to: datetime | None = None,
    enabled: bool = True,
    wire_service: str | None = None,
    policy: ResolvabilityPolicy = ResolvabilityPolicy.RETRIEVAL,
    credential_env: str | None = None,
) -> NewsSourceEntry:
    """A registry entry with sane defaults, one keyword away from any variant."""
    if permitted is None:
        permitted = (
            FULL_TEXT_FIELDS
            if licence in {LicenceClass.FULL_TEXT_PERMITTED, LicenceClass.SNIPPET_ONLY}
            else (StorableField.HASHES,)
        )
    return NewsSourceEntry(
        source_id=source_id,
        display_name=f"Test source {source_id}",
        publisher="Test Publisher",
        acquisition=acquisition,
        languages=languages,
        regions=regions,
        licence_class=licence,
        redistribution=RedistributionPermission.INTERNAL_ONLY,
        permitted_fields=permitted,
        expected_items_per_day=expected_items_per_day,
        resolvability_policy=policy,
        wire_service=wire_service,
        credential_env=credential_env,
        enabled=enabled,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def registry(*entries: NewsSourceEntry) -> NewsSourceRegistry:
    return NewsSourceRegistry(entries=entries or (entry(),))


def record(
    *,
    source_id: str = "outlet_a",
    url: str = "https://example.test/story/1",
    headline: str | None = "A headline",
    body: str | None = "A body with several words in it for shingling purposes.",
    licence: LicenceClass = LicenceClass.FULL_TEXT_PERMITTED,
    published_at: datetime | None = datetime(2026, 3, 1, 6, 0, tzinfo=UTC),
    modified_at: datetime | None = None,
    retrieved_at: datetime = RETRIEVED,
    first_resolvable_at: datetime | None = None,
    language: str | None = "en",
    wire_service: str | None = None,
    revision_of: str | None = None,
    revision_index: int = 0,
    observation_id: str | None = None,
) -> ArticleRecord:
    """An :class:`ArticleRecord` built the way the connector builds one."""
    retained = apply_retention(licence=licence, headline=headline, body=body)
    resolvable = first_resolvable_at or retrieved_at
    canonical = canonical_url(url)
    identity = hash_object(
        {
            "source_id": source_id,
            "canonical_url": canonical,
            "normalised_content_hash": retained.normalised_content_hash,
            "first_resolvable_at": resolvable,
            "revision_index": revision_index,
        }
    )
    return ArticleRecord(
        observation_id=observation_id or ArticleRecord.build_id(source_id, identity, resolvable),
        source_id=source_id,
        source_record_id=f"{source_id}:{url}",
        canonical_url=canonical,
        canonical_url_hash=canonical_url_hash(canonical),
        headline=retained.headline,
        body_text=retained.body_text,
        body_hash=retained.body_hash,
        normalised_content_hash=retained.normalised_content_hash,
        body_characters=retained.body_characters,
        original_language=language,
        script=dominant_script(f"{headline or ''} {body or ''}"),
        published_at=published_at,
        modified_at=modified_at,
        retrieved_at=retrieved_at,
        first_resolvable_at=resolvable,
        wire_service=wire_service,
        licence_class=licence,
        redistribution=RedistributionPermission.INTERNAL_ONLY,
        retention_decision=retained.decision,
        article_content_hash=identity,
        revision_of=revision_of,
        revision_index=revision_index,
    )


WIRE_BODY = (
    "Security forces recovered a cache of explosives during a search operation "
    "in the district on Sunday, officials said, adding that no arrests had yet "
    "been made and the investigation was continuing."
)


def wire_copies(count: int = 5, *, wire: str | None = "PTI") -> list[ArticleRecord]:
    """The same agency file, carried by ``count`` different mastheads.

    Byte-identical bodies, different outlets, different URLs -- which is what a
    syndicated file actually looks like, and what must resolve to one lineage.
    """
    return [
        record(
            source_id=f"outlet_{index}",
            url=f"https://outlet{index}.test/story/{index}",
            headline="Explosives recovered in district search operation",
            body=WIRE_BODY,
            wire_service=wire,
        )
        for index in range(count)
    ]


def read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def reader_for(name: str) -> Callable[[], bytes]:
    """An injected byte reader backed by a recorded fixture."""

    def read() -> bytes:
        return read_fixture(name)

    return read
