"""Complete rows without invented labels, and a roster that changes over time."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from pramaanx.core.errors import ContractViolationError
from pramaanx.geo.roster import Roster, roster_from_districts
from pramaanx.panel.families import ALL_FAMILIES, Family, IncidentLabels
from pramaanx.panel.grid import PanelSpec, build_panel
from pramaanx.panel.outcomes import (
    MaturityStatus,
    ObservationStatus,
    attach_outcomes,
    count_in_window,
    coverage_report,
    maturity_at,
    scorable,
    trainable,
)
from pramaanx.panel.windows import CalendarContract, monthly_origins

IST = CalendarContract(timezone="Asia/Kolkata")

V1 = roster_from_districts(
    "lgd-2019", date(2019, 1, 1), [("101", "bihar"), ("102", "bihar"), ("201", "odisha")]
)
V2 = roster_from_districts(
    "lgd-2022",
    date(2022, 4, 1),
    [("101", "bihar"), ("102", "bihar"), ("103", "bihar"), ("201", "odisha")],
)
ROSTER = Roster(versions=(V1, V2))


def _spec(**overrides: object) -> PanelSpec:
    base: dict[str, object] = {
        "origins": monthly_origins(date(2022, 1, 1), date(2022, 6, 1), calendar=IST),
        "roster": ROSTER,
        "calendar": IST,
        "window_days": 30,
    }
    base.update(overrides)
    return PanelSpec(**base)  # type: ignore[arg-type]


# -- the grid --------------------------------------------------------------
def test_the_panel_holds_every_district_family_origin_row() -> None:
    spec = _spec()
    panel = build_panel(spec)
    assert panel.height == spec.expected_rows()
    assert panel.select(["origin", "district_id", "family"]).n_unique() == panel.height


def test_the_row_count_follows_a_roster_that_changes() -> None:
    """Not a constant Cartesian product (S31.1).

    District 103 is notified in April 2022. Three origins before it and three
    after gives 3 x 3 + 3 x 4 = 21 district-origins, not 6 x 4 = 24.
    """
    panel = build_panel(_spec())
    per_origin = (
        panel.group_by("origin")
        .agg(district_count=pl.col("district_id").n_unique())
        .sort("origin")["district_count"]
        .to_list()
    )
    assert per_origin == [3, 3, 3, 4, 4, 4]
    assert panel.height == 21 * len(ALL_FAMILIES)


def test_a_fixed_geography_still_validates_as_a_constant() -> None:
    """A run pinned to one boundary version is the special case, not a
    different code path."""
    fixed = Roster(versions=(V1,))
    panel = build_panel(_spec(roster=fixed))
    assert panel.height == 6 * 3 * len(ALL_FAMILIES)


def test_the_boundary_version_travels_with_every_row() -> None:
    panel = build_panel(_spec())
    versions = set(panel["boundary_version"].to_list())
    assert versions == {"lgd-2019", "lgd-2022"}


def test_an_origin_before_any_boundary_version_is_refused() -> None:
    """Rather than silently handed today's roster."""
    with pytest.raises(ContractViolationError, match="no boundary version"):
        build_panel(
            _spec(origins=monthly_origins(date(2015, 1, 1), date(2015, 2, 1), calendar=IST))
        )


def test_origins_must_be_chronological() -> None:
    origins = monthly_origins(date(2022, 1, 1), date(2022, 3, 1), calendar=IST)
    with pytest.raises(ContractViolationError, match="chronological"):
        _spec(origins=tuple(reversed(origins)))


# -- outcomes: a gap is not a zero ----------------------------------------
def _panel_with_outcomes(coverage: dict[str, ObservationStatus], **overrides: object):
    spec = _spec(origins=monthly_origins(date(2022, 1, 1), date(2022, 1, 1), calendar=IST))
    panel = build_panel(spec)
    kwargs: dict[str, object] = {
        "counts": {"101": {"lwe": 2, "terrorism": 0, "insurgency": 1}},
        "coverage": coverage,
        "maturation_days": 14,
        "as_of": datetime(2023, 1, 1, tzinfo=UTC),
        "label_manifest": "sha256:labels",
        "label_available_time": datetime(2022, 3, 1, tzinfo=UTC),
    }
    kwargs.update(overrides)
    return attach_outcomes(panel, **kwargs)  # type: ignore[arg-type]


def test_an_observed_district_with_no_incidents_gets_a_real_zero() -> None:
    """The plan's naming rule: y_observed == 0 means zero observed events."""
    panel = _panel_with_outcomes(dict.fromkeys(("101", "102", "201"), ObservationStatus.OBSERVED))
    quiet = panel.filter(pl.col("district_id") == "102")
    assert quiet["y_observed"].to_list() == [0, 0, 0]


def test_an_outage_produces_unknown_labels_not_zeros() -> None:
    """The failure ``fillna(0)`` causes: a missing release becomes a quiet day."""
    coverage = {
        "101": ObservationStatus.OBSERVED,
        "102": ObservationStatus.UNAVAILABLE,
        "201": ObservationStatus.PARTIAL,
    }
    panel = _panel_with_outcomes(coverage)
    assert panel.filter(pl.col("district_id") == "102")["y_observed"].null_count() == 3
    assert panel.filter(pl.col("district_id") == "201")["y_observed"].null_count() == 3
    assert panel.filter(pl.col("district_id") == "101")["y_observed"].null_count() == 0


def test_a_district_nobody_described_cannot_default_to_observed() -> None:
    """The check that stops a forgotten parser from becoming a run of zeros."""
    with pytest.raises(ContractViolationError, match="must not default to observed"):
        _panel_with_outcomes({"101": ObservationStatus.OBSERVED})


def test_family_labels_come_from_the_multi_label_counts() -> None:
    panel = _panel_with_outcomes(dict.fromkeys(("101", "102", "201"), ObservationStatus.OBSERVED))
    row = panel.filter((pl.col("district_id") == "101") & (pl.col("family") == str(Family.LWE)))
    assert row["y_observed"].to_list() == [2]


# -- maturity --------------------------------------------------------------
def test_maturity_is_measured_from_the_window_end() -> None:
    window = IST.window(date(2026, 1, 1), 30)
    just_before = window.end + timedelta(days=13)
    assert maturity_at(window, maturation_days=14, as_of=just_before) is MaturityStatus.IMMATURE
    assert (
        maturity_at(window, maturation_days=14, as_of=window.matures_at(14))
        is MaturityStatus.MATURE
    )


def test_an_immature_row_is_not_trainable_and_not_scorable() -> None:
    panel = _panel_with_outcomes(
        dict.fromkeys(("101", "102", "201"), ObservationStatus.OBSERVED),
        as_of=datetime(2022, 1, 15, tzinfo=UTC),
    )
    assert trainable(panel, fit_cutoff=datetime(2024, 1, 1, tzinfo=UTC)).height == 0
    assert scorable(panel).height == 0


def test_a_label_revision_that_arrived_after_the_fit_is_not_trainable() -> None:
    """Mature is not enough: the exact revision has to have been available.

    This is the condition that gets forgotten, and it is the one that lets a
    fit read a correction published after it ran (S31.1).
    """
    panel = _panel_with_outcomes(
        dict.fromkeys(("101", "102", "201"), ObservationStatus.OBSERVED),
        label_available_time=datetime(2022, 6, 1, tzinfo=UTC),
    )
    assert trainable(panel, fit_cutoff=datetime(2022, 5, 1, tzinfo=UTC)).height == 0
    assert trainable(panel, fit_cutoff=datetime(2022, 7, 1, tzinfo=UTC)).height == 9


def test_the_coverage_report_carries_the_denominator() -> None:
    """A score over 60% of the panel is a different claim from one over all of
    it, and only the denominator says which (S33.3)."""
    coverage = {
        "101": ObservationStatus.OBSERVED,
        "102": ObservationStatus.UNAVAILABLE,
        "201": ObservationStatus.OBSERVED,
    }
    report = coverage_report(_panel_with_outcomes(coverage))
    assert report["total"] == 9
    assert report["scorable"] == 6
    assert report[str(ObservationStatus.UNAVAILABLE)] == 3


# -- counting inside a window ---------------------------------------------
def test_counting_respects_the_half_open_window_and_the_union_rule() -> None:
    window = IST.window(date(2026, 1, 1), 30)
    instants = {
        "i1": window.start,
        "i2": window.start + timedelta(days=5),
        "i3": window.end,  # belongs to the next window
    }
    incidents = [
        IncidentLabels(incident_id="i1", district_id="101", families=frozenset({Family.LWE})),
        IncidentLabels(
            incident_id="i2",
            district_id="101",
            families=frozenset({Family.LWE, Family.INSURGENCY}),
        ),
        IncidentLabels(incident_id="i3", district_id="101", families=frozenset({Family.LWE})),
    ]
    counts, unions = count_in_window(incidents, window=window, instants=instants)
    assert counts["101"]["lwe"] == 2
    assert counts["101"]["insurgency"] == 1
    assert unions["101"] == 2
