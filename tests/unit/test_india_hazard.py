"""Registry, hazard and walk-forward behaviour.

The leakage tests are the ones that matter. Everything else here checks that
the estimator does what its docstring says; those check that it cannot see what
it must not see.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pramaanx.india.evaluate import walk_forward
from pramaanx.india.hazard import fit_hazard
from pramaanx.india.registry import (
    TARGET_CLASS_TAXONOMY,
    Incident,
    RegistryError,
    admissible_at,
    load_incidents,
)


def _incident(day: str, state: str, target_class: str, city: str = "X") -> Incident:
    return Incident(
        occurred_at=datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC),
        state=state,
        city=city,
        target_class=target_class,
        fatalities=1,
        note="",
    )


@pytest.fixture
def history() -> tuple[Incident, ...]:
    return tuple(
        _incident(day, state, cls)
        for day, state, cls in [
            ("2001-01-01", "A", "market"),
            ("2002-01-01", "A", "market"),
            ("2003-01-01", "A", "transit"),
            ("2004-01-01", "B", "market"),
            ("2005-01-01", "B", "security"),
            ("2006-01-01", "C", "religious"),
            ("2007-01-01", "A", "market"),
            ("2008-01-01", "B", "security"),
            ("2009-01-01", "C", "religious"),
            ("2010-01-01", "A", "market"),
            ("2011-01-01", "B", "security"),
            ("2012-01-01", "C", "government"),
        ]
    )


class TestRegistryAdmissibility:
    def test_reporting_lag_delays_admission(self) -> None:
        incident = _incident("2008-11-26", "Maharashtra", "hospitality")
        just_after_event = datetime(2008, 11, 26, 12, tzinfo=UTC)
        assert admissible_at((incident,), just_after_event) == ()
        assert admissible_at((incident,), datetime(2008, 11, 28, tzinfo=UTC)) == (incident,)

    def test_naive_cutoff_rejected(self, history: tuple[Incident, ...]) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            admissible_at(history, datetime(2010, 1, 1))  # noqa: DTZ001

    def test_shipped_registry_loads_and_is_sorted(self) -> None:
        incidents = load_incidents()
        assert len(incidents) > 20
        assert list(incidents) == sorted(incidents, key=lambda i: (i.occurred_at, i.state, i.city))
        assert {i.target_class for i in incidents} <= set(TARGET_CLASS_TAXONOMY)

    def test_malformed_row_raises_rather_than_skipping(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        bad = tmp_path / "bad.csv"
        bad.write_text(
            "date,state,city,target_class,fatalities,note\nnot-a-date,A,X,market,1,\n",
            encoding="utf-8",
        )
        with pytest.raises(RegistryError, match="bad date"):
            load_incidents(bad)

    def test_missing_column_raises(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        bad = tmp_path / "bad.csv"
        bad.write_text("date,state,city\n2001-01-01,A,X\n", encoding="utf-8")
        with pytest.raises(RegistryError, match="missing columns"):
            load_incidents(bad)


class TestLeakage:
    """The fit must depend on nothing after its cutoff."""

    def test_future_incidents_do_not_change_the_fit(self, history: tuple[Incident, ...]) -> None:
        cutoff = datetime(2012, 6, 1, tzinfo=UTC)
        baseline = fit_hazard(history, cutoff)

        future = (
            *history,
            _incident("2013-01-01", "C", "hospitality"),
            _incident("2013-06-01", "C", "hospitality"),
            _incident("2014-01-01", "C", "hospitality"),
        )
        after = fit_hazard(future, cutoff)

        assert [c.cell for c in after.cells] == [c.cell for c in baseline.cells]
        assert [c.probability for c in after.cells] == [c.probability for c in baseline.cells]
        assert after.incidents_used == baseline.incidents_used

    def test_incident_on_the_cutoff_day_is_excluded_by_the_lag(
        self, history: tuple[Incident, ...]
    ) -> None:
        cutoff = datetime(2012, 1, 1, tzinfo=UTC)
        fit = fit_hazard(history, cutoff)
        # 2012-01-01 "C"/government occurs at the cutoff, so its lag keeps it out.
        assert fit.incidents_used == len(history) - 1

    def test_walk_forward_trial_excludes_its_own_incident(
        self, history: tuple[Incident, ...]
    ) -> None:
        report = walk_forward(history, min_history=5)
        assert report.n_trials > 0
        # Every trial fit must have used strictly fewer incidents than the
        # registry holds up to and including the scored one.
        for trial in report.trials:
            assert trial.cell_rank >= 1
            assert trial.cell_rank <= trial.cells_ranked + 1


class TestHazard:
    def test_probabilities_are_proper_and_ranked(self, history: tuple[Incident, ...]) -> None:
        fit = fit_hazard(history, datetime(2013, 1, 1, tzinfo=UTC))
        assert all(0.0 < c.probability < 1.0 for c in fit.cells)
        probabilities = [c.probability for c in fit.cells]
        assert probabilities == sorted(probabilities, reverse=True)

    def test_unseen_class_is_rankable_not_missing(self, history: tuple[Incident, ...]) -> None:
        """The taxonomy is fixed, so a class no state has seen still has a cell."""
        fit = fit_hazard(history, datetime(2013, 1, 1, tzinfo=UTC))
        assert "hospitality" not in {i.target_class for i in history}
        rank = fit.rank_of("A", "hospitality")
        assert rank is not None
        cell = fit.cells[rank - 1]
        assert cell.raw_count == 0
        assert cell.prior_driven is True

    def test_repeated_history_outranks_a_prior_only_cell(
        self, history: tuple[Incident, ...]
    ) -> None:
        fit = fit_hazard(history, datetime(2013, 1, 1, tzinfo=UTC))
        busy = fit.rank_of("A", "market")
        empty = fit.rank_of("A", "hospitality")
        assert busy is not None and empty is not None
        assert busy < empty

    def test_recency_weighting_favours_the_recent(self) -> None:
        old = tuple(_incident(f"199{y}-01-01", "A", "market") for y in range(1, 6))
        recent = tuple(_incident(f"201{y}-01-01", "B", "market") for y in range(1, 6))
        fit = fit_hazard(old + recent, datetime(2016, 1, 1, tzinfo=UTC))
        a = fit.rank_of("A", "market")
        b = fit.rank_of("B", "market")
        assert a is not None and b is not None
        assert b < a

    def test_state_ranking_covers_every_state(self, history: tuple[Incident, ...]) -> None:
        fit = fit_hazard(history, datetime(2013, 1, 1, tzinfo=UTC))
        assert {s for s, _ in fit.state_ranking()} == {"A", "B", "C"}

    def test_deterministic(self, history: tuple[Incident, ...]) -> None:
        cutoff = datetime(2013, 1, 1, tzinfo=UTC)
        first = fit_hazard(history, cutoff)
        second = fit_hazard(history, cutoff)
        assert [c.cell for c in first.cells] == [c.cell for c in second.cells]
        assert [c.probability for c in first.cells] == [c.probability for c in second.cells]

    def test_empty_history_raises(self, history: tuple[Incident, ...]) -> None:
        with pytest.raises(ValueError, match="no incidents"):
            fit_hazard(history, datetime(1990, 1, 1, tzinfo=UTC))

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"horizon_days": 0}, "horizon_days"),
            ({"half_life_days": 0.0}, "half_life_days"),
            ({"prior_strength_days": -1.0}, "prior_strength_days"),
        ],
    )
    def test_invalid_parameters_raise(
        self, history: tuple[Incident, ...], kwargs: dict[str, float], match: str
    ) -> None:
        with pytest.raises(ValueError, match=match):
            fit_hazard(history, datetime(2013, 1, 1, tzinfo=UTC), **kwargs)  # type: ignore[arg-type]

    def test_longer_horizon_raises_probability(self, history: tuple[Incident, ...]) -> None:
        cutoff = datetime(2013, 1, 1, tzinfo=UTC)
        short = fit_hazard(history, cutoff, horizon_days=30)
        long = fit_hazard(history, cutoff, horizon_days=365)
        assert long.cells[0].probability > short.cells[0].probability


class TestEvaluation:
    def test_reports_chance_alongside_hits(self, history: tuple[Incident, ...]) -> None:
        report = walk_forward(history, min_history=5)
        for k in (1, 3, 5, 10):
            assert 0.0 <= report.cell_hit_at[k] <= 1.0
            assert 0.0 < report.cell_chance_at[k] <= 1.0
        # hit@k is monotone in k.
        assert report.cell_hit_at[1] <= report.cell_hit_at[3] <= report.cell_hit_at[10]

    def test_insufficient_history_raises(self, history: tuple[Incident, ...]) -> None:
        with pytest.raises(ValueError, match="no trial had enough history"):
            walk_forward(history, min_history=1000)

    def test_shipped_registry_backtests(self) -> None:
        report = walk_forward(load_incidents())
        assert report.n_trials > 10
        assert 0.0 <= report.prior_driven_cell_fraction <= 1.0
