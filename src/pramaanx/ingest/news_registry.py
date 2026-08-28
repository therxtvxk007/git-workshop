"""Which news sources exist, what may be kept from them, and when that was true.

A news source is not a constant. Publishers change terms, feeds move, an outlet
that was licensed in March is not in September, and a regional edition launches
mid-year. A registry that stored only the *current* answer would silently
re-license the past: rebuilding a 2025 snapshot in 2026 would apply 2026's
terms to 2025's articles, and the rebuild would not match the original.

So every entry is effective-dated over a half-open interval
``[effective_from, effective_to)`` and read through :meth:`NewsSourceRegistry.as_of`.
Two vintages of one source may not overlap, because an overlap means two
different answers to "what were we allowed to store on this date?" and the
resolver would have to pick one. Picking one is guessing, and this project does
not guess about licences.

Credentials never appear here. An entry names the *environment variable* a
credential is read from and nothing else, and :class:`NewsSourceEntry` refuses
anything that looks like a value rather than a name -- because a registry is a
tracked file, and a tracked file is a published file.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from pramaanx.ingest.article_content import LicenceClass, RedistributionPermission
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel

REGISTRY_VERSION = "news-registry/1.0.0"

#: Where a registry document lives inside :attr:`pramaanx.config.Settings.extras`.
#: ``extras`` is the one part of the settings schema that accepts arbitrary
#: structure, which is what lets a news registry ship as a normal config file
#: without WP1 editing the shared settings model. WP9 may promote it to a
#: first-class ``NewsConfig`` block; until then this key is the contract.
EXTRAS_KEY = "news_registry"

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")

#: Licence classes under which any article text at all may be retained.
_TEXT_RETAINING = frozenset({LicenceClass.FULL_TEXT_PERMITTED, LicenceClass.SNIPPET_ONLY})

#: Substrings that mark a string as a credential rather than a variable name.
#: Deliberately blunt: the cost of a false positive is renaming a variable, and
#: the cost of a false negative is a secret in git history for ever.
_SECRET_MARKERS: tuple[str, ...] = (
    "-----begin",
    "api_key=",
    "apikey=",
    "bearer ",
    "password=",
    "secret=",
    "token=",
)


class NewsRegistryError(ValueError):
    """The registry is inconsistent, or would have to guess to answer."""


class AcquisitionMethod(StrEnum):
    """How articles from this source are legally obtained.

    The list is the acquisition families WP1 must be able to serve. Which of
    them has a working implementation today is a separate question, answered by
    :mod:`pramaanx.ingest.connectors.news` and recorded in
    ``docs/integration/wp01_news.md`` -- a method being nameable here is not a
    claim that it has ever run.
    """

    RSS = "rss"
    ATOM = "atom"
    PUBLISHER_API = "publisher_api"
    GDELT_ARTICLE_URL = "gdelt_article_url"
    RELIEFWEB_REPORT = "reliefweb_report"
    GOVERNMENT_FEED = "government_feed"
    LICENSED_ARCHIVE = "licensed_archive"


class ResolvabilityPolicy(StrEnum):
    """How ``first_resolvable_at`` is derived for a source.

    The two answers differ by hours, and hours are the whole margin a 30-day
    forecast has at its cutoff boundary.

    ``RETRIEVAL`` is the conservative default: this project could first have
    acted on an article when it actually fetched it, and a publisher's own
    timestamp is a claim nobody here verified. ``PUBLICATION`` says the
    publisher's timestamp has been checked against reality for this source and
    may be trusted -- which is a statement about the source, made once, in the
    registry, rather than a per-article guess made silently in a parser.

    ``PUBLICATION`` still clamps to the retrieval time. A feed claiming an
    article was published after this project downloaded it is describing a
    clock problem, not a scoop.
    """

    RETRIEVAL = "retrieval"
    PUBLICATION = "publication"


class StorableField(StrEnum):
    """Fields a source permits this project to retain.

    Narrower than the licence class, and checked against it: a source may
    permit full text under its licence and still be configured to keep only
    headlines, but it may never be configured to keep more than its licence
    class allows.
    """

    HEADLINE = "headline"
    BODY = "body"
    BYLINE = "byline"
    URL = "url"
    TIMESTAMPS = "timestamps"
    HASHES = "hashes"


def _reject_secret_like(value: str, *, field: str, source_id: str) -> None:
    lowered = value.lower()
    for marker in _SECRET_MARKERS:
        if marker in lowered:
            raise NewsRegistryError(
                f"{source_id}.{field} looks like a credential ({marker!r} appears in it). "
                "The registry is a tracked file: name the environment variable, never "
                "the value it holds."
            )


class NewsSourceEntry(VersionedModel):
    """One source, as it stood over one interval of time."""

    source_id: str
    display_name: str
    publisher: str
    homepage: str | None = None
    acquisition: AcquisitionMethod

    #: ISO-639-1 codes this source publishes in. Used by coverage accounting to
    #: notice a language going missing, so an empty list is a real gap rather
    #: than a shorthand for "all".
    languages: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    #: State or region names this source covers. Free text at WP1: the district
    #: layer that would validate these is WP0's, and importing it here would
    #: make this package depend on a package it is meant to run in parallel to.
    regions: tuple[str, ...] = ()

    licence_class: LicenceClass
    redistribution: RedistributionPermission
    licence_url: str | None = None
    permitted_fields: tuple[StorableField, ...] = ()

    #: How many items a healthy day produces. The denominator of retrieval
    #: completeness; ``None`` means nobody has measured it, and completeness is
    #: then reported as unknown rather than as 1.0.
    expected_items_per_day: float | None = Field(default=None, ge=0.0)
    #: Typical lag between an event and this source publishing about it.
    normal_publication_delay_seconds: float = Field(default=0.0, ge=0.0)

    #: Whether this source's own publication timestamps may be trusted for
    #: cutoff purposes. Conservative by default; see :class:`ResolvabilityPolicy`.
    resolvability_policy: ResolvabilityPolicy = ResolvabilityPolicy.RETRIEVAL

    reliability_prior: float = Field(default=0.5, ge=0.0, le=1.0)
    provenance_notes: str | None = None
    wire_service: str | None = None

    #: The name of an environment variable, never a credential.
    credential_env: str | None = None

    enabled: bool = True
    effective_from: UtcDatetime
    #: Exclusive upper bound. ``None`` means "still in force".
    effective_to: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check_validity_window(self) -> NewsSourceEntry:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise NewsRegistryError(
                f"{self.source_id}: effective_to ({self.effective_to.isoformat()}) must be "
                f"strictly after effective_from ({self.effective_from.isoformat()}). A "
                "zero-width vintage can never be selected, so it would be silently dead "
                "configuration."
            )
        return self

    @model_validator(mode="after")
    def _check_no_credentials(self) -> NewsSourceEntry:
        if self.credential_env is not None and not _ENV_NAME.match(self.credential_env):
            raise NewsRegistryError(
                f"{self.source_id}.credential_env must be an environment variable name "
                f"(upper snake case), got {self.credential_env!r}. A value here would be "
                "a secret committed to the repository."
            )
        for field in ("homepage", "licence_url", "provenance_notes", "display_name"):
            value = getattr(self, field)
            if isinstance(value, str):
                _reject_secret_like(value, field=field, source_id=self.source_id)
        return self

    @model_validator(mode="after")
    def _check_fields_within_licence(self) -> NewsSourceEntry:
        """Configuration may narrow a licence. It may never widen one."""
        permitted = set(self.permitted_fields)
        if self.licence_class not in {
            LicenceClass.FULL_TEXT_PERMITTED,
            LicenceClass.SNIPPET_ONLY,
        } and (StorableField.BODY in permitted):
            raise NewsRegistryError(
                f"{self.source_id}: licence class {self.licence_class.value!r} permits no body "
                "text, but permitted_fields lists 'body'. The registry cannot grant a right "
                "the licence withholds."
            )
        if self.licence_class in {LicenceClass.UNKNOWN, LicenceClass.PROHIBITED}:
            forbidden = permitted - {StorableField.HASHES}
            if forbidden:
                raise NewsRegistryError(
                    f"{self.source_id}: licence class {self.licence_class.value!r} retains "
                    f"hashes only, but permitted_fields lists "
                    f"{sorted(field.value for field in forbidden)}."
                )
        return self

    def covers(self, moment: datetime) -> bool:
        """Whether this vintage is in force at ``moment`` -- half-open."""
        if moment < self.effective_from:
            return False
        return self.effective_to is None or moment < self.effective_to

    @property
    def vintage_id(self) -> str:
        """``source_id@effective_from`` -- what a manifest records."""
        return f"{self.source_id}@{self.effective_from.isoformat()}"


class NewsSourceRegistry(PramaanModel):
    """Every known vintage of every news source, resolvable as of a date."""

    registry_version: str = REGISTRY_VERSION
    entries: tuple[NewsSourceEntry, ...] = ()

    @model_validator(mode="after")
    def _reject_overlapping_vintages(self) -> NewsSourceRegistry:
        by_source: dict[str, list[NewsSourceEntry]] = {}
        for entry in self.entries:
            by_source.setdefault(entry.source_id, []).append(entry)
        for source_id, vintages in by_source.items():
            ordered = sorted(vintages, key=lambda item: item.effective_from)
            for earlier, later in pairwise(ordered):
                closes_at = earlier.effective_to
                if closes_at is None or closes_at > later.effective_from:
                    raise NewsRegistryError(
                        f"{source_id}: vintage starting {earlier.effective_from.isoformat()} "
                        f"overlaps the one starting {later.effective_from.isoformat()}. Two "
                        "answers to 'what were we allowed to store on this date?' is not a "
                        "registry, it is a coin toss."
                    )
        return self

    def as_of(self, moment: datetime) -> tuple[NewsSourceEntry, ...]:
        """Enabled vintages in force at ``moment``, sorted by source id.

        Disabled entries are excluded here rather than deleted from the file:
        a source that was switched off still has to be resolvable for the
        period it was on, or old snapshots stop reconstructing.
        """
        if moment.tzinfo is None:
            raise NewsRegistryError("as_of requires a timezone-aware moment")
        instant = moment.astimezone(UTC)
        selected = [entry for entry in self.entries if entry.enabled and entry.covers(instant)]
        return tuple(sorted(selected, key=lambda entry: entry.source_id))

    def entry_as_of(self, source_id: str, moment: datetime) -> NewsSourceEntry:
        """The one vintage of ``source_id`` in force at ``moment``.

        Raises rather than returning ``None``. A caller that reached here has an
        article in hand and needs to know what may be kept from it; answering
        "no idea" by returning nothing invites a default, and the default would
        be more permissive than the truth.
        """
        for entry in self.as_of(moment):
            if entry.source_id == source_id:
                return entry
        known = ", ".join(sorted({entry.source_id for entry in self.entries})) or "<none>"
        raise NewsRegistryError(
            f"no enabled vintage of news source {source_id!r} in force at "
            f"{moment.isoformat()}. Registered sources: {known}."
        )

    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted({entry.source_id for entry in self.entries}))

    @property
    def registry_hash(self) -> str:
        """Content hash of the whole registry, recorded in every manifest."""
        return self.content_hash()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> NewsSourceRegistry:
        """Build from the ``news_registry`` block of a config document."""
        if "sources" not in payload:
            raise NewsRegistryError(
                "news registry document has no 'sources' key; an empty registry must say so "
                "explicitly with 'sources: []' rather than by omission"
            )
        raw_sources = payload["sources"] or []
        if not isinstance(raw_sources, list):
            raise NewsRegistryError("news registry 'sources' must be a list")
        entries = tuple(NewsSourceEntry.model_validate(item) for item in raw_sources)
        version = str(payload.get("registry_version", REGISTRY_VERSION))
        return cls(registry_version=version, entries=entries)

    @classmethod
    def from_yaml(cls, path: Path) -> NewsSourceRegistry:
        """Load a registry from a config file that carries it under ``extras``."""
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(document, Mapping):
            raise NewsRegistryError(f"{path} does not contain a mapping")
        extras = document.get("extras") or {}
        block = extras.get(EXTRAS_KEY) if isinstance(extras, Mapping) else None
        if block is None:
            raise NewsRegistryError(
                f"{path} carries no extras.{EXTRAS_KEY} block. The registry lives under "
                "'extras' so that it is validated and hashed as part of the run "
                "configuration rather than loaded from an untracked side file."
            )
        return cls.from_mapping(block)

    @classmethod
    def from_extras(cls, extras: Mapping[str, Any]) -> NewsSourceRegistry:
        """Build from an already-loaded ``Settings.extras`` mapping."""
        block = extras.get(EXTRAS_KEY)
        if block is None:
            raise NewsRegistryError(
                f"settings.extras has no {EXTRAS_KEY!r} block; layer "
                "configs/sources/news_india.yaml over the base config"
            )
        if not isinstance(block, Mapping):
            raise NewsRegistryError(f"extras.{EXTRAS_KEY} must be a mapping")
        return cls.from_mapping(block)


def coverage_gaps(
    registry: NewsSourceRegistry,
    *,
    moment: datetime,
    required_languages: Iterable[str],
    require_readable: bool = False,
) -> tuple[str, ...]:
    """Required languages that no enabled source covers at ``moment``.

    A language with no source is not a language with no news. Reporting the gap
    is the difference between "nothing happened in Manipur" and "nothing we can
    read reaches us from Manipur", and only one of those belongs in a forecast.

    ``require_readable`` narrows the question from "is this language indexed?"
    to "can we read anything written in it?". The two answers differ, and the
    difference is load-bearing: a URL index covers a dozen Indian languages
    while retaining no body text in any of them, so it closes every gap for
    counting purposes and none at all for extraction. WP2 needs text; a coverage
    feature needs volume. Ask the question you actually mean.
    """
    entries = registry.as_of(moment)
    if require_readable:
        entries = tuple(
            entry
            for entry in entries
            if entry.licence_class in _TEXT_RETAINING
            and StorableField.BODY in entry.permitted_fields
        )
    available = {language for entry in entries for language in entry.languages}
    return tuple(sorted(set(required_languages) - available))
