"""How much of the news actually arrived, and whether silence means anything.

This module exists to prevent one specific inference, which is the most
dangerous one available to a district risk model: reading *no reports* as *no
incidents*.

A district with zero articles this week is in one of two states. Either the
press covered it and found nothing worth reporting -- genuine quiet -- or the
feeds that cover it went down, the licensed archive lapsed, the
regional-language source stopped publishing, or nobody ever configured a source
for that region at all. The two states produce identical data and opposite
conclusions. A model that cannot tell them apart will learn that the districts
it cannot see are the safest ones in India.

So every health record carries :attr:`SourceHealth.coverage_interpretable`, and
every count of zero is accompanied by whether that zero may be read as
evidence. Downstream features are expected to consult it; abstention in WP7
consumes it directly.

Everything here takes an explicit ``as_of``. Health computed over records that
were not yet resolvable at the cutoff would describe a corpus the forecaster
never had.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.ingest.article_content import (
    SCRIPT_UNKNOWN,
    ArticleRecord,
    group_syndication,
    latest_as_of,
)
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.news_registry import NewsSourceEntry, NewsSourceRegistry
from pramaanx.schemas.base import UtcDatetime, VersionedModel

HEALTH_VERSION = "news-source-health/1.0.0"

#: Retrieval completeness at or below which a source counts as out entirely.
#: A source delivering under a tenth of its expected volume is not degraded,
#: it is broken, and treating the difference as a matter of degree invites a
#: threshold nobody chose.
OUTAGE_COMPLETENESS = 0.1

#: Below this a source is degraded: usable, but its silences prove nothing.
DEGRADED_COMPLETENESS = 0.6


class OutageStatus(StrEnum):
    """What is known about whether a source was working.

    ``UNKNOWN`` is not a synonym for ``HEALTHY``. It is the state of a source
    whose expected volume nobody has measured, and it withholds the right to
    read that source's silence as information.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OUTAGE = "outage"
    UNKNOWN = "unknown"


#: The statuses under which an absence of articles may be read as an absence of
#: news. Exactly one qualifies, and it has to be earned.
_SILENCE_IS_EVIDENCE = frozenset({OutageStatus.HEALTHY})


class SourceHealth(VersionedModel):
    """Delivery, delay, duplication and coverage for one source and window."""

    source_id: str
    #: ``None`` means "across all languages this source published".
    language: str | None = None
    region: str | None = None

    window_start: UtcDatetime
    window_end: UtcDatetime
    as_of: UtcDatetime

    expected_documents: float | None = Field(default=None, ge=0.0)
    retrieved_documents: int = Field(default=0, ge=0)
    #: ``None`` when no expectation has been measured. Never defaulted to 1.0:
    #: an unmeasured source must not report perfect delivery.
    retrieval_completeness: float | None = Field(default=None, ge=0.0)

    #: Seconds between a publisher's stated publication time and this project
    #: being able to act on the article. ``None`` when no article in the window
    #: carried a publication timestamp.
    median_publication_delay_seconds: float | None = Field(default=None, ge=0.0)
    p95_publication_delay_seconds: float | None = Field(default=None, ge=0.0)

    #: Share of articles that arrived as a revision of one already held.
    revision_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    #: Share of documents that added no new information lineage.
    duplicate_proportion: float = Field(default=0.0, ge=0.0, le=1.0)
    independent_lineages: int = Field(default=0, ge=0)

    status: OutageStatus = OutageStatus.UNKNOWN
    #: Languages the registry says this source publishes, from which nothing
    #: arrived in the window.
    missing_languages: tuple[str, ...] = ()
    #: Regions the registry says this source covers, from which nothing arrived.
    #: Only meaningful when ``regions_resolved`` is true.
    missing_regions: tuple[str, ...] = ()
    #: True only when a region resolver ran. Absent regions are otherwise
    #: unmeasured, not empty.
    regions_resolved: bool = False
    #: Districts seen in the window, when a resolver was supplied.
    covered_districts: tuple[str, ...] = ()
    #: True only when a district resolver ran. Absent districts are otherwise
    #: unmeasured, not empty.
    districts_resolved: bool = False

    @model_validator(mode="after")
    def _check_window(self) -> SourceHealth:
        if self.window_end <= self.window_start:
            raise ValueError(
                f"{self.source_id}: empty health window "
                f"{self.window_start.isoformat()} -> {self.window_end.isoformat()}"
            )
        return self

    @property
    def coverage_interpretable(self) -> bool:
        """Whether this window's silence may be read as an absence of news.

        The single most consequential flag in the news layer. False whenever the
        source was degraded, out, or never measured -- which is to say, whenever
        "nothing was reported" and "nothing reached us" cannot be told apart.
        """
        return self.status in _SILENCE_IS_EVIDENCE

    @property
    def window_days(self) -> float:
        return (self.window_end - self.window_start).total_seconds() / 86400.0

    def as_feature_row(self) -> dict[str, object]:
        """The flat form a district feature builder consumes.

        ``coverage_interpretable`` travels with the counts rather than being
        recoverable from them, so a downstream model cannot use the volume
        without also being handed the reason to distrust it.
        """
        return {
            "source_id": self.source_id,
            "language": self.language,
            "region": self.region,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "retrieved_documents": self.retrieved_documents,
            "retrieval_completeness": self.retrieval_completeness,
            "independent_lineages": self.independent_lineages,
            "duplicate_proportion": self.duplicate_proportion,
            "revision_rate": self.revision_rate,
            "median_publication_delay_seconds": self.median_publication_delay_seconds,
            "status": self.status.value,
            "coverage_interpretable": self.coverage_interpretable,
            "districts_resolved": self.districts_resolved,
        }


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile. Deterministic, and defined on tiny samples."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-fraction * len(ordered) // 1))))
    return ordered[rank - 1]


def classify_status(completeness: float | None) -> OutageStatus:
    """Map retrieval completeness onto an outage status.

    ``None`` maps to :attr:`OutageStatus.UNKNOWN` rather than to healthy. A
    source nobody has characterised has not been shown to be working; it has
    only been shown not to have failed loudly.
    """
    if completeness is None:
        return OutageStatus.UNKNOWN
    if completeness <= OUTAGE_COMPLETENESS:
        return OutageStatus.OUTAGE
    if completeness < DEGRADED_COMPLETENESS:
        return OutageStatus.DEGRADED
    return OutageStatus.HEALTHY


def compute_source_health(
    records: Iterable[ArticleRecord],
    *,
    entry: NewsSourceEntry,
    window: FetchWindow,
    as_of: datetime,
    language: str | None = None,
    region: str | None = None,
    district_resolver: Callable[[ArticleRecord], str | None] | None = None,
    region_resolver: Callable[[ArticleRecord], str | None] | None = None,
) -> SourceHealth:
    """Health for one source over one window, as known at ``as_of``.

    Only records resolvable at ``as_of`` are counted, and only the revision of
    each article that was current then. Counting a later revision would let a
    correction filed next month improve last month's measured delivery.

    ``district_resolver`` is injected rather than imported. District identity is
    WP0's, and a package that runs in parallel to WP0 must not depend on it; a
    caller that has a resolver passes one, and a caller that does not gets
    ``districts_resolved=False`` rather than a silently empty district list.
    """
    if as_of.tzinfo is None:
        raise ValueError("compute_source_health requires a timezone-aware as_of")
    cutoff = as_of.astimezone(UTC)

    usable = [
        record
        for record in records
        if record.source_id == entry.source_id
        and record.usable_at(cutoff)
        and window.contains(record.first_resolvable_at)
    ]
    if language is not None:
        usable = [record for record in usable if record.original_language == language]

    current = latest_as_of(usable, cutoff)
    retrieved = len(current)

    expected: float | None = None
    completeness: float | None = None
    if entry.expected_items_per_day is not None:
        expected = entry.expected_items_per_day * window.days
        completeness = retrieved / expected if expected > 0 else 0.0

    delays = [
        (record.first_resolvable_at - record.published_at).total_seconds()
        for record in current
        if record.published_at is not None
    ]
    non_negative = [delay for delay in delays if delay >= 0.0]

    revisions = sum(1 for record in usable if record.revision_index > 0)
    revision_rate = revisions / len(usable) if usable else 0.0

    report = group_syndication(current)
    lineages = report.independent_lineage_count
    duplicate_proportion = 1.0 - (lineages / retrieved) if retrieved else 0.0

    seen_languages = {record.original_language for record in current if record.original_language}
    missing_languages = tuple(sorted(set(entry.languages) - seen_languages))

    missing_regions: tuple[str, ...] = ()
    if region_resolver is not None:
        seen_regions = {
            resolved for record in current if (resolved := region_resolver(record)) is not None
        }
        missing_regions = tuple(sorted(set(entry.regions) - seen_regions))

    districts: tuple[str, ...] = ()
    if district_resolver is not None:
        districts = tuple(
            sorted(
                {
                    resolved
                    for record in current
                    if (resolved := district_resolver(record)) is not None
                }
            )
        )

    return SourceHealth(
        source_id=entry.source_id,
        language=language,
        region=region,
        window_start=window.start,
        window_end=window.end,
        as_of=cutoff,
        expected_documents=expected,
        retrieved_documents=retrieved,
        retrieval_completeness=completeness,
        median_publication_delay_seconds=_percentile(non_negative, 0.5),
        p95_publication_delay_seconds=_percentile(non_negative, 0.95),
        revision_rate=revision_rate,
        duplicate_proportion=max(0.0, min(1.0, duplicate_proportion)),
        independent_lineages=lineages,
        status=classify_status(completeness),
        missing_languages=missing_languages,
        missing_regions=missing_regions,
        regions_resolved=region_resolver is not None,
        covered_districts=districts,
        districts_resolved=district_resolver is not None,
    )


class CoverageReport(VersionedModel):
    """Health across every source in force, plus what nothing covered at all."""

    as_of: UtcDatetime
    window_start: UtcDatetime
    window_end: UtcDatetime
    registry_version: str
    registry_hash: str
    sources: tuple[SourceHealth, ...] = ()
    #: Required languages no enabled source produced anything in.
    uncovered_languages: tuple[str, ...] = ()
    #: Scripts observed in the window. A regional-language feed going silent
    #: shows up here before it shows up in any district count.
    observed_scripts: tuple[str, ...] = ()

    @property
    def interpretable_sources(self) -> tuple[str, ...]:
        return tuple(
            sorted(health.source_id for health in self.sources if health.coverage_interpretable)
        )

    @property
    def sources_out(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                health.source_id for health in self.sources if health.status is OutageStatus.OUTAGE
            )
        )

    @property
    def any_coverage_interpretable(self) -> bool:
        """Whether *any* source was healthy enough for silence to mean something.

        When this is false the window supports no negative conclusion at all,
        and a district count of zero drawn from it is not a zero -- it is a
        missing value that happens to be spelled with a digit.
        """
        return bool(self.interpretable_sources)


def build_coverage_report(
    records: Iterable[ArticleRecord],
    *,
    registry: NewsSourceRegistry,
    window: FetchWindow,
    as_of: datetime,
    required_languages: Iterable[str] = (),
    district_resolver: Callable[[ArticleRecord], str | None] | None = None,
) -> CoverageReport:
    """Health for every source in force at ``as_of``, in a deterministic order."""
    if as_of.tzinfo is None:
        raise ValueError("build_coverage_report requires a timezone-aware as_of")
    cutoff = as_of.astimezone(UTC)
    materialised = list(records)

    healths = tuple(
        compute_source_health(
            materialised,
            entry=entry,
            window=window,
            as_of=cutoff,
            district_resolver=district_resolver,
        )
        for entry in registry.as_of(cutoff)
    )

    in_window = [
        record
        for record in materialised
        if record.usable_at(cutoff) and window.contains(record.first_resolvable_at)
    ]
    produced = {record.original_language for record in in_window if record.original_language}
    scripts = {record.script for record in in_window if record.script != SCRIPT_UNKNOWN}

    return CoverageReport(
        as_of=cutoff,
        window_start=window.start,
        window_end=window.end,
        registry_version=registry.registry_version,
        registry_hash=registry.registry_hash,
        sources=healths,
        uncovered_languages=tuple(sorted(set(required_languages) - produced)),
        observed_scripts=tuple(sorted(scripts)),
    )


def health_by_source(healths: Iterable[SourceHealth]) -> Mapping[str, SourceHealth]:
    """Index health records by source id, latest window wins on a tie."""
    indexed: dict[str, SourceHealth] = {}
    for health in sorted(healths, key=lambda item: (item.source_id, item.window_end)):
        indexed[health.source_id] = health
    return dict(sorted(indexed.items()))
