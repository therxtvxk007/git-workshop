"""Event-family classification, incident normalisation and the outcome panel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.geography import DistrictRegistry, DistrictResolver
from pramaanx.isolation import OutcomeAccessError, forecasting_pass
from pramaanx.outcomes import (
    EventFamily,
    ExternalForecastError,
    NormalisationError,
    PanelError,
    ReportingDelayError,
    ReportingDelayPolicy,
    assert_not_used_as_labels,
    available_at,
    benchmark_alignment,
    build_district_panel,
    classify_acled,
    classify_ucdp,
    deduplicate_incidents,
    known_families,
    normalise_acled_rows,
    normalise_cast_rows,
    normalise_ucdp_rows,
    observed_delay_days,
    validate_panel,
)
from pramaanx.schemas.district_panel import (
    DistrictIncident,
    ExternalForecastRecord,
    LabelStatus,
)
from pramaanx.schemas.geography import DistrictRef, district_id_for, state_id_for

BV = "lgd-2024-01-01"
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
CUTOFF = datetime(2024, 2, 1, tzinfo=UTC)
HORIZON_END = CUTOFF + timedelta(days=30)
FAMILIES = ["left_wing_extremism", "terrorism"]


def district(code: int, name: str, state: int, state_name: str) -> DistrictRef:
    return DistrictRef(
        district_id=district_id_for(code),
        district_name=name,
        state_id=state_id_for(state),
        state_name=state_name,
        boundary_version=BV,
        valid_from=EPOCH,
    )


@pytest.fixture
def registry() -> DistrictRegistry:
    return DistrictRegistry(
        [
            district(100, "Bastar", 22, "Chhattisgarh"),
            district(532, "Guntur", 28, "Andhra Pradesh"),
        ]
    )


@pytest.fixture
def resolver(registry: DistrictRegistry) -> DistrictResolver:
    return DistrictResolver(registry)


def incident(
    ident: str,
    *,
    day: int,
    family: str = "left_wing_extremism",
    district_id: str = "IND-D-100",
    delay_days: float = 5.0,
    dataset: str = "acled",
) -> DistrictIncident:
    occurred = datetime(2024, 2, day, tzinfo=UTC)
    return DistrictIncident(
        incident_id=ident,
        source_dataset=dataset,
        source_record_id=ident,
        district_id=district_id,
        state_id="IND-S-22",
        boundary_version=BV,
        event_family=family,
        occurred_at=occurred,
        first_resolvable_at=occurred + timedelta(days=delay_days),
        fatalities=2,
    )


def acled_row(**overrides: object) -> dict[str, object]:
    occurred = datetime(2024, 2, 10, tzinfo=UTC)
    row: dict[str, object] = {
        "event_id_cnty": "IND1",
        "event_date": "2024-02-10",
        "timestamp": int((occurred + timedelta(days=5)).timestamp()),
        "event_type": "Explosions/Remote violence",
        "sub_event_type": "Remote explosive/landmine/IED",
        "actor1": "CPI-Maoist",
        "admin1": "Chhattisgarh",
        "admin2": "Bastar",
        "fatalities": 3,
    }
    row.update(overrides)
    return row


class TestOntology:
    def test_actor_identity_beats_tactic(self) -> None:
        # An IED is terrorism by tactic; laid by a Maoist unit it is left-wing
        # extremism, and putting it in the wrong family makes both base rates
        # wrong at once.
        assert (
            classify_acled(
                event_type="Explosions/Remote violence",
                sub_event_type="Remote explosive/landmine/IED",
                actors=("CPI-Maoist",),
            )
            is EventFamily.LEFT_WING_EXTREMISM
        )
        assert (
            classify_acled(
                event_type="Explosions/Remote violence",
                sub_event_type="Remote explosive/landmine/IED",
            )
            is EventFamily.TERRORISM
        )

    def test_protest_is_excluded_outright(self) -> None:
        assert classify_acled(event_type="Protests", sub_event_type="Peaceful protest") is None
        assert classify_acled(event_type="Riots", sub_event_type="Mob violence") is None

    def test_an_unmapped_category_is_excluded_not_guessed(self) -> None:
        assert classify_acled(event_type="Something New", sub_event_type="Unheard Of") is None

    def test_ucdp_violence_types_map(self) -> None:
        assert classify_ucdp(type_of_violence=3) is EventFamily.TERRORISM
        assert classify_ucdp(type_of_violence=1) is EventFamily.INSURGENCY
        assert classify_ucdp(type_of_violence=9) is None

    def test_ucdp_actor_override_applies_too(self) -> None:
        assert (
            classify_ucdp(type_of_violence=1, actors=("CPI-Maoist",))
            is EventFamily.LEFT_WING_EXTREMISM
        )

    def test_the_family_list_is_stable(self) -> None:
        assert known_families() == ["terrorism", "left_wing_extremism", "insurgency"]


class TestReportingDelay:
    def test_the_slowest_dataset_binds(self) -> None:
        policy = ReportingDelayPolicy.default()
        assert policy.worst_delay(["acled", "ucdp_ged"]) == timedelta(days=400)

    def test_an_undeclared_dataset_is_refused(self) -> None:
        # Defaulting to zero would treat an unpublished window as an empty one.
        with pytest.raises(ReportingDelayError, match="no reporting delay"):
            ReportingDelayPolicy.default().delay_for("gdelt")

    def test_a_panel_needs_at_least_one_dataset(self) -> None:
        with pytest.raises(ReportingDelayError, match="at least one"):
            ReportingDelayPolicy.default().worst_delay([])

    def test_settle_time_is_horizon_end_plus_delay(self) -> None:
        policy = ReportingDelayPolicy(delays_days={"acled": 14.0})
        assert policy.settles_at(HORIZON_END, ["acled"]) == HORIZON_END + timedelta(days=14)

    def test_observed_delay_reports_a_delay_that_actually_happened(self) -> None:
        base = datetime(2024, 1, 1, tzinfo=UTC)
        pairs = [(base, base + timedelta(days=d)) for d in (1, 2, 3, 40)]
        assert observed_delay_days(pairs, quantile=1.0) == pytest.approx(40.0)
        assert observed_delay_days(pairs, quantile=0.5) == pytest.approx(2.5)
        assert observed_delay_days([]) is None

    def test_a_single_observation_is_its_own_quantile(self) -> None:
        base = datetime(2024, 1, 1, tzinfo=UTC)
        assert observed_delay_days([(base, base + timedelta(days=7))]) == pytest.approx(7.0)

    def test_an_impossible_quantile_is_refused(self) -> None:
        base = datetime(2024, 1, 1, tzinfo=UTC)
        with pytest.raises(ReportingDelayError, match="quantile"):
            observed_delay_days([(base, base), (base, base)], quantile=1.5)


class TestAcledNormalisation:
    def test_availability_comes_from_the_upload_timestamp(self, resolver: DistrictResolver) -> None:
        # Building labels from event_date would give every model perfect
        # knowledge of the last two weeks of every horizon.
        result = normalise_acled_rows([acled_row()], resolver=resolver)
        (found,) = result.incidents
        assert found.occurred_at == datetime(2024, 2, 10, tzinfo=UTC)
        assert found.first_resolvable_at == datetime(2024, 2, 15, tzinfo=UTC)
        assert found.event_family == "left_wing_extremism"
        assert found.district_id == "IND-D-100"

    def test_out_of_scope_rows_are_counted_not_dropped_silently(
        self, resolver: DistrictResolver
    ) -> None:
        rows = [acled_row(), acled_row(event_id_cnty="IND2", event_type="Protests")]
        result = normalise_acled_rows(rows, resolver=resolver)
        manifest = result.report.to_manifest()
        assert manifest["out_of_scope"] == 1
        assert manifest["placed"] == 1
        assert manifest["placement_rate"] == 1.0

    def test_an_unplaceable_row_becomes_an_unplaced_incident(
        self, resolver: DistrictResolver
    ) -> None:
        result = normalise_acled_rows([acled_row(admin2="Nowhere")], resolver=resolver)
        assert result.incidents == ()
        (unplaced,) = result.unplaced
        assert unplaced.reason == "unknown"
        assert unplaced.location_text == "Nowhere"
        assert result.report.unplaced_reasons == {"unknown": 1}

    def test_a_row_with_no_district_at_all_is_unplaced(self, resolver: DistrictResolver) -> None:
        result = normalise_acled_rows([acled_row(admin2="")], resolver=resolver)
        (unplaced,) = result.unplaced
        assert unplaced.location_text == ""

    def test_a_timestamp_before_the_event_is_refused(self, resolver: DistrictResolver) -> None:
        row = acled_row(timestamp=int(datetime(2020, 1, 1, tzinfo=UTC).timestamp()))
        with pytest.raises(NormalisationError, match="precedes event_date"):
            normalise_acled_rows([row], resolver=resolver)

    def test_lenient_mode_counts_malformed_rows_instead(self, resolver: DistrictResolver) -> None:
        row = acled_row(timestamp="not a number")
        result = normalise_acled_rows([row], resolver=resolver, strict=False)
        assert result.report.malformed == 1
        assert result.incidents == ()

    def test_a_row_without_an_id_is_refused(self, resolver: DistrictResolver) -> None:
        with pytest.raises(NormalisationError, match="event_id_cnty"):
            normalise_acled_rows([acled_row(event_id_cnty="", event_id="")], resolver=resolver)


class TestUcdpNormalisation:
    RELEASES = {2024: datetime(2025, 6, 1, tzinfo=UTC)}

    def row(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "id": "U1",
            "date_start": "2024-02-10",
            "type_of_violence": 3,
            "side_a": "Government of India",
            "adm_1": "Chhattisgarh",
            "adm_2": "Bastar",
            "best": 4,
            "where_prec": 1,
            "date_prec": 1,
            "ged_version_year": 2024,
        }
        row.update(overrides)
        return row

    def test_availability_is_the_release_of_the_version_that_carried_it(
        self, resolver: DistrictResolver
    ) -> None:
        result = normalise_ucdp_rows([self.row()], resolver=resolver, release_dates=self.RELEASES)
        (found,) = result.incidents
        assert found.first_resolvable_at == datetime(2025, 6, 1, tzinfo=UTC)

    def test_an_undeclared_version_is_refused(self, resolver: DistrictResolver) -> None:
        with pytest.raises(NormalisationError, match="no release date"):
            normalise_ucdp_rows(
                [self.row(ged_version_year=2030)],
                resolver=resolver,
                release_dates=self.RELEASES,
            )

    def test_coarse_location_is_not_a_district_outcome(self, resolver: DistrictResolver) -> None:
        result = normalise_ucdp_rows(
            [self.row(where_prec=5)], resolver=resolver, release_dates=self.RELEASES
        )
        assert result.report.out_of_scope == 1

    def test_coarse_dating_cannot_be_placed_in_a_horizon(self, resolver: DistrictResolver) -> None:
        result = normalise_ucdp_rows(
            [self.row(date_prec=5)], resolver=resolver, release_dates=self.RELEASES
        )
        assert result.report.out_of_scope == 1

    def test_a_missing_violence_type_is_refused(self, resolver: DistrictResolver) -> None:
        with pytest.raises(NormalisationError, match="type_of_violence"):
            normalise_ucdp_rows(
                [self.row(type_of_violence=None)],
                resolver=resolver,
                release_dates=self.RELEASES,
            )


class TestDeduplication:
    def test_the_same_attack_from_two_datasets_counts_once(self) -> None:
        acled = incident("a1", day=10, delay_days=5, dataset="acled")
        ucdp = incident("u1", day=10, delay_days=400, dataset="ucdp_ged")
        kept, duplicates = deduplicate_incidents([acled, ucdp])
        assert duplicates == 1
        assert len(kept) == 1
        # The later availability survives: an incident is knowable only once.
        assert kept[0].source_dataset == "ucdp_ged"
        assert kept[0].notes == "duplicate of a1"

    def test_different_days_are_different_incidents(self) -> None:
        kept, duplicates = deduplicate_incidents([incident("a1", day=10), incident("a2", day=11)])
        assert duplicates == 0
        assert len(kept) == 2


class TestPanelShape:
    def test_every_district_gets_a_row_including_the_empty_ones(
        self, registry: DistrictRegistry
    ) -> None:
        result = build_district_panel(
            registry=registry,
            incidents=[incident("a1", day=10)],
            cutoffs=[CUTOFF],
            event_families=FAMILIES,
            horizon_days=30,
            as_of=datetime(2024, 4, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        # 2 districts x 2 families, not 1 row for the district that had an event.
        assert result.report.rows == 4
        assert result.report.positive_rows == 1
        assert result.report.base_rate_by_family["left_wing_extremism"] == pytest.approx(0.5)
        assert result.report.base_rate_by_family["terrorism"] == 0.0

    def test_both_targets_agree_on_the_same_window(self, registry: DistrictRegistry) -> None:
        result = build_district_panel(
            registry=registry,
            incidents=[incident("a1", day=10), incident("a2", day=11)],
            cutoffs=[CUTOFF],
            event_families=["left_wing_extremism"],
            horizon_days=30,
            as_of=datetime(2024, 4, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        row = next(r for r in result.rows if r.district_id == "IND-D-100")
        assert row.incident_occurred == 1
        assert row.incident_count == 2
        assert row.first_incident_at == datetime(2024, 2, 10, tzinfo=UTC)
        assert row.first_resolvable_at == datetime(2024, 2, 15, tzinfo=UTC)
        assert row.fatalities == 4

    def test_an_incident_at_the_cutoff_instant_is_not_a_forecast(
        self, registry: DistrictRegistry
    ) -> None:
        result = build_district_panel(
            registry=registry,
            incidents=[incident("a1", day=1)],
            cutoffs=[CUTOFF],
            event_families=["left_wing_extremism"],
            horizon_days=30,
            as_of=datetime(2024, 4, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        assert result.report.positive_rows == 0
        assert result.report.incidents_outside_every_window == 1

    def test_labels_walk_pending_then_censored_then_resolved(
        self, registry: DistrictRegistry
    ) -> None:
        def status_at(as_of: datetime) -> LabelStatus:
            result = build_district_panel(
                registry=registry,
                incidents=[],
                cutoffs=[CUTOFF],
                event_families=["terrorism"],
                horizon_days=30,
                as_of=as_of,
                datasets=["acled"],
            )
            return result.rows[0].label_status

        assert status_at(datetime(2024, 2, 15, tzinfo=UTC)) is LabelStatus.PENDING
        assert status_at(datetime(2024, 3, 5, tzinfo=UTC)) is LabelStatus.CENSORED
        assert status_at(datetime(2024, 4, 1, tzinfo=UTC)) is LabelStatus.RESOLVED

    def test_only_resolved_rows_are_scorable(self, registry: DistrictRegistry) -> None:
        result = build_district_panel(
            registry=registry,
            incidents=[incident("a1", day=10)],
            cutoffs=[CUTOFF],
            event_families=["left_wing_extremism"],
            horizon_days=30,
            as_of=datetime(2024, 3, 5, tzinfo=UTC),
            datasets=["acled"],
        )
        assert not any(row.is_scorable for row in result.rows)
        # A censored fold must not contribute a base rate diluted by windows
        # whose incidents have not been published yet.
        assert result.report.base_rate_by_family == {}

    def test_an_unplaceable_incident_is_not_a_confirmed_zero(
        self, registry: DistrictRegistry, resolver: DistrictResolver
    ) -> None:
        normalised = normalise_acled_rows([acled_row(admin2="Nowhere")], resolver=resolver)
        result = build_district_panel(
            registry=registry,
            incidents=[],
            cutoffs=[CUTOFF],
            event_families=["left_wing_extremism"],
            horizon_days=30,
            as_of=datetime(2024, 4, 1, tzinfo=UTC),
            datasets=["acled"],
            unplaced=list(normalised.unplaced),
        )
        assert result.report.unresolved_location_rows == 2
        assert all(row.unplaced_incidents == 1 for row in result.rows)
        assert not any(row.is_scorable for row in result.rows)

    def test_building_a_panel_mid_forecast_is_refused(self, registry: DistrictRegistry) -> None:
        with (
            pytest.raises(OutcomeAccessError, match="forecasting pass"),
            forecasting_pass("backtest"),
        ):
            build_district_panel(
                registry=registry,
                incidents=[],
                cutoffs=[CUTOFF],
                event_families=["terrorism"],
                horizon_days=30,
                as_of=datetime(2024, 4, 1, tzinfo=UTC),
                datasets=["acled"],
            )

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"event_families": []}, "event family"),
            ({"horizon_days": 0}, "horizon_days"),
            ({"cutoffs": []}, "cutoff"),
        ],
    )
    def test_a_panel_that_cannot_be_specified_is_refused(
        self, registry: DistrictRegistry, kwargs: dict[str, object], message: str
    ) -> None:
        base: dict[str, object] = {
            "registry": registry,
            "incidents": [],
            "cutoffs": [CUTOFF],
            "event_families": ["terrorism"],
            "horizon_days": 30,
            "as_of": datetime(2024, 4, 1, tzinfo=UTC),
            "datasets": ["acled"],
        }
        base.update(kwargs)
        with pytest.raises(PanelError, match=message):
            build_district_panel(**base)  # type: ignore[arg-type]

    def test_a_period_the_registry_does_not_cover_is_refused(
        self, registry: DistrictRegistry
    ) -> None:
        with pytest.raises(PanelError, match="no districts are in effect"):
            build_district_panel(
                registry=registry,
                incidents=[],
                cutoffs=[datetime(1900, 1, 1, tzinfo=UTC)],
                event_families=["terrorism"],
                horizon_days=30,
                as_of=datetime(2024, 4, 1, tzinfo=UTC),
                datasets=["acled"],
            )

    def test_a_naive_cutoff_is_refused(self, registry: DistrictRegistry) -> None:
        with pytest.raises(PanelError, match="timezone-aware"):
            build_district_panel(
                registry=registry,
                incidents=[],
                cutoffs=[datetime(2024, 2, 1)],  # noqa: DTZ001
                event_families=["terrorism"],
                horizon_days=30,
                as_of=datetime(2024, 4, 1, tzinfo=UTC),
                datasets=["acled"],
            )


class TestPanelValidation:
    def test_a_complete_panel_passes(self, registry: DistrictRegistry) -> None:
        result = build_district_panel(
            registry=registry,
            incidents=[],
            cutoffs=[CUTOFF],
            event_families=FAMILIES,
            horizon_days=30,
            as_of=datetime(2024, 4, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        report = validate_panel(result.rows, registry=registry, event_families=FAMILIES)
        assert report["ok"]
        assert report["problem_count"] == 0

    def test_a_missing_negative_row_is_caught(self, registry: DistrictRegistry) -> None:
        result = build_district_panel(
            registry=registry,
            incidents=[],
            cutoffs=[CUTOFF],
            event_families=FAMILIES,
            horizon_days=30,
            as_of=datetime(2024, 4, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        trimmed = [row for row in result.rows if row.district_id != "IND-D-532"]
        report = validate_panel(trimmed, registry=registry, event_families=FAMILIES)
        assert not report["ok"]
        assert "negative class is incomplete" in report["problems"][0]

    def test_a_duplicated_row_is_caught(self, registry: DistrictRegistry) -> None:
        result = build_district_panel(
            registry=registry,
            incidents=[],
            cutoffs=[CUTOFF],
            event_families=["terrorism"],
            horizon_days=30,
            as_of=datetime(2024, 4, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        report = validate_panel(
            [*result.rows, result.rows[0]], registry=registry, event_families=["terrorism"]
        )
        assert any("duplicate row" in problem for problem in report["problems"])


class TestExternalForecastsAreNotLabels:
    def forecast(self, **overrides: object) -> ExternalForecastRecord:
        base: dict[str, object] = {
            "provider": "acled_cast",
            "provider_version": "2024-02",
            "district_id": "IND-D-100",
            "cutoff_at": CUTOFF,
            "horizon_start": CUTOFF,
            "horizon_end": HORIZON_END,
            "event_family": "terrorism",
            "predicted_count": 2.5,
            "published_at": datetime(2024, 2, 3, tzinfo=UTC),
            "retrieved_at": datetime(2024, 2, 4, tzinfo=UTC),
            "licence": "ACLED terms of use",
        }
        base.update(overrides)
        return ExternalForecastRecord(**base)  # type: ignore[arg-type]

    def test_a_forecast_may_never_stand_in_for_an_outcome(self) -> None:
        with pytest.raises(ExternalForecastError, match="never a label"):
            assert_not_used_as_labels([incident("a1", day=10), self.forecast()])

    def test_ordinary_incidents_pass_the_guard(self) -> None:
        assert_not_used_as_labels([incident("a1", day=10)])

    def test_availability_is_publication_not_cutoff(self) -> None:
        record = self.forecast()
        # Joining on cutoff would hand the ensemble a forecast published two
        # days after the cutoff it is due at.
        assert not record.is_available_at(CUTOFF)
        assert record.is_available_at(datetime(2024, 2, 3, tzinfo=UTC))
        assert available_at([record], moment=CUTOFF) == []

    def test_a_forecast_needs_a_number(self) -> None:
        with pytest.raises(ValueError, match="probability or a count"):
            self.forecast(predicted_count=None)

    def test_a_forecast_published_before_its_own_cutoff_is_refused(self) -> None:
        with pytest.raises(ValueError, match="published before its own cutoff"):
            self.forecast(published_at=datetime(2024, 1, 1, tzinfo=UTC))

    def test_cast_rows_normalise_through_the_resolver(self, resolver: DistrictResolver) -> None:
        rows = [
            {
                "cutoff_at": "2024-02-01T00:00:00Z",
                "horizon_start": "2024-02-01T00:00:00Z",
                "horizon_end": "2024-03-02T00:00:00Z",
                "published_at": "2024-02-03T00:00:00Z",
                "event_family": "terrorism",
                "admin1": "Chhattisgarh",
                "admin2": "Bastar",
                "prediction": 3.0,
            },
            {"cutoff_at": "2024-02-01T00:00:00Z", "admin2": "Nowhere"},
        ]
        records = normalise_cast_rows(
            rows,
            resolver=resolver,
            provider_version="2024-02",
            retrieved_at=datetime(2024, 2, 4, tzinfo=UTC),
        )
        # The unplaceable benchmark row is a missing comparison point, not a
        # manufactured outcome, so it is skipped rather than raising.
        assert len(records) == 1
        assert records[0].district_id == "IND-D-100"

    def test_alignment_reports_what_can_actually_be_compared(self) -> None:
        report = benchmark_alignment([self.forecast()], [incident("a1", day=10)])
        assert report["providers"] == ["acled_cast"]
        assert report["horizon_lengths_days"] == [30]
        assert report["horizon_is_uniform"]
        assert report["districts_without_outcome_history"] == 0
