"""Historical geography: versioned rosters and a crosswalk that shows its gaps."""

from __future__ import annotations

from datetime import date

import pytest

from pramaanx.core.errors import ContractViolationError
from pramaanx.geo.crosswalk import (
    ChangeKind,
    Crosswalk,
    CrosswalkEdge,
    WeightBasis,
    allocate_counts,
    identity_crosswalk,
)
from pramaanx.geo.roster import District, Roster, roster_from_districts

V1 = roster_from_districts("lgd-2019", date(2019, 1, 1), [("101", "bihar"), ("201", "odisha")])
V2 = roster_from_districts(
    "lgd-2022", date(2022, 4, 1), [("101", "bihar"), ("102", "bihar"), ("201", "odisha")]
)


# -- the roster ------------------------------------------------------------
def test_the_version_in_force_is_chosen_by_date_not_by_recency() -> None:
    """A replay of 2020 must not be handed a 2022 reorganisation."""
    roster = Roster(versions=(V1, V2))
    assert roster.in_force_on(date(2020, 6, 1)).version == "lgd-2019"
    assert roster.in_force_on(date(2022, 4, 1)).version == "lgd-2022"
    assert roster.codes_on(date(2020, 6, 1)) == ("101", "201")


def test_an_origin_before_the_earliest_version_is_refused() -> None:
    with pytest.raises(ContractViolationError, match="no boundary version"):
        Roster(versions=(V1,)).in_force_on(date(2015, 1, 1))


def test_versions_must_be_in_effective_date_order() -> None:
    with pytest.raises(ContractViolationError, match="effective-date order"):
        Roster(versions=(V2, V1))


def test_district_codes_are_strings_because_leading_zeros_matter() -> None:
    """An integer cast merges "007" with "7"."""
    district = District(district_id="007", state_id="goa")
    assert district.district_id == "007"
    with pytest.raises(ContractViolationError, match="must not be blank"):
        District(district_id="", state_id="goa")


def test_a_repeated_code_within_one_version_is_refused() -> None:
    with pytest.raises(ContractViolationError, match="codes repeat"):
        roster_from_districts("v", date(2020, 1, 1), [("101", "bihar"), ("101", "odisha")])


# -- the crosswalk ---------------------------------------------------------
def _split() -> Crosswalk:
    """101 splits into 101 and 102, weighted by population."""
    return Crosswalk(
        from_version="lgd-2019",
        to_version="lgd-2022",
        effective_from=date(2022, 4, 1),
        edges=(
            CrosswalkEdge(
                from_id="101",
                to_id="101",
                share=0.6,
                kind=ChangeKind.SPLIT,
                basis=WeightBasis.POPULATION,
            ),
            CrosswalkEdge(
                from_id="101",
                to_id="102",
                share=0.4,
                kind=ChangeKind.SPLIT,
                basis=WeightBasis.POPULATION,
            ),
            CrosswalkEdge(from_id="201", to_id="201", share=1.0, kind=ChangeKind.IDENTITY),
        ),
    )


def test_an_exhaustive_crosswalk_sums_to_one_per_source_district() -> None:
    assert _split().check_mass() == {"101": 0.0, "201": 0.0}


def test_over_allocation_is_always_an_error() -> None:
    """A district cannot contribute more than itself, exhaustive or not."""
    over = Crosswalk(
        from_version="a",
        to_version="b",
        effective_from=date(2022, 1, 1),
        exhaustive=False,
        edges=(
            CrosswalkEdge(
                from_id="101",
                to_id="101",
                share=0.7,
                kind=ChangeKind.SPLIT,
                basis=WeightBasis.AREA,
            ),
            CrosswalkEdge(
                from_id="101",
                to_id="102",
                share=0.7,
                kind=ChangeKind.SPLIT,
                basis=WeightBasis.AREA,
            ),
        ),
    )
    with pytest.raises(ContractViolationError, match="do not sum to one"):
        over.check_mass()


def test_unresolved_mass_stays_unresolved_rather_than_being_forced_somewhere() -> None:
    """The rule the plan is explicit about (S31.2).

    Forcing the missing 0.15 into a neighbour would make the sum-to-one check
    pass on a number invented to make it pass.
    """
    partial = Crosswalk(
        from_version="a",
        to_version="b",
        effective_from=date(2022, 1, 1),
        exhaustive=False,
        edges=(
            CrosswalkEdge(
                from_id="101",
                to_id="101",
                share=0.85,
                kind=ChangeKind.SPLIT,
                basis=WeightBasis.POPULATION,
            ),
        ),
    )
    assert partial.check_mass() == pytest.approx({"101": 0.15})
    assert partial.unresolved_mass("101") == pytest.approx(0.15)


def test_an_incomplete_exhaustive_crosswalk_is_an_error() -> None:
    """Claiming completeness and not delivering it is the case that must fail."""
    claimed = Crosswalk(
        from_version="a",
        to_version="b",
        effective_from=date(2022, 1, 1),
        exhaustive=True,
        edges=(
            CrosswalkEdge(
                from_id="101",
                to_id="101",
                share=0.85,
                kind=ChangeKind.SPLIT,
                basis=WeightBasis.POPULATION,
            ),
        ),
    )
    with pytest.raises(ContractViolationError, match="do not sum to one"):
        claimed.check_mass()


def test_a_rename_is_not_a_split() -> None:
    """Same shape, different meaning for a time series."""
    with pytest.raises(ContractViolationError, match="the change is a split"):
        CrosswalkEdge(from_id="101", to_id="199", share=0.4, kind=ChangeKind.RENAME)

    rename = CrosswalkEdge(from_id="101", to_id="199", share=1.0, kind=ChangeKind.RENAME)
    assert rename.basis is WeightBasis.WHOLE


def test_a_whole_district_move_has_no_weighting_basis() -> None:
    with pytest.raises(ContractViolationError, match="no weighting basis"):
        CrosswalkEdge(
            from_id="101",
            to_id="199",
            share=1.0,
            kind=ChangeKind.TRANSFER,
            basis=WeightBasis.AREA,
        )


def test_the_same_pair_cannot_appear_twice() -> None:
    with pytest.raises(ContractViolationError, match="twice in one crosswalk"):
        Crosswalk(
            from_version="a",
            to_version="b",
            effective_from=date(2022, 1, 1),
            edges=(
                CrosswalkEdge(
                    from_id="101",
                    to_id="101",
                    share=0.5,
                    kind=ChangeKind.SPLIT,
                    basis=WeightBasis.AREA,
                ),
                CrosswalkEdge(
                    from_id="101",
                    to_id="101",
                    share=0.5,
                    kind=ChangeKind.SPLIT,
                    basis=WeightBasis.AREA,
                ),
            ),
        )


# -- counts are not weights ------------------------------------------------
def test_allocation_returns_weighted_aggregates_not_counts() -> None:
    """The one thing this module will not do is print a fraction in a column
    labelled "incidents" (S31.2)."""
    results = {item.district_id: item for item in allocate_counts({"101": 10, "201": 3}, _split())}
    assert results["101"].value == pytest.approx(6.0)
    assert results["102"].value == pytest.approx(4.0)
    assert results["201"].value == pytest.approx(3.0)
    assert results["101"].basis is WeightBasis.POPULATION
    assert results["201"].basis is WeightBasis.WHOLE


def test_an_identity_crosswalk_preserves_counts_exactly() -> None:
    crosswalk = identity_crosswalk(
        ["101", "201"], from_version="a", to_version="b", effective_from=date(2022, 1, 1)
    )
    results = {
        item.district_id: item.value for item in allocate_counts({"101": 7, "201": 0}, crosswalk)
    }
    assert results == {"101": 7.0, "201": 0.0}


def test_a_district_with_no_mapping_is_an_error_not_a_disappearance() -> None:
    crosswalk = identity_crosswalk(
        ["101"], from_version="a", to_version="b", effective_from=date(2022, 1, 1)
    )
    with pytest.raises(ContractViolationError, match="no crosswalk edge"):
        allocate_counts({"101": 1, "999": 4}, crosswalk)


def test_unresolved_mass_travels_with_the_aggregate() -> None:
    """So a reader can see how much of the total could not be placed."""
    partial = Crosswalk(
        from_version="a",
        to_version="b",
        effective_from=date(2022, 1, 1),
        exhaustive=False,
        edges=(
            CrosswalkEdge(
                from_id="101",
                to_id="101",
                share=0.5,
                kind=ChangeKind.SPLIT,
                basis=WeightBasis.AREA,
            ),
        ),
    )
    (result,) = allocate_counts({"101": 10}, partial)
    assert result.value == pytest.approx(5.0)
    assert result.unresolved == pytest.approx(2.5)


def test_looking_up_a_district_outside_its_version_is_refused() -> None:
    """Rather than returning a state that belonged to a different roster."""
    assert V2.state_of("102") == "bihar"
    with pytest.raises(ContractViolationError, match="not in this boundary version"):
        V1.state_of("102")


def test_repeated_version_names_are_refused() -> None:
    """Two rosters under one name make ``get`` a coin toss."""
    with pytest.raises(ContractViolationError, match="version names repeat"):
        Roster(versions=(V1, V1))


def test_an_unknown_version_is_refused() -> None:
    with pytest.raises(ContractViolationError, match="no such boundary version"):
        Roster(versions=(V1, V2)).get("lgd-2030")
