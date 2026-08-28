"""Immutable run manifests: writing them, reading them, refusing to lose them.

A manifest is the only durable evidence that a run happened the way it is later
described. Three properties are enforced here.

*Deterministic identity.* A run's identifier comes from the plan that produced
it and the seed it used -- never from a clock or a counter. Two machines running
the same plan agree on the identifier; re-running the same thing does not mint a
fresh name that quietly sits beside the first.

*Refusal to overwrite.* :meth:`ManifestStore.write` fails if the path exists.
Overwriting a manifest is how a failed run becomes invisible, and an invisible
failed run turns a reported score into the maximum over attempts. A genuine
second run is a *rerun*: it gets its own file and points back at the first
through ``is_rerun_of``.

*Order independence.* A manifest's hash depends on its content and not on the
order the content was assembled in, so a reproducibility test can compare two
independently built manifests directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pramaanx.benchmarks.schemas import (
    FailureClass,
    PreparedEnvironment,
    RawRunResult,
    ReproductionPlan,
    ReproductionRun,
)
from pramaanx.hashing import canonical_json, hash_object

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

MANIFEST_SUFFIX = ".run.json"


class ManifestExistsError(FileExistsError):
    """A manifest was written where one already exists.

    Never resolved by deleting the old file. Either the run is genuinely the same
    -- in which case the existing manifest already records it -- or it is a new
    run, and a new run is a rerun with its own identity.
    """


class ManifestStore:
    """A directory of run manifests, one JSON file per run.

    Flat files rather than a database: a manifest has to remain readable after
    the code that wrote it has changed, and has to diff usefully in review.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, run_id: str) -> Path:
        return self.root / f"{run_id}{MANIFEST_SUFFIX}"

    def exists(self, run_id: str) -> bool:
        return self.path_for(run_id).exists()

    def write(self, run: ReproductionRun, *, dry_run: bool = False) -> Path:
        """Persist a manifest, refusing to replace one that is already there.

        With ``dry_run`` the path is computed and returned and nothing is
        written, so a caller can show where a manifest *would* go without
        touching the filesystem.
        """
        target = self.path_for(run.run_id)
        if target.exists():
            raise ManifestExistsError(
                f"a manifest for run {run.run_id} already exists at {target}. "
                "Manifests are immutable: record a second attempt as a rerun with "
                "is_rerun_of set, rather than replacing the first."
            )
        if dry_run:
            return target
        self.root.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical_json(run.canonical_dict()), encoding="utf-8")
        return target

    def read(self, run_id: str) -> ReproductionRun:
        return ReproductionRun.model_validate_json(
            self.path_for(run_id).read_text(encoding="utf-8")
        )

    def read_all(self) -> list[ReproductionRun]:
        """Every manifest in the store, ordered by run id.

        Ordered by identity rather than by mtime so that two checkouts of the
        same store produce reports in the same order.
        """
        if not self.root.exists():
            return []
        runs = [
            ReproductionRun.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.root.glob(f"*{MANIFEST_SUFFIX}"))
        ]
        return sorted(runs, key=lambda run: run.run_id)

    def for_benchmark(self, benchmark_id: str) -> list[ReproductionRun]:
        return [run for run in self.read_all() if run.benchmark_id == benchmark_id]


def classify_failure(result: RawRunResult, plan: ReproductionPlan) -> FailureClass:
    """Name the failure mode of a raw result.

    There is deliberately no ``flaky`` class. A run that failed failed for a
    reason, and a classification scheme with an escape hatch collects every
    inconvenient failure in it.
    """
    if result.duration_seconds >= plan.timeout_seconds:
        return FailureClass.TIMEOUT
    if result.exit_code == 0:
        return FailureClass.NONE
    if result.exit_code == 137:
        return FailureClass.OUT_OF_MEMORY
    return FailureClass.NONZERO_EXIT


def build_manifest(
    plan: ReproductionPlan,
    prepared: PreparedEnvironment,
    result: RawRunResult,
    *,
    parsed_metrics: Mapping[str, float] | None = None,
    per_unit_scores: Mapping[str, Iterable[float]] | None = None,
    unit_ids: Iterable[str] = (),
    metric_code_hash: str | None = None,
    package_lock_hash: str | None = None,
    artefact_hashes: Mapping[str, str] | None = None,
    role: str = "control",
    reads_test_period: bool = False,
    test_access_authorisation: str | None = None,
    is_rerun_of: str | None = None,
    post_test_changes: Iterable[str] = (),
) -> ReproductionRun:
    """Assemble the immutable record of one run.

    Every field the run manifest is required to carry is populated here, from the
    plan (what was meant to happen), the prepared environment (what was set up)
    and the raw result (what happened). Nothing is defaulted silently: a metric
    the parser did not produce is absent from ``parsed_metrics`` rather than
    present as zero.
    """
    if result.plan_hash != plan.plan_hash():
        raise ValueError(
            f"raw result belongs to plan {result.plan_hash[:19]}... but the manifest is "
            f"being built from plan {plan.plan_hash()[:19]}..."
        )
    if prepared.plan_hash != plan.plan_hash():
        raise ValueError("prepared environment does not belong to this plan")

    return ReproductionRun(
        run_id=plan.run_id(result.seed),
        benchmark_id=plan.benchmark_id,
        contract_hash=plan.contract_hash,
        contract_version=plan.contract_version,
        official_commit=plan.official_commit,
        dataset_hash=plan.data_hash,
        split_hash=plan.split_hash,
        environment_hash=plan.environment_hash(),
        metric_code_hash=metric_code_hash,
        package_lock_hash=package_lock_hash,
        command=plan.command,
        seed=result.seed,
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_seconds=result.duration_seconds,
        hardware_description=result.hardware_description,
        driver_version=result.driver_version,
        cuda_version=result.cuda_version,
        stdout_hash=result.stdout_hash,
        stderr_hash=result.stderr_hash,
        raw_output_hashes=dict(result.raw_output_hashes),
        artefact_hashes=dict(artefact_hashes or {}),
        parsed_metrics=dict(parsed_metrics or {}),
        per_unit_scores={key: list(values) for key, values in (per_unit_scores or {}).items()},
        unit_ids=sorted(unit_ids),
        gpu_hours=result.gpu_hours,
        cpu_hours=result.cpu_hours,
        peak_memory_gb=result.peak_memory_gb,
        energy_estimate_kwh=result.energy_estimate_kwh,
        energy_estimate_method=result.energy_estimate_method,
        exit_status=result.exit_code,
        failure_classification=classify_failure(result, plan),
        role=role,
        reads_test_period=reads_test_period,
        test_access_authorisation=test_access_authorisation,
        is_rerun_of=is_rerun_of,
        post_test_changes=sorted(post_test_changes),
    )


def manifest_digest(runs: Iterable[ReproductionRun]) -> str:
    """One digest over a set of manifests, independent of the order supplied."""
    return hash_object(sorted(run.manifest_hash() for run in runs))
