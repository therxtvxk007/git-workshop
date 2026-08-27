"""Calibration and conformal risk control."""

from __future__ import annotations

import pytest
from _phase2_builders import at

from pramaanx.calibration import (
    EXCHANGEABILITY_CAVEAT,
    IDENTITY_CALIBRATION,
    PLACEHOLDER_POLICY,
    BetaCalibrator,
    CalibrationSample,
    FixedThresholdController,
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    RecallFirstController,
    empirical_miss_rate,
    hoeffding_slack,
    required_positives,
)
from pramaanx.config import AlertPolicyConfig
from pramaanx.schemas.forecast import ForecastStatus


def _sample(size: int = 200, *, positives: int | None = None) -> CalibrationSample:
    """A monotone sample: higher scores really are more likely to resolve true."""
    positives = positives if positives is not None else size // 4
    probabilities: list[float] = []
    outcomes: list[int] = []
    for index in range(size):
        score = (index + 0.5) / size
        probabilities.append(score)
        outcomes.append(1 if index >= size - positives else 0)
    return CalibrationSample(
        probabilities=probabilities,
        outcomes=outcomes,
        sample_start=at(0),
        sample_end=at(100),
    )


class TestDefaults:
    def test_identity_reproduces_the_m0_label_exactly(self) -> None:
        assert IdentityCalibrator().version == IDENTITY_CALIBRATION

    def test_identity_passes_probabilities_through(self) -> None:
        calibrator = IdentityCalibrator()
        assert calibrator.apply(0.37) == pytest.approx(0.37)

    def test_identity_reports_itself_unfitted(self) -> None:
        assert IdentityCalibrator().report().fitted is False

    def test_fixed_threshold_reproduces_the_m0_label(self) -> None:
        assert FixedThresholdController(AlertPolicyConfig()).version == PLACEHOLDER_POLICY

    def test_fixed_threshold_retains_rather_than_drops(self) -> None:
        controller = FixedThresholdController(AlertPolicyConfig())
        status = controller.assign(0.0, uncertainty=0.0, evidence_count=99, novelty=0.0)
        assert status is ForecastStatus.MONITOR

    def test_insufficient_evidence_outranks_a_high_score(self) -> None:
        policy = AlertPolicyConfig()
        controller = FixedThresholdController(policy)
        status = controller.assign(0.99, uncertainty=0.0, evidence_count=0, novelty=0.0)
        assert status is ForecastStatus.INSUFFICIENT_EVIDENCE


class TestSampleValidation:
    def test_mismatched_lengths_are_refused(self) -> None:
        with pytest.raises(ValueError, match="differ in length"):
            CalibrationSample(
                probabilities=[0.1, 0.2], outcomes=[1], sample_start=at(0), sample_end=at(1)
            )

    def test_single_class_sample_cannot_be_fitted(self) -> None:
        sample = CalibrationSample(
            probabilities=[0.1] * 50,
            outcomes=[0] * 50,
            sample_start=at(0),
            sample_end=at(1),
        )
        with pytest.raises(ValueError, match="one outcome class"):
            sample.validate_fittable()

    def test_tiny_sample_cannot_be_fitted(self) -> None:
        sample = CalibrationSample(
            probabilities=[0.1, 0.9], outcomes=[0, 1], sample_start=at(0), sample_end=at(1)
        )
        with pytest.raises(ValueError, match="need at least"):
            sample.validate_fittable()

    def test_out_of_range_probability_is_refused(self) -> None:
        with pytest.raises(ValueError, match="outside"):
            CalibrationSample(
                probabilities=[1.4], outcomes=[1], sample_start=at(0), sample_end=at(1)
            )


class TestFitters:
    def test_platt_fit_records_provenance(self) -> None:
        calibrator = PlattCalibrator().fit(_sample())
        report = calibrator.report()
        assert report.fitted
        assert report.sample_size == 200
        assert report.base_rate == pytest.approx(0.25)
        assert "fitted" in calibrator.version

    def test_platt_output_stays_a_probability(self) -> None:
        calibrator = PlattCalibrator().fit(_sample())
        for raw in (0.0, 0.01, 0.5, 0.99, 1.0):
            assert 0.0 <= calibrator.apply(raw) <= 1.0

    def test_platt_preserves_ordering(self) -> None:
        calibrator = PlattCalibrator().fit(_sample())
        assert calibrator.apply(0.2) <= calibrator.apply(0.8)

    def test_isotonic_demands_a_larger_sample(self) -> None:
        with pytest.raises(ValueError, match="need at least"):
            IsotonicCalibrator().fit(_sample(size=100))

    def test_isotonic_fits_on_a_large_sample(self) -> None:
        calibrator = IsotonicCalibrator().fit(_sample(size=400))
        assert calibrator.report().fitted
        assert 0.0 <= calibrator.apply(0.5) <= 1.0

    def test_isotonic_before_fit_raises(self) -> None:
        with pytest.raises(RuntimeError, match="before fit"):
            IsotonicCalibrator().apply(0.5)

    def test_beta_fit_records_three_parameters(self) -> None:
        calibrator = BetaCalibrator().fit(_sample())
        assert len(calibrator.report().notes) == 3
        assert 0.0 <= calibrator.apply(0.5) <= 1.0


class TestConformalControl:
    def test_required_positives_grows_as_alpha_tightens(self) -> None:
        assert required_positives(0.05, 0.05) > required_positives(0.2, 0.05)

    def test_slack_shrinks_with_more_positives(self) -> None:
        assert hoeffding_slack(1000, 0.05) < hoeffding_slack(10, 0.05)

    def test_too_few_positives_raises_rather_than_loosening(self) -> None:
        controller = RecallFirstController(AlertPolicyConfig())
        with pytest.raises(ValueError, match="cannot certify"):
            controller.fit(_sample(size=60, positives=5), alpha=0.05, delta=0.05)

    def test_fit_reports_the_exchangeability_caveat(self) -> None:
        controller = RecallFirstController(AlertPolicyConfig())
        controller.fit(_sample(size=4000, positives=1500), alpha=0.2, delta=0.1)
        assert EXCHANGEABILITY_CAVEAT in controller.report().caveats

    def test_fitted_threshold_holds_the_miss_rate_on_its_own_sample(self) -> None:
        sample = _sample(size=4000, positives=1500)
        controller = RecallFirstController(AlertPolicyConfig())
        controller.fit(sample, alpha=0.2, delta=0.1)
        observed = empirical_miss_rate(
            sample.probabilities, sample.outcomes, controller.threshold
        )
        assert observed <= 0.2

    def test_unfitted_controller_says_so_in_its_version(self) -> None:
        controller = RecallFirstController(AlertPolicyConfig())
        assert "unfitted" in controller.version
        assert controller.report().fitted is False

    def test_retention_discipline_survives_fitting(self) -> None:
        controller = RecallFirstController(AlertPolicyConfig())
        controller.fit(_sample(size=4000, positives=1500), alpha=0.2, delta=0.1)
        assert (
            controller.assign(0.0, uncertainty=0.0, evidence_count=99, novelty=0.0)
            is ForecastStatus.MONITOR
        )

    def test_high_uncertainty_abstains(self) -> None:
        controller = RecallFirstController(AlertPolicyConfig())
        status = controller.assign(0.9, uncertainty=0.9, evidence_count=99, novelty=0.0)
        assert status is ForecastStatus.ABSTAIN

    def test_empirical_miss_rate_with_no_positives_is_zero(self) -> None:
        assert empirical_miss_rate([0.1, 0.2], [0, 0], 0.5) == 0.0
