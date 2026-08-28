"""The news layer's cutoff guarantees, stated as things that must not change.

Every test here has the same shape: build an output at a cutoff, add something
that happened after it, and assert the output is *byte-identical*. Not similar,
not equal as a set -- identical, because the whole claim being made about this
project is that a forecast can be reconstructed exactly, and a reconstruction
that differs by one field is a reconstruction that cannot be checked.

These are negative controls. They are supposed to fail loudly the day somebody
adds a convenience that reads a record it should not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from _news_builders import entry, reader_for, record, registry
from pramaanx.ingest.article_content import (
    ArticleRecord,
    SnapshotWriteError,
    group_syndication,
    latest_as_of,
    snapshot_payload,
    write_snapshot,
)
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.news import FeedAcquisition, NewsConnector
from pramaanx.ingest.news_registry import AcquisitionMethod
from pramaanx.ingest.source_health import build_coverage_report, compute_source_health

CUTOFF = datetime(2026, 3, 5, tzinfo=UTC)
BEFORE = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)
AFTER = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
WINDOW = FetchWindow(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 8, tzinfo=UTC))


def before_cutoff(index: int) -> ArticleRecord:
    return record(
        url=f"https://example.test/before/{index}",
        body=f"A story filed before the cutoff, number {index}, with enough words.",
        retrieved_at=BEFORE,
        first_resolvable_at=BEFORE,
    )


def after_cutoff(index: int) -> ArticleRecord:
    return record(
        url=f"https://example.test/after/{index}",
        body=f"A story filed after the cutoff, number {index}, with enough words.",
        retrieved_at=AFTER,
        first_resolvable_at=AFTER,
    )


class TestFutureDocumentInjection:
    def test_future_articles_cannot_change_an_earlier_snapshot(self, tmp_path: Path) -> None:
        # Required behaviour 1. The negative control the whole layer exists to
        # pass: tomorrow's news must not be able to edit yesterday's evidence.
        early = [before_cutoff(index) for index in range(3)]
        baseline = write_snapshot(early, path=tmp_path / "a.jsonl", cutoff=CUTOFF)

        injected = [*early, *(after_cutoff(index) for index in range(3))]
        usable = latest_as_of(injected, CUTOFF)
        replayed = write_snapshot(usable, path=tmp_path / "b.jsonl", cutoff=CUTOFF)

        assert replayed.output_hash == baseline.output_hash
        assert replayed.input_hash == baseline.input_hash
        assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()

    def test_a_snapshot_refuses_to_contain_post_cutoff_evidence(self, tmp_path: Path) -> None:
        # Filtering is the caller's job, but a snapshot that was handed
        # unfiltered records must not quietly write them.
        with pytest.raises(SnapshotWriteError, match="after the snapshot cutoff"):
            write_snapshot(
                [before_cutoff(0), after_cutoff(0)], path=tmp_path / "a.jsonl", cutoff=CUTOFF
            )

    def test_future_articles_cannot_change_earlier_health(self) -> None:
        source = entry("outlet_a", expected_items_per_day=1.0)
        early = [before_cutoff(index) for index in range(3)]
        baseline = compute_source_health(early, entry=source, window=WINDOW, as_of=CUTOFF)

        injected = [*early, *(after_cutoff(index) for index in range(20))]
        replayed = compute_source_health(injected, entry=source, window=WINDOW, as_of=CUTOFF)

        assert replayed.model_dump() == baseline.model_dump()

    def test_future_articles_cannot_change_an_earlier_coverage_report(self) -> None:
        built = registry(entry("outlet_a", expected_items_per_day=1.0))
        early = [before_cutoff(index) for index in range(3)]
        baseline = build_coverage_report(early, registry=built, window=WINDOW, as_of=CUTOFF)

        injected = [*early, *(after_cutoff(index) for index in range(5))]
        replayed = build_coverage_report(injected, registry=built, window=WINDOW, as_of=CUTOFF)

        assert replayed.model_dump() == baseline.model_dump()

    def test_a_future_source_vintage_cannot_change_an_earlier_universe(self) -> None:
        # A licence agreed next year does not retroactively license last year.
        built = registry(
            entry("outlet_a", effective_from=datetime(2024, 1, 1, tzinfo=UTC)),
            entry("outlet_future", effective_from=datetime(2027, 1, 1, tzinfo=UTC)),
        )
        assert [item.source_id for item in built.as_of(CUTOFF)] == ["outlet_a"]


class TestPostCutoffRevision:
    def _revision_pair(self) -> tuple[ArticleRecord, ArticleRecord]:
        original = record(
            url="https://example.test/story/42",
            headline="Two injured in blast near market",
            body="Two people were injured in a blast near the market, police said.",
            retrieved_at=BEFORE,
            first_resolvable_at=BEFORE,
        )
        revision = record(
            url="https://example.test/story/42",
            headline="Nine killed in blast near market",
            body="Nine people were killed in a blast near the market, police said.",
            retrieved_at=AFTER,
            first_resolvable_at=AFTER,
            modified_at=AFTER,
            revision_of=original.observation_id,
            revision_index=1,
        )
        return original, revision

    def test_a_post_cutoff_revision_cannot_change_earlier_content(self) -> None:
        # Required behaviour 2. The revision is not a smaller version of the
        # truth arriving late; at the cutoff it does not exist, and a death
        # toll revised upward next week is exactly the kind of hindsight that
        # would make a backtest look prophetic.
        original, revision = self._revision_pair()
        visible = latest_as_of([original, revision], CUTOFF)
        assert len(visible) == 1
        assert visible[0].observation_id == original.observation_id
        assert visible[0].headline == "Two injured in blast near market"

    def test_the_revision_becomes_visible_only_after_it_is_resolvable(self) -> None:
        original, revision = self._revision_pair()
        later = latest_as_of([original, revision], datetime(2026, 3, 9, tzinfo=UTC))
        assert later[0].observation_id == revision.observation_id

    def test_a_revision_never_mutates_the_record_it_supersedes(self) -> None:
        # Immutability is what makes the guarantee checkable rather than
        # merely intended.
        original, revision = self._revision_pair()
        before = original.model_dump_json()
        latest_as_of([original, revision], datetime(2026, 3, 9, tzinfo=UTC))
        assert original.model_dump_json() == before
        assert revision.revision_of == original.observation_id

    def test_a_revised_snapshot_is_byte_identical_to_the_original(self, tmp_path: Path) -> None:
        original, revision = self._revision_pair()
        baseline = write_snapshot([original], path=tmp_path / "a.jsonl", cutoff=CUTOFF)
        replayed = write_snapshot(
            latest_as_of([original, revision], CUTOFF), path=tmp_path / "b.jsonl", cutoff=CUTOFF
        )
        assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()
        assert replayed.output_hash == baseline.output_hash


class TestConnectorEndToEnd:
    """The same guarantee, driven through acquisition rather than hand-built.

    The unit tests above build records directly. These run the real connector
    over a real fixture, because the leak that matters is the one a parser
    introduces, and a guarantee proved only on hand-made records proves only
    that the records were made correctly.
    """

    def _connector(self, retrieved_at: datetime) -> NewsConnector:
        source = entry("pib", acquisition=AcquisitionMethod.GOVERNMENT_FEED)
        return NewsConnector(
            registry(source),
            {
                "pib": FeedAcquisition(
                    source_record_id_prefix="pib",
                    reader=reader_for("pib_feed.xml"),
                    retrieved_at=retrieved_at,
                    language="en",
                )
            },
        )

    def test_acquired_records_are_invisible_before_they_were_retrieved(self) -> None:
        records = self._connector(AFTER).acquire(WINDOW, as_of=datetime(2026, 3, 8, tzinfo=UTC))
        assert records
        assert all(not item.usable_at(CUTOFF) for item in records)
        assert latest_as_of(records, CUTOFF) == ()

    def test_a_second_acquisition_of_the_same_feed_is_byte_identical(
        self, tmp_path: Path
    ) -> None:
        # Determinism through the whole path: identifiers, hashes and ordering
        # all derive from content, never from a clock or a counter.
        first = self._connector(BEFORE).acquire(WINDOW, as_of=CUTOFF)
        second = self._connector(BEFORE).acquire(WINDOW, as_of=CUTOFF)
        a = write_snapshot(first, path=tmp_path / "a.jsonl", cutoff=CUTOFF)
        b = write_snapshot(second, path=tmp_path / "b.jsonl", cutoff=CUTOFF)
        assert a.output_hash == b.output_hash
        assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()

    def test_a_later_acquisition_does_not_alter_the_earlier_snapshot(
        self, tmp_path: Path
    ) -> None:
        early = self._connector(BEFORE).acquire(WINDOW, as_of=CUTOFF)
        baseline = write_snapshot(early, path=tmp_path / "a.jsonl", cutoff=CUTOFF)

        # The same feed re-fetched after the cutoff: new records, new ids.
        late = self._connector(AFTER).acquire(WINDOW, as_of=datetime(2026, 3, 8, tzinfo=UTC))
        assert {item.observation_id for item in early}.isdisjoint(
            item.observation_id for item in late
        )

        replayed = write_snapshot(
            latest_as_of([*early, *late], CUTOFF), path=tmp_path / "b.jsonl", cutoff=CUTOFF
        )
        assert replayed.output_hash == baseline.output_hash


class TestGroupingIsCutoffBound:
    def test_future_wire_copies_do_not_change_earlier_lineage_counts(self) -> None:
        # Independence measured at a cutoff must not improve because the story
        # was picked up more widely afterwards.
        early = [before_cutoff(index) for index in range(2)]
        baseline = group_syndication(latest_as_of(early, CUTOFF))

        late = [after_cutoff(index) for index in range(4)]
        replayed = group_syndication(latest_as_of([*early, *late], CUTOFF))

        assert replayed.model_dump() == baseline.model_dump()
        assert replayed.independent_lineage_count == baseline.independent_lineage_count


class TestOrderingIndependence:
    def test_reordered_input_produces_identical_bytes(self, tmp_path: Path) -> None:
        # Required behaviour 11, on the write path. Two runs that acquire the
        # same articles in a different order must produce the same file.
        records = [before_cutoff(index) for index in range(6)]
        forward = write_snapshot(records, path=tmp_path / "a.jsonl", cutoff=CUTOFF)
        backward = write_snapshot(list(reversed(records)), path=tmp_path / "b.jsonl", cutoff=CUTOFF)
        assert forward.output_hash == backward.output_hash
        assert forward.input_hash == backward.input_hash
        assert snapshot_payload(records) == snapshot_payload(list(reversed(records)))
