"""Evidence coverage: measured exposure, and abstention when it is missing.

The bug this guards produced a real forecast of 0.999975 from six hours of
GDELT, because the base-rate estimator took its exposure from a configuration
constant instead of from the evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.coverage import DEFAULT_MIN_COVERAGE, EvidenceCoverage, measure_coverage
from pramaanx.generators.base import ForecastContext
from pramaanx.generators.base_rate import BaseRateGenerator
from pramaanx.schemas.observation import Modality, Observation

CUTOFF = datetime(2026, 8, 27, 14, tzinfo=UTC)


def _obs(index: int, observed_at: datetime, source_id: str = "gdelt") -> Observation:
    return Observation(
        observation_id=f"obs_{source_id}_{index}",
        source_id=source_id,
        source_type="test",
        modality=Modality.TEXT,
        retrieved_at=max(observed_at, CUTOFF),
        first_observed_at=observed_at,
        raw_content_hash=f"sha256:{index:064x}",
        payload_ref=f"ab/{index}.bin",
    )


class TestMeasurement:
    def test_span_is_measured_not_assumed(self) -> None:
        """Six hours of evidence is six hours, whatever the config asked for."""
        # Spread across the full six hours rather than clustered: the span is
        # first-to-last, so forty observations a minute apart would describe a
        # thirty-nine minute window, not a six-hour one.
        observations = [
            _obs(i, CUTOFF - timedelta(hours=6) + timedelta(hours=6 * i / 39)) for i in range(40)
        ]
        coverage = measure_coverage(observations, cutoff_at=CUTOFF, lookback_days=365)
        assert coverage.observed_span_days == pytest.approx(6 / 24, abs=1e-3)
        assert coverage.coverage_ratio < 0.001
        assert not coverage.sufficient

    def test_evidence_after_the_cutoff_does_not_count(self) -> None:
        """The same rule the cutoff guard enforces, for the same reason."""
        observations = [
            _obs(0, CUTOFF - timedelta(days=200)),
            _obs(1, CUTOFF + timedelta(days=5)),
        ]
        coverage = measure_coverage(observations, cutoff_at=CUTOFF, lookback_days=365)
        assert coverage.observation_count == 1

    def test_more_history_than_requested_is_not_over_full_coverage(self) -> None:
        observations = [
            _obs(0, CUTOFF - timedelta(days=900)),
            _obs(1, CUTOFF - timedelta(days=300)),
            _obs(2, CUTOFF - timedelta(days=1)),
        ]
        coverage = measure_coverage(observations, cutoff_at=CUTOFF, lookback_days=365)
        assert coverage.coverage_ratio <= 1.0
        assert coverage.sufficient

    def test_per_source_spans_are_reported_separately(self) -> None:
        observations = [
            _obs(0, CUTOFF - timedelta(days=300), "gdelt"),
            _obs(1, CUTOFF - timedelta(days=2), "gdelt"),
            _obs(2, CUTOFF - timedelta(days=3), "reliefweb"),
        ]
        coverage = measure_coverage(observations, cutoff_at=CUTOFF, lookback_days=365)
        manifest = coverage.manifest()
        assert set(manifest["sources"]) == {"gdelt", "reliefweb"}
        assert manifest["sources"]["gdelt"]["observed_span_days"] > 290
        assert manifest["sources"]["reliefweb"]["observed_span_days"] == 0.0


class TestSufficiency:
    def test_an_empty_corpus_is_not_a_rate_of_zero(self) -> None:
        """The distinction the whole module exists for."""
        coverage = measure_coverage([], cutoff_at=CUTOFF, lookback_days=365)
        assert not coverage.sufficient
        reason = coverage.reason()
        assert reason is not None
        assert "no events occurred" in reason

    def test_the_reason_says_what_to_do_about_it(self) -> None:
        observations = [
            _obs(i, CUTOFF - timedelta(hours=6) + timedelta(minutes=i)) for i in range(5)
        ]
        reason = measure_coverage(observations, cutoff_at=CUTOFF, lookback_days=365).reason()
        assert reason is not None
        assert "lower generators.lookback_days" in reason

    def test_sufficient_coverage_has_no_complaint(self) -> None:
        observations = [
            _obs(0, CUTOFF - timedelta(days=364)),
            _obs(1, CUTOFF - timedelta(days=1)),
        ]
        coverage = measure_coverage(observations, cutoff_at=CUTOFF, lookback_days=365)
        assert coverage.sufficient
        assert coverage.reason() is None

    def test_effective_exposure_is_the_observed_span_never_the_request(self) -> None:
        observations = [
            _obs(0, CUTOFF - timedelta(days=100)),
            _obs(1, CUTOFF - timedelta(days=1)),
        ]
        coverage = measure_coverage(observations, cutoff_at=CUTOFF, lookback_days=365)
        assert coverage.effective_exposure_days == pytest.approx(99.0, abs=0.1)
        assert coverage.effective_exposure_days != 365


class TestGeneratorAbstains:
    def test_the_generator_produces_nothing_under_thin_coverage(self) -> None:
        """The regression for the 0.999975 forecast from six hours of GDELT."""
        coverage = EvidenceCoverage(
            cutoff_at=CUTOFF,
            requested_lookback_days=365,
            observed_span_days=0.25,
            observation_count=155,
        )
        generator = BaseRateGenerator([], time_buckets=["0-7d"], coverage=coverage)
        proposals = generator.propose(
            ForecastContext(
                cutoff_at=CUTOFF,
                evidence_snapshot_id="snap_x",
                proposal_budget=100,
                horizon_days=90,
            )
        )
        assert proposals == []

    def test_a_generator_with_no_coverage_object_still_runs(self) -> None:
        """Direct construction stays usable; the pipeline always measures."""
        generator = BaseRateGenerator([], time_buckets=["0-7d"])
        assert generator.coverage is None
        assert (
            generator.propose(
                ForecastContext(
                    cutoff_at=CUTOFF,
                    evidence_snapshot_id="snap_x",
                    proposal_budget=100,
                    horizon_days=90,
                )
            )
            == []
        )

    def test_the_default_threshold_is_declared_not_hidden(self) -> None:
        assert 0.0 < DEFAULT_MIN_COVERAGE <= 1.0
