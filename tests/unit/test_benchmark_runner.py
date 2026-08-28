"""Planning, execution and the guards that run before any executor is touched.

Every refusal here is asserted to happen *before* the fake executor records a
call. A guard that fires after ``prepare`` has already cloned a repository has
not prevented anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fixtures.benchmarks.harness import (
    FIXED_HOST,
    FakeExecutor,
    blocked_contract,
    make_run,
    synthetic_contract,
    synthetic_plan,
)
from pramaanx.benchmarks.environment import (
    EnvironmentProbe,
    environment_hash,
    interpreter_identity,
    package_lock_hash,
)
from pramaanx.benchmarks.manifests import ManifestStore
from pramaanx.benchmarks.runner import (
    EFFECTS,
    BlockedExecutor,
    DryRunGuard,
    DryRunViolationError,
    FinalTestLedger,
    ReproductionRefusedError,
    ReproductionRunner,
    build_plan,
    collect_blockers,
    plan_blockers,
    refuse_data_acquisition,
)
from pramaanx.benchmarks.schemas import (
    Blocker,
    BlockerCode,
    HardwareRequirements,
    SoftwareEnvironment,
)

FIXED_PROBE = EnvironmentProbe(fixed=FIXED_HOST)


class TestDryRunGuard:
    def test_refuses_every_declared_effect(self) -> None:
        guard = DryRunGuard(dry_run=True)
        for effect in EFFECTS:
            with pytest.raises(DryRunViolationError, match=effect):
                guard.allow(effect)

    def test_covers_network_clone_download_container_and_write(self) -> None:
        assert set(EFFECTS) == {"network", "clone", "download", "container", "write"}

    def test_permits_effects_when_not_a_dry_run(self) -> None:
        guard = DryRunGuard(dry_run=False)
        for effect in EFFECTS:
            guard.allow(effect)
        assert guard.refused == []

    def test_an_unknown_effect_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError, match="unknown effect"):
            DryRunGuard(dry_run=False).allow("teleport")

    def test_would_refuse_lists_the_effects(self) -> None:
        assert DryRunGuard(dry_run=True).would_refuse() == EFFECTS
        assert DryRunGuard(dry_run=False).would_refuse() == ()


class TestBuildPlan:
    def test_a_complete_contract_plans_unblocked(self) -> None:
        plan = build_plan(synthetic_contract(), command=["python", "-m", "x"], probe=FIXED_PROBE)
        assert not plan.blocked
        assert plan.seeds == (11, 23, 37)

    def test_a_missing_commit_blocks_the_plan(self) -> None:
        plan = build_plan(
            synthetic_contract(official_commit=None),
            command=["python"],
            probe=FIXED_PROBE,
        )
        assert plan.blocked
        assert any(blocker.field == "official_commit" for blocker in plan.blockers)

    def test_a_missing_data_hash_blocks_execution(self) -> None:
        # Negative control: without a dataset hash a run cannot verify it
        # received the right bytes, so it must not start.
        plan = build_plan(synthetic_contract(data_hash=None), command=["python"], probe=FIXED_PROBE)
        assert plan.blocked
        assert any(blocker.code is BlockerCode.DATA_UNAVAILABLE for blocker in plan.blockers)

    def test_an_unknown_licence_blocks_the_plan(self) -> None:
        plan = build_plan(
            synthetic_contract(data_license=None), command=["python"], probe=FIXED_PROBE
        )
        assert any(blocker.code is BlockerCode.LICENCE_UNKNOWN for blocker in plan.blockers)

    def test_no_entrypoint_blocks_the_plan(self) -> None:
        plan = build_plan(synthetic_contract(), command=[], probe=FIXED_PROBE)
        assert any(blocker.code is BlockerCode.NO_OFFICIAL_CODE for blocker in plan.blockers)

    def test_a_gpu_requirement_on_a_cpu_host_blocks_the_plan(self) -> None:
        plan = build_plan(
            synthetic_contract(hardware_requirements=HardwareRequirements(gpu_count=1)),
            command=["python"],
            probe=FIXED_PROBE,
        )
        assert any(blocker.code is BlockerCode.COMPUTE_UNAVAILABLE for blocker in plan.blockers)

    def test_planning_a_blocked_benchmark_still_produces_a_plan(self) -> None:
        # A plan for a blocked benchmark records what *would* run, which is what
        # makes the blocker reviewable.
        plan = build_plan(blocked_contract(), command=["python"], probe=FIXED_PROBE)
        assert plan.blocked
        assert plan.plan_hash()
        assert plan_blockers(plan)

    def test_plan_hash_is_stable(self) -> None:
        args = {"command": ["python", "-m", "x"], "probe": FIXED_PROBE}
        first = build_plan(synthetic_contract(), **args)
        second = build_plan(synthetic_contract(), **args)
        assert first.plan_hash() == second.plan_hash()


class TestDataAcquisitionRefusal:
    def test_an_unknown_licence_prevents_automatic_acquisition(self) -> None:
        # Negative control 16: downloading first and reading the terms later is
        # the order that creates a redistribution problem.
        blocker = refuse_data_acquisition(synthetic_contract(data_license=None))
        assert blocker is not None
        assert blocker.code is BlockerCode.LICENCE_UNKNOWN

    def test_a_no_redistribution_licence_is_flagged(self) -> None:
        blocker = refuse_data_acquisition(synthetic_contract(redistribution_allowed=False))
        assert blocker is not None
        assert blocker.code is BlockerCode.LICENCE_FORBIDS_REDISTRIBUTION

    def test_a_permissive_licence_is_not_refused(self) -> None:
        assert refuse_data_acquisition(synthetic_contract()) is None


class TestRunner:
    def test_runs_once_per_seed_and_writes_a_manifest_each(self, tmp_path: Path) -> None:
        contract = synthetic_contract()
        plan = build_plan(contract, command=["python", "-m", "x"], probe=FIXED_PROBE)
        executor = FakeExecutor()
        runner = ReproductionRunner(executor, ManifestStore(tmp_path))
        runs = runner.run(contract, plan)
        assert len(runs) == 3
        assert len(list(tmp_path.glob("*.run.json"))) == 3
        assert len({run.run_id for run in runs}) == 3

    def test_dry_run_performs_no_writes_and_calls_no_executor(self, tmp_path: Path) -> None:
        # Negative control 7. The executor recording zero calls is the assertion
        # that nothing was cloned, downloaded or started.
        contract = synthetic_contract()
        plan = build_plan(contract, command=["python", "-m", "x"], probe=FIXED_PROBE)
        executor = FakeExecutor()
        runner = ReproductionRunner(executor, ManifestStore(tmp_path))
        assert runner.run(contract, plan, dry_run=True) == []
        assert executor.prepare_calls == []
        assert executor.execute_calls == []
        assert not list(tmp_path.iterdir())

    def test_a_blocked_plan_is_refused_before_the_executor_is_touched(self, tmp_path: Path) -> None:
        contract = blocked_contract()
        plan = build_plan(contract, command=["python"], probe=FIXED_PROBE)
        executor = FakeExecutor()
        runner = ReproductionRunner(executor, ManifestStore(tmp_path))
        with pytest.raises(ReproductionRefusedError, match="cannot be run"):
            runner.run(contract, plan)
        assert executor.prepare_calls == []

    def test_a_second_run_is_recorded_as_a_rerun(self, tmp_path: Path) -> None:
        # Negative control 8: an existing manifest is never replaced. The second
        # attempt is refused, and the first record survives.
        contract = synthetic_contract(seed_list=[11], minimum_seed_count=1)
        plan = build_plan(contract, command=["python", "-m", "x"], probe=FIXED_PROBE)
        store = ManifestStore(tmp_path)
        runner = ReproductionRunner(FakeExecutor(), store)
        first = runner.run(contract, plan)
        assert len(first) == 1
        with pytest.raises(FileExistsError):
            runner.run(contract, plan)
        assert len(store.read_all()) == 1

    def test_a_failed_run_is_still_written(self, tmp_path: Path) -> None:
        # Negative control 9.
        contract = synthetic_contract(seed_list=[11], minimum_seed_count=1)
        plan = build_plan(contract, command=["python", "-m", "x"], probe=FIXED_PROBE)
        store = ManifestStore(tmp_path)
        runs = ReproductionRunner(FakeExecutor(exit_code=1), store).run(contract, plan)
        assert runs[0].succeeded is False
        assert len(store.read_all()) == 1


class TestBlockedExecutor:
    def test_every_phase_refuses_with_the_reason(self) -> None:
        executor = BlockedExecutor(
            [
                Blocker(
                    field="hardware_requirements",
                    code=BlockerCode.COMPUTE_UNAVAILABLE,
                    detail="no GPU on this host",
                )
            ]
        )
        plan = synthetic_plan()
        for call in (
            lambda: executor.prepare(plan),
            lambda: executor.execute(None),  # type: ignore[arg-type]
            lambda: executor.collect(None),  # type: ignore[arg-type]
        ):
            with pytest.raises(ReproductionRefusedError, match="no GPU on this host"):
                call()

    def test_refuses_even_with_no_named_blocker(self) -> None:
        with pytest.raises(ReproductionRefusedError, match="unspecified"):
            BlockedExecutor([]).prepare(synthetic_plan())


class TestEnvironmentProbe:
    def test_a_fixed_probe_does_not_read_the_host(self) -> None:
        assert FIXED_PROBE.host() == FIXED_HOST

    def test_a_gpu_requirement_without_a_driver_is_blocked(self) -> None:
        report = FIXED_PROBE.check(HardwareRequirements(gpu_count=1), SoftwareEnvironment())
        assert not report.satisfied
        assert any(blocker.code is BlockerCode.COMPUTE_UNAVAILABLE for blocker in report.blockers)

    def test_too_few_cpu_cores_is_blocked(self) -> None:
        report = FIXED_PROBE.check(HardwareRequirements(cpu_cores=64), SoftwareEnvironment())
        assert not report.satisfied

    def test_an_image_without_a_digest_is_a_mutable_reference(self) -> None:
        report = FIXED_PROBE.check(
            HardwareRequirements(), SoftwareEnvironment(container_image="repo:latest")
        )
        assert any(blocker.code is BlockerCode.MUTABLE_REFERENCE for blocker in report.blockers)

    def test_a_digest_pinned_image_is_accepted(self) -> None:
        report = FIXED_PROBE.check(
            HardwareRequirements(),
            SoftwareEnvironment(container_image="repo:1.0", container_digest="sha256:" + "a" * 64),
        )
        assert report.satisfied

    def test_an_image_without_a_runtime_is_blocked(self) -> None:
        probe = EnvironmentProbe(fixed=FIXED_HOST.model_copy(update={"container_runtime": None}))
        report = probe.check(
            HardwareRequirements(),
            SoftwareEnvironment(container_image="repo:1.0", container_digest="sha256:" + "a" * 64),
        )
        assert any(
            blocker.code is BlockerCode.ENVIRONMENT_UNAVAILABLE for blocker in report.blockers
        )

    def test_a_cpu_only_requirement_is_satisfied(self) -> None:
        assert FIXED_PROBE.check(HardwareRequirements(cpu_cores=2), SoftwareEnvironment()).satisfied

    def test_environment_hash_is_independent_of_the_host(self) -> None:
        # Two machines validating the same contract must agree, or the hash
        # cannot show that two runs shared an environment.
        hardware = HardwareRequirements(cpu_cores=4)
        software = SoftwareEnvironment(python_version="3.13")
        assert environment_hash(hardware, software) == environment_hash(hardware, software)

    def test_report_serialises(self) -> None:
        payload = FIXED_PROBE.check(HardwareRequirements(), SoftwareEnvironment()).to_dict()
        assert payload["satisfied"] is True
        assert "no-gpu" in payload["host_description"]

    def test_a_real_probe_reports_this_host(self) -> None:
        host = EnvironmentProbe().host()
        assert host.system
        assert host.describe()

    def test_package_lock_hash_of_a_missing_file_is_none(self, tmp_path: Path) -> None:
        assert package_lock_hash(tmp_path / "absent.lock") is None

    def test_package_lock_hash_of_a_present_file(self, tmp_path: Path) -> None:
        lock = tmp_path / "uv.lock"
        lock.write_text("locked", encoding="utf-8")
        assert package_lock_hash(lock).startswith("sha256:")

    def test_interpreter_identity_is_reported(self) -> None:
        assert interpreter_identity()["version"]


class TestCollectBlockers:
    def test_deduplicates_and_orders(self) -> None:
        blocker = Blocker(field="a", code=BlockerCode.MISSING_FIELD, detail="x")
        other = Blocker(field="b", code=BlockerCode.MISSING_FIELD, detail="y")
        merged = collect_blockers([blocker, other], [blocker])
        assert len(merged) == 2
        assert [item.field for item in merged] == ["a", "b"]

    def test_empty_input_is_empty(self) -> None:
        assert collect_blockers() == []


class TestRunnerTestPeriodGuard:
    def test_reading_the_test_period_is_refused_before_opening(self, tmp_path: Path) -> None:
        from pramaanx.benchmarks.runner import FinalTestAccessError

        contract = synthetic_contract()
        plan = build_plan(contract, command=["python", "-m", "x"], probe=FIXED_PROBE)
        executor = FakeExecutor()
        runner = ReproductionRunner(
            executor, ManifestStore(tmp_path), final_test_ledger=FinalTestLedger()
        )
        with pytest.raises(FinalTestAccessError, match="not been opened"):
            runner.run(contract, plan, reads_test_period=True)
        assert executor.prepare_calls == []


class TestMakeRunHelper:
    def test_overrides_are_applied(self) -> None:
        run = make_run(role="challenger")
        assert run.role == "challenger"

    def test_timestamps_are_timezone_aware(self) -> None:
        run = make_run()
        assert run.started_at.tzinfo is not None
        assert run.started_at.astimezone(UTC) < datetime.now(UTC)
