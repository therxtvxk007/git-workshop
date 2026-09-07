"""The capability tokens, and the chronology guards they carry.

A guard nobody tests is a guard nobody has. Each of these is a rule the plan
states and the type system cannot enforce (S29.3, S33.1).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from _builders import ORIGIN

from pramaanx.core.contexts import (
    AvailabilityBasis,
    FitContext,
    ForecastContext,
    InformationProfile,
    OriginRole,
    ScoreContext,
)
from pramaanx.core.errors import ContractViolationError


def _forecast(**overrides: object) -> ForecastContext:
    base: dict[str, object] = {
        "issue_time": ORIGIN,
        "cutoff_at": ORIGIN,
        "input_manifest": "sha256:inputs",
        "profile": InformationProfile.PROSPECTIVE_OBSERVED,
        "role": OriginRole.RETRO_TEST,
        "policy_hash": "sha256:policy",
        "boundary_version": "v1",
    }
    base.update(overrides)
    return ForecastContext.model_validate(base)


def _fit(**overrides: object) -> FitContext:
    base: dict[str, object] = {
        "issue_time": ORIGIN,
        "cutoff_at": ORIGIN,
        "input_manifest": "sha256:inputs",
        "profile": InformationProfile.PROSPECTIVE_OBSERVED,
        "role": OriginRole.TRAIN,
        "policy_hash": "sha256:policy",
        "boundary_version": "v1",
        "fit_cutoff": ORIGIN,
        "label_manifest": "sha256:labels",
        "maturation_days": 14,
    }
    base.update(overrides)
    return FitContext.model_validate(base)


# -- chronology guards -----------------------------------------------------
def test_a_cutoff_after_the_issue_time_is_refused() -> None:
    """A run cannot have seen more than existed when it was issued."""
    with pytest.raises(ContractViolationError, match="cutoff_at is after issue_time"):
        _forecast(cutoff_at=ORIGIN + timedelta(days=1))


def test_a_fit_cutoff_after_the_issue_time_is_refused() -> None:
    with pytest.raises(ContractViolationError, match="fit_cutoff is after issue_time"):
        _fit(fit_cutoff=ORIGIN + timedelta(days=1))


def test_a_training_origin_after_the_fit_cutoff_is_refused() -> None:
    with pytest.raises(ContractViolationError, match="training origin is after"):
        _fit(training_origins=(ORIGIN + timedelta(days=30),))


def test_a_prospective_score_may_not_reuse_its_own_input_snapshot() -> None:
    """Matured outcomes cannot be in the snapshot the forecast was built from."""
    with pytest.raises(ContractViolationError, match="reuses the forecast's own"):
        ScoreContext(
            issue_time=ORIGIN,
            cutoff_at=ORIGIN,
            input_manifest="sha256:same",
            profile=InformationProfile.PROSPECTIVE_OBSERVED,
            role=OriginRole.PROSPECTIVE,
            policy_hash="sha256:policy",
            boundary_version="v1",
            forecast_artifact="sha256:forecast",
            reference_manifest="sha256:same",
            maturation_days=14,
            evaluation_contract="sha256:evaluation",
        )


def test_a_retrospective_score_may_reuse_the_snapshot() -> None:
    """A retrospective replay reads one archive for both halves; the guard is
    about a *prospective* claim, where the outcome had not happened yet."""
    context = ScoreContext(
        issue_time=ORIGIN,
        cutoff_at=ORIGIN,
        input_manifest="sha256:same",
        profile=InformationProfile.ENGINEERING_REPLAY,
        role=OriginRole.RETRO_TEST,
        policy_hash="sha256:policy",
        boundary_version="v1",
        forecast_artifact="sha256:forecast",
        reference_manifest="sha256:same",
        maturation_days=14,
        evaluation_contract="sha256:evaluation",
    )
    assert context.reference_manifest == context.input_manifest


# -- what a profile decides ------------------------------------------------
def test_the_profile_decides_which_instant_eligibility_uses() -> None:
    available = ORIGIN
    retrieved = ORIGIN + timedelta(days=10)

    prospective = _forecast(profile=InformationProfile.PROSPECTIVE_OBSERVED)
    assert prospective.eligibility_instant(available, retrieved) == retrieved

    for profile in (
        InformationProfile.STRICT_HISTORICAL,
        InformationProfile.ENGINEERING_REPLAY,
    ):
        assert _forecast(profile=profile).eligibility_instant(available, retrieved) == available


def test_strict_bases_exclude_an_unresolved_claim() -> None:
    from pramaanx.core.contexts import STRICT_BASES

    assert AvailabilityBasis.UNRESOLVED not in STRICT_BASES
    assert AvailabilityBasis.VERIFIED_ARCHIVE_CAPTURE in STRICT_BASES


# -- narrowing, never widening --------------------------------------------
def test_a_fit_context_narrows_to_a_predictor_only_view() -> None:
    """And there is no conversion the other way, which is the point."""
    fit = _fit()
    narrowed = fit.forecast_context()
    assert isinstance(narrowed, ForecastContext)
    assert not hasattr(narrowed, "label_manifest")
    assert not hasattr(narrowed, "forecast_artifact")


def test_narrowing_to_an_earlier_origin_moves_the_cutoff_back() -> None:
    """A training row's features are built at that row's own origin, so the
    narrowed context must not carry the fit's later cutoff."""
    fit = _fit(issue_time=ORIGIN + timedelta(days=90), fit_cutoff=ORIGIN + timedelta(days=90))
    earlier = fit.forecast_context(issue_time=ORIGIN)
    assert earlier.issue_time == ORIGIN
    assert earlier.cutoff_at == ORIGIN


def test_the_horizon_end_is_measured_from_the_issue_time() -> None:
    assert _forecast().horizon_end(30) == ORIGIN + timedelta(days=30)


# -- identity --------------------------------------------------------------
def test_the_identity_changes_with_anything_that_changes_a_read() -> None:
    baseline = _forecast().identity()
    assert _forecast(policy_hash="sha256:with-shadow").identity() != baseline
    assert _forecast(profile=InformationProfile.ENGINEERING_REPLAY).identity() != baseline
    assert _forecast(boundary_version="v2").identity() != baseline
    assert _forecast().identity() == baseline


def test_a_context_is_frozen() -> None:
    """A context that could be edited after a read is not a capability token."""
    context = _forecast()
    with pytest.raises((ValueError, TypeError)):
        context.cutoff_at = datetime(2030, 1, 1, tzinfo=UTC)  # type: ignore[misc]
