"""District identity, crosswalks, adjacency and name resolution."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pramaanx.geography import (
    AdjacencyError,
    CrosswalkError,
    DistrictAdjacency,
    DistrictCrosswalk,
    DistrictRegistry,
    DistrictResolver,
    GeographyError,
    LgdContractError,
    Resolution,
    Unresolved,
    normalise_lgd_rows,
    normalise_place_name,
)
from pramaanx.schemas.geography import (
    AdjacencyEdge,
    CrosswalkEdge,
    DistrictRef,
    district_id_for,
    state_id_for,
)

BV = "lgd-2024-01-01"
OLD = "lgd-2014-01-01"
SPLIT = datetime(2022, 4, 4, tzinfo=UTC)
BEFORE = datetime(2019, 6, 1, tzinfo=UTC)
AFTER = datetime(2024, 6, 1, tzinfo=UTC)
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def district(
    code: int,
    name: str,
    *,
    state: int = 28,
    state_name: str = "Andhra Pradesh",
    valid_from: datetime = EPOCH,
    valid_until: datetime | None = None,
    boundary_version: str = BV,
) -> DistrictRef:
    return DistrictRef(
        district_id=district_id_for(code),
        district_name=name,
        state_id=state_id_for(state),
        state_name=state_name,
        boundary_version=boundary_version,
        valid_from=valid_from,
        valid_until=valid_until,
    )


class TestIdentity:
    def test_identity_comes_from_the_lgd_code(self) -> None:
        assert district_id_for(532) == "IND-D-532"
        assert district_id_for("0532") == "IND-D-532"
        assert state_id_for(28) == "IND-S-28"

    def test_a_non_numeric_code_is_not_an_identity(self) -> None:
        with pytest.raises(ValueError, match="numeric"):
            district_id_for("Guntur")

    def test_an_invented_identity_format_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="LGD-derived"):
            DistrictRef(
                district_id="guntur",
                district_name="Guntur",
                state_id="IND-S-28",
                state_name="Andhra Pradesh",
                boundary_version=BV,
                valid_from=EPOCH,
            )

    def test_a_record_cannot_end_before_it_starts(self) -> None:
        with pytest.raises(ValueError, match="strictly after"):
            district(532, "Guntur", valid_from=AFTER, valid_until=BEFORE)

    def test_an_unversioned_boundary_is_refused(self) -> None:
        with pytest.raises(ValueError, match="boundary_version"):
            district(532, "Guntur", boundary_version="")


class TestLgdNormalisation:
    def test_known_column_spellings_are_accepted(self) -> None:
        rows = [
            {
                "District Code": 532,
                "District Name": "Guntur",
                "State Code": 28,
                "State Name": "Andhra Pradesh",
            }
        ]
        (record,) = normalise_lgd_rows(rows, boundary_version=BV, default_valid_from=EPOCH)
        assert record.district_id == "IND-D-532"
        assert record.valid_from == EPOCH

    def test_a_missing_code_is_an_error_not_a_guess(self) -> None:
        rows = [{"district_name": "Guntur", "state_code": 28, "state_name": "Andhra Pradesh"}]
        with pytest.raises(LgdContractError, match="district_code"):
            normalise_lgd_rows(rows, boundary_version=BV, default_valid_from=EPOCH)

    def test_an_explicit_creation_date_beats_the_default(self) -> None:
        rows = [
            {
                "district_code": 754,
                "district_name": "Palnadu",
                "state_code": 28,
                "state_name": "Andhra Pradesh",
                "valid_from": "2022-04-04",
            }
        ]
        (record,) = normalise_lgd_rows(rows, boundary_version=BV, default_valid_from=EPOCH)
        assert record.valid_from == SPLIT

    def test_optional_exposure_columns_survive(self) -> None:
        rows = [
            {
                "district_code": 532,
                "district_name": "Guntur",
                "state_code": 28,
                "state_name": "Andhra Pradesh",
                "population": "2091075",
                "area": "2443.0",
            }
        ]
        (record,) = normalise_lgd_rows(rows, boundary_version=BV, default_valid_from=EPOCH)
        assert record.population == 2091075
        assert record.area_sq_km == pytest.approx(2443.0)

    def test_a_malformed_date_names_the_row(self) -> None:
        rows = [
            {
                "district_code": 754,
                "district_name": "Palnadu",
                "state_code": 28,
                "state_name": "Andhra Pradesh",
                "valid_from": "the fourth of April",
            }
        ]
        with pytest.raises(LgdContractError, match="row 0"):
            normalise_lgd_rows(rows, boundary_version=BV, default_valid_from=EPOCH)

    def test_a_naive_default_is_refused(self) -> None:
        with pytest.raises(LgdContractError, match="timezone-aware"):
            normalise_lgd_rows(
                [],
                boundary_version=BV,
                default_valid_from=datetime(2000, 1, 1),  # noqa: DTZ001
            )

    def test_boundary_version_is_required(self) -> None:
        with pytest.raises(LgdContractError, match="boundary_version"):
            normalise_lgd_rows([], boundary_version="", default_valid_from=EPOCH)


class TestRegistryIsAlwaysAsOf:
    @pytest.fixture
    def registry(self) -> DistrictRegistry:
        return DistrictRegistry(
            [
                district(532, "Guntur", valid_until=SPLIT),
                district(532, "Guntur", valid_from=SPLIT),
                district(754, "Palnadu", valid_from=SPLIT),
                district(100, "Bastar", state=22, state_name="Chhattisgarh"),
            ]
        )

    def test_the_universe_excludes_a_district_created_later(
        self, registry: DistrictRegistry
    ) -> None:
        assert registry.universe_ids(BEFORE) == ["IND-D-100", "IND-D-532"]
        assert registry.universe_ids(AFTER) == ["IND-D-100", "IND-D-532", "IND-D-754"]

    def test_a_district_not_yet_in_effect_has_no_record(self, registry: DistrictRegistry) -> None:
        assert registry.at("IND-D-754", BEFORE) is None
        with pytest.raises(GeographyError, match="not in effect"):
            registry.require_at("IND-D-754", BEFORE)

    def test_every_district_belongs_to_exactly_one_state(self, registry: DistrictRegistry) -> None:
        states = registry.states_as_of(AFTER)
        assert states == {
            "IND-S-22": ["IND-D-100"],
            "IND-S-28": ["IND-D-532", "IND-D-754"],
        }
        assigned = [d for ids in states.values() for d in ids]
        assert len(assigned) == len(set(assigned))

    def test_overlapping_intervals_are_refused(self) -> None:
        with pytest.raises(GeographyError, match="overlapping"):
            DistrictRegistry(
                [
                    district(532, "Guntur", valid_until=AFTER),
                    district(532, "Guntur", valid_from=SPLIT),
                ]
            )

    def test_an_unclosed_earlier_record_is_refused(self) -> None:
        with pytest.raises(GeographyError, match="open-ended"):
            DistrictRegistry([district(532, "Guntur"), district(532, "Guntur", valid_from=SPLIT)])

    def test_a_naive_moment_is_refused(self, registry: DistrictRegistry) -> None:
        with pytest.raises(GeographyError, match="timezone-aware"):
            registry.as_of(datetime(2024, 6, 1))  # noqa: DTZ001

    def test_a_mixed_vintage_universe_is_ambiguous(self) -> None:
        registry = DistrictRegistry(
            [district(532, "Guntur"), district(100, "Bastar", boundary_version=OLD)]
        )
        with pytest.raises(GeographyError, match="mixes boundary versions"):
            registry.boundary_version_at(AFTER)

    def test_a_single_vintage_universe_reports_it(self, registry: DistrictRegistry) -> None:
        assert registry.boundary_version_at(AFTER) == BV

    def test_an_empty_period_has_no_vintage(self, registry: DistrictRegistry) -> None:
        with pytest.raises(GeographyError, match="no districts"):
            registry.boundary_version_at(datetime(1900, 1, 1, tzinfo=UTC))

    def test_history_and_membership(self, registry: DistrictRegistry) -> None:
        assert len(registry.history("IND-D-532")) == 2
        assert "IND-D-532" in registry
        assert len(registry) == 3
        assert len(DistrictRegistry.empty()) == 0


class TestCrosswalk:
    @pytest.fixture
    def crosswalk(self) -> DistrictCrosswalk:
        return DistrictCrosswalk(
            [
                CrosswalkEdge(
                    source_district_id="IND-D-999",
                    target_district_id="IND-D-532",
                    effective_from=SPLIT,
                    weight=0.6,
                    relation="split",
                ),
                CrosswalkEdge(
                    source_district_id="IND-D-999",
                    target_district_id="IND-D-754",
                    effective_from=SPLIT,
                    weight=0.4,
                    relation="split",
                ),
            ]
        )

    def test_before_the_change_the_source_stands(self, crosswalk: DistrictCrosswalk) -> None:
        assert crosswalk.successors("IND-D-999", BEFORE) == {"IND-D-999": 1.0}

    def test_after_the_change_territory_is_apportioned(self, crosswalk: DistrictCrosswalk) -> None:
        assert crosswalk.successors("IND-D-999", AFTER) == {
            "IND-D-532": pytest.approx(0.6),
            "IND-D-754": pytest.approx(0.4),
        }

    def test_predecessors_run_the_other_way(self, crosswalk: DistrictCrosswalk) -> None:
        assert set(crosswalk.predecessors("IND-D-754", AFTER)) == {"IND-D-999"}

    def test_counts_may_be_apportioned(self, crosswalk: DistrictCrosswalk) -> None:
        assert crosswalk.project({"IND-D-999": 10.0}, moment=AFTER, divisible=True) == {
            "IND-D-532": pytest.approx(6.0),
            "IND-D-754": pytest.approx(4.0),
        }

    def test_an_indivisible_label_is_never_split(self, crosswalk: DistrictCrosswalk) -> None:
        # Half an incident is not an incident. Splitting a 0/1 label across a
        # split district manufactures two half-events out of one real one.
        with pytest.raises(CrosswalkError, match="indivisible"):
            crosswalk.project({"IND-D-999": 1.0}, moment=AFTER, divisible=False)

    def test_a_district_with_no_edges_passes_through(self, crosswalk: DistrictCrosswalk) -> None:
        assert crosswalk.project({"IND-D-100": 3.0}, moment=AFTER, divisible=False) == {
            "IND-D-100": 3.0
        }

    def test_splits_compose_transitively(self) -> None:
        later = datetime(2023, 1, 1, tzinfo=UTC)
        crosswalk = DistrictCrosswalk(
            [
                CrosswalkEdge(
                    source_district_id="IND-D-999",
                    target_district_id="IND-D-532",
                    effective_from=SPLIT,
                    weight=0.5,
                    relation="split",
                ),
                CrosswalkEdge(
                    source_district_id="IND-D-999",
                    target_district_id="IND-D-754",
                    effective_from=SPLIT,
                    weight=0.5,
                    relation="split",
                ),
                CrosswalkEdge(
                    source_district_id="IND-D-754",
                    target_district_id="IND-D-755",
                    effective_from=later,
                    weight=1.0,
                    relation="rename",
                ),
            ]
        )
        assert crosswalk.successors("IND-D-999", AFTER) == {
            "IND-D-532": pytest.approx(0.5),
            "IND-D-755": pytest.approx(0.5),
        }

    def test_weights_that_lose_territory_are_refused(self) -> None:
        with pytest.raises(CrosswalkError, match="sum to"):
            DistrictCrosswalk(
                [
                    CrosswalkEdge(
                        source_district_id="IND-D-999",
                        target_district_id="IND-D-532",
                        effective_from=SPLIT,
                        weight=0.6,
                        relation="split",
                    )
                ]
            )

    def test_a_multi_target_rename_is_mislabelled(self) -> None:
        with pytest.raises(CrosswalkError, match="label it a split"):
            DistrictCrosswalk(
                [
                    CrosswalkEdge(
                        source_district_id="IND-D-999",
                        target_district_id="IND-D-532",
                        effective_from=SPLIT,
                        weight=0.5,
                    ),
                    CrosswalkEdge(
                        source_district_id="IND-D-999",
                        target_district_id="IND-D-754",
                        effective_from=SPLIT,
                        weight=0.5,
                    ),
                ]
            )

    def test_a_cycle_is_refused(self) -> None:
        crosswalk = DistrictCrosswalk(
            [
                CrosswalkEdge(
                    source_district_id="IND-D-1",
                    target_district_id="IND-D-2",
                    effective_from=SPLIT,
                ),
                CrosswalkEdge(
                    source_district_id="IND-D-2",
                    target_district_id="IND-D-1",
                    effective_from=SPLIT,
                ),
            ]
        )
        with pytest.raises(CrosswalkError, match="cycle"):
            crosswalk.successors("IND-D-1", AFTER)

    def test_an_edge_to_itself_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cross-walk to itself"):
            CrosswalkEdge(
                source_district_id="IND-D-1",
                target_district_id="IND-D-1",
                effective_from=SPLIT,
            )

    def test_an_unknown_relation_is_refused(self) -> None:
        with pytest.raises(ValueError, match="relation"):
            CrosswalkEdge(
                source_district_id="IND-D-1",
                target_district_id="IND-D-2",
                effective_from=SPLIT,
                relation="dissolved",
            )

    def test_a_naive_moment_is_refused(self, crosswalk: DistrictCrosswalk) -> None:
        with pytest.raises(CrosswalkError, match="timezone-aware"):
            crosswalk.successors("IND-D-999", datetime(2024, 1, 1))  # noqa: DTZ001

    def test_an_empty_crosswalk_is_the_identity(self) -> None:
        assert DistrictCrosswalk.empty().successors("IND-D-1", AFTER) == {"IND-D-1": 1.0}


class TestAdjacency:
    @pytest.fixture
    def adjacency(self) -> DistrictAdjacency:
        return DistrictAdjacency(
            [
                AdjacencyEdge(boundary_version=BV, district_id="IND-D-1", neighbour_id="IND-D-2"),
                AdjacencyEdge(boundary_version=BV, district_id="IND-D-2", neighbour_id="IND-D-3"),
                AdjacencyEdge(boundary_version=OLD, district_id="IND-D-1", neighbour_id="IND-D-9"),
            ]
        )

    def test_edges_are_symmetric_however_they_were_supplied(
        self, adjacency: DistrictAdjacency
    ) -> None:
        assert adjacency.neighbours("IND-D-2", boundary_version=BV) == ["IND-D-1", "IND-D-3"]
        assert adjacency.neighbours("IND-D-1", boundary_version=BV) == ["IND-D-2"]

    def test_hops_are_deterministic_and_exclude_the_origin(
        self, adjacency: DistrictAdjacency
    ) -> None:
        assert adjacency.within_hops("IND-D-1", boundary_version=BV, hops=2) == {
            "IND-D-2": 1,
            "IND-D-3": 2,
        }
        assert adjacency.within_hops("IND-D-1", boundary_version=BV, hops=1) == {"IND-D-2": 1}
        assert adjacency.within_hops("IND-D-1", boundary_version=BV, hops=0) == {}

    def test_vintages_do_not_bleed_into_each_other(self, adjacency: DistrictAdjacency) -> None:
        # IND-D-9 neighbours IND-D-1 in the old vintage only. A feature window
        # on the new vintage must not see it.
        assert adjacency.neighbours("IND-D-1", boundary_version=OLD) == ["IND-D-9"]
        assert "IND-D-9" not in adjacency.neighbours("IND-D-1", boundary_version=BV)

    def test_an_unloaded_vintage_raises_rather_than_falling_back(
        self, adjacency: DistrictAdjacency
    ) -> None:
        with pytest.raises(AdjacencyError, match="not carried over"):
            adjacency.neighbours("IND-D-1", boundary_version="lgd-2030-01-01")

    def test_restricting_drops_districts_outside_the_universe(
        self, adjacency: DistrictAdjacency
    ) -> None:
        restricted = adjacency.restricted_to(["IND-D-1", "IND-D-2"], boundary_version=BV)
        assert restricted.neighbours("IND-D-2", boundary_version=BV) == ["IND-D-1"]

    def test_negative_hops_are_refused(self, adjacency: DistrictAdjacency) -> None:
        with pytest.raises(AdjacencyError, match="non-negative"):
            adjacency.within_hops("IND-D-1", boundary_version=BV, hops=-1)

    def test_a_district_cannot_neighbour_itself(self) -> None:
        with pytest.raises(ValueError, match="neighbour itself"):
            AdjacencyEdge(boundary_version=BV, district_id="IND-D-1", neighbour_id="IND-D-1")

    def test_an_unknown_derivation_method_is_refused(self) -> None:
        with pytest.raises(ValueError, match="method"):
            AdjacencyEdge(
                boundary_version=BV,
                district_id="IND-D-1",
                neighbour_id="IND-D-2",
                method="guessed",
            )

    def test_versions_are_listed(self, adjacency: DistrictAdjacency) -> None:
        assert adjacency.boundary_versions == [OLD, BV]
        assert DistrictAdjacency.empty().boundary_versions == []


class TestNameResolution:
    @pytest.fixture
    def resolver(self) -> DistrictResolver:
        registry = DistrictRegistry(
            [
                district(532, "Guntur"),
                district(754, "Palnadu", valid_from=SPLIT),
                district(100, "Bastar", state=22, state_name="Chhattisgarh"),
                district(200, "Bastar", state=29, state_name="Karnataka"),
            ]
        )
        return DistrictResolver(registry, aliases=[("Bellary", "IND-D-200")])

    def test_suffixes_and_diacritics_are_normalised(self) -> None:
        assert normalise_place_name("Palnādu District") == "palnadu"
        assert normalise_place_name("Guntur Dist.") == "guntur"
        # Only a *trailing* suffix is dropped.
        assert normalise_place_name("District Council") == "district council"

    def test_a_district_not_yet_created_does_not_resolve(self, resolver: DistrictResolver) -> None:
        outcome = resolver.resolve("Palnadu", moment=BEFORE)
        assert isinstance(outcome, Unresolved)
        assert outcome.reason == "unknown"
        assert not outcome

    def test_it_resolves_once_the_district_exists(self, resolver: DistrictResolver) -> None:
        outcome = resolver.resolve("Palnadu Dist.", moment=AFTER)
        assert isinstance(outcome, Resolution)
        assert outcome.district_id == "IND-D-754"
        assert outcome.matched_on == "name"
        assert outcome

    def test_a_name_in_two_states_is_ambiguous_not_a_guess(
        self, resolver: DistrictResolver
    ) -> None:
        outcome = resolver.resolve("Bastar", moment=AFTER)
        assert isinstance(outcome, Unresolved)
        assert outcome.reason == "ambiguous"
        assert outcome.candidates == ("IND-D-100", "IND-D-200")

    def test_a_state_hint_disambiguates(self, resolver: DistrictResolver) -> None:
        outcome = resolver.resolve("Bastar", moment=AFTER, state_name="Chhattisgarh")
        assert isinstance(outcome, Resolution)
        assert outcome.district_id == "IND-D-100"

    def test_an_unknown_state_does_not_widen_the_search(self, resolver: DistrictResolver) -> None:
        # Narrowing to an empty set and then searching the whole country would
        # turn a typo'd state into a nationwide guess.
        outcome = resolver.resolve("Guntur", moment=AFTER, state_name="Atlantis")
        assert isinstance(outcome, Unresolved)
        assert outcome.reason == "unknown"

    def test_an_alias_resolves_when_the_name_does_not(self, resolver: DistrictResolver) -> None:
        outcome = resolver.resolve("Bellary", moment=AFTER)
        assert isinstance(outcome, Resolution)
        assert outcome.matched_on == "alias"

    def test_an_empty_name_is_unresolved(self, resolver: DistrictResolver) -> None:
        assert isinstance(resolver.resolve("   ", moment=AFTER), Unresolved)
