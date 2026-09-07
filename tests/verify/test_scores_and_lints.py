"""Proper scores that keep their endpoints, and the lints that scope the zero rule."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from pramaanx.core.errors import ContractViolationError
from pramaanx.models.capabilities import CapabilityManifest
from pramaanx.models.samples import PanelKey, ProbabilityMethod, WindowForecast
from pramaanx.panel.windows import CalendarContract
from pramaanx.verify.lints import (
    check_coherence,
    check_monte_carlo_zeros,
    check_nested_windows,
    check_no_hard_zero,
    run_all,
)
from pramaanx.verify.scores import (
    Orientation,
    ScoreState,
    brier,
    count_crps,
    log_loss,
    skill,
)

IST = CalendarContract(timezone="Asia/Kolkata")
WINDOW = IST.window(date(2026, 1, 1), 30)


def _forecast(
    *,
    p_occ: float,
    method: ProbabilityMethod = ProbabilityMethod.MONTE_CARLO,
    n_draws: int = 1000,
    p_mc: float | None = None,
    pmf: tuple[float, ...] | None = None,
    district: str = "101",
) -> WindowForecast:
    empirical = p_occ if p_mc is None else p_mc
    return WindowForecast(
        key=PanelKey(district, "lwe"),
        window=WINDOW,
        p_occ=p_occ,
        method=method,
        n_draws=n_draws,
        p_occ_mc=empirical,
        pmf=pmf or (1.0 - p_occ, p_occ),
        tail_mass=0.0,
        mean=p_occ,
    )


# -- hand-checked score values --------------------------------------------
def test_brier_matches_a_hand_calculation() -> None:
    """Verified against the definition rather than against another library."""
    result = brier([0.9, 0.2, 0.5], [1, 0, 1])
    expected = ((0.9 - 1) ** 2 + 0.2**2 + 0.5**2) / 3
    assert result.value == pytest.approx(expected)
    assert result.n == 3
    assert result.orientation is Orientation.LOWER_IS_BETTER


def test_log_loss_matches_a_hand_calculation() -> None:
    result = log_loss([0.8, 0.25], [1, 0])
    expected = (-math.log(0.8) - math.log(0.75)) / 2
    assert result.value == pytest.approx(expected)
    assert result.non_finite == 0


# -- endpoints are kept ----------------------------------------------------
def test_a_confident_miss_scores_infinitely_and_says_so() -> None:
    """The plan's rule (S32.2): the infinity is the result, not a nuisance.

    The existing evaluation module clips to 1e-6 for its dashboard; this one
    does not, because a clipped score reports a claim the model did not make.
    """
    result = log_loss([0.0, 0.5], [1, 1])
    assert result.value == math.inf
    assert result.non_finite == 1
    assert result.state is ScoreState.NON_FINITE
    assert "zero mass" in result.detail


def test_a_confident_hit_stays_finite() -> None:
    result = log_loss([0.0, 1.0], [0, 1])
    assert result.value == pytest.approx(0.0)
    assert result.non_finite == 0


def test_the_zero_baseline_scores_correctly_on_both_outcomes() -> None:
    """Ladder rung 1 against a quiet panel and against one positive."""
    quiet = brier([0.0] * 5, [0] * 5)
    assert quiet.value == pytest.approx(0.0)

    one_hit = brier([0.0] * 5, [0, 0, 1, 0, 0])
    assert one_hit.value == pytest.approx(0.2)
    assert log_loss([0.0] * 5, [0, 0, 1, 0, 0]).value == math.inf


# -- states that are not numbers ------------------------------------------
def test_an_empty_subgroup_is_not_scorable_rather_than_perfect() -> None:
    result = brier([], [])
    assert result.value is None
    assert result.state is ScoreState.NOT_SCORABLE


def test_skill_is_undefined_against_a_perfect_reference() -> None:
    """Zero skill and undefined skill are different findings (S33.3)."""
    model = brier([0.1], [0])
    reference = brier([0.0], [0])
    result = skill(model, reference)
    assert result.value is None
    assert result.state is ScoreState.NOT_SCORABLE
    assert "perfect score" in result.detail


def test_skill_is_undefined_against_a_non_finite_reference() -> None:
    model = log_loss([0.5], [1])
    reference = log_loss([0.0], [1])
    assert skill(model, reference).state is ScoreState.NON_FINITE


def test_skill_refuses_to_compare_scores_over_different_row_sets() -> None:
    """Common support first, or a model's failures quietly improve its mean."""
    with pytest.raises(ContractViolationError, match="different row sets"):
        skill(brier([0.5, 0.5], [0, 1]), brier([0.5], [0]))


def test_skill_reads_the_expected_way_round() -> None:
    better = brier([0.1, 0.9], [0, 1])
    worse = brier([0.5, 0.5], [0, 1])
    result = skill(better, worse)
    assert result.value is not None
    assert result.value > 0.0
    assert result.orientation is Orientation.HIGHER_IS_BETTER


# -- validation ------------------------------------------------------------
def test_unpaired_inputs_are_refused() -> None:
    with pytest.raises(ContractViolationError, match="paired row for row"):
        brier([0.5, 0.5], [1])


def test_probabilities_outside_the_unit_interval_are_refused() -> None:
    with pytest.raises(ContractViolationError, match=r"\[0, 1\]"):
        brier([1.5], [1])


def test_non_binary_outcomes_are_refused() -> None:
    with pytest.raises(ContractViolationError, match="must be 0 or 1"):
        brier([0.5], [2])


# -- count CRPS ------------------------------------------------------------
def test_count_crps_reduces_to_brier_on_a_binary_support() -> None:
    """A useful check that the discrete form is the one it claims to be."""
    pmfs = [(0.3, 0.7), (0.9, 0.1)]
    outcomes = [1, 0]
    crps = count_crps(pmfs, outcomes)
    equivalent = brier([0.7, 0.1], outcomes)
    assert crps.value == pytest.approx(equivalent.value)


def test_count_crps_prefers_the_sharper_correct_forecast() -> None:
    sharp = count_crps([(0.05, 0.9, 0.05)], [1])
    diffuse = count_crps([(0.33, 0.34, 0.33)], [1])
    assert sharp.value is not None and diffuse.value is not None
    assert sharp.value < diffuse.value


def test_an_observation_beyond_the_pmf_support_is_unsupported_not_scored() -> None:
    """One tail bucket does not say where in the tail the mass sits (S32.2)."""
    result = count_crps([(0.5, 0.3, 0.2)], [7], tail_mass=[0.0])
    assert result.value is None
    assert result.state is ScoreState.UNSUPPORTED
    assert result.n == 0


def test_partially_unsupported_rows_are_reported_in_the_denominator() -> None:
    result = count_crps([(0.5, 0.5), (0.5, 0.5)], [1, 9])
    assert result.n == 1
    assert "beyond the PMF support" in result.detail


def test_tail_mass_beyond_the_support_is_penalised() -> None:
    """A model that hid mass past K must not be flattered for it."""
    honest = count_crps([(0.5, 0.5)], [1], tail_mass=[0.0])
    hiding = count_crps([(0.5, 0.4)], [1], tail_mass=[0.1])
    assert honest.value is not None and hiding.value is not None
    assert hiding.value > honest.value


# -- the zero lint, scoped --------------------------------------------------
def test_an_ordinary_model_may_not_assert_a_hard_zero() -> None:
    manifest = CapabilityManifest(model_id="climatology")
    report = check_no_hard_zero(
        [_forecast(p_occ=0.0, method=ProbabilityMethod.ANALYTIC)], capabilities=manifest
    )
    assert not report.clean
    with pytest.raises(ContractViolationError, match="run lint failed"):
        report.raise_if_dirty()


def test_the_declared_zero_baseline_is_exempt() -> None:
    """The plan's resolution: scope the lint, do not epsilon the comparator."""
    manifest = CapabilityManifest(model_id="ladder.zero", diagnostic_zero_baseline=True)
    report = check_no_hard_zero(
        [_forecast(p_occ=0.0, method=ProbabilityMethod.ANALYTIC)], capabilities=manifest
    )
    assert report.clean


def test_a_sampled_zero_is_not_a_hard_zero() -> None:
    manifest = CapabilityManifest(model_id="climatology")
    sampled = _forecast(p_occ=0.0, method=ProbabilityMethod.MONTE_CARLO, n_draws=4000)
    assert check_no_hard_zero([sampled], capabilities=manifest).clean


def test_an_undersampled_zero_is_flagged_with_what_it_actually_rules_out() -> None:
    report = check_monte_carlo_zeros([_forecast(p_occ=0.0, n_draws=10)])
    assert not report.clean
    assert "0.3000" in report.findings[0].detail


def test_a_well_sampled_zero_passes() -> None:
    assert check_monte_carlo_zeros([_forecast(p_occ=0.0, n_draws=4000)]).clean


def test_incoherent_occurrence_and_count_heads_are_caught() -> None:
    incoherent = _forecast(p_occ=0.9, method=ProbabilityMethod.ANALYTIC, pmf=(0.8, 0.2))
    report = check_coherence([incoherent])
    assert not report.clean
    assert report.findings[0].rule == "occurrence_count_incoherence"


def test_nested_window_incoherence_is_caught() -> None:
    """Independent per-horizon heads violate this; daily paths cannot."""
    narrow = [_forecast(p_occ=0.6, method=ProbabilityMethod.ANALYTIC, n_draws=10_000)]
    wide = [_forecast(p_occ=0.2, method=ProbabilityMethod.ANALYTIC, n_draws=10_000)]
    assert not check_nested_windows(narrow, wide).clean
    assert check_nested_windows(wide, narrow).clean


def test_run_all_combines_every_per_forecast_lint() -> None:
    manifest = CapabilityManifest(model_id="m")
    report = run_all(
        [
            _forecast(p_occ=0.0, method=ProbabilityMethod.ANALYTIC, district="101"),
            _forecast(p_occ=0.0, n_draws=5, district="102"),
        ],
        capabilities=manifest,
    )
    rules = {finding.rule for finding in report.findings}
    assert rules == {"hard_zero_probability", "undersampled_zero"}
    assert report.to_dict()["clean"] is False


# -- a real ladder forecast passes its own lints --------------------------
def test_a_sampled_ladder_forecast_is_coherent() -> None:
    generator = np.random.default_rng(4)
    draws = generator.poisson(0.4, size=2000)
    forecast = _forecast(
        p_occ=float(np.mean(draws > 0)),
        n_draws=2000,
        pmf=tuple(np.bincount(draws, minlength=11)[:11] / 2000),
    )
    forecast.check_coherence()
    assert run_all([forecast], capabilities=CapabilityManifest(model_id="m")).clean
