"""Acquiring news articles under a declared licence, as of a declared cutoff.

The acquisition families this project needs -- licensed RSS/Atom, publisher
APIs, article URLs surfaced by GDELT, ReliefWeb reports, government feeds, and
archives a licensee supplies directly -- differ only in how bytes arrive and
which keys hold which field. They do not differ in what has to be true
afterwards: a canonical URL, four separate timestamps, a licence decision made
before anything is written, and a content hash that identifies the document.

So :class:`NewsAcquisition` is the narrow part -- bytes in, :class:`RawArticle`
out -- and :class:`NewsConnector` is the wide part that every family shares.
Adding a publisher becomes a registry entry plus, at most, a field map; it is
not a new module with its own opinion about timestamps.

Nothing here calls the network. Every adapter takes an injected reader, which
the tests fill with recorded fixtures and a live deployment fills with the
project's existing HTTP client. That split is why the offline suite can prove
cutoff behaviour: a test that has to reach a publisher to check a cutoff rule
is a test that checks the publisher's uptime.

This connector is deliberately **not** registered with
:func:`pramaanx.ingest.base.register_connector`. Registration requires an entry
in :data:`pramaanx.config.SOURCE_OPTION_MODELS` and in
:data:`pramaanx.ingest.contracts.SOURCE_CONTRACTS`, both of which are shared
integration surfaces that WP1 does not own. ``docs/integration/wp01_news.md``
records exactly what WP9 has to add.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pramaanx.clock import Clock, SystemClock
from pramaanx.ingest.article_content import (
    PARSER_VERSION,
    ArticleRecord,
    RetentionDecision,
    apply_retention,
    build_content_hash,
    canonical_url,
    canonical_url_hash,
    dominant_script,
)
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.news_registry import (
    NewsSourceEntry,
    NewsSourceRegistry,
    ResolvabilityPolicy,
    StorableField,
)

CONNECTOR_VERSION = "news-connector/1.0.0"

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


class NewsAcquisitionError(RuntimeError):
    """A feed or archive could not be read without guessing."""


@dataclass(frozen=True)
class RawArticle:
    """One article as a source described it, before any licence is applied.

    Deliberately holds the *acquired* headline and body even for sources that
    may not retain them. Discarding text is :func:`~pramaanx.ingest.
    article_content.apply_retention`'s job, and it needs the text in order to
    hash it. Nothing constructs an :class:`ArticleRecord` directly from one of
    these without going through that step.
    """

    source_record_id: str
    url: str
    retrieved_at: datetime
    headline: str | None = None
    body: str | None = None
    published_at: datetime | None = None
    modified_at: datetime | None = None
    language: str | None = None
    byline: str | None = None
    wire_service: str | None = None
    revision_of: str | None = None
    revision_index: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("retrieved_at", "published_at", "modified_at"):
            value = getattr(self, name)
            if isinstance(value, datetime) and value.tzinfo is None:
                raise NewsAcquisitionError(
                    f"RawArticle.{name} is naive. A guessed timezone is a cutoff bug "
                    "waiting to happen, so it is refused at the boundary."
                )


class NewsAcquisition:
    """Turns whatever a source hands over into :class:`RawArticle` values.

    A class rather than a ``Protocol`` so that the shared window check lives in
    one place: an adapter that returns an article from outside the requested
    window has misread a date field, and finding that out three stages later
    costs a rebuilt panel.
    """

    #: Which registry acquisition methods this adapter serves. Informational,
    #: and checked when a connector is assembled.
    method_name: str = "abstract"

    def fetch(self, window: FetchWindow) -> Iterable[RawArticle]:
        raise NotImplementedError

    def guarded_fetch(self, window: FetchWindow) -> Iterator[RawArticle]:
        for article in self.fetch(window):
            if not window.contains(article.retrieved_at):
                raise NewsAcquisitionError(
                    f"{type(self).__name__} returned an article retrieved at "
                    f"{article.retrieved_at.isoformat()}, outside the requested window "
                    f"[{window.start.isoformat()}, {window.end.isoformat()})"
                )
            yield article


def parse_feed_datetime(value: str) -> datetime:
    """Parse a feed timestamp, refusing to invent a timezone.

    RFC 822 (RSS) and ISO 8601 (Atom) are both accepted. A timestamp with no
    offset is rejected rather than assumed to be UTC: Indian publishers post in
    IST, and reading 09:00 IST as 09:00 UTC moves an article five and a half
    hours earlier -- across a cutoff boundary often enough to matter.
    """
    text = value.strip()
    if not text:
        raise NewsAcquisitionError("empty timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        from email.utils import parsedate_to_datetime

        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError) as error:
            raise NewsAcquisitionError(f"unparseable timestamp {value!r}") from error
    if parsed.tzinfo is None:
        raise NewsAcquisitionError(
            f"timestamp {value!r} carries no timezone offset. Assuming one would silently "
            "move the article across a cutoff boundary."
        )
    return parsed.astimezone(UTC)


class FeedAcquisition(NewsAcquisition):
    """Licensed RSS/Atom and government feeds.

    Government portals in India publish plain RSS, and so do most licensed
    newsroom feeds, so one parser serves both families. The bytes come from an
    injected reader; this class never opens a socket.

    A ``DOCTYPE`` declaration is refused before parsing. Feeds are attacker-
    influenced input, and an entity-expansion payload in a feed would be a
    denial of service delivered through the evidence pipeline.
    """

    method_name = "feed"

    def __init__(
        self,
        *,
        source_record_id_prefix: str,
        reader: Callable[[], bytes],
        retrieved_at: datetime,
        language: str | None = None,
        wire_service: str | None = None,
    ) -> None:
        if retrieved_at.tzinfo is None:
            raise NewsAcquisitionError("FeedAcquisition requires a timezone-aware retrieved_at")
        self._prefix = source_record_id_prefix
        self._reader = reader
        self._retrieved_at = retrieved_at.astimezone(UTC)
        self._language = language
        self._wire_service = wire_service

    def fetch(self, window: FetchWindow) -> Iterable[RawArticle]:
        del window  # the reader decides what it hands over; the guard checks it
        payload = self._reader()
        if _DOCTYPE.search(payload):
            raise NewsAcquisitionError(
                "feed declares a DOCTYPE; refusing to parse. Entity expansion in an "
                "attacker-influenced feed is a denial of service, not a formatting choice."
            )
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as error:
            raise NewsAcquisitionError(f"feed is not well-formed XML: {error}") from error

        items = root.findall(".//item")
        if items:
            return [self._from_rss(item) for item in items]
        entries = root.findall(f".//{_ATOM_NS}entry")
        if entries:
            return [self._from_atom(entry) for entry in entries]
        raise NewsAcquisitionError(
            "feed contains neither RSS <item> nor Atom <entry> elements. An empty parse "
            "result and an unrecognised dialect must not look the same."
        )

    def _from_rss(self, item: ElementTree.Element) -> RawArticle:
        link = _text(item, "link")
        if link is None:
            raise NewsAcquisitionError("RSS item has no <link>; it cannot be identified")
        published = _text(item, "pubDate")
        return RawArticle(
            source_record_id=f"{self._prefix}:{_text(item, 'guid') or link}",
            url=link,
            retrieved_at=self._retrieved_at,
            headline=_text(item, "title"),
            body=_text(item, "description"),
            published_at=parse_feed_datetime(published) if published else None,
            language=self._language,
            byline=_text(item, "author"),
            wire_service=self._wire_service,
        )

    def _from_atom(self, entry: ElementTree.Element) -> RawArticle:
        link_element = entry.find(f"{_ATOM_NS}link")
        link = link_element.get("href") if link_element is not None else None
        if not link:
            raise NewsAcquisitionError("Atom entry has no link href; it cannot be identified")
        published = _text(entry, f"{_ATOM_NS}published")
        updated = _text(entry, f"{_ATOM_NS}updated")
        author = entry.find(f"{_ATOM_NS}author")
        return RawArticle(
            source_record_id=f"{self._prefix}:{_text(entry, f'{_ATOM_NS}id') or link}",
            url=link,
            retrieved_at=self._retrieved_at,
            headline=_text(entry, f"{_ATOM_NS}title"),
            body=_text(entry, f"{_ATOM_NS}summary") or _text(entry, f"{_ATOM_NS}content"),
            published_at=parse_feed_datetime(published) if published else None,
            modified_at=parse_feed_datetime(updated) if updated else None,
            language=self._language,
            byline=_text(author, f"{_ATOM_NS}name") if author is not None else None,
            wire_service=self._wire_service,
        )


def _text(element: ElementTree.Element | None, tag: str) -> str | None:
    if element is None:
        return None
    found = element.find(tag)
    if found is None or found.text is None:
        return None
    stripped = found.text.strip()
    return stripped or None


@dataclass(frozen=True)
class FieldMap:
    """Where an API keeps each field this project needs.

    A declared map, rather than a per-publisher parser, is what makes the
    publisher-API, GDELT-article-URL and ReliefWeb families one implementation.
    Every key is named explicitly: an API that omits a mapped key raises, so a
    field silently disappearing from a response is a failure rather than a
    column of nulls.
    """

    record_id: str
    url: str
    headline: str | None = None
    body: str | None = None
    published_at: str | None = None
    modified_at: str | None = None
    language: str | None = None
    byline: str | None = None
    wire_service: str | None = None
    #: Dotted path to the list of records inside the response envelope.
    items_path: str = "items"


class JsonApiAcquisition(NewsAcquisition):
    """Publisher APIs, GDELT-derived article lists and ReliefWeb reports.

    All three answer with JSON whose shape differs only in key names, so they
    are one adapter plus a :class:`FieldMap`. Bytes come from an injected
    reader; the envelope path is declared rather than guessed.
    """

    method_name = "json_api"

    def __init__(
        self,
        *,
        source_record_id_prefix: str,
        reader: Callable[[], bytes],
        field_map: FieldMap,
        retrieved_at: datetime,
        language: str | None = None,
        wire_service: str | None = None,
    ) -> None:
        if retrieved_at.tzinfo is None:
            raise NewsAcquisitionError("JsonApiAcquisition requires a timezone-aware retrieved_at")
        self._prefix = source_record_id_prefix
        self._reader = reader
        self._map = field_map
        self._retrieved_at = retrieved_at.astimezone(UTC)
        self._language = language
        self._wire_service = wire_service

    def fetch(self, window: FetchWindow) -> Iterable[RawArticle]:
        del window
        try:
            document = json.loads(self._reader())
        except json.JSONDecodeError as error:
            raise NewsAcquisitionError(f"response is not valid JSON: {error}") from error

        cursor: Any = document
        for part in self._map.items_path.split("."):
            if not isinstance(cursor, Mapping) or part not in cursor:
                raise NewsAcquisitionError(
                    f"response has no {self._map.items_path!r} path (stopped at {part!r}). "
                    "A missing envelope path must not read as an empty result set."
                )
            cursor = cursor[part]
        if not isinstance(cursor, list):
            raise NewsAcquisitionError(f"{self._map.items_path!r} is not a list")
        return [self._from_item(item) for item in cursor]

    def _from_item(self, item: Any) -> RawArticle:
        if not isinstance(item, Mapping):
            raise NewsAcquisitionError(f"record is not an object: {item!r}")

        def read(key: str | None) -> Any:
            if key is None:
                return None
            if key not in item:
                raise NewsAcquisitionError(
                    f"record is missing mapped field {key!r}. A mapped field that vanished "
                    "upstream is a contract change, not a null."
                )
            return item[key]

        published = read(self._map.published_at)
        modified = read(self._map.modified_at)
        return RawArticle(
            source_record_id=f"{self._prefix}:{read(self._map.record_id)}",
            url=str(read(self._map.url)),
            retrieved_at=self._retrieved_at,
            headline=_optional_str(read(self._map.headline)),
            body=_optional_str(read(self._map.body)),
            published_at=parse_feed_datetime(str(published)) if published else None,
            modified_at=parse_feed_datetime(str(modified)) if modified else None,
            language=_optional_str(read(self._map.language)) or self._language,
            byline=_optional_str(read(self._map.byline)),
            wire_service=_optional_str(read(self._map.wire_service)) or self._wire_service,
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class LicensedArchiveAcquisition(NewsAcquisition):
    """A licensee-supplied archive: one JSON object per line.

    The path a licensed corpus actually arrives by. Reading it from disk rather
    than from a network call is a feature: the archive is the licensed artefact,
    and re-fetching it would replace evidence somebody paid for and froze with
    whatever the publisher serves today.
    """

    method_name = "licensed_archive"

    def __init__(
        self,
        *,
        source_record_id_prefix: str,
        path: Path,
        retrieved_at: datetime,
        language: str | None = None,
        wire_service: str | None = None,
    ) -> None:
        if retrieved_at.tzinfo is None:
            raise NewsAcquisitionError(
                "LicensedArchiveAcquisition requires a timezone-aware retrieved_at"
            )
        self._prefix = source_record_id_prefix
        self._path = Path(path)
        self._retrieved_at = retrieved_at.astimezone(UTC)
        self._language = language
        self._wire_service = wire_service

    def fetch(self, window: FetchWindow) -> Iterable[RawArticle]:
        del window
        if not self._path.exists():
            raise NewsAcquisitionError(f"licensed archive not found: {self._path}")
        articles: list[RawArticle] = []
        for number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise NewsAcquisitionError(
                    f"{self._path}:{number} is not valid JSON: {error}"
                ) from error
            published = record.get("published_at")
            modified = record.get("modified_at")
            articles.append(
                RawArticle(
                    source_record_id=f"{self._prefix}:{record['record_id']}",
                    url=str(record["url"]),
                    retrieved_at=self._retrieved_at,
                    headline=_optional_str(record.get("headline")),
                    body=_optional_str(record.get("body")),
                    published_at=parse_feed_datetime(str(published)) if published else None,
                    modified_at=parse_feed_datetime(str(modified)) if modified else None,
                    language=_optional_str(record.get("language")) or self._language,
                    byline=_optional_str(record.get("byline")),
                    wire_service=_optional_str(record.get("wire_service")) or self._wire_service,
                    revision_of=_optional_str(record.get("revision_of")),
                    revision_index=int(record.get("revision_index", 0)),
                )
            )
        return articles


class NewsConnector:
    """Assembles licensed article records from one or more acquisitions.

    The connector owns the invariants every family shares: canonicalisation,
    the four timestamps, the licence decision, deterministic identifiers and
    ordering. An adapter that gets a date field wrong fails here rather than
    contributing a plausible-looking record.
    """

    connector_version = CONNECTOR_VERSION

    def __init__(
        self,
        registry: NewsSourceRegistry,
        acquisitions: Mapping[str, NewsAcquisition],
        *,
        clock: Clock | None = None,
    ) -> None:
        self.registry = registry
        self.acquisitions = dict(sorted(acquisitions.items()))
        self.clock = clock or SystemClock()
        unknown = sorted(set(self.acquisitions) - set(registry.source_ids()))
        if unknown:
            raise NewsAcquisitionError(
                f"acquisitions supplied for sources absent from the registry: {unknown}. "
                "A source with no registry entry has no licence, and a source with no "
                "licence may not be read."
            )

    def plan(self, window: FetchWindow, *, as_of: datetime) -> dict[str, Any]:
        """Describe what an acquisition would do, without doing it."""
        entries = {entry.source_id: entry for entry in self.registry.as_of(as_of)}
        return {
            "connector_version": self.connector_version,
            "parser_version": PARSER_VERSION,
            "registry_version": self.registry.registry_version,
            "registry_hash": self.registry.registry_hash,
            "as_of": as_of.astimezone(UTC).isoformat(),
            "window_start": window.start.isoformat(),
            "window_end": window.end.isoformat(),
            "sources": [
                {
                    "source_id": source_id,
                    "acquisition": type(acquisition).__name__,
                    "in_force": source_id in entries,
                    "licence_class": (
                        entries[source_id].licence_class.value if source_id in entries else None
                    ),
                    "vintage": entries[source_id].vintage_id if source_id in entries else None,
                }
                for source_id, acquisition in self.acquisitions.items()
            ],
        }

    def acquire(self, window: FetchWindow, *, as_of: datetime) -> tuple[ArticleRecord, ...]:
        """Every article record legally readable at ``as_of``, in a stable order.

        Sources with no vintage in force at ``as_of`` are skipped rather than
        read under today's terms. That is the whole reason the registry is
        effective-dated: rebuilding a 2025 window in 2026 must apply 2025's
        licences, or the rebuild is a different corpus wearing the same name.
        """
        if as_of.tzinfo is None:
            raise NewsAcquisitionError("acquire requires a timezone-aware as_of")
        in_force = {entry.source_id: entry for entry in self.registry.as_of(as_of)}
        records: list[ArticleRecord] = []
        for source_id, acquisition in self.acquisitions.items():
            entry = in_force.get(source_id)
            if entry is None:
                continue
            for raw in acquisition.guarded_fetch(window):
                records.append(self.build_record(raw, entry))
        return tuple(sorted(records, key=lambda record: record.observation_id))

    def build_record(self, raw: RawArticle, entry: NewsSourceEntry) -> ArticleRecord:
        """Turn one acquired article into a record its licence permits."""
        url = canonical_url(raw.url)
        retained = apply_retention(
            licence=entry.licence_class, headline=raw.headline, body=raw.body
        )
        first_resolvable = _first_resolvable_at(raw, entry)

        # The licence class sets the ceiling; permitted_fields may lower it.
        # Both are applied, and the recorded decision reflects what was actually
        # kept -- not what the licence would have allowed. A record claiming
        # STORED_FULL while holding no body would misreport the corpus to every
        # coverage feature downstream of it.
        permitted = set(entry.permitted_fields)
        headline = retained.headline if StorableField.HEADLINE in permitted else None
        body_text = retained.body_text if StorableField.BODY in permitted else None
        byline = raw.byline if StorableField.BYLINE in permitted else None
        if retained.decision is RetentionDecision.WITHHELD_FAIL_CLOSED:
            # A byline is a person's name attached to content nobody cleared.
            byline = None

        decision = retained.decision
        if decision in {RetentionDecision.STORED_FULL, RetentionDecision.STORED_SNIPPET}:
            if body_text is None:
                decision = (
                    RetentionDecision.METADATA_KEPT
                    if headline is not None
                    else RetentionDecision.HASH_KEPT
                )
        elif decision is RetentionDecision.METADATA_KEPT and headline is None:
            decision = RetentionDecision.HASH_KEPT

        script = dominant_script(f"{raw.headline or ''} {raw.body or ''}")
        identity = {
            "source_id": entry.source_id,
            "source_record_id": raw.source_record_id,
            "canonical_url": url,
            "normalised_content_hash": retained.normalised_content_hash,
            "body_hash": retained.body_hash,
            "published_at": raw.published_at,
            "modified_at": raw.modified_at,
            "first_resolvable_at": first_resolvable,
            "parser_version": PARSER_VERSION,
            "licence_class": entry.licence_class.value,
        }
        content_hash = build_content_hash(identity)

        return ArticleRecord(
            observation_id=ArticleRecord.build_id(entry.source_id, content_hash, first_resolvable),
            source_id=entry.source_id,
            source_record_id=raw.source_record_id,
            canonical_url=url,
            canonical_url_hash=canonical_url_hash(url),
            headline=headline,
            body_text=body_text,
            body_hash=retained.body_hash,
            normalised_content_hash=retained.normalised_content_hash,
            body_characters=retained.body_characters,
            original_language=raw.language,
            detected_language=None,
            script=script,
            published_at=raw.published_at,
            modified_at=raw.modified_at,
            retrieved_at=raw.retrieved_at,
            first_resolvable_at=first_resolvable,
            byline=byline,
            wire_service=raw.wire_service or entry.wire_service,
            licence_class=entry.licence_class,
            redistribution=entry.redistribution,
            retention_decision=decision,
            publisher_timestamp_disputed=(
                raw.published_at is not None and raw.published_at > raw.retrieved_at
            ),
            source_version=entry.vintage_id,
            parser_version=PARSER_VERSION,
            article_content_hash=content_hash,
            revision_of=raw.revision_of,
            revision_index=raw.revision_index,
        )


def _first_resolvable_at(raw: RawArticle, entry: NewsSourceEntry) -> datetime:
    """When this project could first legitimately have acted on ``raw``.

    Under :attr:`ResolvabilityPolicy.PUBLICATION` the publisher's timestamp is
    used, clamped to the retrieval time. Under the default the retrieval time is
    used outright. Either way the answer never exceeds ``retrieved_at``, and
    never precedes ``published_at``.
    """
    if entry.resolvability_policy is ResolvabilityPolicy.PUBLICATION and raw.published_at:
        return min(raw.published_at, raw.retrieved_at)
    return raw.retrieved_at


def articles_by_source(records: Iterable[ArticleRecord]) -> dict[str, list[ArticleRecord]]:
    """Group records by source, each list sorted for deterministic downstream use."""
    grouped: dict[str, list[ArticleRecord]] = {}
    for record in records:
        grouped.setdefault(record.source_id, []).append(record)
    for values in grouped.values():
        values.sort(key=lambda record: record.observation_id)
    return dict(sorted(grouped.items()))


def acquisition_for(entry: NewsSourceEntry, **kwargs: Any) -> NewsAcquisition:
    """Build the adapter a registry entry's acquisition method calls for.

    Raises for the methods WP1 declares but does not implement, naming the
    method rather than returning something that quietly yields nothing. A
    connector that returns an empty list is indistinguishable from a source
    with no news, and that confusion is exactly what corrupts a base rate.
    """
    from pramaanx.ingest.news_registry import AcquisitionMethod

    method = entry.acquisition
    if method in {
        AcquisitionMethod.RSS,
        AcquisitionMethod.ATOM,
        AcquisitionMethod.GOVERNMENT_FEED,
    }:
        return FeedAcquisition(source_record_id_prefix=entry.source_id, **kwargs)
    if method in {
        AcquisitionMethod.PUBLISHER_API,
        AcquisitionMethod.GDELT_ARTICLE_URL,
        AcquisitionMethod.RELIEFWEB_REPORT,
    }:
        return JsonApiAcquisition(source_record_id_prefix=entry.source_id, **kwargs)
    if method is AcquisitionMethod.LICENSED_ARCHIVE:
        return LicensedArchiveAcquisition(source_record_id_prefix=entry.source_id, **kwargs)
    raise NewsAcquisitionError(f"no acquisition adapter for method {method.value!r}")


__all__: Sequence[str] = (
    "CONNECTOR_VERSION",
    "FeedAcquisition",
    "FieldMap",
    "JsonApiAcquisition",
    "LicensedArchiveAcquisition",
    "NewsAcquisition",
    "NewsAcquisitionError",
    "NewsConnector",
    "RawArticle",
    "acquisition_for",
    "articles_by_source",
    "parse_feed_datetime",
)
