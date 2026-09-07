"""Role assignment, purge, and a block that opens once."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from pramaanx.clock import FixedClock
from pramaanx.core.contexts import OriginRole
from pramaanx.core.errors import ContractViolationError
from pramaanx.panel.windows import CalendarContract, monthly_origins
from pramaanx.protocol.lockbox import Lockbox, LockboxSeal, RoleSeparation
from pramaanx.protocol.splitter import SplitManifest, check_purge, chronological_split

IST = CalendarContract(timezone="Asia/Kolkata")
ORIGINS = monthly_origins(date(2024, 1, 1), date(2025, 12, 1), calendar=IST)
NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _split(**overrides: object) -> SplitManifest:
    base: dict[str, object] = {
        "select_from": IST.instant(date(2025, 1, 1)),
        "calibrate_from": IST.instant(date(2025, 5, 1)),
        "retro_test_from": IST.instant(date(2025, 8, 1)),
        "prospective_from": IST.instant(date(2025, 11, 1)),
        "window_days": 30,
        "maturation_days": 14,
    }
    base.update(overrides)
    return chronological_split(ORIGINS, **base)  # type: ignore[arg-type]


# -- role assignment -------------------------------------------------------
def test_every_origin_gets_exactly_one_role() -> None:
    manifest = _split()
    assert len(manifest.roles) == len(ORIGINS)
    counted = sum(len(manifest.origins_with(role)) for role in OriginRole)
    assert counted == len(ORIGINS)


def test_roles_follow_the_preregistered_date_bands() -> None:
    manifest = _split()
    assert manifest.role_of(IST.instant(date(2024, 6, 1))) is OriginRole.TRAIN
    assert manifest.role_of(IST.instant(date(2025, 2, 1))) is OriginRole.SELECT
    assert manifest.role_of(IST.instant(date(2025, 6, 1))) is OriginRole.CALIBRATE
    assert manifest.role_of(IST.instant(date(2025, 9, 1))) is OriginRole.RETRO_TEST
    assert manifest.role_of(IST.instant(date(2025, 12, 1))) is OriginRole.PROSPECTIVE


def test_boundaries_out_of_order_are_refused() -> None:
    with pytest.raises(ContractViolationError, match="chronological order"):
        _split(calibrate_from=IST.instant(date(2024, 1, 1)))


def test_a_role_map_that_does_not_cover_the_origins_is_refused() -> None:
    with pytest.raises(ContractViolationError, match="does not cover the origins"):
        SplitManifest(origins=ORIGINS[:3], roles={}, window_days=30, maturation_days=14)


# -- purge -----------------------------------------------------------------
def test_a_label_whose_window_has_not_closed_is_purged() -> None:
    """The invariant: window plus maturation must fit before the fit cutoff."""
    manifest = _split()
    issue = IST.instant(date(2025, 1, 1))
    purged = manifest.purged_for(issue)

    assert purged
    for origin in purged:
        assert manifest.label_settled_at(origin) > issue
    for origin in manifest.training_origins_for(issue):
        assert manifest.label_settled_at(origin) <= issue
    check_purge(manifest, issue_time=issue)


def test_purge_follows_the_window_rather_than_a_row_count() -> None:
    """A longer window purges more origins, which a fixed row count would not."""
    issue = IST.instant(date(2025, 1, 1))
    short = _split(window_days=7, maturation_days=0).purged_for(issue)
    long = _split(window_days=90, maturation_days=30).purged_for(issue)
    assert len(long) > len(short)


def test_a_selection_origin_does_not_become_training_data_by_ageing() -> None:
    """Without walk_forward, a role band is not a waiting room (S33.1)."""
    manifest = _split()
    late = IST.instant(date(2025, 12, 1))
    training = manifest.training_origins_for(late)
    assert all(manifest.role_of(origin) is OriginRole.TRAIN for origin in training)


def test_walk_forward_is_a_declared_choice_not_an_inference() -> None:
    manifest = _split(walk_forward=True)
    late = IST.instant(date(2025, 12, 1))
    roles = {manifest.role_of(origin) for origin in manifest.training_origins_for(late)}
    assert OriginRole.SELECT in roles
    assert manifest.walk_forward is True


def test_the_manifest_identity_changes_with_the_protocol() -> None:
    assert _split().identity() != _split(maturation_days=30).identity()
    assert _split().identity() != _split(walk_forward=True).identity()
    assert _split().identity() == _split().identity()


# -- the lockbox -----------------------------------------------------------
@pytest.fixture
def lockbox(tmp_path: Path) -> Lockbox:
    return Lockbox(tmp_path / "lockbox", clock=FixedClock(NOW))


def _seal(lockbox: Lockbox) -> LockboxSeal:
    return lockbox.seal(
        "retro-2025",
        origins=ORIGINS[-4:],
        evaluation_contract="sha256:evaluation",
        permitted_models=("ladder.hist12", "ladder.zero"),
    )


def test_a_sealed_block_opens_once(lockbox: Lockbox) -> None:
    _seal(lockbox)
    first = lockbox.open("retro-2025", run_id="run-a")
    assert first.run_id == "run-a"

    with pytest.raises(ContractViolationError, match="already opened by another run"):
        lockbox.open("retro-2025", run_id="run-b")


def test_the_owning_run_may_resume_a_failed_opening(lockbox: Lockbox) -> None:
    """A crash between authorisation and the report must not burn the one
    opportunity (S33.2)."""
    _seal(lockbox)
    first = lockbox.open("retro-2025", run_id="run-a")
    resumed = lockbox.open("retro-2025", run_id="run-a")
    assert resumed.opened_at == first.opened_at


def test_a_modified_block_fails_its_seal(lockbox: Lockbox) -> None:
    seal = _seal(lockbox)
    tampered = seal.model_copy(update={"evaluation_contract": "sha256:something-else"})
    with pytest.raises(ContractViolationError, match="does not match its contents"):
        tampered.verify()


def test_re_sealing_a_block_is_refused(lockbox: Lockbox) -> None:
    _seal(lockbox)
    with pytest.raises(ContractViolationError, match="already sealed"):
        _seal(lockbox)


def test_a_model_absent_from_the_seal_cannot_be_added_later(lockbox: Lockbox) -> None:
    """The substance of 'no later tuning'."""
    _seal(lockbox)
    assert lockbox.permits("retro-2025", "ladder.hist12") is True
    assert lockbox.permits("retro-2025", "challengers.tft") is False


def test_a_second_report_against_one_opening_is_refused(lockbox: Lockbox) -> None:
    _seal(lockbox)
    lockbox.record_report("retro-2025", run_id="run-a", report_hash="sha256:report")
    again = lockbox.record_report("retro-2025", run_id="run-a", report_hash="sha256:report")
    assert again.report_hash == "sha256:report"

    with pytest.raises(ContractViolationError, match="different report"):
        lockbox.record_report("retro-2025", run_id="run-a", report_hash="sha256:other")


def test_the_manifest_lists_what_is_sealed_and_what_is_open(lockbox: Lockbox) -> None:
    _seal(lockbox)
    assert lockbox.manifest() == {"lockboxes": [{"name": "retro-2025", "opened": False}]}
    lockbox.open("retro-2025", run_id="run-a")
    entry = lockbox.manifest()["lockboxes"][0]  # type: ignore[index]
    assert entry == {"name": "retro-2025", "opened": True, "opened_by": "run-a"}


def test_opening_an_unsealed_block_is_refused(lockbox: Lockbox) -> None:
    with pytest.raises(ContractViolationError, match="no such lockbox"):
        lockbox.open("nothing-here", run_id="run-a")


# -- calibration origins stay disjoint ------------------------------------
def test_calibration_origins_must_not_overlap_selection_or_test() -> None:
    """Calibration on the test origins is calibration on the answer (S13)."""
    manifest = _split()
    separation = RoleSeparation(
        select_origins=manifest.origins_with(OriginRole.SELECT),
        calibrate_origins=manifest.origins_with(OriginRole.CALIBRATE),
        test_origins=manifest.origins_with(OriginRole.RETRO_TEST),
    )
    separation.check_disjoint()

    with pytest.raises(ContractViolationError, match="overlap across roles"):
        RoleSeparation(
            select_origins=manifest.origins_with(OriginRole.SELECT),
            calibrate_origins=manifest.origins_with(OriginRole.SELECT),
            test_origins=manifest.origins_with(OriginRole.RETRO_TEST),
        ).check_disjoint()
