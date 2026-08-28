"""Run manifests: deterministic identity, and refusal to lose a record.

The two properties that matter are that a manifest's name comes from its inputs
rather than from a clock, and that writing one never destroys another. Both are
what stop a failed run from quietly disappearing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures.benchmarks.harness import (
    END,
    START,
    FakeExecutor,
    make_run,
    synthetic_contract,
    synthetic_plan,
)
from pramaanx.benchmarks.manifests import (
    ManifestExistsError,
    ManifestStore,
    build_manifest,
    classify_failure,
    manifest_digest,
)
from pramaanx.benchmarks.schemas import FailureClass, PreparedEnvironment, RawRunResult
from pramaanx.hashing import hash_text


def raw(seed: int = 11, *, exit_code: int = 0, duration: float = 300.0) -> RawRunResult:
    return RawRunResult(
        plan_hash=synthetic_plan(seeds=(seed,)).plan_hash(),
        seed=seed,
        exit_code=exit_code,
        stdout_hash=hash_text("out"),
        stderr_hash=hash_text("err"),
        started_at=START,
        finished_at=END,
        duration_seconds=duration,
    )


class TestRunIdentity:
    def test_run_id_is_deterministic_across_rebuilds(self) -> None:
        assert make_run().run_id == make_run().run_id

    def test_run_id_does_not_depend_on_wall_clock(self) -> None:
        # Two manifests with different timestamps but identical inputs must share
        # an id, or re-running would mint a fresh name and hide the collision.
        first = make_run()
        later = make_run().model_copy(update={"finished_at": END})
        assert first.run_id == later.run_id

    def test_run_id_changes_when_the_metric_code_changes(self) -> None:
        # Negative control: changing the metric code must change the identity of
        # everything downstream of it.
        contract = synthetic_contract()
        other = synthetic_contract(metric_code_hash=hash_text("different-metric-code"))
        assert synthetic_plan(contract).run_id(11) != synthetic_plan(other).run_id(11)

    def test_run_id_changes_when_the_split_changes(self) -> None:
        contract = synthetic_contract()
        other = synthetic_contract(split_hash=hash_text("different-split"))
        assert synthetic_plan(contract).run_id(11) != synthetic_plan(other).run_id(11)

    def test_manifest_hash_covers_the_parsed_metrics(self) -> None:
        base = make_run()
        changed = make_run(metrics={"average_precision": 0.9})
        assert base.manifest_hash() != changed.manifest_hash()


class TestManifestContent:
    def test_records_every_required_field(self) -> None:
        run = make_run()
        for field in (
            "run_id",
            "contract_hash",
            "contract_version",
            "official_commit",
            "dataset_hash",
            "split_hash",
            "environment_hash",
            "command",
            "seed",
            "started_at",
            "finished_at",
            "hardware_description",
            "stdout_hash",
            "stderr_hash",
            "raw_output_hashes",
            "parsed_metrics",
            "metric_code_hash",
            "package_lock_hash",
            "duration_seconds",
            "gpu_hours",
            "cpu_hours",
            "peak_memory_gb",
            "energy_estimate_method",
            "energy_estimate_kwh",
            "exit_status",
            "failure_classification",
            "artefact_hashes",
            "driver_version",
            "cuda_version",
        ):
            assert hasattr(run, field), field

    def test_records_the_energy_estimate_and_its_method(self) -> None:
        run = make_run()
        assert run.energy_estimate_kwh is not None
        assert run.energy_estimate_method

    def test_refuses_a_result_from_another_plan(self) -> None:
        plan = synthetic_plan()
        prepared = PreparedEnvironment(
            plan_hash=plan.plan_hash(),
            environment_hash=plan.environment_hash(),
            workspace="/w",
        )
        mismatched = raw().model_copy(update={"plan_hash": "sha256:" + "0" * 64})
        with pytest.raises(ValueError, match="belongs to plan"):
            build_manifest(plan, prepared, mismatched)

    def test_refuses_a_prepared_environment_from_another_plan(self) -> None:
        plan = synthetic_plan()
        prepared = PreparedEnvironment(
            plan_hash="sha256:" + "0" * 64, environment_hash="x", workspace="/w"
        )
        with pytest.raises(ValueError, match="does not belong"):
            build_manifest(plan, prepared, raw())


class TestFailureClassification:
    def test_a_clean_exit_is_not_a_failure(self) -> None:
        assert classify_failure(raw(), synthetic_plan()) is FailureClass.NONE

    def test_a_nonzero_exit_is_classified(self) -> None:
        assert classify_failure(raw(exit_code=1), synthetic_plan()) is FailureClass.NONZERO_EXIT

    def test_a_kill_signal_is_out_of_memory(self) -> None:
        assert classify_failure(raw(exit_code=137), synthetic_plan()) is (
            FailureClass.OUT_OF_MEMORY
        )

    def test_reaching_the_timeout_is_a_timeout(self) -> None:
        plan = synthetic_plan(timeout_seconds=100)
        assert classify_failure(raw(duration=100.0), plan) is FailureClass.TIMEOUT

    def test_there_is_no_flaky_classification(self) -> None:
        # A run that failed failed for a reason. An escape hatch would collect
        # every inconvenient failure.
        assert "flaky" not in {member.value for member in FailureClass}


class TestManifestStore:
    def test_writes_and_reads_back(self, tmp_path: Path) -> None:
        store = ManifestStore(tmp_path)
        run = make_run()
        path = store.write(run)
        assert path.exists()
        assert store.read(run.run_id).manifest_hash() == run.manifest_hash()

    def test_refuses_to_overwrite_an_existing_manifest(self, tmp_path: Path) -> None:
        store = ManifestStore(tmp_path)
        run = make_run()
        store.write(run)
        with pytest.raises(ManifestExistsError, match="immutable"):
            store.write(run)

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        store = ManifestStore(tmp_path)
        path = store.write(make_run(), dry_run=True)
        assert not path.exists()
        assert list(tmp_path.iterdir()) == []

    def test_a_failed_run_remains_in_the_store(self, tmp_path: Path) -> None:
        # Negative control: failures are records, not noise to be swept up.
        store = ManifestStore(tmp_path)
        failed = make_run(seed=11, exit_code=1)
        passed = make_run(seed=23)
        store.write(failed)
        store.write(passed)
        recorded = store.read_all()
        assert len(recorded) == 2
        assert any(not run.succeeded for run in recorded)

    def test_read_all_is_ordered_by_identity_not_mtime(self, tmp_path: Path) -> None:
        store = ManifestStore(tmp_path)
        runs = [make_run(seed=seed) for seed in (37, 11, 23)]
        for run in runs:
            store.write(run)
        assert [run.run_id for run in store.read_all()] == sorted(run.run_id for run in runs)

    def test_read_all_on_a_missing_directory_is_empty(self, tmp_path: Path) -> None:
        assert ManifestStore(tmp_path / "absent").read_all() == []

    def test_for_benchmark_filters(self, tmp_path: Path) -> None:
        store = ManifestStore(tmp_path)
        store.write(make_run())
        assert store.for_benchmark("synthetic_fixture")
        assert store.for_benchmark("something_else") == []

    def test_exists_reports_presence(self, tmp_path: Path) -> None:
        store = ManifestStore(tmp_path)
        run = make_run()
        assert not store.exists(run.run_id)
        store.write(run)
        assert store.exists(run.run_id)


class TestManifestDigest:
    def test_is_order_independent(self) -> None:
        runs = [make_run(seed=seed) for seed in (11, 23, 37)]
        assert manifest_digest(runs) == manifest_digest(list(reversed(runs)))

    def test_changes_when_a_run_is_dropped(self) -> None:
        runs = [make_run(seed=seed) for seed in (11, 23, 37)]
        assert manifest_digest(runs) != manifest_digest(runs[:2])


class TestFakeExecutorContract:
    def test_the_fake_executor_satisfies_the_protocol(self) -> None:
        from pramaanx.benchmarks.runner import BenchmarkExecutor

        assert isinstance(FakeExecutor(), BenchmarkExecutor)
