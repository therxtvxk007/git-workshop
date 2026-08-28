"""Whether silence means anything, and the refusal to assume it does.

The inference these tests exist to block is the one that would otherwise be
most attractive to a district model: no reports, therefore no incidents. A
district nobody covers would learn to look like the safest place in India.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from _news_builders import entry, record, registry, wire_copies
from pramaanx.ingest.article_content import ArticleRecord
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.source_health import (
    DEGRADED_COMPLETENESS,
    OUTAGE_COMPLETENESS,
    OutageStatus,
    build_coverage_report,
    classify_status,
    compute_source_health,
    health_by_source,
)

WINDOW = FetchWindow(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 8, tzinfo=UTC))
AS_OF = datetime(2026, 3, 8, tzinfo=UTC)
IN_WINDOW = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)


def articles(
    count: int, *, source_id: str = "outlet_a", language: str = "en"
) -> list[ArticleRecord]:
    return [
        record(
            source_id=source_id,
            url=f"https://example.test/{source_id}/{index}",
            body=f"Body number {index} with enough words to shingle properly here.",
            language=language,
            retrieved_at=IN_WINDOW,
            first_resolvable_at=IN_WINDOW,
        )
        for index in range(count)
    ]


class TestStatusClassification:
    def test_an_unmeasured_source_is_unknown_not_healthy(self) -> None:
        # A source nobody has characterised has not been shown to be working;
        # it has only been shown not to have failed loudly.
        assert classify_status(None) is OutageStatus.UNKNOWN

    @pytest.mark.parametrize(
        ("completeness", "expected"),
        [
            (0.0, OutageStatus.OUTAGE),
            (OUTAGE_COMPLETENESS, OutageStatus.OUTAGE),
            (0.3, OutageStatus.DEGRADED),
            (DEGRADED_COMPLETENESS, OutageStatus.HEALTHY),
            (1.0, OutageStatus.HEALTHY),
            (2.0, OutageStatus.HEALTHY),
        ],
    )
    def test_thresholds(self, completeness: float, expected: OutageStatus) -> None:
        assert classify_status(completeness) is expected


class TestCoverageInterpretability:
    def test_only_a_healthy_source_licenses_reading_silence(self) -> None:
        # This is the single most consequential flag in the news layer.
        source = entry("outlet_a", expected_items_per_day=10.0)
        healthy = compute_source_health(articles(70), entry=source, window=WINDOW, as_of=AS_OF)
        assert healthy.status is OutageStatus.HEALTHY
        assert healthy.coverage_interpretable is True

    def test_an_outage_appears_in_the_metrics_and_voids_interpretation(self) -> None:
        # Required behaviour 8. Zero articles from a source expected to produce
        # seventy is an outage, and its zero is not evidence of anything.
        source = entry("outlet_a", expected_items_per_day=10.0)
        health = compute_source_health([], entry=source, window=WINDOW, as_of=AS_OF)
        assert health.retrieved_documents == 0
        assert health.expected_documents == pytest.approx(70.0)
        assert health.retrieval_completeness == pytest.approx(0.0)
        assert health.status is OutageStatus.OUTAGE
        assert health.coverage_interpretable is False

    def test_a_degraded_source_also_voids_interpretation(self) -> None:
        source = entry("outlet_a", expected_items_per_day=10.0)
        health = compute_source_health(articles(14), entry=source, window=WINDOW, as_of=AS_OF)
        assert health.status is OutageStatus.DEGRADED
        assert health.coverage_interpretable is False

    def test_an_unmeasured_source_voids_interpretation(self) -> None:
        # Completeness is never defaulted to 1.0: an unmeasured source must not
        # report perfect delivery.
        source = entry("outlet_a", expected_items_per_day=None)
        health = compute_source_health([], entry=source, window=WINDOW, as_of=AS_OF)
        assert health.retrieval_completeness is None
        assert health.status is OutageStatus.UNKNOWN
        assert health.coverage_interpretable is False

    def test_the_flag_travels_with_the_counts(self) -> None:
        # A downstream model must not be able to use the volume without also
        # being handed the reason to distrust it.
        source = entry("outlet_a", expected_items_per_day=10.0)
        row = compute_source_health([], entry=source, window=WINDOW, as_of=AS_OF).as_feature_row()
        assert row["retrieved_documents"] == 0
        assert row["coverage_interpretable"] is False


class TestDelayAndDuplication:
    def test_publication_delay_is_measured_from_publication_to_resolvability(self) -> None:
        published = datetime(2026, 3, 3, 6, 0, tzinfo=UTC)
        built = [
            record(
                url="https://example.test/x/1",
                published_at=published,
                retrieved_at=IN_WINDOW,
                first_resolvable_at=IN_WINDOW,
            )
        ]
        health = compute_source_health(built, entry=entry("outlet_a"), window=WINDOW, as_of=AS_OF)
        assert health.median_publication_delay_seconds == pytest.approx(6 * 3600.0)

    def test_delay_is_none_when_nothing_declared_a_publication_time(self) -> None:
        built = [
            record(
                url="https://example.test/x/1",
                published_at=None,
                retrieved_at=IN_WINDOW,
                first_resolvable_at=IN_WINDOW,
            )
        ]
        health = compute_source_health(built, entry=entry("outlet_a"), window=WINDOW, as_of=AS_OF)
        assert health.median_publication_delay_seconds is None
        assert health.p95_publication_delay_seconds is None

    def test_wire_copy_shows_up_as_duplication_not_as_volume(self) -> None:
        # Five mastheads, one file. The document count is five; the honest
        # independence count is one, and the gap is the duplicate proportion.
        copies = [
            item.model_copy(
                update={
                    "source_id": "outlet_a",
                    "retrieved_at": IN_WINDOW,
                    "first_resolvable_at": IN_WINDOW,
                }
            )
            for item in wire_copies(5)
        ]
        health = compute_source_health(copies, entry=entry("outlet_a"), window=WINDOW, as_of=AS_OF)
        assert health.retrieved_documents == 5
        assert health.independent_lineages == 1
        assert health.duplicate_proportion == pytest.approx(0.8)

    def test_distinct_stories_are_not_duplication(self) -> None:
        health = compute_source_health(
            articles(4), entry=entry("outlet_a"), window=WINDOW, as_of=AS_OF
        )
        assert health.independent_lineages == 4
        assert health.duplicate_proportion == pytest.approx(0.0)

    def test_revision_rate_counts_revisions_not_originals(self) -> None:
        original = record(
            url="https://example.test/r/1",
            body="First version of this story.",
            retrieved_at=IN_WINDOW,
            first_resolvable_at=IN_WINDOW,
        )
        revision = record(
            url="https://example.test/r/1",
            body="Second version of this story, revised.",
            retrieved_at=IN_WINDOW,
            first_resolvable_at=IN_WINDOW,
            revision_of=original.observation_id,
            revision_index=1,
        )
        health = compute_source_health(
            [original, revision], entry=entry("outlet_a"), window=WINDOW, as_of=AS_OF
        )
        assert health.revision_rate == pytest.approx(0.5)
        # Only the current revision counts as a delivered document.
        assert health.retrieved_documents == 1


class TestCoverageAccounting:
    def test_a_missing_language_is_reported(self) -> None:
        # Required behaviour 9, per source: a bilingual feed producing only
        # English has a hole in it, and the hole has a name.
        source = entry("outlet_a", languages=("en", "ml"), expected_items_per_day=1.0)
        health = compute_source_health(
            articles(7, language="en"), entry=source, window=WINDOW, as_of=AS_OF
        )
        assert health.missing_languages == ("ml",)

    def test_regions_are_unmeasured_rather_than_empty_without_a_resolver(self) -> None:
        source = entry("outlet_a", regions=("Kerala", "Tamil Nadu"))
        health = compute_source_health(articles(3), entry=source, window=WINDOW, as_of=AS_OF)
        assert health.regions_resolved is False
        assert health.missing_regions == ()

    def test_regions_are_reported_when_a_resolver_is_supplied(self) -> None:
        source = entry("outlet_a", regions=("Kerala", "Tamil Nadu"))
        health = compute_source_health(
            articles(3),
            entry=source,
            window=WINDOW,
            as_of=AS_OF,
            region_resolver=lambda _: "Kerala",
        )
        assert health.regions_resolved is True
        assert health.missing_regions == ("Tamil Nadu",)

    def test_districts_are_unmeasured_rather_than_empty_without_a_resolver(self) -> None:
        # District identity is WP0's. Absent a resolver, the district list is
        # unmeasured -- which is a different claim from "no districts".
        health = compute_source_health(
            articles(3), entry=entry("outlet_a"), window=WINDOW, as_of=AS_OF
        )
        assert health.districts_resolved is False
        assert health.covered_districts == ()

    def test_districts_are_reported_when_a_resolver_is_supplied(self) -> None:
        health = compute_source_health(
            articles(3),
            entry=entry("outlet_a"),
            window=WINDOW,
            as_of=AS_OF,
            district_resolver=lambda item: item.source_id.upper(),
        )
        assert health.districts_resolved is True
        assert health.covered_districts == ("OUTLET_A",)

    def test_a_resolver_returning_none_contributes_nothing(self) -> None:
        health = compute_source_health(
            articles(3),
            entry=entry("outlet_a"),
            window=WINDOW,
            as_of=AS_OF,
            district_resolver=lambda _: None,
        )
        assert health.districts_resolved is True
        assert health.covered_districts == ()

    def test_language_filtering_narrows_the_window(self) -> None:
        mixed = articles(3, language="en") + articles(2, language="ml")
        health = compute_source_health(
            mixed, entry=entry("outlet_a"), window=WINDOW, as_of=AS_OF, language="ml"
        )
        assert health.retrieved_documents == 2
        assert health.language == "ml"


class TestCoverageReport:
    def test_a_language_no_source_produced_is_uncovered(self) -> None:
        # Required behaviour 9, across the registry: a language nobody
        # published in is a gap, not a quiet week.
        built = registry(entry("outlet_a", languages=("en",), expected_items_per_day=1.0))
        report = build_coverage_report(
            articles(7),
            registry=built,
            window=WINDOW,
            as_of=AS_OF,
            required_languages=["en", "ml", "bn"],
        )
        assert report.uncovered_languages == ("bn", "ml")

    def test_observed_scripts_are_reported(self) -> None:
        malayalam = record(
            source_id="outlet_a",
            url="https://example.test/ml/1",
            headline="കേരളത്തിൽ",
            body="കേരളത്തിൽ ഒരു വാർത്ത ഇവിടെ ഉണ്ട്",
            language="ml",
            retrieved_at=IN_WINDOW,
            first_resolvable_at=IN_WINDOW,
        )
        report = build_coverage_report(
            [*articles(2), malayalam],
            registry=registry(entry("outlet_a")),
            window=WINDOW,
            as_of=AS_OF,
        )
        assert report.observed_scripts == ("Latin", "Malayalam")

    def test_a_report_names_which_sources_are_out(self) -> None:
        built = registry(
            entry("outlet_a", expected_items_per_day=10.0),
            entry("outlet_b", expected_items_per_day=10.0),
        )
        report = build_coverage_report(
            articles(70, source_id="outlet_a"), registry=built, window=WINDOW, as_of=AS_OF
        )
        assert report.sources_out == ("outlet_b",)
        assert report.interpretable_sources == ("outlet_a",)
        assert report.any_coverage_interpretable is True

    def test_a_window_in_which_nothing_worked_supports_no_conclusion(self) -> None:
        # When this is false the window supports no negative conclusion at all,
        # and a district count of zero drawn from it is a missing value that
        # happens to be spelled with a digit.
        built = registry(entry("outlet_a", expected_items_per_day=10.0))
        report = build_coverage_report([], registry=built, window=WINDOW, as_of=AS_OF)
        assert report.any_coverage_interpretable is False
        assert report.interpretable_sources == ()

    def test_the_registry_hash_is_recorded(self) -> None:
        built = registry(entry("outlet_a"))
        report = build_coverage_report([], registry=built, window=WINDOW, as_of=AS_OF)
        assert report.registry_hash == built.registry_hash

    def test_a_naive_as_of_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            build_coverage_report(
                [],
                registry=registry(),
                window=WINDOW,
                as_of=datetime(2026, 3, 8),  # noqa: DTZ001
            )

    def test_compute_refuses_a_naive_as_of(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            compute_source_health(
                [],
                entry=entry(),
                window=WINDOW,
                as_of=datetime(2026, 3, 8),  # noqa: DTZ001
            )


class TestWindowArithmetic:
    def test_window_days_matches_the_window(self) -> None:
        health = compute_source_health([], entry=entry(), window=WINDOW, as_of=AS_OF)
        assert health.window_days == pytest.approx(7.0)


class TestHealthIndexing:
    def test_the_latest_window_wins(self) -> None:
        early = compute_source_health([], entry=entry("outlet_a"), window=WINDOW, as_of=AS_OF)
        later_window = FetchWindow(
            datetime(2026, 3, 8, tzinfo=UTC), datetime(2026, 3, 15, tzinfo=UTC)
        )
        late = compute_source_health(
            [],
            entry=entry("outlet_a"),
            window=later_window,
            as_of=datetime(2026, 3, 15, tzinfo=UTC),
        )
        indexed = health_by_source([late, early])
        assert indexed["outlet_a"].window_end == later_window.end

    def test_an_empty_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="empty health window"):
            compute_source_health([], entry=entry(), window=WINDOW, as_of=AS_OF).model_validate(
                compute_source_health([], entry=entry(), window=WINDOW, as_of=AS_OF).model_dump()
                | {"window_end": WINDOW.start}
            )
