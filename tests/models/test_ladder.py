"""The first five ladder rungs, and the capability asymmetry between them."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from _panel_fixture import MiniPanel, build

from pramaanx.core.errors import CapabilityUnsupportedError, ContractViolationError
from pramaanx.core.rng import RandomStreams
from pramaanx.models.base import ForecastArtifact
from pramaanx.models.capabilities import Capability
from pramaanx.models.ladder import (
    LADDER,
    Climatology,
    EmpiricalBayes,
    Hist12,
    Persistence,
    ZeroBaseline,
)


@pytest.fixture(scope="module")
def mini() -> MiniPanel:
    return build()


def _run(model: object, mini: MiniPanel, *, seed: int = 5) -> ForecastArtifact:
    rng = RandomStreams(root_seed=seed)
    artifact = model.fit(mini.training_rows(), ctx=mini.fit_context(), rng=rng)  # type: ignore[attr-defined]
    return model.predict(  # type: ignore[attr-defined]
        mini.issue_rows(), model=artifact, ctx=mini.forecast_context(), rng=rng
    )


# -- every rung runs -------------------------------------------------------
@pytest.mark.parametrize("factory", LADDER, ids=lambda cls: cls.__name__)
def test_every_rung_produces_non_negative_integer_counts(factory: type, mini: MiniPanel) -> None:
    forecast = _run(factory(), mini)
    samples = forecast.window(*mini.window())
    assert np.issubdtype(samples.counts.dtype, np.integer)
    assert samples.counts.min() >= 0
    assert samples.counts.shape[1] == mini.issue_rows().height


@pytest.mark.parametrize("factory", LADDER, ids=lambda cls: cls.__name__)
def test_every_rung_covers_every_panel_row(factory: type, mini: MiniPanel) -> None:
    forecasts = _run(factory(), mini).summarise(*mini.window())
    keys = {forecast.key.as_tuple() for forecast in forecasts}
    expected = set(
        zip(
            mini.issue_rows()["district_id"].to_list(),
            mini.issue_rows()["family"].to_list(),
            strict=True,
        )
    )
    assert keys == expected


@pytest.mark.parametrize("factory", LADDER, ids=lambda cls: cls.__name__)
def test_the_same_seed_reproduces_the_same_forecast(factory: type, mini: MiniPanel) -> None:
    first = _run(factory(), mini, seed=11).window(*mini.window()).counts
    second = _run(factory(), mini, seed=11).window(*mini.window()).counts
    assert np.array_equal(first, second)


# -- the capability asymmetry ---------------------------------------------
def test_three_rungs_have_a_daily_process_and_two_do_not() -> None:
    """The plan's rule made visible (S42): persistence and a rolling empirical
    distribution predict window totals and have no within-window process."""
    daily = {
        factory().model_id
        for factory in LADDER
        if factory().capabilities().supports(Capability.DAILY_PATHS)
    }
    assert daily == {"ladder.climatology", "ladder.empirical_bayes"}
    assert "ladder.persistence" not in daily
    assert "ladder.hist12" not in daily
    assert "ladder.zero" not in daily


def test_a_window_only_rung_refuses_a_different_window(mini: MiniPanel) -> None:
    """Rather than scattering its total across days under an assumption."""
    forecast = _run(Persistence(), mini)
    start, end = mini.window()
    with pytest.raises(CapabilityUnsupportedError, match="no daily process"):
        forecast.window(start, start + (end - start) / 2)


def test_a_window_only_rung_says_why_it_declines(mini: MiniPanel) -> None:
    manifest = Hist12().capabilities()
    assert not manifest.supports(Capability.DAILY_PATHS)
    assert "within-window process" in manifest.unresolved[str(Capability.DAILY_PATHS)]


def test_a_daily_rung_names_its_construction() -> None:
    """The assumption is on the record rather than inside the sampler."""
    assert Climatology().capabilities().daily_construction == (
        "homogeneous_poisson_from_long_run_rate"
    )
    assert (
        EmpiricalBayes().capabilities().daily_construction
        == Climatology().capabilities().daily_construction
    )


def test_a_daily_rung_answers_every_contracted_horizon(mini: MiniPanel) -> None:
    """7, 14 and 30 days from one fit, coherently nested."""
    forecast = _run(Climatology(), mini)
    edges = forecast.paths.edges  # type: ignore[union-attr]
    nested = [forecast.summarise(edges[0], edges[length])[0].p_occ for length in (7, 14, 30)]
    assert nested == sorted(nested)
    assert nested[0] < nested[-1]


# -- rung behaviour --------------------------------------------------------
def test_the_zero_rung_predicts_exactly_zero_and_declares_it(mini: MiniPanel) -> None:
    forecast = _run(ZeroBaseline(), mini)
    rows = forecast.summarise(*mini.window())
    assert {row.p_occ for row in rows} == {0.0}
    assert forecast.capabilities.diagnostic_zero_baseline is True


def test_persistence_repeats_the_last_observed_count(mini: MiniPanel) -> None:
    forecast = _run(Persistence(), mini)
    rows = {row.key.as_tuple(): row for row in forecast.summarise(*mini.window())}
    history = mini.training_rows().sort("origin")
    last = history.filter((pl.col("district_id") == "101") & (pl.col("family") == "lwe"))[
        "y_observed"
    ].to_list()[-1]
    assert rows[("101", "lwe")].mean == pytest.approx(float(last))


def test_a_quiet_district_gets_a_low_probability_not_a_zero_one(mini: MiniPanel) -> None:
    """District 102 has never had an event. Climatology says almost never,
    which is a different statement from never (S32.2)."""
    forecast = _run(Climatology(), mini)
    rows = {row.key.as_tuple(): row for row in forecast.summarise(*mini.window())}
    assert rows[("102", "lwe")].p_occ == 0.0
    _, high = rows[("102", "lwe")].mc_interval()
    assert high > 0.0


def test_hist12_refuses_a_cell_it_has_never_observed(mini: MiniPanel) -> None:
    """An empirical distribution over nothing is not a forecast of zero."""
    model = Hist12()
    rng = RandomStreams(root_seed=1)
    artifact = model.fit(mini.training_rows(), ctx=mini.fit_context(), rng=rng)
    stranger = mini.issue_rows().with_columns(pl.lit("999").alias("district_id"))
    with pytest.raises(ContractViolationError, match="not a forecast of zero"):
        model.predict(stranger, model=artifact, ctx=mini.forecast_context(), rng=rng)


def test_hist12_only_draws_counts_it_has_actually_seen(mini: MiniPanel) -> None:
    forecast = _run(Hist12(), mini)
    samples = forecast.window(*mini.window())
    index = [key.as_tuple() for key in samples.keys].index(("101", "lwe"))
    observed = set(
        mini.training_rows()
        .filter((pl.col("district_id") == "101") & (pl.col("family") == "lwe"))["y_observed"]
        .to_list()[-12:]
    )
    assert set(samples.counts[:, index].tolist()) <= observed


def test_empirical_bayes_shrinks_a_thin_cell_towards_the_family(mini: MiniPanel) -> None:
    """District 201 is intermittent; pooling should pull it off its own noisy
    rate and towards the family's."""
    rng = RandomStreams(root_seed=2)
    artifact = EmpiricalBayes().fit(mini.training_rows(), ctx=mini.fit_context(), rng=rng)
    rates = artifact.parameters["rate_per_day"]
    quiet = rates["102|lwe"]
    thin = rates["201|lwe"]
    active = rates["101|lwe"]
    assert 0.0 < quiet < thin < active


def test_a_batch_spanning_two_windows_is_refused(mini: MiniPanel) -> None:
    """One artifact must not claim a window half its rows do not have."""
    mixed = pl.concat(
        [
            mini.panel.filter(pl.col("origin") == mini.origins[-1]),
            mini.panel.filter(pl.col("origin") == mini.origins[-2]),
        ]
    )
    model = ZeroBaseline()
    rng = RandomStreams(root_seed=1)
    artifact = model.fit(mini.training_rows(), ctx=mini.fit_context(), rng=rng)
    with pytest.raises(ContractViolationError, match="one outcome window"):
        model.predict(mixed, model=artifact, ctx=mini.forecast_context(), rng=rng)


def test_a_panel_missing_required_columns_is_refused(mini: MiniPanel) -> None:
    model = ZeroBaseline()
    rng = RandomStreams(root_seed=1)
    artifact = model.fit(mini.training_rows(), ctx=mini.fit_context(), rng=rng)
    with pytest.raises(ContractViolationError, match="missing required columns"):
        model.predict(
            mini.issue_rows().drop("family"),
            model=artifact,
            ctx=mini.forecast_context(),
            rng=rng,
        )
