"""Reproduction planning, execution and the final-test access ledger.

The runner never runs third-party benchmark code itself. It builds a
:class:`~pramaanx.benchmarks.schemas.ReproductionPlan`, hands it to a
:class:`BenchmarkExecutor`, and turns what comes back into an immutable
manifest. Isolation is therefore the executor's responsibility and is visible in
the type: running an official repository inside the main Pramaan-X process would
mean writing an executor that does so, deliberately, rather than it happening
because a helper quietly imported something.

Two guards live here because both must hold *before* any executor is invoked.

:class:`DryRunGuard` makes the dry-run promise structural. In dry-run mode the
guard refuses network, clone, download, container start and filesystem write --
so a dry run that would have touched any of them raises instead of silently
doing it. It is not a flag threaded through call sites and occasionally missed.

:class:`FinalTestLedger` seals the frozen test period. Before the test is opened,
test labels cannot be loaded, the test metric refuses to run, and selection code
cannot read test results. Opening requires a frozen contract, frozen artefact
hashes, frozen config hashes and a one-time authorisation record; after opening,
any change to the model or config invalidates the result, and a second run is
recorded as a rerun rather than replacing the first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import Field

from pramaanx.benchmarks.environment import EnvironmentProbe
from pramaanx.benchmarks.manifests import ManifestStore, build_manifest
from pramaanx.benchmarks.schemas import (
    BenchmarkContract,
    Blocker,
    BlockerCode,
    HardwareRequirements,
    PreparedEnvironment,
    RawRunResult,
    ReproductionPlan,
    ReproductionRun,
    SoftwareEnvironment,
)
from pramaanx.hashing import hash_object, stable_id
from pramaanx.schemas.base import PramaanModel, UtcDatetime

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class DryRunViolationError(RuntimeError):
    """A dry run attempted an effect it promised not to have."""


class FinalTestAccessError(RuntimeError):
    """Something tried to reach the frozen test period before it was opened."""


class ReproductionRefusedError(RuntimeError):
    """A run was refused before it started, and the reason is in the message."""


EFFECTS = ("network", "clone", "download", "container", "write")
"""Every effect a dry run promises not to have. Named so refusals can say which."""


class DryRunGuard:
    """Refuses side effects while a dry run is in progress.

    Deliberately not a context manager over a global: an executor gets the guard
    passed to it, so an executor that ignores it has visibly ignored an argument
    rather than merely failed to import something.
    """

    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.refused: list[str] = []

    def allow(self, effect: str) -> None:
        """Permit ``effect``, or refuse it if this is a dry run."""
        if effect not in EFFECTS:
            raise ValueError(f"unknown effect {effect!r}; expected one of {EFFECTS}")
        if self.dry_run:
            self.refused.append(effect)
            raise DryRunViolationError(
                f"dry-run refused a {effect} operation. Dry run performs no network "
                "access, no clone, no data download, no container execution and no "
                "filesystem writes."
            )

    def would_refuse(self) -> tuple[str, ...]:
        return EFFECTS if self.dry_run else ()


@runtime_checkable
class BenchmarkExecutor(Protocol):
    """How a reproduction is actually carried out.

    Three phases, kept separate so that each can be blocked, faked or audited on
    its own: ``prepare`` may fetch and build but must not run the benchmark;
    ``execute`` runs it and reports raw bytes and resource use; ``collect`` parses
    the raw result into a manifest. Unit tests supply a fake executor, and no
    test in this repository executes a third party's benchmark code.
    """

    def prepare(self, plan: ReproductionPlan) -> PreparedEnvironment: ...

    def execute(self, prepared: PreparedEnvironment) -> RawRunResult: ...

    def collect(self, result: RawRunResult) -> ReproductionRun: ...


class BlockedExecutor:
    """The executor for a benchmark that cannot run here.

    Exists so that "no GPU on this machine" produces a refusal naming the
    missing resource, rather than an import error or an empty result that
    something downstream treats as a zero score.
    """

    def __init__(self, blockers: Sequence[Blocker]) -> None:
        self.blockers = list(blockers)

    def _refuse(self) -> ReproductionRefusedError:
        reasons = "; ".join(str(blocker) for blocker in self.blockers) or "unspecified"
        return ReproductionRefusedError(f"execution is blocked: {reasons}")

    # The three parameters below are unused by design: they exist to satisfy
    # BenchmarkExecutor, and this executor's whole behaviour is to refuse before
    # looking at any of them.
    def prepare(self, plan: ReproductionPlan) -> PreparedEnvironment:  # noqa: ARG002
        raise self._refuse()

    def execute(self, prepared: PreparedEnvironment) -> RawRunResult:  # noqa: ARG002
        raise self._refuse()

    def collect(self, result: RawRunResult) -> ReproductionRun:  # noqa: ARG002
        raise self._refuse()


class FinalTestAuthorisation(PramaanModel):
    """The one-time record that opens a frozen test period.

    Every hash it carries is a thing that must not change afterwards. If any of
    them does, results computed under this authorisation are invalidated -- which
    is the point: the authorisation is what makes "we changed the model after
    seeing the test set" a detectable event rather than an honour system.
    """

    authorisation_id: str
    benchmark_id: str
    contract_hash: str
    model_artefact_hashes: dict[str, str] = Field(default_factory=dict)
    config_hashes: dict[str, str] = Field(default_factory=dict)
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    authorised_by: str
    authorised_at: UtcDatetime
    reason: str

    def frozen_state_hash(self) -> str:
        """Identity of everything this authorisation froze."""
        return hash_object(
            {
                "contract_hash": self.contract_hash,
                "model_artefact_hashes": dict(sorted(self.model_artefact_hashes.items())),
                "config_hashes": dict(sorted(self.config_hashes.items())),
                "prompt_hashes": dict(sorted(self.prompt_hashes.items())),
            }
        )


class FinalTestAccessLedger(PramaanModel):
    """The append-only record of who opened which final test, and when.

    Never rewritten. A ledger that can be edited to remove an opening is a
    ledger that cannot establish that only one opening occurred.
    """

    entries: list[FinalTestAuthorisation] = Field(default_factory=list)

    def for_benchmark(self, benchmark_id: str) -> list[FinalTestAuthorisation]:
        return [entry for entry in self.entries if entry.benchmark_id == benchmark_id]

    def is_open(self, benchmark_id: str) -> bool:
        return bool(self.for_benchmark(benchmark_id))

    def authorisation(self, benchmark_id: str) -> FinalTestAuthorisation | None:
        entries = self.for_benchmark(benchmark_id)
        return entries[0] if entries else None


class FinalTestLedger:
    """Gate on the frozen test period.

    Wraps a :class:`FinalTestAccessLedger` with the checks that must pass before any
    test-period data is touched, and the checks that decide whether an already
    opened test has since been invalidated.
    """

    def __init__(self, ledger: FinalTestAccessLedger | None = None) -> None:
        self.ledger = ledger or FinalTestAccessLedger()

    def is_open(self, contract: BenchmarkContract) -> bool:
        return self.ledger.is_open(contract.benchmark_id)

    def guard_label_access(self, contract: BenchmarkContract, operation: str) -> None:
        """Refuse to load test labels before the test has been opened.

        Called by anything that would read the frozen period: label loading, the
        test metric command, and challenger-selection code reading test results.
        """
        if not self.is_open(contract):
            raise FinalTestAccessError(
                f"{operation} would read the frozen test period of "
                f"{contract.benchmark_id!r}, which has not been opened. Opening requires "
                "a frozen contract, frozen model artefact hashes, frozen config hashes "
                "and a one-time authorisation record."
            )

    def guard_selection(self, contract: BenchmarkContract, operation: str) -> None:
        """Refuse to let model selection read test-period results, ever.

        Distinct from :meth:`guard_label_access`: selection must not read test
        results even *after* the test is opened, because a selection informed by
        the test set is exactly the post-test tuning that invalidates a result.
        """
        raise FinalTestAccessError(
            f"{operation} must not read test-period results for "
            f"{contract.benchmark_id!r}. Model and challenger selection use the "
            "validation and calibration windows; a selection informed by the test "
            "period invalidates the final result whether or not the test is open."
        )

    def open_final_test(
        self,
        contract: BenchmarkContract,
        *,
        authorised_by: str,
        authorised_at: UtcDatetime,
        reason: str,
        model_artefact_hashes: dict[str, str],
        config_hashes: dict[str, str],
        prompt_hashes: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> FinalTestAuthorisation:
        """Open the frozen test once, recording everything that is being frozen.

        Refuses a second opening: the whole value of a held-out period is that it
        was looked at once. A benchmark whose test set can be reopened has a
        validation set with a more impressive name.
        """
        if self.ledger.is_open(contract.benchmark_id):
            existing = self.ledger.authorisation(contract.benchmark_id)
            assert existing is not None
            raise FinalTestAccessError(
                f"the final test for {contract.benchmark_id!r} was already opened by "
                f"authorisation {existing.authorisation_id}. Re-opening is not permitted; "
                "a further run must be recorded as a rerun."
            )
        if contract.final_test_policy.requires_frozen_artefacts and not model_artefact_hashes:
            raise FinalTestAccessError(
                "cannot open the final test without model artefact hashes: there would be "
                "no way to detect a model change afterwards"
            )
        if contract.final_test_policy.requires_frozen_configs and not config_hashes:
            raise FinalTestAccessError(
                "cannot open the final test without config hashes: there would be no way "
                "to detect a configuration change afterwards"
            )
        authorisation = FinalTestAuthorisation(
            authorisation_id=stable_id(
                "auth",
                contract.benchmark_id,
                contract.contract_hash(),
                sorted(model_artefact_hashes.items()),
                sorted(config_hashes.items()),
                authorised_by,
            ),
            benchmark_id=contract.benchmark_id,
            contract_hash=contract.contract_hash(),
            model_artefact_hashes=dict(model_artefact_hashes),
            config_hashes=dict(config_hashes),
            prompt_hashes=dict(prompt_hashes or {}),
            authorised_by=authorised_by,
            authorised_at=authorised_at,
            reason=reason,
        )
        if not dry_run:
            self.ledger.entries.append(authorisation)
        return authorisation

    def detect_post_test_changes(
        self,
        contract: BenchmarkContract,
        *,
        model_artefact_hashes: dict[str, str],
        config_hashes: dict[str, str],
        prompt_hashes: dict[str, str] | None = None,
    ) -> list[str]:
        """Name every artefact that has changed since the test was opened.

        A non-empty result invalidates the final result. It is returned rather
        than raised so a report can list precisely what changed.
        """
        authorisation = self.ledger.authorisation(contract.benchmark_id)
        if authorisation is None:
            return []
        changes: list[str] = []
        for label, frozen, current in (
            ("model_artefact", authorisation.model_artefact_hashes, model_artefact_hashes),
            ("config", authorisation.config_hashes, config_hashes),
            ("prompt", authorisation.prompt_hashes, prompt_hashes or {}),
        ):
            for key in sorted(set(frozen) | set(current)):
                if frozen.get(key) != current.get(key):
                    changes.append(f"{label}:{key}")
        if authorisation.contract_hash != contract.contract_hash():
            changes.append("contract")
        return changes


def build_plan(
    contract: BenchmarkContract,
    *,
    command: Sequence[str] = (),
    expected_outputs: Sequence[str] = (),
    metric_parser: str | None = None,
    timeout_seconds: int = 3600,
    input_hashes: dict[str, str] | None = None,
    output_root: str | None = None,
    probe: EnvironmentProbe | None = None,
) -> ReproductionPlan:
    """Turn a contract into a plan, or into an honest statement of why not.

    Planning touches nothing: no network, no clone, no download. A plan for a
    blocked benchmark is still produced and still useful -- it records exactly
    what would be run, which is what makes a blocker reviewable rather than a
    shrug.
    """
    blockers: list[Blocker] = []
    hardware = contract.hardware_requirements or HardwareRequirements()
    software = contract.software_environment or SoftwareEnvironment()

    if contract.official_commit is None:
        blockers.append(
            Blocker(
                field="official_commit",
                code=BlockerCode.MISSING_FIELD,
                detail="no immutable commit to check out",
            )
        )
    if contract.data_hash is None:
        blockers.append(
            Blocker(
                field="data_hash",
                code=BlockerCode.DATA_UNAVAILABLE,
                detail="no dataset hash; execution cannot verify it received the right data",
            )
        )
    if contract.data_license is None:
        blockers.append(
            Blocker(
                field="data_license",
                code=BlockerCode.LICENCE_UNKNOWN,
                detail="licence unknown; automatic data acquisition is refused",
            )
        )
    if not contract.seed_list:
        blockers.append(
            Blocker(
                field="seed_list",
                code=BlockerCode.MISSING_FIELD,
                detail="no seeds to run",
            )
        )
    if not command:
        # Distinguish "we know of no entrypoint" from "we have one written down
        # as prose". A README line is not an argv, and a plan cannot run it.
        recorded = contract.metric_implementation
        detail = (
            f"no executable entrypoint was supplied for this plan. The contract records "
            f"metric_implementation={recorded!r}, which is prose rather than a runnable "
            "command."
            if recorded
            else "no entrypoint is recorded for the official code, in any form"
        )
        blockers.append(
            Blocker(
                field="metric_implementation",
                code=BlockerCode.NO_OFFICIAL_CODE,
                detail=detail,
            )
        )

    environment_report = (probe or EnvironmentProbe()).check(hardware, software)
    blockers.extend(environment_report.blockers)

    return ReproductionPlan(
        benchmark_id=contract.benchmark_id,
        contract_hash=contract.contract_hash(),
        contract_version=contract.contract_version,
        official_commit=contract.official_commit,
        data_version=contract.data_version,
        data_hash=contract.data_hash,
        split_hash=contract.split_hash,
        environment=software,
        hardware=hardware,
        command=tuple(command),
        seeds=tuple(contract.seed_list),
        expected_outputs=tuple(expected_outputs),
        metric_parser=metric_parser,
        timeout_seconds=timeout_seconds,
        input_hashes=dict(input_hashes or {}),
        output_root=output_root,
        blocked=bool(blockers),
        blockers=blockers,
    )


class ReproductionRunner:
    """Drives an executor through a plan and records what happened.

    The runner enforces the preconditions; the executor does the work. Every
    refusal below happens before ``prepare`` is called, so a blocked benchmark
    never reaches third-party code at all.
    """

    def __init__(
        self,
        executor: BenchmarkExecutor,
        store: ManifestStore,
        *,
        final_test_ledger: FinalTestLedger | None = None,
    ) -> None:
        self.executor = executor
        self.store = store
        self.final_test_ledger = final_test_ledger or FinalTestLedger()

    def run(
        self,
        contract: BenchmarkContract,
        plan: ReproductionPlan,
        *,
        dry_run: bool = False,
        reads_test_period: bool = False,
        role: str = "control",
        metric_code_hash: str | None = None,
        package_lock_hash: str | None = None,
    ) -> list[ReproductionRun]:
        """Execute the plan once per seed, returning one manifest per seed.

        In dry-run mode nothing is prepared, executed or written: the plan is
        checked, the manifest paths that *would* be produced are computed, and an
        empty result list is returned. A dry run that produced manifests would be
        indistinguishable from a real one in the store.
        """
        if plan.blocked:
            reasons = "; ".join(str(blocker) for blocker in plan.blockers)
            raise ReproductionRefusedError(f"{contract.benchmark_id} cannot be run: {reasons}")
        if reads_test_period:
            self.final_test_ledger.guard_label_access(contract, "reproduction run")

        guard = DryRunGuard(dry_run=dry_run)
        if dry_run:
            # Compute the paths without creating them, then stop.
            for seed in plan.seeds:
                self.store.path_for(plan.run_id(seed))
            return []

        authorisation = self.final_test_ledger.ledger.authorisation(contract.benchmark_id)
        runs: list[ReproductionRun] = []
        for seed in plan.seeds:
            seeded = plan.model_copy(update={"seeds": (seed,)})
            guard.allow("clone")
            prepared = self.executor.prepare(seeded)
            guard.allow("container")
            result = self.executor.execute(prepared)
            # Collected once: three calls could disagree, and a metric parser is
            # not required to be free of side effects.
            collected = self.executor.collect(result)
            run = build_manifest(
                seeded,
                prepared,
                result,
                parsed_metrics=collected.parsed_metrics,
                per_unit_scores=collected.per_unit_scores,
                unit_ids=collected.unit_ids,
                metric_code_hash=metric_code_hash or contract.metric_code_hash,
                package_lock_hash=package_lock_hash,
                role=role,
                reads_test_period=reads_test_period,
                test_access_authorisation=(
                    authorisation.authorisation_id if authorisation else None
                ),
                is_rerun_of=_existing_run_id(self.store, seeded, seed),
            )
            guard.allow("write")
            self.store.write(run)
            runs.append(run)
        return runs


def _existing_run_id(store: ManifestStore, plan: ReproductionPlan, seed: int) -> str | None:
    """If this exact run already has a manifest, the new one is a rerun of it.

    Recording the link is what stops a second attempt from quietly replacing the
    first in a report.
    """
    run_id = plan.run_id(seed)
    return run_id if store.exists(run_id) else None


def plan_blockers(plan: ReproductionPlan) -> list[str]:
    return [str(blocker) for blocker in plan.blockers]


def refuse_data_acquisition(contract: BenchmarkContract) -> Blocker | None:
    """Refuse to fetch data whose licence has not been read.

    An unknown licence is not a neutral state. Downloading first and reading the
    terms afterwards is the order that produces a redistribution problem.
    """
    if contract.data_license is None:
        return Blocker(
            field="data_license",
            code=BlockerCode.LICENCE_UNKNOWN,
            detail=f"{contract.benchmark_id}: licence unknown, automatic acquisition refused",
        )
    if contract.redistribution_allowed is False:
        return Blocker(
            field="redistribution_allowed",
            code=BlockerCode.LICENCE_FORBIDS_REDISTRIBUTION,
            detail=f"{contract.benchmark_id}: licence forbids redistribution; data may be "
            "fetched to a local cache but never committed or republished",
        )
    return None


def collect_blockers(*sources: Iterable[Blocker]) -> list[Blocker]:
    """Merge blocker lists, de-duplicated and ordered deterministically."""
    seen: dict[tuple[str, str, str], Blocker] = {}
    for source in sources:
        for blocker in source:
            seen[(blocker.field, blocker.code.value, blocker.detail)] = blocker
    return [seen[key] for key in sorted(seen)]
