"""Strict contract validation and source verification.

Validation here is fail-closed by construction: a contract is invalid until it
proves otherwise, and every rule below exists because its absence produces a
claim that reads as verified and is not.

The rules divide into two kinds.

*Structural* rules ask whether the contract pins what it must pin -- a commit
that cannot move, a dataset version, a split, a metric direction, a tolerance,
seeds. These are decidable offline and run on every ``validate``.

*Ordering* rules ask whether the work happened in a defensible order -- that a
challenger was not recorded before the control reproduced, that a claim of
"exceeded" carries a statistical comparison, that test-period results do not
exist before the test was opened. These are the rules that catch a benchmark
being written up backwards from its conclusion.

Source verification (:func:`verify_source`) never executes downloaded code and,
in ``offline`` mode, never opens a socket. Its output is a record of what was
checked, including what could *not* be reached -- an unreachable primary source
is a finding, not a reason to accept a number.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field

from pramaanx.benchmarks.schemas import (
    REPRODUCED_OR_BEYOND,
    BenchmarkContract,
    BenchmarkStatus,
    Blocker,
    BlockerCode,
    MetricDirection,
    ReproductionRun,
    SourceKind,
    SourceReference,
    ToleranceCheck,
)
from pramaanx.schemas.base import PramaanModel

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

_HEX_SHA = re.compile(r"\A[0-9a-f]{40}\Z|\A[0-9a-f]{64}\Z")
_REPO_URL = re.compile(r"\Ahttps://[a-z0-9.\-]+/[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+\Z")

INCOMPLETE_CODES = frozenset(
    {
        BlockerCode.MISSING_FIELD,
        BlockerCode.UNVERIFIED_SOURCE,
        BlockerCode.SOURCE_UNREACHABLE,
        BlockerCode.NO_OFFICIAL_CODE,
        BlockerCode.MUTABLE_REFERENCE,
        BlockerCode.AWAITING_MEASUREMENT,
        BlockerCode.POLICY_NOT_OPENED,
    }
)
"""Blockers that mean the contract is not yet defined, rather than not yet runnable."""

LICENCE_CODES = frozenset({BlockerCode.LICENCE_UNKNOWN, BlockerCode.LICENCE_FORBIDS_REDISTRIBUTION})

ENVIRONMENT_CODES = frozenset(
    {BlockerCode.ENVIRONMENT_UNAVAILABLE, BlockerCode.COMPUTE_UNAVAILABLE}
)

MUTABLE_REFERENCES = frozenset(
    {"main", "master", "head", "develop", "development", "trunk", "latest", "default"}
)
"""Names that resolve to different bytes on different days.

``main`` is not a version. A contract pinned to a branch reproduces whatever
that branch happens to contain at run time, which is the failure this package
exists to make impossible.
"""


class Severity(StrEnum):
    """``ERROR`` blocks; ``WARNING`` is recorded and does not."""

    ERROR = "error"
    WARNING = "warning"


class Violation(PramaanModel):
    """One rule a contract broke, named by the rule and the field."""

    rule: str
    field: str
    severity: Severity
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.rule} ({self.field}): {self.message}"


class ValidationReport(PramaanModel):
    """The verdict on one contract."""

    benchmark_id: str
    contract_hash: str
    violations: list[Violation] = Field(default_factory=list)
    declared_status: BenchmarkStatus = BenchmarkStatus.NOT_STARTED
    permitted_status: BenchmarkStatus = BenchmarkStatus.NOT_STARTED

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity is Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        """Valid means: no errors, and the declared status is one the evidence allows."""
        return not self.errors and self.declared_status is self.permitted_status

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "contract_hash": self.contract_hash,
            "declared_status": self.declared_status.value,
            "permitted_status": self.permitted_status.value,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "violations": [v.canonical_dict() for v in self.violations],
        }


def is_immutable_sha(value: str | None) -> bool:
    """Whether ``value`` names bytes that cannot change under it.

    A full hex object name qualifies. A branch, a tag, a short SHA and the empty
    string do not: tags move, short SHAs collide as history grows, and a branch
    is a pointer by definition.
    """
    if not value:
        return False
    return _HEX_SHA.fullmatch(value.strip().lower()) is not None


def is_mutable_reference(value: str | None) -> bool:
    """Whether ``value`` looks like a branch name someone tried to pin to."""
    if not value:
        return False
    return value.strip().lower() in MUTABLE_REFERENCES


def is_internal_track(contract: BenchmarkContract) -> bool:
    """Whether this benchmark is this project's own track rather than a reproduction.

    An internal track has no published score to land inside, because there is no
    paper. That changes two rules: it is not required to record one, and it can
    never reach ``reproduced`` -- there is nothing to have reproduced. Its
    strongest honest status is ``running``.
    """
    reference = contract.paper_reference
    return reference is not None and reference.kind is SourceKind.INTERNAL


def _blocked_field(contract: BenchmarkContract, field: str) -> bool:
    """Whether an empty field is accounted for by an explicit blocker."""
    return field in contract.blocker_fields()


def _needs(
    contract: BenchmarkContract,
    *,
    rule: str,
    field: str,
    message: str,
) -> Violation | None:
    """Emit an error unless a blocker takes responsibility for the gap.

    An acknowledged gap is not a rule violation; it is a benchmark that is
    honestly ``contract_incomplete``. An unacknowledged gap is a contract
    claiming to be something it is not.
    """
    if _blocked_field(contract, field):
        return None
    return Violation(rule=rule, field=field, severity=Severity.ERROR, message=message)


def _structural_violations(contract: BenchmarkContract) -> list[Violation]:
    """Rules about what the contract pins."""
    found: list[Violation] = []

    def add(violation: Violation | None) -> None:
        if violation is not None:
            found.append(violation)

    # Official repository is missing.
    if not contract.official_repository:
        add(
            _needs(
                contract,
                rule="official_repository_required",
                field="official_repository",
                message="no official repository recorded; a published result with no "
                "released code cannot be reproduced, only re-implemented",
            )
        )
    elif not _REPO_URL.fullmatch(contract.official_repository):
        found.append(
            Violation(
                rule="official_repository_wellformed",
                field="official_repository",
                severity=Severity.ERROR,
                message=f"{contract.official_repository!r} is not an https host/owner/repo URL",
            )
        )

    # Official commit is not an immutable SHA.
    if is_mutable_reference(contract.official_commit):
        found.append(
            Violation(
                rule="official_commit_immutable",
                field="official_commit",
                severity=Severity.ERROR,
                message=f"{contract.official_commit!r} is a branch name, not a commit; "
                "a branch resolves to different code on different days",
            )
        )
    elif contract.official_commit is not None and not is_immutable_sha(contract.official_commit):
        found.append(
            Violation(
                rule="official_commit_immutable",
                field="official_commit",
                severity=Severity.ERROR,
                message=f"{contract.official_commit!r} is not a full hex object name "
                "(40 or 64 hex characters)",
            )
        )
    elif contract.official_commit is None:
        add(
            _needs(
                contract,
                rule="official_commit_required",
                field="official_commit",
                message="no immutable commit recorded for the published result",
            )
        )

    # Data version / hash are missing.
    for field, value in (
        ("data_name", contract.data_name),
        ("data_version", contract.data_version),
        ("data_hash", contract.data_hash),
    ):
        if not value:
            add(
                _needs(
                    contract,
                    rule="dataset_pinned",
                    field=field,
                    message=f"{field} is unset; the dataset the published score was "
                    "computed on is therefore unidentified",
                )
            )

    # Licence is unknown without a blocker.
    if not contract.data_license:
        add(
            _needs(
                contract,
                rule="licence_known",
                field="data_license",
                message="dataset licence unknown; acquisition must stay blocked until "
                "the terms are read",
            )
        )
    if contract.redistribution_allowed is None:
        add(
            _needs(
                contract,
                rule="redistribution_declared",
                field="redistribution_allowed",
                message="redistribution permission undeclared",
            )
        )

    # Train/test split is incomplete.
    for field, period in (
        ("training_period", contract.training_period),
        ("test_period", contract.test_period),
    ):
        if period is None or not period.is_complete:
            add(
                _needs(
                    contract,
                    rule="split_complete",
                    field=field,
                    message=f"{field} is not a closed date range",
                )
            )
    if not contract.split_hash:
        add(
            _needs(
                contract,
                rule="split_pinned",
                field="split_hash",
                message="split_hash is unset; two runs cannot be shown to have used "
                "the same partition",
            )
        )
    if (
        contract.training_period is not None
        and contract.test_period is not None
        and contract.training_period.overlaps(contract.test_period)
    ):
        found.append(
            Violation(
                rule="split_disjoint",
                field="test_period",
                severity=Severity.ERROR,
                message="training_period overlaps test_period; the reported score would "
                "include days the model was fitted on",
            )
        )

    # Primary metric has no direction.
    if not contract.primary_metric:
        add(
            _needs(
                contract,
                rule="primary_metric_required",
                field="primary_metric",
                message="no primary metric named",
            )
        )
    elif contract.direction_of(contract.primary_metric) is None:
        found.append(
            Violation(
                rule="metric_direction_required",
                field="metric_direction",
                severity=Severity.ERROR,
                message=f"no direction declared for primary metric "
                f"{contract.primary_metric!r}; 'better' is undefined without it",
            )
        )
    for metric in contract.secondary_metrics:
        if contract.direction_of(metric) is None:
            found.append(
                Violation(
                    rule="metric_direction_required",
                    field="metric_direction",
                    severity=Severity.WARNING,
                    message=f"no direction declared for secondary metric {metric!r}",
                )
            )
    if not contract.metric_implementation:
        add(
            _needs(
                contract,
                rule="metric_implementation_required",
                field="metric_implementation",
                message="metric implementation unnamed; 'average precision' is at least "
                "three different numbers depending on whose code computes it",
            )
        )
    if not contract.metric_code_hash:
        add(
            _needs(
                contract,
                rule="metric_code_pinned",
                field="metric_code_hash",
                message="metric_code_hash unset; a metric change would not alter the contract hash",
            )
        )

    # Published score lacks a source.
    for score in contract.published_score:
        if score.source.citation.strip() == "":
            found.append(
                Violation(
                    rule="published_score_sourced",
                    field="published_score",
                    severity=Severity.ERROR,
                    message=f"published score for {score.metric!r} has an empty citation",
                )
            )
        if not score.verified_against_primary and not _blocked_field(contract, "published_score"):
            found.append(
                Violation(
                    rule="published_score_verified",
                    field="published_score",
                    severity=Severity.ERROR,
                    message=f"published score for {score.metric!r} was not read from the "
                    "primary source; a value quoted from a design document or a "
                    "summary is not a published score",
                )
            )
    if (
        contract.primary_metric
        and not contract.published_for(contract.primary_metric)
        and not is_internal_track(contract)
    ):
        add(
            _needs(
                contract,
                rule="published_score_required",
                field="published_score",
                message=f"no published score recorded for the primary metric "
                f"{contract.primary_metric!r}",
            )
        )

    # Reproduction tolerance is absent.
    if not contract.reproduction_tolerance:
        add(
            _needs(
                contract,
                rule="tolerance_required",
                field="reproduction_tolerance",
                message="no reproduction tolerance; 'close enough' would be decided "
                "after seeing the result",
            )
        )
    elif contract.primary_metric and contract.primary_metric not in contract.reproduction_tolerance:
        found.append(
            Violation(
                rule="tolerance_required",
                field="reproduction_tolerance",
                severity=Severity.ERROR,
                message=f"no tolerance for primary metric {contract.primary_metric!r}",
            )
        )

    # Seed list is empty.
    if not contract.seed_list:
        add(
            _needs(
                contract,
                rule="seeds_required",
                field="seed_list",
                message="seed_list is empty; a single unlabelled run cannot separate "
                "an improvement from an initialisation",
            )
        )
    if contract.minimum_seed_count is None:
        add(
            _needs(
                contract,
                rule="minimum_seed_count_required",
                field="minimum_seed_count",
                message="minimum_seed_count unset",
            )
        )
    elif len(contract.seed_list) < contract.minimum_seed_count:
        found.append(
            Violation(
                rule="seeds_sufficient",
                field="seed_list",
                severity=Severity.ERROR,
                message=f"{len(contract.seed_list)} seeds listed but "
                f"{contract.minimum_seed_count} required",
            )
        )

    # Confidence method is absent.
    if contract.confidence_method is None:
        add(
            _needs(
                contract,
                rule="confidence_method_required",
                field="confidence_method",
                message="no confidence method; a difference would be reported without an interval",
            )
        )
    if contract.paired_test is None:
        add(
            _needs(
                contract,
                rule="paired_test_required",
                field="paired_test",
                message="no paired test declared",
            )
        )

    # Environment.
    if contract.software_environment is None:
        add(
            _needs(
                contract,
                rule="environment_required",
                field="software_environment",
                message="no software environment recorded",
            )
        )
    if not contract.software_lock_hash:
        add(
            _needs(
                contract,
                rule="environment_pinned",
                field="software_lock_hash",
                message="software_lock_hash unset; an environment change would not "
                "alter the contract hash",
            )
        )
    if contract.hardware_requirements is None:
        add(
            _needs(
                contract,
                rule="hardware_required",
                field="hardware_requirements",
                message="no hardware requirements recorded",
            )
        )

    # Cost ceilings. A report that omits cost makes every result look free.
    for field, budget in (
        ("maximum_training_cost", contract.maximum_training_cost),
        ("maximum_inference_cost", contract.maximum_inference_cost),
    ):
        if budget is None:
            add(
                _needs(
                    contract,
                    rule="cost_budget_required",
                    field=field,
                    message=f"{field} unset; cost cannot be omitted from a comparison",
                )
            )

    # A blocker must not be recorded against a field that is actually populated.
    for blocker in contract.blockers:
        if blocker.field not in type(contract).model_fields:
            found.append(
                Violation(
                    rule="blocker_names_real_field",
                    field=blocker.field,
                    severity=Severity.ERROR,
                    message=f"blocker names {blocker.field!r}, which is not a contract field",
                )
            )

    return found


def _ordering_violations(
    contract: BenchmarkContract,
    runs: Sequence[ReproductionRun] = (),
) -> list[Violation]:
    """Rules about the order in which the work is allowed to have happened."""
    found: list[Violation] = []
    by_id = {run.run_id: run for run in runs}

    # Challenger recorded before reproduction.
    if contract.challenger_run_ids and contract.status not in REPRODUCED_OR_BEYOND:
        found.append(
            Violation(
                rule="challenger_after_reproduction",
                field="challenger_run_ids",
                severity=Severity.ERROR,
                message=f"{len(contract.challenger_run_ids)} challenger run(s) recorded "
                f"while status is {contract.status.value}; a challenger is only "
                "meaningful against a control that reproduced",
            )
        )
    if contract.challenger_run_ids and not contract.control_run_id:
        found.append(
            Violation(
                rule="challenger_after_reproduction",
                field="control_run_id",
                severity=Severity.ERROR,
                message="challenger runs recorded with no control run",
            )
        )

    # "Exceeded" without a statistical comparison.
    if contract.status is BenchmarkStatus.EXCEEDED:
        if not contract.challenger_run_ids:
            found.append(
                Violation(
                    rule="exceeded_requires_comparison",
                    field="status",
                    severity=Severity.ERROR,
                    message="status is 'exceeded' with no challenger run recorded",
                )
            )
        if contract.confidence_method is None or contract.paired_test is None:
            found.append(
                Violation(
                    rule="exceeded_requires_comparison",
                    field="status",
                    severity=Severity.ERROR,
                    message="status is 'exceeded' without a declared confidence method "
                    "and paired test; a larger number is not a result",
                )
            )

    # Test-period results before the test was opened.
    if not contract.final_test_policy.opened:
        for run in runs:
            if run.reads_test_period:
                found.append(
                    Violation(
                        rule="test_period_sealed",
                        field="final_test_policy",
                        severity=Severity.ERROR,
                        message=f"run {run.run_id} reports test-period results while the "
                        "final test is not open",
                    )
                )
    elif contract.final_test_policy.authorisation_id is None:
        found.append(
            Violation(
                rule="test_opening_authorised",
                field="final_test_policy",
                severity=Severity.ERROR,
                message="final test is marked open with no authorisation record",
            )
        )

    # Post-test changes invalidate.
    for run in runs:
        if run.post_test_changes and contract.status is not BenchmarkStatus.INVALIDATED:
            found.append(
                Violation(
                    rule="post_test_change_invalidates",
                    field="status",
                    severity=Severity.ERROR,
                    message=f"run {run.run_id} records {len(run.post_test_changes)} change(s) "
                    "after the final test was opened; the result is invalidated",
                )
            )

    # A run must have been produced under this contract version.
    for run in runs:
        if run.contract_hash != contract.contract_hash():
            found.append(
                Violation(
                    rule="run_matches_contract",
                    field="contract_version",
                    severity=Severity.ERROR,
                    message=f"run {run.run_id} was produced under contract hash "
                    f"{run.contract_hash[:19]}..., which is not the current contract; "
                    "a changed metric or environment requires a new contract version",
                )
            )

    # Cross-references must resolve when the runs were supplied.
    if runs:
        for run_id in filter(None, [contract.control_run_id, *contract.challenger_run_ids]):
            if run_id not in by_id:
                found.append(
                    Violation(
                        rule="run_reference_resolves",
                        field="control_run_id",
                        severity=Severity.WARNING,
                        message=f"run {run_id} is referenced but was not supplied",
                    )
                )

    return found


def permitted_status(
    contract: BenchmarkContract,
    violations: Iterable[Violation],
    runs: Sequence[ReproductionRun] = (),
) -> BenchmarkStatus:
    """The strongest status the evidence actually supports.

    Computed from the contract and its runs rather than read from the record, so
    that ``status: reproduced`` in a YAML file is a claim to be checked and not a
    fact to be trusted.
    """
    for run in runs:
        if run.post_test_changes:
            # Checked first: a result invalidated by post-test tuning is a
            # definite verdict, and must not be softened into "incomplete" by
            # whatever else the contract is also missing.
            return BenchmarkStatus.INVALIDATED

    structural = [v for v in violations if v.severity is Severity.ERROR]
    if structural:
        return BenchmarkStatus.CONTRACT_INCOMPLETE

    blocked_codes = {blocker.code for blocker in contract.blockers}
    if blocked_codes & INCOMPLETE_CODES:
        # An unknown field outranks an unobtainable dataset. "We cannot define
        # this benchmark yet" and "we have defined it and cannot download it"
        # are different states, and the first is the weaker claim.
        return BenchmarkStatus.CONTRACT_INCOMPLETE
    if blocked_codes & LICENCE_CODES:
        return BenchmarkStatus.BLOCKED_LICENCE
    if BlockerCode.DATA_UNAVAILABLE in blocked_codes:
        return BenchmarkStatus.BLOCKED_DATA
    if blocked_codes & ENVIRONMENT_CODES:
        return BenchmarkStatus.BLOCKED_ENVIRONMENT
    if blocked_codes:
        return BenchmarkStatus.CONTRACT_INCOMPLETE

    control = next((run for run in runs if run.run_id == contract.control_run_id), None)
    if control is None:
        return BenchmarkStatus.RUNNING if runs else BenchmarkStatus.NOT_STARTED
    if not control.succeeded:
        return BenchmarkStatus.REPRODUCTION_FAILED
    if is_internal_track(contract):
        # Nothing published to reproduce, so 'reproduced' is not available however
        # well the run went.
        return BenchmarkStatus.RUNNING

    tolerance_failures = [
        check for check in tolerance_checks(contract, control) if not check.within_tolerance
    ]
    if tolerance_failures:
        return BenchmarkStatus.REPRODUCTION_FAILED
    if not contract.challenger_run_ids:
        return BenchmarkStatus.REPRODUCED
    return BenchmarkStatus.CHALLENGED_NOT_EXCEEDED


def tolerance_checks(
    contract: BenchmarkContract,
    run: ReproductionRun,
) -> list[ToleranceCheck]:
    """Compare a run's metrics with the published values, metric by metric.

    Imported lazily from :mod:`comparison` to keep the dependency one-way; the
    function lives there because tolerance is a comparison concept.
    """
    from pramaanx.benchmarks.comparison import check_tolerances

    return list(check_tolerances(contract, run))


def validate_contract(
    contract: BenchmarkContract,
    runs: Sequence[ReproductionRun] = (),
) -> ValidationReport:
    """Apply every rule to one contract and return the verdict."""
    violations = _structural_violations(contract) + _ordering_violations(contract, runs)
    allowed = permitted_status(contract, violations, runs)
    if contract.status is not allowed:
        violations.append(
            Violation(
                rule="status_supported_by_evidence",
                field="status",
                severity=Severity.ERROR,
                message=f"record declares {contract.status.value!r} but the evidence "
                f"supports at most {allowed.value!r}",
            )
        )
    return ValidationReport(
        benchmark_id=contract.benchmark_id,
        contract_hash=contract.contract_hash(),
        violations=violations,
        declared_status=contract.status,
        permitted_status=allowed,
    )


class SourceCheck(PramaanModel):
    """One thing that was checked about an official source, and what was found."""

    name: str
    satisfied: bool
    observed: str | None = None
    detail: str = ""


class SourceVerification(PramaanModel):
    """The record of a source-verification pass. Never executes fetched code."""

    benchmark_id: str
    contract_hash: str
    offline: bool
    checks: list[SourceCheck] = Field(default_factory=list)
    references: list[SourceReference] = Field(default_factory=list)

    @property
    def verified(self) -> bool:
        return all(check.satisfied for check in self.checks)

    def unmet(self) -> list[str]:
        return [check.name for check in self.checks if not check.satisfied]

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "contract_hash": self.contract_hash,
            "offline": self.offline,
            "verified": self.verified,
            "unmet": self.unmet(),
            "checks": [check.canonical_dict() for check in self.checks],
        }


def verify_source(contract: BenchmarkContract, *, offline: bool = True) -> SourceVerification:
    """Check what a contract says about its official source.

    ``offline=True`` -- the default, and the only mode the harness uses -- opens
    no socket, clones nothing and runs nothing. It verifies the *shape* of the
    claims: that the repository URL is well formed, that the commit is immutable,
    that an environment file and an entrypoint are named, that the dataset is
    identified and its licence read.

    Downloaded code is never executed here under any mode. Verifying a
    repository by running its setup script is how a verification step becomes an
    arbitrary code execution step.
    """
    checks: list[SourceCheck] = [
        SourceCheck(
            name="repository_url",
            satisfied=bool(contract.official_repository)
            and _REPO_URL.fullmatch(contract.official_repository or "") is not None,
            observed=contract.official_repository,
            detail="an https host/owner/repo URL is recorded",
        ),
        SourceCheck(
            name="immutable_commit",
            satisfied=is_immutable_sha(contract.official_commit),
            observed=contract.official_commit,
            detail="official_commit is a full hex object name",
        ),
        SourceCheck(
            name="archive_or_checkout_hash",
            satisfied=bool(contract.official_code_hash),
            observed=contract.official_code_hash,
            detail="a content hash of the checked-out tree is recorded",
        ),
        SourceCheck(
            name="licence",
            satisfied=bool(contract.data_license),
            observed=contract.data_license,
            detail="the dataset licence has been read and recorded",
        ),
        SourceCheck(
            name="required_submodules",
            satisfied=contract.software_environment is not None,
            observed=None,
            detail="submodule and environment requirements are declared",
        ),
        SourceCheck(
            name="environment_files",
            satisfied=bool(
                contract.software_environment and contract.software_environment.environment_files
            ),
            observed=(
                ",".join(contract.software_environment.environment_files)
                if contract.software_environment
                else None
            ),
            detail="at least one environment file is named",
        ),
        SourceCheck(
            name="expected_entrypoint",
            satisfied=bool(contract.metric_implementation),
            observed=contract.metric_implementation,
            detail="the entrypoint or metric implementation is named",
        ),
        SourceCheck(
            name="expected_dataset_references",
            satisfied=bool(contract.data_name and contract.data_version),
            observed=f"{contract.data_name}@{contract.data_version}",
            detail="the dataset is identified by name and version",
        ),
        SourceCheck(
            name="published_score_primary_verified",
            satisfied=bool(contract.published_score)
            and all(score.verified_against_primary for score in contract.published_score),
            observed=None,
            detail="every published score was read from its primary source",
        ),
    ]
    if offline:
        checks.append(
            SourceCheck(
                name="offline_mode",
                satisfied=True,
                observed="offline",
                detail="no network access, no clone, no execution of third-party code",
            )
        )
    references = [ref for ref in (contract.paper_reference,) if ref is not None]
    return SourceVerification(
        benchmark_id=contract.benchmark_id,
        contract_hash=contract.contract_hash(),
        offline=offline,
        checks=checks,
        references=references,
    )


def blockers_from_validation(report: ValidationReport) -> list[Blocker]:
    """Turn unmet rules into blockers, so a report can list what is missing."""
    return [
        Blocker(
            field=violation.field,
            code=BlockerCode.MISSING_FIELD,
            detail=violation.message,
        )
        for violation in report.errors
    ]


def direction_improves(
    direction: MetricDirection,
    control: float,
    challenger: float,
) -> bool:
    """Whether ``challenger`` is better than ``control`` in the declared direction."""
    if direction is MetricDirection.HIGHER_IS_BETTER:
        return challenger > control
    return challenger < control


def signed_improvement(
    direction: MetricDirection,
    control: float,
    challenger: float,
) -> float:
    """Improvement as a positive-is-better quantity, whatever the direction."""
    if direction is MetricDirection.HIGHER_IS_BETTER:
        return challenger - control
    return control - challenger
