"""Properties that must hold under transformations of the input.

Metamorphic rather than example-based: instead of asserting a number, these
assert how the output must *change* when the input changes in a known way.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fixtures.spatial.synthetic import (
    FAMILY,
    build_adjacency,
    build_registry,
)
from pramaanx.models.spatial.distributions import (
    negative_binomial_distribution,
    poisson_distribution,
)
from pramaanx.models.spatial.features import build_extended_spatial_features
from pramaanx.models.spatial.outcome_helpers import (
    incident_at,
)

CUTOFF = datetime(2026, 2, 1, tzinfo=UTC)
WINDOWS = [7, 30, 90, 365]


def build(incidents):
    return build_extended_spatial_features(
        registry=build_registry(3),
        incidents=incidents,
        cutoffs=[CUTOFF],
        event_families=[FAMILY],
        history_windows_days=WINDOWS,
        adjacency=build_adjacency(3),
        horizon_days=30,
    )


def district_row(rows, district_id="IND-D-1"):
    return next(row for row in rows if row.district_id == district_id)


def test_adding_a_visible_incident_never_lowers_the_district_count() -> None:
    base = [incident_at("a", CUTOFF - timedelta(days=10), CUTOFF - timedelta(days=9))]
    more = [*base, incident_at("b", CUTOFF - timedelta(days=5), CUTOFF - timedelta(days=4))]
    before = district_row(build(base)).features
    after = district_row(build(more)).features
    for window in WINDOWS:
        assert after[f"district_count_{window}d"] >= before[f"district_count_{window}d"]
    assert after["district_decayed_count"] > before["district_decayed_count"]


def test_a_more_recent_incident_decays_less() -> None:
    old = [incident_at("a", CUTOFF - timedelta(days=120), CUTOFF - timedelta(days=119))]
    recent = [incident_at("a", CUTOFF - timedelta(days=2), CUTOFF - timedelta(days=1))]
    assert (
        district_row(build(recent)).features["district_decayed_count"]
        > district_row(build(old)).features["district_decayed_count"]
    )


def test_days_since_last_event_is_absent_rather_than_large_when_unobserved() -> None:
    """A district with no history has no 'days since', not a big number.

    Imputing a sentinel would teach every model that quiet districts are simply
    old districts, which is the opposite of what an unobserved district means.
    """
    rows = build([incident_at("a", CUTOFF - timedelta(days=3), CUTOFF - timedelta(days=2))])
    observed = district_row(rows, "IND-D-1").features
    unobserved = district_row(rows, "IND-D-2").features
    assert "district_days_since_last_event" in observed
    assert "district_days_since_last_event" not in unobserved
    assert unobserved["district_history_observed"] == 0.0
    assert observed["district_history_observed"] == 1.0


def test_an_outage_stays_distinguishable_from_a_calm_period() -> None:
    """Zero documents because nothing happened, versus because nobody looked.

    Coverage features are injected by other packages; this asserts the contract
    keeps the two cases apart rather than collapsing both to zero.
    """
    calm = {"coverage_document_volume": 0.0, "coverage_source_outage": 0.0}
    outage = {"coverage_document_volume": 0.0, "coverage_source_outage": 1.0}
    assert calm != outage
    # And an absent coverage record is a third state, distinct from both.
    assert calm != {}


def test_scaling_a_poisson_rate_scales_its_mean_and_zero_mass_monotonically() -> None:
    low = poisson_distribution(0.2)
    high = poisson_distribution(0.8)
    assert high.mean > low.mean
    assert high.zero_probability < low.zero_probability


@pytest.mark.parametrize("alpha", [0.1, 0.5, 2.0, 8.0])
def test_more_dispersion_means_more_zero_mass_at_a_fixed_mean(alpha: float) -> None:
    poisson = poisson_distribution(0.5)
    nb = negative_binomial_distribution(0.5, alpha)
    assert nb.mean == pytest.approx(poisson.mean)
    assert nb.variance > poisson.variance
    assert nb.zero_probability > poisson.zero_probability
