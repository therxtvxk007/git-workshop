"""Acquisition adapters, and the invariants the connector imposes on all of them.

Every adapter here reads a recorded fixture through an injected reader. None of
them opens a socket, which is what lets the cutoff and licence rules be tested
at all: a test that had to reach a publisher would be testing the publisher.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from _news_builders import FIXTURES, entry, reader_for, registry
from pramaanx.ingest.article_content import LicenceClass, RetentionDecision
from pramaanx.ingest.base import FetchWindow
from pramaanx.ingest.connectors.news import (
    FeedAcquisition,
    FieldMap,
    JsonApiAcquisition,
    LicensedArchiveAcquisition,
    NewsAcquisition,
    NewsAcquisitionError,
    NewsConnector,
    RawArticle,
    acquisition_for,
    articles_by_source,
    parse_feed_datetime,
)
from pramaanx.ingest.news_registry import (
    AcquisitionMethod,
    NewsSourceEntry,
    ResolvabilityPolicy,
    StorableField,
)

WINDOW = FetchWindow(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 8, tzinfo=UTC))
RETRIEVED = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
AS_OF = datetime(2026, 3, 8, tzinfo=UTC)

API_MAP = FieldMap(
    record_id="id",
    url="canonical",
    headline="title",
    body="text",
    published_at="published",
    modified_at="updated",
    language="lang",
    byline="author",
    wire_service="agency",
    items_path="payload.articles",
)


class TestFeedDatetimeParsing:
    def test_rfc_822_with_an_offset_is_accepted(self) -> None:
        assert parse_feed_datetime("Sun, 01 Mar 2026 09:30:00 +0530") == datetime(
            2026, 3, 1, 4, 0, tzinfo=UTC
        )

    def test_iso_8601_is_accepted(self) -> None:
        assert parse_feed_datetime("2026-03-01T05:00:00Z") == datetime(2026, 3, 1, 5, 0, tzinfo=UTC)

    def test_a_timestamp_without_an_offset_is_refused(self) -> None:
        # Indian publishers post in IST. Reading 09:00 IST as 09:00 UTC moves
        # the article five and a half hours earlier -- across a cutoff often
        # enough to matter, and silently every time.
        with pytest.raises(NewsAcquisitionError, match="no timezone offset"):
            parse_feed_datetime("2026-03-01T09:00:00")

    @pytest.mark.parametrize("value", ["", "   ", "not a date", "2026-13-45T99:99:99Z"])
    def test_unparseable_timestamps_are_refused(self, value: str) -> None:
        with pytest.raises(NewsAcquisitionError):
            parse_feed_datetime(value)


class TestRawArticle:
    def test_naive_timestamps_are_refused_at_the_boundary(self) -> None:
        # Required behaviour 6, at the point where a parser hands over.
        for field in ("retrieved_at", "published_at", "modified_at"):
            kwargs = {
                "source_record_id": "x",
                "url": "https://example.test/a",
                "retrieved_at": RETRIEVED,
            }
            kwargs[field] = datetime(2026, 3, 1, 9, 0)  # noqa: DTZ001
            with pytest.raises(NewsAcquisitionError, match="naive"):
                RawArticle(**kwargs)  # type: ignore[arg-type]


class TestFeedAcquisition:
    def _acquisition(self, name: str = "pib_feed.xml") -> FeedAcquisition:
        return FeedAcquisition(
            source_record_id_prefix="pib",
            reader=reader_for(name),
            retrieved_at=RETRIEVED,
            language="en",
        )

    def test_rss_items_become_raw_articles(self) -> None:
        articles = list(self._acquisition().fetch(WINDOW))
        assert len(articles) == 2
        first = articles[0]
        assert first.headline == "Security review meeting held in the state capital"
        assert first.published_at == datetime(2026, 3, 1, 4, 0, tzinfo=UTC)
        assert first.byline == "Ministry Spokesperson"

    def test_atom_entries_become_raw_articles(self) -> None:
        articles = list(self._acquisition("atom_feed.xml").fetch(WINDOW))
        assert len(articles) == 1
        assert articles[0].modified_at == datetime(2026, 3, 1, 6, 15, tzinfo=UTC)
        assert articles[0].byline == "Staff Reporter"

    def test_a_doctype_is_refused_before_parsing(self) -> None:
        # Entity expansion delivered through an evidence feed is a denial of
        # service, not a formatting choice.
        payload = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "b">]><rss><channel/></rss>'
        acquisition = FeedAcquisition(
            source_record_id_prefix="x", reader=lambda: payload, retrieved_at=RETRIEVED
        )
        with pytest.raises(NewsAcquisitionError, match="DOCTYPE"):
            list(acquisition.fetch(WINDOW))

    def test_malformed_xml_is_refused(self) -> None:
        acquisition = FeedAcquisition(
            source_record_id_prefix="x", reader=lambda: b"<rss>", retrieved_at=RETRIEVED
        )
        with pytest.raises(NewsAcquisitionError, match="well-formed"):
            list(acquisition.fetch(WINDOW))

    def test_an_unrecognised_dialect_is_not_an_empty_result(self) -> None:
        # An empty parse and an unreadable feed must never look the same: one
        # means no news, the other means no parser.
        acquisition = FeedAcquisition(
            source_record_id_prefix="x",
            reader=lambda: b"<something><else/></something>",
            retrieved_at=RETRIEVED,
        )
        with pytest.raises(NewsAcquisitionError, match="neither RSS"):
            list(acquisition.fetch(WINDOW))

    def test_an_item_without_a_link_is_refused(self) -> None:
        payload = b"<rss><channel><item><title>t</title></item></channel></rss>"
        acquisition = FeedAcquisition(
            source_record_id_prefix="x", reader=lambda: payload, retrieved_at=RETRIEVED
        )
        with pytest.raises(NewsAcquisitionError, match="no <link>"):
            list(acquisition.fetch(WINDOW))

    def test_a_naive_retrieved_at_is_refused(self) -> None:
        with pytest.raises(NewsAcquisitionError, match="timezone-aware"):
            FeedAcquisition(
                source_record_id_prefix="x",
                reader=lambda: b"",
                retrieved_at=datetime(2026, 3, 1),  # noqa: DTZ001
            )

    def test_an_atom_entry_without_a_link_href_is_refused(self) -> None:
        payload = (
            b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>t</title></entry></feed>'
        )
        acquisition = FeedAcquisition(
            source_record_id_prefix="x", reader=lambda: payload, retrieved_at=RETRIEVED
        )
        with pytest.raises(NewsAcquisitionError, match="no link href"):
            list(acquisition.fetch(WINDOW))

    def test_the_window_guard_rejects_an_out_of_window_article(self) -> None:
        acquisition = FeedAcquisition(
            source_record_id_prefix="pib",
            reader=reader_for("pib_feed.xml"),
            retrieved_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        with pytest.raises(NewsAcquisitionError, match="outside the requested window"):
            list(acquisition.guarded_fetch(WINDOW))


class TestJsonApiAcquisition:
    def _acquisition(self) -> JsonApiAcquisition:
        return JsonApiAcquisition(
            source_record_id_prefix="api",
            reader=reader_for("publisher_api.json"),
            field_map=API_MAP,
            retrieved_at=RETRIEVED,
        )

    def test_records_are_read_through_the_declared_path(self) -> None:
        articles = list(self._acquisition().fetch(WINDOW))
        assert len(articles) == 2
        assert articles[0].language == "en"
        assert articles[1].wire_service == "PTI"

    def test_a_missing_envelope_path_is_refused(self) -> None:
        acquisition = JsonApiAcquisition(
            source_record_id_prefix="api",
            reader=lambda: b'{"payload": {}}',
            field_map=API_MAP,
            retrieved_at=RETRIEVED,
        )
        with pytest.raises(NewsAcquisitionError, match=r"has no 'payload.articles' path"):
            list(acquisition.fetch(WINDOW))

    def test_a_mapped_field_that_vanished_upstream_is_a_failure(self) -> None:
        # Not a column of nulls. A field disappearing from a response is a
        # contract change, and it has to be noticed on the day it happens.
        payload = json.dumps({"payload": {"articles": [{"id": "1", "canonical": "u"}]}})
        acquisition = JsonApiAcquisition(
            source_record_id_prefix="api",
            reader=lambda: payload.encode(),
            field_map=API_MAP,
            retrieved_at=RETRIEVED,
        )
        with pytest.raises(NewsAcquisitionError, match="missing mapped field"):
            list(acquisition.fetch(WINDOW))

    def test_invalid_json_is_refused(self) -> None:
        acquisition = JsonApiAcquisition(
            source_record_id_prefix="api",
            reader=lambda: b"{not json",
            field_map=API_MAP,
            retrieved_at=RETRIEVED,
        )
        with pytest.raises(NewsAcquisitionError, match="not valid JSON"):
            list(acquisition.fetch(WINDOW))

    def test_a_non_list_items_path_is_refused(self) -> None:
        acquisition = JsonApiAcquisition(
            source_record_id_prefix="api",
            reader=lambda: b'{"payload": {"articles": 7}}',
            field_map=API_MAP,
            retrieved_at=RETRIEVED,
        )
        with pytest.raises(NewsAcquisitionError, match="not a list"):
            list(acquisition.fetch(WINDOW))

    def test_a_naive_retrieved_at_is_refused(self) -> None:
        with pytest.raises(NewsAcquisitionError, match="timezone-aware"):
            JsonApiAcquisition(
                source_record_id_prefix="api",
                reader=lambda: b"{}",
                field_map=API_MAP,
                retrieved_at=datetime(2026, 3, 1),  # noqa: DTZ001
            )

    def test_an_unmapped_optional_field_is_simply_absent(self) -> None:
        # A FieldMap that declares no byline must not invent one, and must not
        # fail looking for a key it was never told about.
        minimal = FieldMap(record_id="id", url="canonical", items_path="payload.articles")
        acquisition = JsonApiAcquisition(
            source_record_id_prefix="api",
            reader=reader_for("publisher_api.json"),
            field_map=minimal,
            retrieved_at=RETRIEVED,
        )
        articles = list(acquisition.fetch(WINDOW))
        assert all(item.byline is None and item.headline is None for item in articles)

    def test_a_non_object_record_is_refused(self) -> None:
        acquisition = JsonApiAcquisition(
            source_record_id_prefix="api",
            reader=lambda: b'{"payload": {"articles": ["oops"]}}',
            field_map=API_MAP,
            retrieved_at=RETRIEVED,
        )
        with pytest.raises(NewsAcquisitionError, match="not an object"):
            list(acquisition.fetch(WINDOW))


class TestLicensedArchiveAcquisition:
    def _acquisition(self, path: Path | None = None) -> LicensedArchiveAcquisition:
        return LicensedArchiveAcquisition(
            source_record_id_prefix="arch",
            path=path or (FIXTURES / "archive.jsonl"),
            retrieved_at=RETRIEVED,
            language="en",
        )

    def test_both_revisions_are_read(self) -> None:
        articles = list(self._acquisition().fetch(WINDOW))
        assert len(articles) == 2
        assert articles[1].revision_index == 1
        assert articles[1].revision_of == "arch-1"

    def test_a_missing_archive_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(NewsAcquisitionError, match="not found"):
            list(self._acquisition(tmp_path / "absent.jsonl").fetch(WINDOW))

    def test_a_malformed_line_names_its_line_number(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('{"record_id": "a", "url": "https://x.test/a"}\n{oops\n', encoding="utf-8")
        with pytest.raises(NewsAcquisitionError, match=":2 is not valid JSON"):
            list(self._acquisition(path).fetch(WINDOW))

    def test_a_naive_retrieved_at_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(NewsAcquisitionError, match="timezone-aware"):
            LicensedArchiveAcquisition(
                source_record_id_prefix="arch",
                path=tmp_path / "a.jsonl",
                retrieved_at=datetime(2026, 3, 1),  # noqa: DTZ001
            )

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "gappy.jsonl"
        path.write_text('\n{"record_id": "a", "url": "https://x.test/a"}\n\n', encoding="utf-8")
        assert len(list(self._acquisition(path).fetch(WINDOW))) == 1


class TestAcquisitionSelection:
    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            (AcquisitionMethod.RSS, FeedAcquisition),
            (AcquisitionMethod.ATOM, FeedAcquisition),
            (AcquisitionMethod.GOVERNMENT_FEED, FeedAcquisition),
            (AcquisitionMethod.PUBLISHER_API, JsonApiAcquisition),
            (AcquisitionMethod.GDELT_ARTICLE_URL, JsonApiAcquisition),
            (AcquisitionMethod.RELIEFWEB_REPORT, JsonApiAcquisition),
        ],
    )
    def test_each_method_maps_to_an_adapter(
        self, method: AcquisitionMethod, expected: type[NewsAcquisition]
    ) -> None:
        kwargs: dict[str, object] = {"retrieved_at": RETRIEVED, "reader": lambda: b"{}"}
        if expected is JsonApiAcquisition:
            kwargs["field_map"] = API_MAP
        built = acquisition_for(entry(acquisition=method), **kwargs)
        assert isinstance(built, expected)

    def test_the_licensed_archive_method_maps_to_its_adapter(self, tmp_path: Path) -> None:
        built = acquisition_for(
            entry(acquisition=AcquisitionMethod.LICENSED_ARCHIVE),
            path=tmp_path / "a.jsonl",
            retrieved_at=RETRIEVED,
        )
        assert isinstance(built, LicensedArchiveAcquisition)


class TestNewsConnector:
    def _connector(self, source: NewsSourceEntry | None = None) -> NewsConnector:
        source = source or entry("pib", acquisition=AcquisitionMethod.GOVERNMENT_FEED)
        return NewsConnector(
            registry(source),
            {
                source.source_id: FeedAcquisition(
                    source_record_id_prefix=source.source_id,
                    reader=reader_for("pib_feed.xml"),
                    retrieved_at=RETRIEVED,
                    language="en",
                )
            },
        )

    def test_records_carry_every_required_field(self) -> None:
        records = self._connector().acquire(WINDOW, as_of=AS_OF)
        assert len(records) == 2
        built = records[0]
        for field in (
            "observation_id",
            "source_id",
            "source_record_id",
            "canonical_url",
            "canonical_url_hash",
            "body_hash",
            "retrieved_at",
            "first_resolvable_at",
            "licence_class",
            "redistribution",
            "source_version",
            "parser_version",
            "article_content_hash",
        ):
            assert getattr(built, field) is not None

    def test_tracking_parameters_do_not_survive_into_the_record(self) -> None:
        records = self._connector().acquire(WINDOW, as_of=AS_OF)
        assert all("utm_source" not in item.canonical_url for item in records)

    def test_two_hosts_for_one_article_produce_one_canonical_url(self) -> None:
        # The fixture serves one release from pib.gov.in and another from
        # www.pib.gov.in; both must canonicalise to the same host.
        records = self._connector().acquire(WINDOW, as_of=AS_OF)
        assert all(item.canonical_url.startswith("https://pib.gov.in/") for item in records)

    def test_the_retrieval_policy_is_the_default(self) -> None:
        records = self._connector().acquire(WINDOW, as_of=AS_OF)
        assert all(item.first_resolvable_at == RETRIEVED for item in records)

    def test_the_publication_policy_uses_the_publisher_timestamp(self) -> None:
        source = entry(
            "pib",
            acquisition=AcquisitionMethod.GOVERNMENT_FEED,
            policy=ResolvabilityPolicy.PUBLICATION,
        )
        records = self._connector(source).acquire(WINDOW, as_of=AS_OF)
        assert records[0].first_resolvable_at < RETRIEVED

    def test_the_publication_policy_still_clamps_to_retrieval(self) -> None:
        # A feed claiming publication after this project downloaded it is
        # describing a clock problem, not a scoop. Cutoff safety wins; the
        # publisher's claim is kept but marked, so the source's delay
        # statistics can be discounted rather than believed.
        source = entry("x", policy=ResolvabilityPolicy.PUBLICATION)
        connector = NewsConnector(registry(source), {})
        raw = RawArticle(
            source_record_id="x:1",
            url="https://example.test/a",
            retrieved_at=RETRIEVED,
            published_at=RETRIEVED.replace(hour=23),
        )
        built = connector.build_record(raw, source)
        assert built.first_resolvable_at == RETRIEVED
        assert built.publisher_timestamp_disputed is True
        assert built.published_at == RETRIEVED.replace(hour=23)

    def test_an_undisputed_record_cannot_hide_a_skewed_publisher_clock(self) -> None:
        # The flag is not optional bookkeeping: a record in that state must
        # declare it, or the skew becomes invisible.
        source = entry("x", policy=ResolvabilityPolicy.PUBLICATION)
        connector = NewsConnector(registry(source), {})
        raw = RawArticle(
            source_record_id="x:1",
            url="https://example.test/a",
            retrieved_at=RETRIEVED,
            published_at=RETRIEVED.replace(hour=23),
        )
        built = connector.build_record(raw, source)
        with pytest.raises(ValidationError, match="publisher_timestamp_disputed"):
            type(built).model_validate(built.model_dump() | {"publisher_timestamp_disputed": False})

    def test_a_normal_record_does_not_dispute_its_publisher(self) -> None:
        records = self._connector().acquire(WINDOW, as_of=AS_OF)
        assert all(item.publisher_timestamp_disputed is False for item in records)

    def test_a_restrictive_licence_strips_content_from_the_record(self) -> None:
        source = entry("pib", licence=LicenceClass.UNKNOWN)
        records = self._connector(source).acquire(WINDOW, as_of=AS_OF)
        assert all(item.body_text is None and item.headline is None for item in records)
        assert all(
            item.retention_decision is RetentionDecision.WITHHELD_FAIL_CLOSED for item in records
        )

    def test_a_byline_is_dropped_when_it_is_not_a_permitted_field(self) -> None:
        source = entry(
            "pib",
            licence=LicenceClass.SNIPPET_ONLY,
            permitted=(StorableField.HEADLINE, StorableField.BODY, StorableField.HASHES),
        )
        records = self._connector(source).acquire(WINDOW, as_of=AS_OF)
        assert all(item.byline is None for item in records)

    def test_a_headline_is_dropped_when_it_is_not_a_permitted_field(self) -> None:
        source = entry(
            "pib",
            licence=LicenceClass.SNIPPET_ONLY,
            permitted=(StorableField.BODY, StorableField.HASHES),
        )
        records = self._connector(source).acquire(WINDOW, as_of=AS_OF)
        assert all(item.headline is None for item in records)

    def test_a_body_is_dropped_when_it_is_not_a_permitted_field(self) -> None:
        # The licence sets the ceiling; permitted_fields may lower it. A source
        # licensed for full text but configured to keep headlines only must
        # keep headlines only.
        source = entry(
            "pib",
            licence=LicenceClass.FULL_TEXT_PERMITTED,
            permitted=(StorableField.HEADLINE, StorableField.HASHES),
        )
        records = self._connector(source).acquire(WINDOW, as_of=AS_OF)
        assert all(item.body_text is None for item in records)
        assert all(item.headline is not None for item in records)

    def test_the_recorded_decision_reflects_what_was_actually_kept(self) -> None:
        # Not what the licence would have allowed. A record claiming STORED_FULL
        # while holding no body would misreport the corpus to every coverage
        # feature downstream of it.
        source = entry(
            "pib",
            licence=LicenceClass.FULL_TEXT_PERMITTED,
            permitted=(StorableField.HEADLINE, StorableField.HASHES),
        )
        records = self._connector(source).acquire(WINDOW, as_of=AS_OF)
        assert all(item.retention_decision is RetentionDecision.METADATA_KEPT for item in records)

    def test_keeping_neither_body_nor_headline_records_hashes_only(self) -> None:
        source = entry(
            "pib",
            licence=LicenceClass.FULL_TEXT_PERMITTED,
            permitted=(StorableField.HASHES,),
        )
        records = self._connector(source).acquire(WINDOW, as_of=AS_OF)
        assert all(item.retention_decision is RetentionDecision.HASH_KEPT for item in records)
        assert all(item.body_text is None and item.headline is None for item in records)

    def test_hashes_still_identify_the_article_when_nothing_is_kept(self) -> None:
        # The whole reason narrowing is safe: syndication and revision
        # detection run on hashes, so a hash-only source still contributes.
        wide = entry("pib", licence=LicenceClass.FULL_TEXT_PERMITTED)
        narrow = entry(
            "pib", licence=LicenceClass.FULL_TEXT_PERMITTED, permitted=(StorableField.HASHES,)
        )
        wide_records = self._connector(wide).acquire(WINDOW, as_of=AS_OF)
        narrow_records = self._connector(narrow).acquire(WINDOW, as_of=AS_OF)
        assert [item.normalised_content_hash for item in wide_records] == [
            item.normalised_content_hash for item in narrow_records
        ]

    def test_a_source_out_of_force_is_skipped_not_read_under_current_terms(self) -> None:
        # The whole reason the registry is effective-dated.
        source = entry(
            "pib",
            acquisition=AcquisitionMethod.GOVERNMENT_FEED,
            effective_from=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert self._connector(source).acquire(WINDOW, as_of=AS_OF) == ()

    def test_an_acquisition_without_a_registry_entry_is_refused(self) -> None:
        # A source with no registry entry has no licence, and a source with no
        # licence may not be read at all.
        with pytest.raises(NewsAcquisitionError, match="absent from the registry"):
            NewsConnector(
                registry(entry("known")),
                {
                    "stranger": FeedAcquisition(
                        source_record_id_prefix="s",
                        reader=lambda: b"",
                        retrieved_at=RETRIEVED,
                    )
                },
            )

    def test_a_naive_as_of_is_refused(self) -> None:
        with pytest.raises(NewsAcquisitionError, match="timezone-aware"):
            self._connector().acquire(WINDOW, as_of=datetime(2026, 3, 8))  # noqa: DTZ001

    def test_output_is_sorted_by_observation_id(self) -> None:
        records = self._connector().acquire(WINDOW, as_of=AS_OF)
        assert [item.observation_id for item in records] == sorted(
            item.observation_id for item in records
        )

    def test_the_plan_describes_without_acquiring(self) -> None:
        plan = self._connector().plan(WINDOW, as_of=AS_OF)
        assert plan["registry_hash"].startswith("sha256:")
        assert plan["sources"][0]["in_force"] is True
        assert plan["sources"][0]["licence_class"] == "full_text_permitted"

    def test_the_plan_reports_a_source_that_is_not_in_force(self) -> None:
        source = entry("pib", effective_from=datetime(2027, 1, 1, tzinfo=UTC))
        plan = self._connector(source).plan(WINDOW, as_of=AS_OF)
        assert plan["sources"][0]["in_force"] is False
        assert plan["sources"][0]["licence_class"] is None

    def test_no_credential_appears_in_a_serialised_record(self) -> None:
        # Required behaviour 10, at the record boundary.
        source = entry("pib", credential_env="PRAMAANX_FEED_TOKEN")
        for built in self._connector(source).acquire(WINDOW, as_of=AS_OF):
            dumped = built.model_dump_json()
            assert "PRAMAANX_FEED_TOKEN" not in dumped
            for marker in ("token=", "secret=", "Bearer ", "password="):
                assert marker not in dumped

    def test_articles_by_source_groups_and_sorts(self) -> None:
        records = self._connector().acquire(WINDOW, as_of=AS_OF)
        grouped = articles_by_source(records)
        assert set(grouped) == {"pib"}
        assert [item.observation_id for item in grouped["pib"]] == sorted(
            item.observation_id for item in grouped["pib"]
        )
