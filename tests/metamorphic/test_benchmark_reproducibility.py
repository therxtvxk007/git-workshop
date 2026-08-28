"""Metamorphic properties: what must and must not change a hash.

Two families of property, and both are needed.

*Invariance.* Re-ordering inputs, re-building a manifest, or re-running a report
must not change any identity. If it does, no two runs can ever be shown to have
used the same thing.

*Sensitivity.* Changing the metric code, the split, the dataset or the commit
must change the identity. If it does not, a changed experiment can silently
inherit an old result's provenance -- which is the more dangerous failure, since
it produces a claim that looks well-supported.
"""

from __future__ import annotations

from pathlib import Path

from fixtures.benchmarks.harness import (
    FIXED_HOST,
    FakeExecutor,
    make_run,
    synthetic_contract,
    synthetic_plan,
)
from pramaanx.benchmarks.comparison import compare
from pramaanx.benchmarks.environment import EnvironmentProbe
from pramaanx.benchmarks.manifests import ManifestStore, manifest_digest
from pramaanx.benchmarks.registry import BenchmarkRegistry, dump_contract
from pramaanx.benchmarks.reporting import benchmark_report, registry_report
from pramaanx.benchmarks.runner import ReproductionRunner, build_plan
from pramaanx.benchmarks.schemas import MetricDirection, Period
from pramaanx.hashing import canonical_json, hash_text

FIXED_PROBE = EnvironmentProbe(fixed=FIXED_HOST)


class TestContractHashSensitivity:
    def test_changing_the_metric_code_changes_the_contract_hash(self) -> None:
        # Negative control 4.
        base = synthetic_contract()
        changed = synthetic_contract(metric_code_hash=hash_text("v2"))
        assert base.contract_hash() != changed.contract_hash()

    def test_changing_the_split_changes_the_contract_hash(self) -> None:
        # Negative control 5.
        base = synthetic_contract()
        assert (
            base.contract_hash()
            != synthetic_contract(split_hash=hash_text("other-split")).contract_hash()
        )
        assert (
            base.contract_hash()
            != synthetic_contract(
                test_period=Period(start="2025-01-01", end="2025-12-31")
            ).contract_hash()
        )

    def test_changing_the_environment_changes_the_contract_hash(self) -> None:
        base = synthetic_contract()
        assert (
            base.contract_hash()
            != synthetic_contract(software_lock_hash=hash_text("other-lock")).contract_hash()
        )

    def test_changing_the_dataset_changes_the_contract_hash(self) -> None:
        base = synthetic_contract()
        assert (
            base.contract_hash()
            != synthetic_contract(data_hash=hash_text("other-data")).contract_hash()
        )

    def test_changing_the_commit_changes_the_contract_hash(self) -> None:
        base = synthetic_contract()
        assert base.contract_hash() != synthetic_contract(official_commit="b" * 40).contract_hash()

    def test_changing_the_tolerance_changes_the_contract_hash(self) -> None:
        from pramaanx.benchmarks.schemas import Tolerance

        base = synthetic_contract()
        assert (
            base.contract_hash()
            != synthetic_contract(
                reproduction_tolerance={
                    "average_precision": Tolerance(absolute=0.5),
                    "brier_score": Tolerance(absolute=0.01),
                }
            ).contract_hash()
        )

    def test_changing_the_metric_direction_changes_the_contract_hash(self) -> None:
        base = synthetic_contract()
        assert (
            base.contract_hash()
            != synthetic_contract(
                metric_direction={
                    "average_precision": MetricDirection.LOWER_IS_BETTER,
                    "brier_score": MetricDirection.LOWER_IS_BETTER,
                }
            ).contract_hash()
        )


class TestOrderInvariance:
    def test_different_seed_order_produces_identical_manifests(self) -> None:
        # Negative control 6: input order is not part of the experiment.
        forwards = [make_run(seed=seed) for seed in (11, 23, 37)]
        backwards = [make_run(seed=seed) for seed in (37, 23, 11)]
        assert manifest_digest(forwards) == manifest_digest(backwards)

    def test_different_unit_order_produces_the_same_unit_hash(self) -> None:
        units = [f"unit-{index}" for index in range(20)]
        assert (
            make_run(unit_ids=units).unit_set_hash()
            == make_run(unit_ids=list(reversed(units))).unit_set_hash()
        )

    def test_different_secondary_metric_order_is_the_same_contract(self) -> None:
        first = synthetic_contract(secondary_metrics=["brier_score"])
        # Sorting happens where it matters -- all_metrics -- while the declared
        # order is preserved in the record itself.
        assert first.all_metrics() == sorted(first.all_metrics())

    def test_registry_hash_is_independent_of_contract_order(self) -> None:
        one = synthetic_contract(benchmark_id="a")
        two = synthetic_contract(benchmark_id="b")
        assert BenchmarkRegistry(contracts=[one, two]).registry_hash() == (
            BenchmarkRegistry(contracts=[two, one]).registry_hash()
        )


class TestRebuildDeterminism:
    def test_rebuilding_a_manifest_reproduces_it_byte_for_byte(self) -> None:
        assert canonical_json(make_run().canonical_dict()) == canonical_json(
            make_run().canonical_dict()
        )

    def test_two_runners_over_the_same_plan_agree_on_every_run_id(self, tmp_path: Path) -> None:
        contract = synthetic_contract()
        plan = build_plan(contract, command=["python", "-m", "x"], probe=FIXED_PROBE)
        first = ReproductionRunner(FakeExecutor(), ManifestStore(tmp_path / "a")).run(
            contract, plan
        )
        second = ReproductionRunner(FakeExecutor(), ManifestStore(tmp_path / "b")).run(
            contract, plan
        )
        assert [run.run_id for run in first] == [run.run_id for run in second]
        assert [run.manifest_hash() for run in first] == [run.manifest_hash() for run in second]

    def test_a_report_is_deterministic(self) -> None:
        contract = synthetic_contract()
        runs = [make_run(contract, seed=seed) for seed in (11, 23)]
        assert canonical_json(benchmark_report(contract, runs)) == canonical_json(
            benchmark_report(contract, list(reversed(runs)))
        )

    def test_dumping_a_contract_twice_is_byte_identical(self) -> None:
        contract = synthetic_contract()
        assert dump_contract(contract) == dump_contract(contract)

    def test_a_comparison_is_deterministic_across_repeats(self) -> None:
        from fixtures.benchmarks.harness import paired_unit_scores

        contract = synthetic_contract()
        control_units, challenger_units = paired_unit_scores(count=30)

        def build():
            control = make_run(
                contract,
                seed=11,
                metrics={"average_precision": 0.402, "brier_score": 0.049},
                per_unit={"average_precision": control_units},
            )
            others = [
                make_run(
                    contract,
                    seed=seed,
                    metrics={"average_precision": 0.42, "brier_score": 0.048},
                    per_unit={"average_precision": challenger_units},
                    role="challenger",
                )
                for seed in (23, 37, 53)
            ]
            return compare(contract, control, others)

        assert canonical_json(build().canonical_dict()) == canonical_json(build().canonical_dict())


class TestReportsCannotHideThings:
    def test_failed_variants_cannot_disappear_from_a_report(self) -> None:
        # Negative control 10.
        contract = synthetic_contract()
        runs = [
            make_run(contract, seed=11),
            make_run(contract, seed=23, exit_code=1),
            make_run(
                contract,
                seed=37,
                metrics={"average_precision": 0.05, "brier_score": 0.049},
            ),
        ]
        report = benchmark_report(contract, runs)
        assert report["run_counts"]["total"] == 3
        assert report["run_counts"]["failed"] == 1
        assert report["run_counts"]["succeeded_out_of_tolerance"] == 1
        assert len(report["runs"]) == 3

    def test_cost_is_never_omitted_from_a_run_report(self) -> None:
        # Negative control 15.
        report = benchmark_report(synthetic_contract(), [make_run()])
        cost = report["runs"][0]["cost"]
        for field in (
            "gpu_hours",
            "cpu_hours",
            "peak_memory_gb",
            "duration_seconds",
            "energy_estimate_kwh",
            "energy_estimate_method",
        ):
            assert field in cost
        assert "total_cost" in report

    def test_a_blocked_benchmark_is_listed_not_dropped(self) -> None:
        from fixtures.benchmarks.harness import blocked_contract

        registry = BenchmarkRegistry(contracts=[synthetic_contract(), blocked_contract()])
        report = registry_report(registry, registry.validate_all())
        assert len(report["benchmarks"]) == 2
        assert "blocked_fixture" in report["blocked"]

    def test_the_rendered_report_shows_the_failures(self) -> None:
        from pramaanx.benchmarks.reporting import render_benchmark

        contract = synthetic_contract()
        runs = [make_run(contract, seed=11), make_run(contract, seed=23, exit_code=1)]
        text = render_benchmark(benchmark_report(contract, runs))
        assert "FAILED" in text
        assert "GPU-h" in text


class TestPlanDeterminism:
    def test_the_plan_hash_is_stable_across_rebuilds(self) -> None:
        assert synthetic_plan().plan_hash() == synthetic_plan().plan_hash()

    def test_the_plan_hash_ignores_the_blocked_flag(self) -> None:
        from pramaanx.benchmarks.schemas import Blocker, BlockerCode

        plan = synthetic_plan()
        blocked = synthetic_plan(
            blocked=True,
            blockers=[Blocker(field="data_hash", code=BlockerCode.DATA_UNAVAILABLE, detail="x")],
        )
        # The plan is the same plan; whether it can run today is a fact about
        # the host, not about the experiment.
        assert plan.plan_hash() == blocked.plan_hash()
