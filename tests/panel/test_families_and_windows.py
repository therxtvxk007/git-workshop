"""Family overlap and window semantics -- the plan's two 'fix first' items."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from pramaanx.core.errors import ContractViolationError, UnresolvedContractError
from pramaanx.panel.families import (
    Family,
    IncidentLabels,
    check_union_invariant,
    family_counts,
    observed_counts,
    union_count,
    union_forecast,
)
from pramaanx.panel.windows import (
    CAST_PERIOD_DAYS,
    CalendarContract,
    Window,
    cast_periods,
    monthly_origins,
    next_friday,
    weekly_origins,
)

IST = CalendarContract(timezone="Asia/Kolkata")


def _incident(identifier: str, *families: Family, district: str = "d1") -> IncidentLabels:
    return IncidentLabels(
        incident_id=identifier, district_id=district, families=frozenset(families)
    )


# -- multi-label counting --------------------------------------------------
def test_a_shared_incident_counts_once_in_each_family_and_once_in_the_union() -> None:
    """The rule the panel contract never stated (S4, defect 4).

    Three incidents, one of them both LWE and insurgent. Per-family counts are
    2 and 2; the union is 3, not 4.
    """
    incidents = [
        _incident("i1", Family.LWE),
        _incident("i2", Family.LWE, Family.INSURGENCY),
        _incident("i3", Family.INSURGENCY),
    ]
    counts = family_counts(incidents)
    assert counts[Family.LWE] == 2
    assert counts[Family.INSURGENCY] == 2
    assert counts[Family.TERRORISM] == 0
    assert union_count(incidents) == 3
    assert union_count(incidents) < sum(counts.values())


def test_the_union_never_exceeds_the_sum_of_family_counts() -> None:
    """Equality is possible -- it just means nothing overlapped."""
    disjoint = [_incident("i1", Family.LWE), _incident("i2", Family.TERRORISM)]
    counts, union = observed_counts(disjoint)
    assert union == sum(counts.values()) == 2


def test_a_double_counted_incident_fails_the_invariant() -> None:
    with pytest.raises(ContractViolationError, match="counted twice"):
        check_union_invariant({Family.LWE: 1, Family.TERRORISM: 0, Family.INSURGENCY: 0}, 2)


def test_an_unlabelled_incident_is_refused() -> None:
    """It would be invisible to every family count and present in the union."""
    with pytest.raises(ContractViolationError, match="no family label"):
        IncidentLabels(incident_id="i1", district_id="d1", families=frozenset())
    with pytest.raises(ValidationError):
        IncidentLabels(incident_id="i1", district_id="d1")


def test_a_union_forecast_from_marginals_is_refused() -> None:
    """Summing double-counts, max assumes containment, product assumes
    independence. All three are assumptions the contract has not made (S42)."""
    with pytest.raises(UnresolvedContractError, match="joint family membership"):
        union_forecast({Family.LWE: 0.4, Family.INSURGENCY: 0.3})


# -- half-open windows -----------------------------------------------------
def test_a_window_is_half_open_at_its_end() -> None:
    """An event at ``end`` belongs to the next window, never to both."""
    first = IST.window(date(2026, 1, 1), 30)
    second = IST.window(date(2026, 1, 31), 30)
    assert first.end == second.start
    assert first.contains(first.start) is True
    assert first.contains(first.end) is False
    assert second.contains(second.start) is True


def test_maturation_is_measured_from_the_window_end() -> None:
    """A 30-day window issued on 1 January is not mature on 31 January."""
    window = IST.window(date(2026, 1, 1), 30)
    assert window.matures_at(14) == window.end + timedelta(days=14)
    assert window.matures_at(14) > window.start + timedelta(days=30)


def test_a_zero_length_window_is_refused() -> None:
    instant = IST.instant(date(2026, 1, 1))
    with pytest.raises(ContractViolationError, match="after its start"):
        Window(instant, instant)


def test_naive_bounds_are_refused() -> None:
    with pytest.raises(ContractViolationError, match="timezone-aware"):
        Window(datetime(2026, 1, 1), datetime(2026, 2, 1))  # noqa: DTZ001


# -- the calendar is pinned ------------------------------------------------
def test_a_local_day_is_not_a_utc_day() -> None:
    """UTC storage does not make the reporting day UTC (S29.1).

    India is UTC+05:30, so a local day begins at 18:30 UTC the day before.
    """
    start = IST.instant(date(2026, 1, 1))
    assert start == datetime(2025, 12, 31, 18, 30, tzinfo=UTC)
    assert IST.local_date(datetime(2026, 1, 1, 0, 0, tzinfo=UTC)) == date(2026, 1, 1)
    assert IST.local_date(datetime(2025, 12, 31, 19, 0, tzinfo=UTC)) == date(2026, 1, 1)


def test_two_calendars_disagree_about_the_same_evidence() -> None:
    """Which is why the calendar is a contract field rather than a default."""
    utc = CalendarContract(timezone="UTC")
    assert utc.window(date(2026, 1, 1), 30).start != IST.window(date(2026, 1, 1), 30).start


def test_daily_edges_cover_the_window_exactly() -> None:
    window = IST.window(date(2026, 3, 1), 31)
    edges = IST.daily_edges(window)
    assert len(edges) == 32
    assert edges[0] == window.start
    assert edges[-1] == window.end


def test_daily_edges_refuse_a_window_that_does_not_end_on_a_day_boundary() -> None:
    """A path model that cannot check alignment truncates silently (S32.1)."""
    window = IST.window(date(2026, 3, 1), 31)
    ragged = Window(window.start, window.end + timedelta(hours=7))
    with pytest.raises(ContractViolationError, match="day boundary"):
        IST.daily_edges(ragged)


def test_a_non_midnight_day_boundary_shifts_the_local_date() -> None:
    """Some reporting days start at 06:00. The contract can say so."""
    dawn = CalendarContract(timezone="Asia/Kolkata", day_boundary=time(6, 0))
    # 00:00 UTC is 05:30 local, still before the 06:00 boundary.
    assert dawn.local_date(datetime(2026, 1, 1, 0, 0, tzinfo=UTC)) == date(2025, 12, 31)
    # 03:00 UTC is 08:30 local, after it.
    assert dawn.local_date(datetime(2026, 1, 1, 3, 0, tzinfo=UTC)) == date(2026, 1, 1)


# -- origins ---------------------------------------------------------------
def test_monthly_origins_land_on_the_first_local_day() -> None:
    origins = monthly_origins(date(2026, 1, 1), date(2026, 3, 31), calendar=IST)
    assert [IST.local_date(origin).isoformat() for origin in origins] == [
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
    ]


def test_cast_needs_weekly_origins_not_monthly_ones() -> None:
    """CAST publishes weekly; monthly origins would replay it at a twelfth of
    its update rate (S24.4)."""
    weekly = weekly_origins(date(2026, 1, 1), date(2026, 3, 31), calendar=IST)
    monthly = monthly_origins(date(2026, 1, 1), date(2026, 3, 31), calendar=IST)
    assert len(weekly) > 4 * len(monthly) - 5
    assert all(IST.local_date(origin).weekday() == 4 for origin in weekly)


# -- the CAST window is not a month ---------------------------------------
def test_cast_periods_are_28_days_and_end_on_fridays() -> None:
    """Not a calendar month and not 30 days (S24.4, defect 3)."""
    periods = cast_periods(date(2026, 1, 2), calendar=IST, count=6)
    assert len(periods) == 6
    for window in periods:
        assert window.days == CAST_PERIOD_DAYS
        assert IST.local_date(window.end).weekday() == 4


def test_cast_periods_roll_weekly_and_overlap() -> None:
    """Rolling, not partitioning: consecutive periods share 21 days."""
    first, second = cast_periods(date(2026, 1, 2), calendar=IST, count=2)
    assert (second.start - first.start) == timedelta(days=7)
    assert second.start < first.end


def test_a_cast_period_that_does_not_end_on_a_friday_is_refused() -> None:
    """The alignment comes from the comparator contract, not from a guess here."""
    with pytest.raises(ContractViolationError, match="ends on a Friday"):
        cast_periods(date(2026, 1, 5), calendar=IST)


def test_next_friday_is_idempotent_on_a_friday() -> None:
    assert next_friday(date(2026, 1, 2)) == date(2026, 1, 2)
    assert next_friday(date(2026, 1, 3)) == date(2026, 1, 9)
