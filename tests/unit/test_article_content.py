"""What an article record is allowed to contain, and what it must keep apart.

The tests here are mostly about refusals. Almost every way this layer can fail
in production is a way in which it accepts something it should not: text under
an unread licence, a timestamp with no offset, a URL carrying a token, a
snapshot quietly replacing an earlier one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from _news_builders import RETRIEVED, record
from pramaanx.hashing import hash_text
from pramaanx.ingest.article_content import (
    SCRIPT_UNKNOWN,
    SNIPPET_MAX_CHARS,
    ArticleRecord,
    CanonicalUrlError,
    LicenceClass,
    RetentionDecision,
    SnapshotWriteError,
    apply_retention,
    canonical_url,
    dominant_script,
    latest_as_of,
    normalise_for_comparison,
    normalised_content_hash,
    snapshot_payload,
    write_snapshot,
)


class TestCanonicalUrl:
    def test_tracking_parameters_are_removed(self) -> None:
        # Five newsletter links to one article are one article, not five
        # independent sources. That is the entire reason this runs.
        assert (
            canonical_url("https://example.test/a?utm_source=x&id=7&fbclid=y")
            == "https://example.test/a?id=7"
        )

    def test_host_case_www_and_fragment_are_normalised(self) -> None:
        assert canonical_url("HTTPS://WWW.Example.test/A/#section") == "https://example.test/A"

    def test_default_ports_are_dropped_and_others_kept(self) -> None:
        assert canonical_url("https://example.test:443/a") == "https://example.test/a"
        assert canonical_url("https://example.test:8443/a") == "https://example.test:8443/a"

    def test_query_parameters_are_sorted(self) -> None:
        # Two orderings of the same parameters address the same document, and
        # must therefore hash the same.
        assert canonical_url("https://example.test/a?b=2&a=1") == canonical_url(
            "https://example.test/a?a=1&b=2"
        )

    def test_userinfo_is_refused_rather_than_stripped(self) -> None:
        # Stripping would be worse than failing: the credential would have been
        # read, logged by whatever produced the URL, and silently forgiven.
        with pytest.raises(CanonicalUrlError, match="userinfo"):
            canonical_url("https://user:s3cret@example.test/a")

    @pytest.mark.parametrize(
        "url",
        ["", "   ", "/relative/path", "ftp://example.test/a", "not a url"],
    )
    def test_unusable_urls_are_refused(self, url: str) -> None:
        with pytest.raises(CanonicalUrlError):
            canonical_url(url)

    def test_root_path_keeps_its_slash(self) -> None:
        assert canonical_url("https://example.test") == "https://example.test/"

    def test_a_url_with_a_port_but_no_host_is_refused(self) -> None:
        with pytest.raises(CanonicalUrlError, match="no host"):
            canonical_url("https://:8443/a")


class TestNormalisation:
    def test_unicode_composition_does_not_change_identity(self) -> None:
        # The same Devanagari string composed two ways is one story.
        composed = "कि"
        decomposed = "क" + "ि"
        assert normalise_for_comparison(composed) == normalise_for_comparison(decomposed)

    def test_punctuation_and_case_do_not_change_identity(self) -> None:
        assert normalised_content_hash("A Headline!", "Body -- text.") == normalised_content_hash(
            "a headline", "body text"
        )

    def test_a_headline_only_record_is_not_hash_equal_to_another(self) -> None:
        # A body-less record must not collide with every other body-less record.
        assert normalised_content_hash("first", None) != normalised_content_hash("second", None)


class TestDominantScript:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("plain english text", "Latin"),
            ("नई दिल्ली", "Devanagari"),
            ("കേരളം", "Malayalam"),
            ("বাংলা", "Bengali"),
        ],
    )
    def test_scripts_are_identified(self, text: str, expected: str) -> None:
        assert dominant_script(text) == expected

    def test_unknown_is_not_guessed_as_latin(self) -> None:
        # "we cannot tell" and "it is English" are different claims, and a
        # coverage report built on the second would be confidently wrong.
        assert dominant_script("12345 !!! ") == SCRIPT_UNKNOWN

    def test_mixed_script_resolves_to_the_majority(self) -> None:
        assert dominant_script("കേരളം ok") == "Malayalam"


class TestRetention:
    def test_full_text_is_stored_when_permitted(self) -> None:
        retained = apply_retention(
            licence=LicenceClass.FULL_TEXT_PERMITTED, headline="H", body="B" * 500
        )
        assert retained.body_text == "B" * 500
        assert retained.decision is RetentionDecision.STORED_FULL

    def test_snippet_is_bounded(self) -> None:
        retained = apply_retention(licence=LicenceClass.SNIPPET_ONLY, headline="H", body="B" * 5000)
        assert retained.body_text is not None
        assert len(retained.body_text) == SNIPPET_MAX_CHARS
        assert retained.decision is RetentionDecision.STORED_SNIPPET

    def test_metadata_only_keeps_the_headline_and_drops_the_body(self) -> None:
        retained = apply_retention(licence=LicenceClass.METADATA_ONLY, headline="H", body="B")
        assert retained.headline == "H"
        assert retained.body_text is None

    @pytest.mark.parametrize(
        "licence", [LicenceClass.UNKNOWN, LicenceClass.PROHIBITED, LicenceClass.HASH_ONLY]
    )
    def test_no_text_survives_a_restrictive_licence(self, licence: LicenceClass) -> None:
        retained = apply_retention(licence=licence, headline="H", body="B")
        assert retained.body_text is None
        assert retained.headline is None

    def test_unknown_licence_never_stores_full_text(self) -> None:
        # Required behaviour 5. Stated at the level of the record, because that
        # is the artefact that reaches disk.
        built = record(licence=LicenceClass.UNKNOWN, headline="H", body="secret body")
        assert built.body_text is None
        assert built.headline is None
        assert built.retention_decision is RetentionDecision.WITHHELD_FAIL_CLOSED
        assert "secret body" not in built.model_dump_json()

    def test_hashes_survive_even_when_text_does_not(self) -> None:
        # The point of failing closed rather than refusing the article outright:
        # duplication and revision detection still work on hashes alone.
        withheld = apply_retention(licence=LicenceClass.UNKNOWN, headline="H", body="B")
        permitted = apply_retention(
            licence=LicenceClass.FULL_TEXT_PERMITTED, headline="H", body="B"
        )
        assert withheld.body_hash == permitted.body_hash
        assert withheld.normalised_content_hash == permitted.normalised_content_hash
        assert withheld.body_characters == 1

    def test_a_missing_body_hashes_as_empty_not_as_an_error(self) -> None:
        retained = apply_retention(licence=LicenceClass.METADATA_ONLY, headline="H", body=None)
        assert retained.body_hash == hash_text("")
        assert retained.body_characters == 0


class TestRecordRefusals:
    def test_a_record_cannot_carry_text_its_licence_forbids(self) -> None:
        # Enforced on the model, so a hand-built or deserialised record is
        # refused the same way a connector-built one would be. The payload here
        # is exactly what a licence downgrade upstream would produce: a body
        # retained under yesterday's terms, replayed under today's.
        permissive = record(licence=LicenceClass.FULL_TEXT_PERMITTED)
        assert permissive.body_text is not None
        payload = permissive.model_dump() | {
            "licence_class": LicenceClass.METADATA_ONLY.value,
            "retention_decision": RetentionDecision.METADATA_KEPT.value,
        }
        with pytest.raises(ValidationError, match="stores no body text"):
            ArticleRecord.model_validate(payload)

    def test_an_oversized_snippet_is_refused(self) -> None:
        base = record(licence=LicenceClass.SNIPPET_ONLY, body="B" * 100)
        with pytest.raises(ValidationError, match="exceeds the"):
            base.model_validate(base.model_dump() | {"body_text": "B" * (SNIPPET_MAX_CHARS + 1)})

    def test_a_withheld_record_may_not_carry_a_headline(self) -> None:
        base = record(licence=LicenceClass.UNKNOWN)
        with pytest.raises(ValidationError, match="retains no"):
            base.model_validate(base.model_dump() | {"headline": "leaked"})

    def test_a_withheld_record_must_say_it_was_withheld(self) -> None:
        base = record(licence=LicenceClass.UNKNOWN)
        with pytest.raises(ValidationError, match="must record"):
            base.model_validate(base.model_dump() | {"retention_decision": "hash_kept"})

    def test_naive_timestamps_are_rejected(self) -> None:
        # Required behaviour 6. A guessed timezone moves an Indian publication
        # time five and a half hours, which is enough to cross a cutoff.
        base = record()
        for field in ("published_at", "retrieved_at", "first_resolvable_at", "modified_at"):
            with pytest.raises(ValidationError, match="naive datetime"):
                base.model_validate(
                    base.model_dump() | {field: datetime(2026, 3, 1, 12, 0)}  # noqa: DTZ001
                )

    def test_resolvable_after_retrieval_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="after retrieved_at"):
            record(first_resolvable_at=RETRIEVED + timedelta(hours=1))

    def test_resolvable_before_publication_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="before published_at"):
            record(
                published_at=datetime(2026, 3, 2, 11, 0, tzinfo=UTC),
                first_resolvable_at=datetime(2026, 3, 2, 10, 0, tzinfo=UTC),
            )

    def test_modification_before_publication_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="precedes published_at"):
            record(
                published_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
                modified_at=datetime(2026, 3, 1, 6, 0, tzinfo=UTC),
            )


class TestTimestampsStaySeparate:
    def test_four_timestamps_are_four_fields(self) -> None:
        # Required behaviour 7. The failure this prevents is a later refactor
        # deciding two of these are "the same thing".
        built = record(
            published_at=datetime(2026, 3, 1, 6, 0, tzinfo=UTC),
            modified_at=datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
            retrieved_at=datetime(2026, 3, 2, 12, 0, tzinfo=UTC),
            first_resolvable_at=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
        )
        moments = {
            built.published_at,
            built.modified_at,
            built.retrieved_at,
            built.first_resolvable_at,
        }
        assert len(moments) == 4
        dumped = built.model_dump()
        for field in ("published_at", "modified_at", "retrieved_at", "first_resolvable_at"):
            assert field in dumped

    def test_cutoff_filtering_reads_only_first_resolvable_at(self) -> None:
        # Published early, retrieved late: usable from the retrieval, not from
        # the publisher's claim about when it went out.
        built = record(
            published_at=datetime(2026, 3, 1, 0, 0, tzinfo=UTC),
            retrieved_at=datetime(2026, 3, 5, 0, 0, tzinfo=UTC),
            first_resolvable_at=datetime(2026, 3, 5, 0, 0, tzinfo=UTC),
        )
        assert not built.usable_at(datetime(2026, 3, 2, tzinfo=UTC))
        assert built.usable_at(datetime(2026, 3, 5, tzinfo=UTC))


class TestLatestAsOf:
    def _pair(self) -> tuple[ArticleRecord, ArticleRecord]:
        original = record(
            url="https://example.test/story/9",
            body="First version of the story.",
            first_resolvable_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
            retrieved_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        )
        revision = record(
            url="https://example.test/story/9",
            body="Second version, with the toll revised upward.",
            first_resolvable_at=datetime(2026, 3, 4, 12, 0, tzinfo=UTC),
            retrieved_at=datetime(2026, 3, 4, 12, 0, tzinfo=UTC),
            modified_at=datetime(2026, 3, 4, 11, 0, tzinfo=UTC),
            revision_of=original.observation_id,
            revision_index=1,
        )
        return original, revision

    def test_the_newest_resolvable_revision_wins(self) -> None:
        original, revision = self._pair()
        latest = latest_as_of([original, revision], datetime(2026, 3, 5, tzinfo=UTC))
        assert [item.observation_id for item in latest] == [revision.observation_id]

    def test_an_unresolvable_revision_is_invisible(self) -> None:
        original, revision = self._pair()
        latest = latest_as_of([original, revision], datetime(2026, 3, 2, tzinfo=UTC))
        assert [item.observation_id for item in latest] == [original.observation_id]

    def test_a_naive_cutoff_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            latest_as_of([], datetime(2026, 3, 2))  # noqa: DTZ001

    def test_two_sources_carrying_one_url_are_two_acquisitions(self) -> None:
        # Not two revisions. Collapsing them here would silently discard one
        # source's record of having seen the article; deciding they are the
        # same story is group_syndication's job, and it says so with a lineage
        # rather than by deletion.
        shared = "https://example.test/story/shared"
        indexed = record(source_id="index_a", url=shared, headline="Headline as indexed")
        published = record(source_id="publisher_b", url=shared, headline="Headline as published")
        latest = latest_as_of([indexed, published], datetime(2026, 3, 5, tzinfo=UTC))
        assert {item.source_id for item in latest} == {"index_a", "publisher_b"}

    def test_revisions_still_collapse_within_one_source(self) -> None:
        original, revision = self._pair()
        assert original.source_id == revision.source_id
        assert len(latest_as_of([original, revision], datetime(2026, 3, 5, tzinfo=UTC))) == 1


class TestSnapshotWriting:
    def test_dry_run_writes_nothing_but_computes_everything(self, tmp_path: Path) -> None:
        # Required behaviour 12. A plan that does not compute its hashes is not
        # a plan, it is a guess about what the real run would do.
        target = tmp_path / "snap" / "articles.jsonl"
        manifest = write_snapshot(
            [record()], path=target, cutoff=datetime(2026, 3, 5, tzinfo=UTC), dry_run=True
        )
        assert not target.exists()
        assert not target.parent.exists()
        assert manifest.dry_run is True
        assert manifest.record_count == 1
        assert manifest.input_hash.startswith("sha256:")
        assert manifest.output_hash.startswith("sha256:")

    def test_a_dry_run_predicts_the_real_run_exactly(self, tmp_path: Path) -> None:
        records = [record(url=f"https://example.test/s/{index}") for index in range(3)]
        cutoff = datetime(2026, 3, 5, tzinfo=UTC)
        planned = write_snapshot(records, path=tmp_path / "a.jsonl", cutoff=cutoff, dry_run=True)
        actual = write_snapshot(records, path=tmp_path / "a.jsonl", cutoff=cutoff)
        assert planned.output_hash == actual.output_hash
        assert planned.input_hash == actual.input_hash

    def test_overwrite_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "articles.jsonl"
        cutoff = datetime(2026, 3, 5, tzinfo=UTC)
        write_snapshot([record()], path=target, cutoff=cutoff)
        with pytest.raises(SnapshotWriteError, match="immutable"):
            write_snapshot([record()], path=target, cutoff=cutoff)

    def test_a_snapshot_refuses_evidence_from_after_its_own_cutoff(self, tmp_path: Path) -> None:
        late = record(
            retrieved_at=datetime(2026, 3, 9, tzinfo=UTC),
            first_resolvable_at=datetime(2026, 3, 9, tzinfo=UTC),
        )
        with pytest.raises(SnapshotWriteError, match="after the snapshot cutoff"):
            write_snapshot(
                [late], path=tmp_path / "a.jsonl", cutoff=datetime(2026, 3, 5, tzinfo=UTC)
            )

    def test_the_payload_is_sorted_and_newline_terminated(self, tmp_path: Path) -> None:
        records = [record(url=f"https://example.test/s/{index}") for index in range(4)]
        payload = snapshot_payload(records)
        lines = payload.splitlines()
        assert len(lines) == 4
        assert payload.endswith("\n")
        identifiers = [line.split('"observation_id":"')[1].split('"')[0] for line in lines]
        assert identifiers == sorted(identifiers)

    def test_an_empty_snapshot_is_empty_not_a_blank_line(self, tmp_path: Path) -> None:
        manifest = write_snapshot(
            [], path=tmp_path / "empty.jsonl", cutoff=datetime(2026, 3, 5, tzinfo=UTC)
        )
        assert (tmp_path / "empty.jsonl").read_text(encoding="utf-8") == ""
        assert manifest.record_count == 0

    def test_a_naive_cutoff_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            write_snapshot([], path=tmp_path / "a.jsonl", cutoff=datetime(2026, 3, 5))  # noqa: DTZ001
