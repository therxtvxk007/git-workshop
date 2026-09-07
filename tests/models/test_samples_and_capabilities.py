"""The output contract: windows, rare-event probabilities, and declared capability."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from pramaanx.core.errors import CapabilityUnsupportedError, ContractViolationError
from pramaanx.models.capabilities import Capability, CapabilityManifest
from pramaanx.models.samples import (
    PanelKey,
    PathSamples,
    ProbabilityMethod,
    WindowSamples,
    _summarise,
)
from pramaanx.panel.windows import CalendarContract, Window

IST = CalendarContract(timezone="Asia/Kolkata")
KEYS = (PanelKey("101", "lwe"), PanelKey("102", "lwe"))


def _paths(counts: np.ndarray, *, days: int = 30) -> PathSamples:
    window = IST.window(date(2026, 1, 1), days)
    return PathSamples(keys=KEYS, edges=IST.daily_edges(window), counts=counts)


def _daily(rate: float, *, draws: int = 4000, days: int = 30, seed: int = 0) -> PathSamples:
    generator = np.random.default_rng(seed)
    counts = generator.poisson(rate, size=(draws, len(KEYS), days)).astype(np.int64)
    return _paths(counts, days=days)


# -- windows ---------------------------------------------------------------
def test_any_horizon_comes_from_the_same_paths() -> None:
    """One model, four horizons -- the reason daily paths are the contract."""
    paths = _daily(0.05)
    edges = paths.edges
    for length in (7, 14, 28, 30):
        window = paths.window(edges[0], edges[length])
        assert window.window.days == length
        assert window.counts.shape == (paths.n_draws, len(KEYS))


def test_nested_windows_are_coherent_by_construction() -> None:
    """P(N7>0) <= P(N14>0) <= P(N30>0), because the days are a superset."""
    paths = _daily(0.03)
    edges = paths.edges
    probabilities = [
        paths.window(edges[0], edges[length]).summarise()[0].p_occ for length in (7, 14, 30)
    ]
    assert probabilities == sorted(probabilities)


def test_a_window_outside_the_horizon_is_refused_not_truncated() -> None:
    paths = _daily(0.05, days=30)
    with pytest.raises(CapabilityUnsupportedError, match="outside this forecast's horizon"):
        paths.window(paths.edges[0], paths.edges[-1] + timedelta(days=60))


def test_a_misaligned_window_is_refused() -> None:
    """Silently rounding to the nearest bin is how a 28-day CAST period
    becomes 30 days without anybody noticing."""
    paths = _daily(0.05)
    with pytest.raises(ContractViolationError, match="does not align"):
        paths.window(paths.edges[0] + timedelta(hours=3), paths.edges[7])


def test_the_cast_period_is_reachable_from_the_same_paths() -> None:
    """28 days ending on a Friday, from a model fitted once (S24.4)."""
    window = IST.window(date(2026, 1, 5), 60)
    generator = np.random.default_rng(1)
    paths = PathSamples(
        keys=KEYS,
        edges=IST.daily_edges(window),
        counts=generator.poisson(0.05, size=(500, len(KEYS), 60)).astype(np.int64),
    )
    friday = date(2026, 2, 6)
    assert friday.weekday() == 4
    period = paths.window(IST.instant(friday - timedelta(days=28)), IST.instant(friday))
    assert period.window.days == 28


# -- rare events -----------------------------------------------------------
def test_a_sampled_zero_is_not_a_claim_of_impossibility() -> None:
    """The plan's arithmetic (S32.2): p=0.001 with 1000 draws misses 36.8% of
    the time. An empirical zero is a sampling limit, not a model claim."""
    counts = np.zeros((1000, len(KEYS)), dtype=np.int64)
    forecast = _summarise(
        counts[:, 0],
        key=KEYS[0],
        window=IST.window(date(2026, 1, 1), 30),
        method=ProbabilityMethod.MONTE_CARLO,
        k=10,
    )
    assert forecast.p_occ_mc == 0.0
    low, high = forecast.mc_interval()
    assert low == 0.0
    assert high == pytest.approx(0.003)
    assert forecast.method is ProbabilityMethod.MONTE_CARLO


def test_an_analytic_probability_survives_a_sample_that_missed_it() -> None:
    """Distribution probability and sample frequency are separate fields."""
    counts = np.zeros((200, len(KEYS)), dtype=np.int64)
    forecast = _summarise(
        counts[:, 0],
        key=KEYS[0],
        window=IST.window(date(2026, 1, 1), 30),
        method=ProbabilityMethod.ANALYTIC,
        k=10,
        analytic_p_occ=0.001,
    )
    assert forecast.p_occ == 0.001
    assert forecast.p_occ_mc == 0.0


def test_occurrence_and_the_count_distribution_must_agree() -> None:
    """Separately fitted occurrence and count heads show up here."""
    forecast = _summarise(
        np.array([0, 0, 1, 2]),
        key=KEYS[0],
        window=IST.window(date(2026, 1, 1), 30),
        method=ProbabilityMethod.ANALYTIC,
        k=5,
        analytic_p_occ=0.9,
    )
    with pytest.raises(ContractViolationError, match="disagrees with the count distribution"):
        forecast.check_coherence()


# -- aggregation -----------------------------------------------------------
def test_a_state_probability_is_not_the_sum_of_district_probabilities() -> None:
    """It is the fraction of draws whose state total is positive (S4)."""
    samples = _daily(0.02).window(*[_daily(0.02).edges[i] for i in (0, 30)])
    districts = samples.summarise()
    (state,) = samples.aggregate({"bihar": (0, 1)})

    assert state.p_occ <= sum(forecast.p_occ for forecast in districts)
    assert state.p_occ >= max(forecast.p_occ for forecast in districts)


def test_aggregation_uses_a_wide_accumulator() -> None:
    """Large totals must not wrap around (S32.3)."""
    counts = np.full((3, len(KEYS)), 2_000_000_000, dtype=np.int64)
    samples = WindowSamples(keys=KEYS, window=IST.window(date(2026, 1, 1), 30), counts=counts)
    (total,) = samples.aggregate({"all": (0, 1)})
    assert total.mean == pytest.approx(4_000_000_000.0)


# -- shape and dtype invariants -------------------------------------------
def test_fractional_counts_are_refused() -> None:
    """A fraction is an aggregate, not a draw from a count distribution."""
    with pytest.raises(ContractViolationError, match="counts must be integers"):
        WindowSamples(
            keys=KEYS,
            window=IST.window(date(2026, 1, 1), 30),
            counts=np.array([[0.5, 1.5]]),
        )


def test_negative_counts_are_refused() -> None:
    with pytest.raises(ContractViolationError, match="non-negative"):
        WindowSamples(
            keys=KEYS,
            window=IST.window(date(2026, 1, 1), 30),
            counts=np.array([[-1, 0]], dtype=np.int64),
        )


def test_sample_columns_must_match_the_panel_keys() -> None:
    with pytest.raises(ContractViolationError, match="do not match the panel keys"):
        WindowSamples(
            keys=KEYS,
            window=IST.window(date(2026, 1, 1), 30),
            counts=np.zeros((5, 3), dtype=np.int64),
        )


def test_edges_must_bound_every_bin() -> None:
    window = IST.window(date(2026, 1, 1), 30)
    with pytest.raises(ContractViolationError, match="must bound every bin"):
        PathSamples(
            keys=KEYS,
            edges=IST.daily_edges(window)[:-1],
            counts=np.zeros((2, len(KEYS), 30), dtype=np.int64),
        )


# -- capability declarations ----------------------------------------------
def test_an_undeclared_capability_raises_with_the_reason() -> None:
    manifest = CapabilityManifest(
        model_id="window_only",
        supported=frozenset({Capability.OCCURRENCE_PROBABILITY}),
        unresolved={str(Capability.DAILY_PATHS): "no within-window process"},
    )
    manifest.require(Capability.OCCURRENCE_PROBABILITY)
    with pytest.raises(CapabilityUnsupportedError, match="no within-window process"):
        manifest.require(Capability.DAILY_PATHS)


def test_an_undeclared_capability_without_a_reason_still_raises() -> None:
    manifest = CapabilityManifest(model_id="m", supported=frozenset())
    with pytest.raises(CapabilityUnsupportedError, match="not declared"):
        manifest.require(Capability.COUNT_PMF)


def test_naive_window_bounds_never_reach_the_sampler() -> None:
    with pytest.raises(ContractViolationError, match="timezone-aware"):
        Window(datetime(2026, 1, 1), datetime(2026, 2, 1))  # noqa: DTZ001


def test_summarising_zero_draws_is_refused() -> None:
    with pytest.raises(ContractViolationError, match="zero draws"):
        _summarise(
            np.array([], dtype=np.int64),
            key=KEYS[0],
            window=Window(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
            method=ProbabilityMethod.MONTE_CARLO,
            k=5,
        )


def test_the_rule_of_three_bound_is_clamped_to_one() -> None:
    """With two draws, 3/n exceeds a probability."""
    forecast = _summarise(
        np.zeros(2, dtype=np.int64),
        key=KEYS[0],
        window=IST.window(date(2026, 1, 1), 30),
        method=ProbabilityMethod.MONTE_CARLO,
        k=5,
    )
    low, high = forecast.mc_interval()
    assert (low, high) == (0.0, 1.0)


def test_an_analytic_forecast_reports_no_sampling_uncertainty() -> None:
    """It has none. A degenerate model that claimed a standard error would
    widen every downstream tolerance for nothing."""
    forecast = _summarise(
        np.zeros(1, dtype=np.int64),
        key=KEYS[0],
        window=IST.window(date(2026, 1, 1), 30),
        method=ProbabilityMethod.ANALYTIC,
        k=5,
    )
    assert forecast.mc_standard_error == 0.0
    assert forecast.mc_interval() == (0.0, 0.0)


def test_the_method_travels_from_the_model_through_the_window() -> None:
    """A degenerate model's declaration must survive summing days."""
    window = IST.window(date(2026, 1, 1), 30)
    paths = PathSamples(
        keys=KEYS,
        edges=IST.daily_edges(window),
        counts=np.zeros((1, len(KEYS), 30), dtype=np.int64),
        method=ProbabilityMethod.ANALYTIC,
    )
    assert paths.window(paths.edges[0], paths.edges[7]).method is ProbabilityMethod.ANALYTIC
