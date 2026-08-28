"""Deterministic builders and a fake executor for the benchmark tests.

Nothing here runs a third party's benchmark code, and nothing here downloads
anything. The fake executor returns canned results, which is the only honest way
to unit-test a harness whose whole purpose is refusing to make claims it cannot
support: a test that actually reproduced HydraNet would be a reproduction, and
this suite must not be able to be mistaken for one.

Everything is deterministic. Timestamps are fixed constants rather than
``datetime.now``, so a manifest built twice is byte-identical and the
reproducibility tests are testing the harness rather than the clock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pramaanx.benchmarks.environment import HostDescription
from pramaanx.benchmarks.manifests import build_manifest
from pramaanx.benchmarks.schemas import (
    BenchmarkContract,
    BenchmarkStatus,
    Blocker,
    BlockerCode,
    ConfidenceMethod,
    CostBudget,
    HardwareRequirements,
    MetricDirection,
    PairedTest,
    Period,
    PreparedEnvironment,
    PublishedScore,
    RawRunResult,
    ReproductionPlan,
    ReproductionRun,
    ScoreScale,
    SoftwareEnvironment,
    SourceKind,
    SourceReference,
    Tolerance,
)
from pramaanx.hashing import hash_text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

START = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
END = datetime(2026, 3, 1, 12, 5, tzinfo=UTC)
COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40

FIXED_HOST = HostDescription(
    system="Linux",
    machine="x86_64",
    python_version="3.13.0",
    container_runtime="docker",
    nvidia_driver_version=None,
    gpu_present=False,
    cpu_count=8,
)
"""A fixed host, so environment hashes in tests never depend on the CI runner."""


def synthetic_contract(**overrides: object) -> BenchmarkContract:
    """A complete, valid contract over a synthetic benchmark.

    Complete on purpose: most tests need a contract that passes validation so
    that the one rule under test is the only thing that can fail. The benchmark
    it describes does not exist, which is stated in its notes so that no report
    built from it can be mistaken for a real reproduction.
    """
    defaults: dict[str, object] = {
        "benchmark_id": "synthetic_fixture",
        "task_name": "synthetic occurrence forecasting (fixture only)",
        "benchmark_family": "fixture",
        "paper_title": "A Synthetic Benchmark That Does Not Exist",
        "paper_reference": SourceReference(
            kind=SourceKind.PAPER,
            citation="fixture; no such paper exists",
            url="https://example.invalid/paper",
            identifier="fixture:0001",
        ),
        "official_repository": "https://github.com/example/fixture",
        "official_commit": COMMIT,
        "official_release_or_tag": "v1.0.0",
        "official_code_hash": hash_text("fixture-code"),
        "data_name": "fixture-data",
        "data_version": "1.0.0",
        "data_hash": hash_text("fixture-data"),
        "data_license": "CC BY 4.0",
        "redistribution_allowed": True,
        "target_definition": "binary occurrence in a fixture cell-month",
        "forecast_horizon": "30 days",
        "spatial_unit": "fixture cell",
        "temporal_unit": "month",
        "training_period": Period(start="2020-01-01", end="2022-12-31"),
        "validation_period": Period(start="2023-01-01", end="2023-06-30"),
        "calibration_period": Period(start="2023-07-01", end="2023-12-31"),
        "test_period": Period(start="2024-01-01", end="2024-12-31"),
        "split_hash": hash_text("fixture-split"),
        "primary_metric": "average_precision",
        "secondary_metrics": ["brier_score"],
        "metric_direction": {
            "average_precision": MetricDirection.HIGHER_IS_BETTER,
            "brier_score": MetricDirection.LOWER_IS_BETTER,
        },
        "metric_implementation": "fixture.metrics:average_precision",
        "metric_code_hash": hash_text("fixture-metric-code"),
        "published_score": [
            PublishedScore(
                metric="average_precision",
                value=0.400,
                scale=ScoreScale.FRACTION,
                source=SourceReference(kind=SourceKind.PAPER, citation="fixture table 1"),
                verified_against_primary=True,
            ),
            PublishedScore(
                metric="brier_score",
                value=0.050,
                scale=ScoreScale.FRACTION,
                source=SourceReference(kind=SourceKind.PAPER, citation="fixture table 1"),
                verified_against_primary=True,
            ),
        ],
        "reproduction_tolerance": {
            "average_precision": Tolerance(absolute=0.01),
            "brier_score": Tolerance(absolute=0.01),
        },
        "seed_list": [11, 23, 37],
        "minimum_seed_count": 3,
        "confidence_method": ConfidenceMethod(
            name="paired_percentile_bootstrap", resamples=2000, alpha=0.05
        ),
        "paired_test": PairedTest(
            name="paired_sign_permutation", resamples=2000, alternative="greater"
        ),
        "hardware_requirements": HardwareRequirements(gpu_count=0, cpu_cores=2, memory_gb=4.0),
        "software_environment": SoftwareEnvironment(
            python_version="3.13", environment_files=["requirements.txt"]
        ),
        "software_lock_hash": hash_text("fixture-lock"),
        "maximum_training_cost": CostBudget(cpu_hours=1.0, wall_clock_hours=1.0),
        "maximum_inference_cost": CostBudget(cpu_hours=0.5, wall_clock_hours=0.5),
        "status": BenchmarkStatus.NOT_STARTED,
        "blockers": [],
        "notes": [
            "Fixture only. This benchmark does not exist and no result derived from it "
            "describes any published model.",
        ],
    }
    defaults.update(overrides)
    return BenchmarkContract(**defaults)  # type: ignore[arg-type]


def blocked_contract(**overrides: object) -> BenchmarkContract:
    """A contract with an unread licence and no dataset hash."""
    defaults: dict[str, object] = {
        "benchmark_id": "blocked_fixture",
        "data_license": None,
        "data_hash": None,
        "status": BenchmarkStatus.CONTRACT_INCOMPLETE,
        "blockers": [
            Blocker(
                field="data_license",
                code=BlockerCode.LICENCE_UNKNOWN,
                detail="fixture: licence not read",
            ),
            Blocker(
                field="data_hash",
                code=BlockerCode.DATA_UNAVAILABLE,
                detail="fixture: dataset not obtained",
            ),
        ],
    }
    defaults.update(overrides)
    return synthetic_contract(**defaults)


def synthetic_plan(
    contract: BenchmarkContract | None = None,
    *,
    seeds: Sequence[int] = (11,),
    command: Sequence[str] = ("python", "-m", "fixture.run"),
    **overrides: object,
) -> ReproductionPlan:
    """A runnable plan over the synthetic contract, built without any probing."""
    contract = contract or synthetic_contract()
    defaults: dict[str, object] = {
        "benchmark_id": contract.benchmark_id,
        "contract_hash": contract.contract_hash(),
        "contract_version": contract.contract_version,
        "official_commit": contract.official_commit,
        "data_version": contract.data_version,
        "data_hash": contract.data_hash,
        "split_hash": contract.split_hash,
        "environment": contract.software_environment or SoftwareEnvironment(),
        "hardware": contract.hardware_requirements or HardwareRequirements(),
        "command": tuple(command),
        "seeds": tuple(seeds),
        "expected_outputs": ("metrics.json",),
        "metric_parser": "fixture.parse:metrics",
        "timeout_seconds": 600,
        "input_hashes": {"data": contract.data_hash or ""},
        "output_root": "runs/fixture",
    }
    defaults.update(overrides)
    return ReproductionPlan(**defaults)  # type: ignore[arg-type]


class FakeExecutor:
    """A :class:`BenchmarkExecutor` that returns canned results.

    Records what it was asked to do, so a test can assert that a refusal happened
    *before* any phase ran rather than after. ``prepared_calls`` staying empty is
    the assertion that a blocked benchmark never reached third-party code.
    """

    def __init__(
        self,
        *,
        metrics: Mapping[str, float] | None = None,
        per_unit: Mapping[str, Sequence[float]] | None = None,
        unit_ids: Sequence[str] | None = None,
        exit_code: int = 0,
        duration_seconds: float = 300.0,
        gpu_hours: float = 0.0,
        cpu_hours: float = 0.5,
        peak_memory_gb: float = 2.0,
    ) -> None:
        self.metrics = dict(metrics or {"average_precision": 0.402, "brier_score": 0.049})
        self.per_unit = {key: list(values) for key, values in (per_unit or {}).items()}
        self.unit_ids = list(unit_ids or [f"unit-{index:03d}" for index in range(24)])
        self.exit_code = exit_code
        self.duration_seconds = duration_seconds
        self.gpu_hours = gpu_hours
        self.cpu_hours = cpu_hours
        self.peak_memory_gb = peak_memory_gb
        self.prepare_calls: list[ReproductionPlan] = []
        self.execute_calls: list[PreparedEnvironment] = []
        self.collect_calls: list[RawRunResult] = []
        self._plan: ReproductionPlan | None = None

    def prepare(self, plan: ReproductionPlan) -> PreparedEnvironment:
        self.prepare_calls.append(plan)
        self._plan = plan
        return PreparedEnvironment(
            plan_hash=plan.plan_hash(),
            environment_hash=plan.environment_hash(),
            workspace="/fixture/workspace",
            image_digest=None,
            resolved_command=plan.command,
            prepared_input_hashes=dict(plan.input_hashes),
        )

    def execute(self, prepared: PreparedEnvironment) -> RawRunResult:
        self.execute_calls.append(prepared)
        assert self._plan is not None
        seed = self._plan.seeds[0]
        return RawRunResult(
            plan_hash=prepared.plan_hash,
            seed=seed,
            exit_code=self.exit_code,
            stdout_hash=hash_text(f"stdout-{seed}"),
            stderr_hash=hash_text(f"stderr-{seed}"),
            raw_output_hashes={"metrics.json": hash_text(f"metrics-{seed}")},
            started_at=START,
            finished_at=END,
            duration_seconds=self.duration_seconds,
            gpu_hours=self.gpu_hours,
            cpu_hours=self.cpu_hours,
            peak_memory_gb=self.peak_memory_gb,
            energy_estimate_kwh=0.12,
            energy_estimate_method="cpu_hours * 0.24 kW (fixture constant)",
            hardware_description=FIXED_HOST.describe(),
            driver_version=None,
            cuda_version=None,
        )

    def collect(self, result: RawRunResult) -> ReproductionRun:
        self.collect_calls.append(result)
        assert self._plan is not None
        return build_manifest(
            self._plan,
            PreparedEnvironment(
                plan_hash=self._plan.plan_hash(),
                environment_hash=self._plan.environment_hash(),
                workspace="/fixture/workspace",
            ),
            result,
            parsed_metrics=self.metrics,
            per_unit_scores=self.per_unit,
            unit_ids=self.unit_ids,
        )


def make_run(
    contract: BenchmarkContract | None = None,
    *,
    seed: int = 11,
    metrics: Mapping[str, float] | None = None,
    per_unit: Mapping[str, Sequence[float]] | None = None,
    unit_ids: Sequence[str] | None = None,
    role: str = "control",
    exit_code: int = 0,
    **overrides: object,
) -> ReproductionRun:
    """Build a manifest directly, without going through a runner."""
    contract = contract or synthetic_contract()
    plan = synthetic_plan(contract, seeds=(seed,))
    executor = FakeExecutor(
        metrics=metrics, per_unit=per_unit, unit_ids=unit_ids, exit_code=exit_code
    )
    prepared = executor.prepare(plan)
    result = executor.execute(prepared)
    run = build_manifest(
        plan,
        prepared,
        result,
        parsed_metrics=executor.metrics,
        per_unit_scores=executor.per_unit,
        unit_ids=executor.unit_ids,
        metric_code_hash=contract.metric_code_hash,
        package_lock_hash=hash_text("fixture-lock"),
        role=role,
    )
    return run.model_copy(update=overrides) if overrides else run


def paired_unit_scores(
    count: int = 24,
    *,
    control_base: float = 0.40,
    lift: float = 0.02,
    jitter: float = 0.01,
) -> tuple[list[float], list[float]]:
    """Aligned per-unit scores where the challenger really is better.

    Deterministic by construction rather than by a seeded generator: the point is
    a fixture whose statistical answer is known in advance, not a random sample.
    """
    control = [control_base + jitter * ((index % 5) - 2) for index in range(count)]
    challenger = [value + lift for value in control]
    return control, challenger
