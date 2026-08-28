"""The registry answers one question: what were we allowed to store, and when.

An answer that is merely current is worse than no answer, because it lets a
rebuild apply today's terms to last year's articles and call the result a
reproduction. So most of these tests are about time, and the rest are about
never letting a credential into a tracked file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from _news_builders import entry, registry
from pramaanx.config import load_settings
from pramaanx.ingest.article_content import LicenceClass
from pramaanx.ingest.news_registry import (
    EXTRAS_KEY,
    AcquisitionMethod,
    NewsRegistryError,
    NewsSourceRegistry,
    ResolvabilityPolicy,
    StorableField,
    coverage_gaps,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = REPO_ROOT / "configs" / "sources" / "news_india.yaml"

JAN_2024 = datetime(2024, 1, 1, tzinfo=UTC)
JAN_2025 = datetime(2025, 1, 1, tzinfo=UTC)
JUN_2025 = datetime(2025, 6, 1, tzinfo=UTC)
JAN_2026 = datetime(2026, 1, 1, tzinfo=UTC)


class TestEffectiveDating:
    def test_a_vintage_is_half_open(self) -> None:
        # [from, to): the closing instant belongs to the next vintage, never to
        # both. An inclusive bound would make one instant answer twice.
        single = entry(effective_from=JAN_2025, effective_to=JAN_2026)
        assert single.covers(JAN_2025)
        assert single.covers(JUN_2025)
        assert not single.covers(JAN_2026)
        assert not single.covers(JAN_2024)

    def test_an_open_ended_vintage_never_closes(self) -> None:
        assert entry(effective_from=JAN_2025, effective_to=None).covers(
            datetime(2099, 1, 1, tzinfo=UTC)
        )

    def test_successive_vintages_resolve_to_one_answer_each(self) -> None:
        # The case this exists for: a source whose licence tightened. A 2025
        # article must be read under the 2025 terms even in 2026.
        permissive = entry(
            "outlet_a",
            licence=LicenceClass.FULL_TEXT_PERMITTED,
            effective_from=JAN_2024,
            effective_to=JAN_2026,
        )
        restricted = entry("outlet_a", licence=LicenceClass.METADATA_ONLY, effective_from=JAN_2026)
        built = registry(permissive, restricted)
        assert built.entry_as_of("outlet_a", JUN_2025).licence_class is (
            LicenceClass.FULL_TEXT_PERMITTED
        )
        assert built.entry_as_of("outlet_a", JAN_2026).licence_class is (LicenceClass.METADATA_ONLY)

    def test_overlapping_vintages_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="overlaps"):
            registry(
                entry("outlet_a", effective_from=JAN_2024, effective_to=JAN_2026),
                entry("outlet_a", effective_from=JUN_2025),
            )

    def test_an_unbounded_vintage_cannot_be_followed_by_another(self) -> None:
        # An open-ended vintage covers every later instant, so anything after
        # it overlaps by construction.
        with pytest.raises(ValidationError, match="overlaps"):
            registry(
                entry("outlet_a", effective_from=JAN_2024, effective_to=None),
                entry("outlet_a", effective_from=JAN_2026),
            )

    def test_a_zero_width_vintage_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="strictly after"):
            entry(effective_from=JAN_2025, effective_to=JAN_2025)

    def test_different_sources_may_share_a_period(self) -> None:
        built = registry(
            entry("outlet_a", effective_from=JAN_2024),
            entry("outlet_b", effective_from=JAN_2024),
        )
        assert [item.source_id for item in built.as_of(JUN_2025)] == ["outlet_a", "outlet_b"]

    def test_a_disabled_source_is_excluded_but_not_forgotten(self) -> None:
        built = registry(entry("outlet_a", enabled=False))
        assert built.as_of(JUN_2025) == ()
        # Still present in the file, so an older snapshot naming it stays
        # readable rather than becoming an unresolvable reference.
        assert built.source_ids() == ("outlet_a",)

    def test_a_naive_moment_is_refused(self) -> None:
        with pytest.raises(NewsRegistryError, match="timezone-aware"):
            registry().as_of(datetime(2025, 6, 1))  # noqa: DTZ001

    def test_an_absent_source_raises_rather_than_defaulting(self) -> None:
        # Returning None would invite a default, and a default licence is
        # always more permissive than the truth.
        with pytest.raises(NewsRegistryError, match="no enabled vintage"):
            registry().entry_as_of("nobody", JUN_2025)

    def test_the_error_names_what_is_registered(self) -> None:
        with pytest.raises(NewsRegistryError, match="outlet_a"):
            registry(entry("outlet_a")).entry_as_of("outlet_z", JUN_2025)


class TestCredentialHygiene:
    def test_a_credential_env_must_be_a_variable_name(self) -> None:
        with pytest.raises(ValidationError, match="environment variable name"):
            entry(credential_env="sk-live-abcdef123456")

    @pytest.mark.parametrize(
        "value", ["lowercase_name", "X", "has spaces", "Mixed_Case", "1LEADING"]
    )
    def test_malformed_variable_names_are_refused(self, value: str) -> None:
        with pytest.raises(ValidationError):
            entry(credential_env=value)

    def test_a_well_formed_variable_name_is_accepted(self) -> None:
        assert entry(credential_env="PRAMAANX_FEED_TOKEN").credential_env == ("PRAMAANX_FEED_TOKEN")

    @pytest.mark.parametrize(
        "note",
        [
            "use token=abc123 for access",
            "Authorization: Bearer eyJhbGciOi",
            "-----BEGIN PRIVATE KEY-----",
            "set password=hunter2",
        ],
    )
    def test_secret_shaped_free_text_is_refused(self, note: str) -> None:
        # Free-text fields are where a credential actually gets pasted, so they
        # are checked rather than trusted.
        with pytest.raises(ValidationError, match="looks like a credential"):
            entry().model_copy().model_validate(entry().model_dump() | {"provenance_notes": note})

    def test_no_credential_reaches_a_serialised_entry(self) -> None:
        # Required behaviour 10, at the registry boundary.
        dumped = entry(credential_env="PRAMAANX_FEED_TOKEN").model_dump_json()
        assert "PRAMAANX_FEED_TOKEN" in dumped  # the name may travel
        for marker in ("token=", "secret=", "Bearer ", "password="):
            assert marker not in dumped


class TestLicenceCannotBeWidened:
    def test_body_retention_cannot_exceed_the_licence(self) -> None:
        with pytest.raises(ValidationError, match="permits no body text"):
            entry(
                licence=LicenceClass.METADATA_ONLY,
                permitted=(StorableField.HEADLINE, StorableField.BODY),
            )

    def test_an_unknown_licence_permits_hashes_alone(self) -> None:
        with pytest.raises(ValidationError, match="retains hashes only"):
            entry(licence=LicenceClass.UNKNOWN, permitted=(StorableField.HEADLINE,))

    def test_narrowing_a_licence_is_allowed(self) -> None:
        # Configuration may keep less than the licence permits; that is a
        # policy choice, not a contradiction.
        narrowed = entry(
            licence=LicenceClass.FULL_TEXT_PERMITTED, permitted=(StorableField.HEADLINE,)
        )
        assert narrowed.permitted_fields == (StorableField.HEADLINE,)


class TestDefaults:
    def test_resolvability_defaults_to_retrieval(self) -> None:
        # The conservative answer. Trusting a publisher's clock is a decision
        # somebody has to make explicitly, per source.
        assert entry().resolvability_policy is ResolvabilityPolicy.RETRIEVAL

    def test_an_unmeasured_expectation_stays_none(self) -> None:
        assert entry(expected_items_per_day=None).expected_items_per_day is None

    def test_the_vintage_id_names_the_source_and_its_start(self) -> None:
        assert entry("outlet_a", effective_from=JAN_2025).vintage_id.startswith("outlet_a@2025")


class TestCoverageGaps:
    def test_a_language_no_source_publishes_is_reported(self) -> None:
        built = registry(entry("outlet_a", languages=("en",)))
        assert coverage_gaps(built, moment=JUN_2025, required_languages=["en", "ml"]) == ("ml",)

    def test_a_disabled_source_does_not_close_a_gap(self) -> None:
        # The precise failure this catches: a Malayalam feed listed but off,
        # reported as covering Malayalam, and Kerala therefore looking quiet.
        built = registry(entry("outlet_ml", languages=("ml",), enabled=False))
        assert coverage_gaps(built, moment=JUN_2025, required_languages=["ml"]) == ("ml",)

    def test_no_gap_when_everything_is_covered(self) -> None:
        built = registry(entry("outlet_a", languages=("en", "ml")))
        assert coverage_gaps(built, moment=JUN_2025, required_languages=["en", "ml"]) == ()

    def test_a_metadata_only_source_indexes_a_language_without_making_it_readable(
        self,
    ) -> None:
        # The distinction WP2 will care about: a URL index covers a dozen
        # Indian languages while retaining no text in any of them.
        built = registry(entry("indexer", languages=("ml",), licence=LicenceClass.METADATA_ONLY))
        assert coverage_gaps(built, moment=JUN_2025, required_languages=["ml"]) == ()
        assert coverage_gaps(
            built, moment=JUN_2025, required_languages=["ml"], require_readable=True
        ) == ("ml",)


class TestDocumentLoading:
    def test_a_missing_sources_key_is_refused(self) -> None:
        with pytest.raises(NewsRegistryError, match="no 'sources' key"):
            NewsSourceRegistry.from_mapping({"registry_version": "x"})

    def test_an_explicitly_empty_registry_is_accepted(self) -> None:
        assert NewsSourceRegistry.from_mapping({"sources": []}).entries == ()

    def test_a_non_list_sources_key_is_refused(self) -> None:
        with pytest.raises(NewsRegistryError, match="must be a list"):
            NewsSourceRegistry.from_mapping({"sources": {"a": 1}})

    def test_extras_without_the_block_is_refused(self) -> None:
        with pytest.raises(NewsRegistryError, match=EXTRAS_KEY):
            NewsSourceRegistry.from_extras({})

    def test_a_non_mapping_block_is_refused(self) -> None:
        with pytest.raises(NewsRegistryError, match="must be a mapping"):
            NewsSourceRegistry.from_extras({EXTRAS_KEY: ["not", "a", "mapping"]})

    def test_a_yaml_file_that_is_not_a_mapping_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text(yaml.safe_dump(["one", "two"]), encoding="utf-8")
        with pytest.raises(NewsRegistryError, match="does not contain a mapping"):
            NewsSourceRegistry.from_yaml(path)

    def test_a_yaml_file_without_the_block_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "plain.yaml"
        path.write_text(yaml.safe_dump({"horizon_days": 30}), encoding="utf-8")
        with pytest.raises(NewsRegistryError, match="carries no extras"):
            NewsSourceRegistry.from_yaml(path)


class TestShippedRegistry:
    def test_the_shipped_config_validates_as_settings(self) -> None:
        # It lives under configs/, so the repository's own config contract
        # tests load it. If this fails, so do they.
        settings = load_settings(SHIPPED, environ={})
        assert EXTRAS_KEY in settings.extras

    def test_the_shipped_registry_parses(self) -> None:
        built = NewsSourceRegistry.from_yaml(SHIPPED)
        assert len(built.entries) >= 5
        assert "pib_releases" in built.source_ids()

    def test_the_shipped_registry_is_reachable_from_settings(self) -> None:
        built = NewsSourceRegistry.from_extras(load_settings(SHIPPED, environ={}).extras)
        assert built.source_ids() == NewsSourceRegistry.from_yaml(SHIPPED).source_ids()

    def test_the_registry_travels_in_the_config_hash(self) -> None:
        # A run performed under different licence terms must not be mistakable
        # for one performed under these.
        base = load_settings(SHIPPED, environ={})
        changed = base.model_copy(update={"extras": {}})
        assert base.config_hash != changed.config_hash

    def test_wire_services_are_declared_where_they_exist(self) -> None:
        built = NewsSourceRegistry.from_yaml(SHIPPED)
        wires = {item.source_id: item.wire_service for item in built.entries}
        assert wires["pti_wire"] == "PTI"
        assert wires["ani_wire"] == "ANI"

    def test_no_shipped_source_claims_more_than_hash_retention_when_unknown(self) -> None:
        for item in NewsSourceRegistry.from_yaml(SHIPPED).entries:
            if item.licence_class is LicenceClass.UNKNOWN:
                assert set(item.permitted_fields) <= {StorableField.HASHES}

    def test_no_credential_value_is_committed(self) -> None:
        # Required behaviour 10, at the file level: every credential reference
        # in the shipped registry is a variable name.
        raw = SHIPPED.read_text(encoding="utf-8")
        for marker in ("token=", "secret=", "password=", "Bearer ", "api_key="):
            assert marker not in raw
        for item in NewsSourceRegistry.from_yaml(SHIPPED).entries:
            if item.credential_env is not None:
                assert item.credential_env.isupper()

    def test_regional_language_sources_are_listed_even_when_disabled(self) -> None:
        # Listing them is what makes their absence a reported coverage gap
        # rather than an unremarkable silence.
        built = NewsSourceRegistry.from_yaml(SHIPPED)
        disabled = {item.source_id for item in built.entries if not item.enabled}
        assert "regional_ml_feed" in disabled
        # The GDELT index does cover these languages, so nothing is missing in
        # the "is it indexed?" sense...
        assert coverage_gaps(built, moment=JAN_2026, required_languages=["ml", "bn"]) == ()
        # ...but it retains no body text, so with the regional feeds off there
        # is nothing readable in either language. That is the gap that matters
        # to extraction, and it has to be visible.
        assert coverage_gaps(
            built, moment=JAN_2026, required_languages=["ml", "bn"], require_readable=True
        ) == ("bn", "ml")

    def test_every_acquisition_method_named_is_a_known_one(self) -> None:
        known = set(AcquisitionMethod)
        for item in NewsSourceRegistry.from_yaml(SHIPPED).entries:
            assert item.acquisition in known
