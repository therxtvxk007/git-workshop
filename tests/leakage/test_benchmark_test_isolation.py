"""The frozen final test: sealed before opening, invalidated by later changes.

A held-out period only means anything if it was looked at once. These tests
assert the three refusals that make that enforceable -- labels cannot be loaded,
the metric refuses to run, and selection cannot read test results -- and the two
detections that make a violation visible afterwards.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fixtures.benchmarks.harness import FIXED_HOST, FakeExecutor, synthetic_contract
from pramaanx.benchmarks.environment import EnvironmentProbe
from pramaanx.benchmarks.manifests import ManifestStore
from pramaanx.benchmarks.runner import (
    FinalTestAccessError,
    FinalTestAccessLedger,
    FinalTestLedger,
    ReproductionRunner,
    build_plan,
)
from pramaanx.benchmarks.verification import validate_contract

AUTHORISED_AT = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
FIXED_PROBE = EnvironmentProbe(fixed=FIXED_HOST)
ARTEFACTS = {"model.pt": "sha256:" + "1" * 64}
CONFIGS = {"config.yaml": "sha256:" + "2" * 64}
PROMPTS = {"system.txt": "sha256:" + "3" * 64}


def opened_ledger(contract) -> FinalTestLedger:
    ledger = FinalTestLedger()
    ledger.open_final_test(
        contract,
        authorised_by="reviewer",
        authorised_at=AUTHORISED_AT,
        reason="final evaluation",
        model_artefact_hashes=ARTEFACTS,
        config_hashes=CONFIGS,
        prompt_hashes=PROMPTS,
    )
    return ledger


class TestBeforeOpening:
    def test_test_labels_cannot_be_loaded(self) -> None:
        ledger = FinalTestLedger()
        with pytest.raises(FinalTestAccessError, match="not been opened"):
            ledger.guard_label_access(synthetic_contract(), "load test labels")

    def test_the_test_metric_command_refuses_to_run(self) -> None:
        ledger = FinalTestLedger()
        with pytest.raises(FinalTestAccessError, match="frozen test period"):
            ledger.guard_label_access(synthetic_contract(), "test metric command")

    def test_challenger_selection_cannot_read_test_results(self) -> None:
        # Refused even after opening: a selection informed by the test period is
        # the post-test tuning that invalidates a result.
        contract = synthetic_contract()
        for ledger in (FinalTestLedger(), opened_ledger(contract)):
            with pytest.raises(FinalTestAccessError, match="selection"):
                ledger.guard_selection(contract, "challenger selection")

    def test_a_run_reading_the_test_period_is_refused(self, tmp_path) -> None:
        contract = synthetic_contract()
        plan = build_plan(contract, command=["python", "-m", "x"], probe=FIXED_PROBE)
        executor = FakeExecutor()
        runner = ReproductionRunner(executor, ManifestStore(tmp_path))
        with pytest.raises(FinalTestAccessError):
            runner.run(contract, plan, reads_test_period=True)
        # The refusal happened before anything was prepared or written.
        assert executor.prepare_calls == []
        assert not list(tmp_path.iterdir())

    def test_a_recorded_test_period_result_fails_validation(self) -> None:
        from fixtures.benchmarks.harness import make_run

        contract = synthetic_contract()
        run = make_run(contract).model_copy(update={"reads_test_period": True})
        report = validate_contract(contract, [run])
        assert "test_period_sealed" in {v.rule for v in report.errors}

    def test_the_policy_starts_sealed(self) -> None:
        assert synthetic_contract().final_test_policy.opened is False


class TestOpening:
    def test_opening_records_everything_it_freezes(self) -> None:
        contract = synthetic_contract()
        ledger = opened_ledger(contract)
        authorisation = ledger.ledger.authorisation(contract.benchmark_id)
        assert authorisation is not None
        assert authorisation.model_artefact_hashes == ARTEFACTS
        assert authorisation.config_hashes == CONFIGS
        assert authorisation.prompt_hashes == PROMPTS
        assert authorisation.contract_hash == contract.contract_hash()
        assert authorisation.authorised_by == "reviewer"

    def test_opening_requires_frozen_model_artefacts(self) -> None:
        with pytest.raises(FinalTestAccessError, match="model artefact hashes"):
            FinalTestLedger().open_final_test(
                synthetic_contract(),
                authorised_by="r",
                authorised_at=AUTHORISED_AT,
                reason="x",
                model_artefact_hashes={},
                config_hashes=CONFIGS,
            )

    def test_opening_requires_frozen_configs(self) -> None:
        with pytest.raises(FinalTestAccessError, match="config hashes"):
            FinalTestLedger().open_final_test(
                synthetic_contract(),
                authorised_by="r",
                authorised_at=AUTHORISED_AT,
                reason="x",
                model_artefact_hashes=ARTEFACTS,
                config_hashes={},
            )

    def test_the_test_cannot_be_opened_twice(self) -> None:
        contract = synthetic_contract()
        ledger = opened_ledger(contract)
        with pytest.raises(FinalTestAccessError, match="already opened"):
            ledger.open_final_test(
                contract,
                authorised_by="r",
                authorised_at=AUTHORISED_AT,
                reason="again",
                model_artefact_hashes=ARTEFACTS,
                config_hashes=CONFIGS,
            )

    def test_a_dry_run_opening_records_nothing(self) -> None:
        contract = synthetic_contract()
        ledger = FinalTestLedger()
        ledger.open_final_test(
            contract,
            authorised_by="r",
            authorised_at=AUTHORISED_AT,
            reason="rehearsal",
            model_artefact_hashes=ARTEFACTS,
            config_hashes=CONFIGS,
            dry_run=True,
        )
        assert not ledger.is_open(contract)

    def test_the_authorisation_id_is_deterministic(self) -> None:
        contract = synthetic_contract()
        first = opened_ledger(contract).ledger.entries[0].authorisation_id
        second = opened_ledger(contract).ledger.entries[0].authorisation_id
        assert first == second

    def test_after_opening_labels_may_be_read(self) -> None:
        contract = synthetic_contract()
        opened_ledger(contract).guard_label_access(contract, "load test labels")

    def test_an_open_test_without_an_authorisation_record_fails_validation(self) -> None:
        contract = synthetic_contract()
        contract.final_test_policy.opened = True
        report = validate_contract(contract)
        assert "test_opening_authorised" in {v.rule for v in report.errors}


class TestPostOpeningChanges:
    def test_a_changed_model_artefact_is_detected(self) -> None:
        contract = synthetic_contract()
        ledger = opened_ledger(contract)
        changes = ledger.detect_post_test_changes(
            contract,
            model_artefact_hashes={"model.pt": "sha256:" + "f" * 64},
            config_hashes=CONFIGS,
            prompt_hashes=PROMPTS,
        )
        assert changes == ["model_artefact:model.pt"]

    def test_a_changed_config_is_detected(self) -> None:
        contract = synthetic_contract()
        changes = opened_ledger(contract).detect_post_test_changes(
            contract,
            model_artefact_hashes=ARTEFACTS,
            config_hashes={"config.yaml": "sha256:" + "e" * 64},
            prompt_hashes=PROMPTS,
        )
        assert changes == ["config:config.yaml"]

    def test_a_changed_prompt_is_detected(self) -> None:
        contract = synthetic_contract()
        changes = opened_ledger(contract).detect_post_test_changes(
            contract,
            model_artefact_hashes=ARTEFACTS,
            config_hashes=CONFIGS,
            prompt_hashes={"system.txt": "sha256:" + "d" * 64},
        )
        assert changes == ["prompt:system.txt"]

    def test_an_added_artefact_is_detected(self) -> None:
        contract = synthetic_contract()
        changes = opened_ledger(contract).detect_post_test_changes(
            contract,
            model_artefact_hashes={**ARTEFACTS, "adapter.pt": "sha256:" + "c" * 64},
            config_hashes=CONFIGS,
            prompt_hashes=PROMPTS,
        )
        assert "model_artefact:adapter.pt" in changes

    def test_a_changed_contract_is_detected(self) -> None:
        contract = synthetic_contract()
        ledger = opened_ledger(contract)
        changed = synthetic_contract(data_version="2.0.0")
        changes = ledger.detect_post_test_changes(
            changed,
            model_artefact_hashes=ARTEFACTS,
            config_hashes=CONFIGS,
            prompt_hashes=PROMPTS,
        )
        assert "contract" in changes

    def test_no_change_is_detected_when_nothing_moved(self) -> None:
        contract = synthetic_contract()
        assert (
            opened_ledger(contract).detect_post_test_changes(
                contract,
                model_artefact_hashes=ARTEFACTS,
                config_hashes=CONFIGS,
                prompt_hashes=PROMPTS,
            )
            == []
        )

    def test_nothing_is_detected_for_a_test_never_opened(self) -> None:
        assert (
            FinalTestLedger().detect_post_test_changes(
                synthetic_contract(),
                model_artefact_hashes={"x": "y"},
                config_hashes={},
            )
            == []
        )

    def test_post_test_changes_invalidate_the_result(self) -> None:
        from fixtures.benchmarks.harness import make_run
        from pramaanx.benchmarks.schemas import BenchmarkStatus

        contract = synthetic_contract()
        run = make_run(contract).model_copy(
            update={"post_test_changes": ["model_artefact:model.pt"]}
        )
        report = validate_contract(contract, [run])
        assert report.permitted_status is BenchmarkStatus.INVALIDATED


class TestLedger:
    def test_an_empty_ledger_is_closed(self) -> None:
        assert FinalTestAccessLedger().is_open("anything") is False
        assert FinalTestAccessLedger().authorisation("anything") is None

    def test_entries_are_scoped_by_benchmark(self) -> None:
        contract = synthetic_contract()
        ledger = opened_ledger(contract)
        assert ledger.ledger.is_open(contract.benchmark_id)
        assert not ledger.ledger.is_open("some_other_benchmark")

    def test_the_frozen_state_hash_changes_with_the_artefacts(self) -> None:
        contract = synthetic_contract()
        authorisation = opened_ledger(contract).ledger.entries[0]
        other = authorisation.model_copy(
            update={"model_artefact_hashes": {"model.pt": "sha256:" + "0" * 64}}
        )
        assert authorisation.frozen_state_hash() != other.frozen_state_hash()
