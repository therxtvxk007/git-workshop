"""Benchmark registry and exact-reproduction harness (WP-B0).

This package defines the contracts that any future challenger model must satisfy
before its result may be described in words like "reproduced", "challenged" or
"exceeded". It implements none of those models. It is the referee, not a player.

The shape of the thing:

``schemas``       the contract, plan, run manifest and comparison records;
``registry``      loading and writing the machine-readable registry;
``verification``  strict validation, and offline source verification;
``environment``   what this host can run, and honest blockers when it cannot;
``manifests``     immutable, deterministically named run records;
``runner``        planning, the executor protocol, and the final-test ledger;
``statistics``    paired bootstrap, block bootstrap and randomisation tests;
``comparison``    the eight gates between "a bigger number" and "exceeded";
``reporting``     JSON and human renderings that cannot omit failures or cost.

The command surface is ``python -m pramaanx.benchmarks``. It is deliberately not
registered as a subcommand of the main ``pramaanx`` CLI: a later integration
package can do that once the benchmark work is more than a contract.
"""

from __future__ import annotations

from pramaanx.benchmarks.comparison import ComparisonError, check_tolerances, compare
from pramaanx.benchmarks.environment import (
    EnvironmentProbe,
    EnvironmentReport,
    HostDescription,
    environment_hash,
)
from pramaanx.benchmarks.manifests import (
    ManifestExistsError,
    ManifestStore,
    build_manifest,
    classify_failure,
)
from pramaanx.benchmarks.registry import (
    BenchmarkRegistry,
    RegistryError,
    load_contract,
    load_registry,
    write_contract,
)
from pramaanx.benchmarks.reporting import benchmark_report, registry_report, run_report
from pramaanx.benchmarks.runner import (
    BenchmarkExecutor,
    BlockedExecutor,
    DryRunGuard,
    DryRunViolationError,
    FinalTestAccessError,
    FinalTestAccessLedger,
    FinalTestLedger,
    ReproductionRefusedError,
    ReproductionRunner,
    build_plan,
)
from pramaanx.benchmarks.schemas import (
    BenchmarkContract,
    BenchmarkStatus,
    Blocker,
    BlockerCode,
    ComparisonResult,
    FailureClass,
    MetricDirection,
    Period,
    PublishedScore,
    RawRunResult,
    ReproductionPlan,
    ReproductionRun,
    ScoreScale,
    SourceReference,
    Tolerance,
)
from pramaanx.benchmarks.statistics import (
    block_bootstrap_ci,
    paired_bootstrap_ci,
    paired_effect_size,
    paired_permutation_test,
    summarise,
)
from pramaanx.benchmarks.verification import (
    ValidationReport,
    Violation,
    is_immutable_sha,
    validate_contract,
    verify_source,
)

__all__ = [
    "BenchmarkContract",
    "BenchmarkExecutor",
    "BenchmarkRegistry",
    "BenchmarkStatus",
    "BlockedExecutor",
    "Blocker",
    "BlockerCode",
    "ComparisonError",
    "ComparisonResult",
    "DryRunGuard",
    "DryRunViolationError",
    "EnvironmentProbe",
    "EnvironmentReport",
    "FailureClass",
    "FinalTestAccessError",
    "FinalTestAccessLedger",
    "FinalTestLedger",
    "HostDescription",
    "ManifestExistsError",
    "ManifestStore",
    "MetricDirection",
    "Period",
    "PublishedScore",
    "RawRunResult",
    "RegistryError",
    "ReproductionPlan",
    "ReproductionRefusedError",
    "ReproductionRun",
    "ReproductionRunner",
    "ScoreScale",
    "SourceReference",
    "Tolerance",
    "ValidationReport",
    "Violation",
    "benchmark_report",
    "block_bootstrap_ci",
    "build_manifest",
    "build_plan",
    "check_tolerances",
    "classify_failure",
    "compare",
    "environment_hash",
    "is_immutable_sha",
    "load_contract",
    "load_registry",
    "paired_bootstrap_ci",
    "paired_effect_size",
    "paired_permutation_test",
    "registry_report",
    "run_report",
    "summarise",
    "validate_contract",
    "verify_source",
    "write_contract",
]
