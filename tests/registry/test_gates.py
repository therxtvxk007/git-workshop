"""Registry gates: what may be collected, what may move a probability, what may run."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from pramaanx.core.contexts import InformationProfile
from pramaanx.core.errors import ContractViolationError
from pramaanx.registry.models import (
    IntendedUse,
    ModelEntry,
    ModelRegistry,
    Verdict,
    may_use_model,
)
from pramaanx.registry.policy import ReadPurpose, RegistryReadPolicy
from pramaanx.registry.sources import (
    ApprovalStatus,
    CollectionApproval,
    SourceEntry,
    SourceRegistry,
    SourceTier,
    may_alter_probability,
    may_collect,
    may_create_candidate,
)

TODAY = date(2026, 6, 1)
ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


def _approval(**overrides: object) -> CollectionApproval:
    base: dict[str, object] = {
        "status": ApprovalStatus.APPROVED,
        "owner": "mentor",
        "scope": "public incident pages, 1 request per second",
        "effective_from": date(2026, 1, 1),
        "evidence_ref": "docs/approvals/satp.md",
    }
    base.update(overrides)
    return CollectionApproval.model_validate(base)


def _source(**overrides: object) -> SourceEntry:
    base: dict[str, object] = {
        "source_id": "satp",
        "tier": SourceTier.VALIDATED,
        "approval": _approval(),
    }
    base.update(overrides)
    return SourceEntry.model_validate(base)


# -- collection ------------------------------------------------------------
def test_a_quarantined_source_cannot_be_collected_however_approved() -> None:
    """New sources start quarantined and stay there until they are described."""
    assert may_collect(_source(tier=SourceTier.QUARANTINED), on=TODAY) is False


def test_an_unapproved_source_cannot_be_collected_however_validated() -> None:
    """Both gates, not either: a good source with no approval is still off."""
    pending = _source(approval=CollectionApproval(status=ApprovalStatus.PENDING))
    assert may_collect(pending, on=TODAY) is False


def test_an_approval_needs_evidence_not_just_an_owner() -> None:
    """The failure mode this replaces: a name that looks like a decision."""
    with pytest.raises(ContractViolationError, match="not a decision"):
        CollectionApproval(status=ApprovalStatus.APPROVED, owner="mentor")


def test_an_approval_expires() -> None:
    lapsed = _source(approval=_approval(effective_to=date(2026, 3, 1)))
    assert may_collect(lapsed, on=date(2026, 2, 1)) is True
    assert may_collect(lapsed, on=TODAY) is False


def test_collection_without_a_date_is_refused() -> None:
    """An approval is a statement about a period, so a gate needs the day."""
    assert may_collect(_source(), on=None) is False


# -- what a tier licenses --------------------------------------------------
@pytest.mark.parametrize(
    "tier, candidate, probability",
    [
        (SourceTier.VALIDATED, True, True),
        (SourceTier.DISCOVERY_ONLY, True, False),
        (SourceTier.MONITORING_ONLY, False, False),
        (SourceTier.QUARANTINED, False, False),
    ],
)
def test_tiers_license_actions_not_quality(
    tier: SourceTier, candidate: bool, probability: bool
) -> None:
    """A discovery-only source surfaces candidates and never moves a number."""
    source = _source(tier=tier)
    assert may_create_candidate(source) is candidate
    assert may_alter_probability(source) is probability


# -- the store's step-5 policy --------------------------------------------
def _registry() -> SourceRegistry:
    return SourceRegistry(
        entries=(
            _source(source_id="acled", tier=SourceTier.VALIDATED),
            _source(source_id="rumour_feed", tier=SourceTier.DISCOVERY_ONLY),
            _source(source_id="weather", tier=SourceTier.MONITORING_ONLY),
            _source(source_id="local_paper", tier=SourceTier.VALIDATED, shadow=True),
        )
    )


def test_the_purpose_decides_which_sources_a_read_admits() -> None:
    registry = _registry()
    adjudication = RegistryReadPolicy(registry, ReadPurpose.ADJUDICATION)
    discovery = RegistryReadPolicy(registry, ReadPurpose.DISCOVERY)

    assert adjudication.deny_reason("acled") is None
    assert adjudication.deny_reason("rumour_feed") == "tier_discovery_only"
    assert discovery.deny_reason("rumour_feed") is None
    assert discovery.deny_reason("weather") == "tier_monitoring_only"


def test_a_shadow_source_is_invisible_to_forecasting_and_visible_to_the_audit() -> None:
    """The whole design of a shadow stream (S9): withheld from the forecaster,
    read by the audit that measures what the forecaster missed."""
    registry = _registry()
    assert (
        RegistryReadPolicy(registry, ReadPurpose.ADJUDICATION).deny_reason("local_paper")
        == "shadow_withheld"
    )
    assert RegistryReadPolicy(registry, ReadPurpose.AUDIT).deny_reason("local_paper") is None


def test_an_unregistered_source_is_denied() -> None:
    assert (
        RegistryReadPolicy(_registry(), ReadPurpose.DISCOVERY).deny_reason("mystery")
        == "unregistered"
    )


def test_a_tier_change_changes_the_policy_hash() -> None:
    """So a context over identical bytes is still a different read (S36.2)."""
    before = RegistryReadPolicy(_registry(), ReadPurpose.ADJUDICATION).policy_hash()
    promoted = SourceRegistry(
        entries=tuple(
            entry.model_copy(update={"tier": SourceTier.VALIDATED})
            if entry.source_id == "rumour_feed"
            else entry
            for entry in _registry().entries
        )
    )
    after = RegistryReadPolicy(promoted, ReadPurpose.ADJUDICATION).policy_hash()
    assert before != after


def test_an_attribution_change_does_not_change_the_policy_hash() -> None:
    """The hash covers what changes a read, not the whole registry."""
    before = RegistryReadPolicy(_registry(), ReadPurpose.ADJUDICATION).policy_hash()
    edited = SourceRegistry(
        entries=tuple(
            entry.model_copy(update={"attribution_rule": "cite the outlet"})
            for entry in _registry().entries
        )
    )
    assert RegistryReadPolicy(edited, ReadPurpose.ADJUDICATION).policy_hash() == before


# -- the parameter-cutoff gate --------------------------------------------
def _model(**overrides: object) -> ModelEntry:
    base: dict[str, object] = {
        "model_id": "indictrans2",
        "training_data_cutoff": datetime(2023, 1, 1, tzinfo=UTC),
        "cutoff_scope": "web crawl and parallel corpora to 2023-01",
        "release_date": datetime(2023, 6, 1, tzinfo=UTC),
        "weights_licence": "MIT",
        "commercial_use": True,
        "operational_use": True,
        "weights_hash": "sha256:w",
        "tokenizer_hash": "sha256:t",
        "config_hash": "sha256:c",
    }
    base.update(overrides)
    return ModelEntry.model_validate(base)


def test_a_model_trained_past_the_origin_is_blocked() -> None:
    """The leak the as-of store cannot see: it is inside the parameters."""
    late = _model(
        training_data_cutoff=datetime(2026, 8, 1, tzinfo=UTC),
        cutoff_scope="web crawl to 2026-08",
    )
    decision = may_use_model(late, ORIGIN, profile=InformationProfile.STRICT_HISTORICAL)
    assert decision.verdict is Verdict.BLOCKED
    assert any("past the" in reason for reason in decision.reasons)


def test_a_derived_artifact_can_push_the_effective_cutoff_past_the_origin() -> None:
    """A 2023 model with a 2026 retrieval index has a 2026 cutoff."""
    entry = _model(derived_artifact_cutoff=datetime(2026, 7, 1, tzinfo=UTC))
    assert entry.effective_cutoff == datetime(2026, 7, 1, tzinfo=UTC)
    assert may_use_model(
        entry, ORIGIN, profile=InformationProfile.PROSPECTIVE_OBSERVED
    ).verdict is (Verdict.BLOCKED)


def test_an_undocumented_cutoff_is_unknown_not_fine() -> None:
    """Strict runs reject unknown; an engineering replay records and proceeds."""
    entry = _model(training_data_cutoff=None, cutoff_scope="")
    strict = may_use_model(entry, ORIGIN, profile=InformationProfile.STRICT_HISTORICAL)
    replay = may_use_model(entry, ORIGIN, profile=InformationProfile.ENGINEERING_REPLAY)

    assert strict.verdict is Verdict.UNKNOWN
    assert replay.verdict is Verdict.ALLOWED
    assert any("undocumented" in reason for reason in replay.reasons)


def test_a_cutoff_without_a_scope_is_refused_at_registration() -> None:
    with pytest.raises(ContractViolationError, match="without a claim"):
        ModelEntry(model_id="x", training_data_cutoff=ORIGIN)


def test_strict_history_needs_the_exact_artifact_pinned() -> None:
    """The dates can look right and still not identify the historical weights."""
    entry = _model(weights_hash="", tokenizer_hash="", config_hash="")
    decision = may_use_model(entry, ORIGIN, profile=InformationProfile.STRICT_HISTORICAL)
    assert decision.verdict is Verdict.UNKNOWN
    assert any("cannot be shown to be the historical one" in r for r in decision.reasons)


def test_a_model_released_after_the_origin_fails_a_historical_claim() -> None:
    entry = _model(release_date=datetime(2026, 8, 31, tzinfo=UTC))
    decision = may_use_model(entry, ORIGIN, profile=InformationProfile.STRICT_HISTORICAL)
    assert decision.verdict is Verdict.BLOCKED
    assert any("could not have been used then" in r for r in decision.reasons)


def test_a_licence_can_block_a_model_that_wins_on_score() -> None:
    """TimesFM-3's published terms, as the plan records them (S11)."""
    timesfm = _model(
        model_id="timesfm-3",
        weights_licence="non-commercial, non-production",
        commercial_use=False,
        operational_use=False,
    )
    research = may_use_model(
        timesfm,
        ORIGIN,
        profile=InformationProfile.ENGINEERING_REPLAY,
        intended_use=IntendedUse.RESEARCH,
    )
    operational = may_use_model(
        timesfm,
        ORIGIN,
        profile=InformationProfile.ENGINEERING_REPLAY,
        intended_use=IntendedUse.OPERATIONAL,
    )
    assert research.allowed is True
    assert operational.verdict is Verdict.BLOCKED
    assert any("operational or production" in r for r in operational.reasons)


def test_an_unregistered_model_cannot_run() -> None:
    registry = ModelRegistry(entries=(_model(),))
    assert registry.decide(
        "indictrans2", ORIGIN, profile=InformationProfile.STRICT_HISTORICAL
    ).allowed
    with pytest.raises(ContractViolationError, match="not registered"):
        registry.decide("gpt-mystery", ORIGIN, profile=InformationProfile.ENGINEERING_REPLAY)


def test_a_blocked_decision_raises_where_a_caller_asks_it_to() -> None:
    entry = _model(training_data_cutoff=datetime(2027, 1, 1, tzinfo=UTC), cutoff_scope="later")
    decision = may_use_model(entry, ORIGIN, profile=InformationProfile.PROSPECTIVE_OBSERVED)
    with pytest.raises(ContractViolationError, match="not permitted"):
        decision.raise_if_blocked()
