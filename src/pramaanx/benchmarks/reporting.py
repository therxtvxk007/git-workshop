"""Rendering benchmark state, in JSON and for people.

Two rules govern every report here, and both are about what may not be left out.

*Failed variants stay visible.* A report lists every run recorded against a
benchmark, including the ones that failed and the ones that missed tolerance. A
report that shows only successful runs turns a reported score into the maximum
over attempts, which is the single easiest way to publish a number nobody can
reproduce.

*Cost is never omitted.* GPU hours, CPU hours, peak memory and the energy
estimate appear in every run report. A comparison that omits cost makes a model
that took four hundred GPU-hours look like a free improvement over one that took
four.

Both renderings come from the same structure, so the human-readable text cannot
quietly say something the JSON does not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pramaanx.benchmarks.comparison import check_tolerances
from pramaanx.benchmarks.registry import BenchmarkRegistry
from pramaanx.benchmarks.schemas import (
    BenchmarkContract,
    BenchmarkStatus,
    ComparisonResult,
    ReproductionRun,
)
from pramaanx.benchmarks.verification import ValidationReport

if TYPE_CHECKING:
    from collections.abc import Sequence

UNKNOWN = "—"


def _cost_row(run: ReproductionRun) -> dict[str, Any]:
    """The cost of a run. Always present, even when every value is zero."""
    return {
        "gpu_hours": run.gpu_hours,
        "cpu_hours": run.cpu_hours,
        "peak_memory_gb": run.peak_memory_gb,
        "duration_seconds": run.duration_seconds,
        "energy_estimate_kwh": run.energy_estimate_kwh,
        "energy_estimate_method": run.energy_estimate_method,
    }


def run_report(contract: BenchmarkContract, run: ReproductionRun) -> dict[str, Any]:
    """One run, with its outcome, its metrics and what it cost."""
    checks = list(check_tolerances(contract, run))
    return {
        "run_id": run.run_id,
        "role": run.role,
        "seed": run.seed,
        "succeeded": run.succeeded,
        "exit_status": run.exit_status,
        "failure_classification": run.failure_classification.value,
        "is_rerun_of": run.is_rerun_of,
        "post_test_changes": run.post_test_changes,
        "reads_test_period": run.reads_test_period,
        "official_commit": run.official_commit,
        "dataset_hash": run.dataset_hash,
        "split_hash": run.split_hash,
        "environment_hash": run.environment_hash,
        "metric_code_hash": run.metric_code_hash,
        "package_lock_hash": run.package_lock_hash,
        "parsed_metrics": dict(sorted(run.parsed_metrics.items())),
        "tolerance_checks": [check.canonical_dict() for check in checks],
        "within_tolerance": bool(checks) and all(check.within_tolerance for check in checks),
        "cost": _cost_row(run),
        "manifest_hash": run.manifest_hash(),
    }


def benchmark_report(
    contract: BenchmarkContract,
    runs: Sequence[ReproductionRun] = (),
    validation: ValidationReport | None = None,
    comparison: ComparisonResult | None = None,
) -> dict[str, Any]:
    """Everything known about one benchmark, in a single structure.

    ``runs`` is reported in full. The counts below are derived from that list
    rather than tracked separately, so a failed run cannot be dropped from the
    detail while still being counted -- or, worse, dropped from both.
    """
    ordered = sorted(runs, key=lambda run: run.run_id)
    reports = [run_report(contract, run) for run in ordered]
    failed = [item for item in reports if not item["succeeded"]]
    out_of_tolerance = [
        item for item in reports if item["succeeded"] and not item["within_tolerance"]
    ]
    return {
        "benchmark_id": contract.benchmark_id,
        "task_name": contract.task_name,
        "family": contract.benchmark_family,
        "status": contract.status.value,
        "contract_hash": contract.contract_hash(),
        "contract_version": contract.contract_version,
        "paper_title": contract.paper_title,
        "official_repository": contract.official_repository,
        "official_commit": contract.official_commit,
        "data": {
            "name": contract.data_name,
            "version": contract.data_version,
            "hash": contract.data_hash,
            "licence": contract.data_license,
            "redistribution_allowed": contract.redistribution_allowed,
        },
        "primary_metric": contract.primary_metric,
        "secondary_metrics": contract.secondary_metrics,
        "published_score": [score.canonical_dict() for score in contract.published_score],
        "published_scores_verified": all(
            score.verified_against_primary for score in contract.published_score
        )
        and bool(contract.published_score),
        "final_test_opened": contract.final_test_policy.opened,
        "blockers": [blocker.canonical_dict() for blocker in contract.blockers],
        "notes": contract.notes,
        "validation": validation.to_dict() if validation else None,
        "comparison": comparison.canonical_dict() if comparison else None,
        "runs": reports,
        "run_counts": {
            "total": len(reports),
            "failed": len(failed),
            "succeeded_out_of_tolerance": len(out_of_tolerance),
            "reproduced": len(reports) - len(failed) - len(out_of_tolerance),
        },
        "total_cost": {
            "gpu_hours": sum(run.gpu_hours for run in ordered),
            "cpu_hours": sum(run.cpu_hours for run in ordered),
            "peak_memory_gb": max((run.peak_memory_gb for run in ordered), default=0.0),
        },
    }


def registry_report(
    registry: BenchmarkRegistry,
    validations: dict[str, ValidationReport] | None = None,
) -> dict[str, Any]:
    """The whole registry, summarised without hiding the blocked entries."""
    validations = validations or {}
    rows = [
        {
            "benchmark_id": contract.benchmark_id,
            "task_name": contract.task_name,
            "family": contract.benchmark_family,
            "status": contract.status.value,
            "blockers": [str(blocker) for blocker in contract.blockers],
            "contract_hash": contract.contract_hash(),
            "valid": (
                validations[contract.benchmark_id].is_valid
                if contract.benchmark_id in validations
                else None
            ),
        }
        for contract in registry
    ]
    return {
        "version": registry.version,
        "registry_hash": registry.registry_hash(),
        "count": len(registry),
        "by_status": {
            status.value: sum(1 for row in rows if row["status"] == status.value)
            for status in BenchmarkStatus
            if any(row["status"] == status.value for row in rows)
        },
        "complete": [row["benchmark_id"] for row in rows if not row["blockers"]],
        "blocked": [row["benchmark_id"] for row in rows if row["blockers"]],
        "benchmarks": rows,
    }


def render_registry_table(report: dict[str, Any]) -> str:
    """The registry as a plain-text table."""
    lines = [
        f"benchmark registry ({report['count']} contracts, hash "
        f"{str(report['registry_hash'])[:19]}...)",
        "",
        f"{'benchmark_id':<44} {'status':<22} blockers",
        f"{'-' * 44} {'-' * 22} {'-' * 8}",
    ]
    for row in report["benchmarks"]:
        lines.append(f"{row['benchmark_id']:<44} {row['status']:<22} {len(row['blockers'])}")
    lines.extend(["", "by status:"])
    for status, count in sorted(report["by_status"].items()):
        lines.append(f"  {status:<24} {count}")
    lines.append("")
    lines.append(
        f"complete: {len(report['complete'])}    blocked or incomplete: {len(report['blocked'])}"
    )
    return "\n".join(lines)


def render_benchmark(report: dict[str, Any]) -> str:
    """One benchmark, rendered for a person, with nothing omitted."""
    data = report["data"]
    lines = [
        f"{report['benchmark_id']}  [{report['status']}]",
        f"  task            {report['task_name']}",
        f"  family          {report['family']}",
        f"  paper           {report['paper_title'] or UNKNOWN}",
        f"  repository      {report['official_repository'] or UNKNOWN}",
        f"  commit          {report['official_commit'] or UNKNOWN}",
        f"  data            {data['name'] or UNKNOWN} @ {data['version'] or UNKNOWN}",
        f"  licence         {data['licence'] or UNKNOWN} "
        f"(redistribution: {data['redistribution_allowed']})",
        f"  primary metric  {report['primary_metric'] or UNKNOWN}",
        f"  contract hash   {report['contract_hash']}",
        f"  final test      {'OPEN' if report['final_test_opened'] else 'sealed'}",
    ]

    lines.append("")
    if report["published_score"]:
        verified = (
            "verified against primary source"
            if report["published_scores_verified"]
            else ("NOT verified against a primary source")
        )
        lines.append(f"  published scores ({verified}):")
        for score in report["published_score"]:
            mark = "ok" if score["verified_against_primary"] else "unverified"
            lines.append(
                f"    {score['metric']:<28} {score['value']:<12} ({score['scale']}, {mark})"
            )
    else:
        lines.append("  published scores: none recorded")

    if report["blockers"]:
        lines.extend(["", f"  blockers ({len(report['blockers'])}):"])
        for blocker in report["blockers"]:
            lines.append(f"    {blocker['field']}: {blocker['code']}")
            lines.append(f"      {blocker['detail']}")

    counts = report["run_counts"]
    lines.extend(
        [
            "",
            f"  runs: {counts['total']} total, {counts['reproduced']} within tolerance, "
            f"{counts['succeeded_out_of_tolerance']} out of tolerance, {counts['failed']} failed",
        ]
    )
    for run in report["runs"]:
        status = (
            "ok"
            if run["succeeded"] and run["within_tolerance"]
            else "out-of-tolerance"
            if run["succeeded"]
            else f"FAILED/{run['failure_classification']}"
        )
        cost = run["cost"]
        lines.append(f"    {run['run_id']}  seed={run['seed']:<6} {run['role']:<10} {status}")
        lines.append(
            f"      cost: {cost['gpu_hours']:.3f} GPU-h, {cost['cpu_hours']:.3f} CPU-h, "
            f"{cost['peak_memory_gb']:.2f} GB peak, {cost['duration_seconds']:.1f} s, "
            f"energy: {cost['energy_estimate_kwh']} kWh "
            f"({cost['energy_estimate_method'] or 'no method recorded'})"
        )
        if run["post_test_changes"]:
            lines.append(f"      POST-TEST CHANGES: {', '.join(run['post_test_changes'])}")
        if run["is_rerun_of"]:
            lines.append(f"      rerun of {run['is_rerun_of']}")

    total = report["total_cost"]
    lines.append(
        f"  total cost: {total['gpu_hours']:.3f} GPU-h, {total['cpu_hours']:.3f} CPU-h, "
        f"{total['peak_memory_gb']:.2f} GB peak"
    )

    if report["comparison"]:
        lines.extend(["", render_comparison(report["comparison"])])
    if report["validation"] and not report["validation"]["is_valid"]:
        lines.extend(["", "  validation errors:"])
        for violation in report["validation"]["violations"]:
            lines.append(
                f"    [{violation['severity']}] {violation['rule']}: {violation['message']}"
            )
    if report["notes"]:
        lines.extend(["", "  notes:"])
        lines.extend(f"    - {note}" for note in report["notes"])
    return "\n".join(lines)


def render_comparison(comparison: dict[str, Any]) -> str:
    """A comparison, with every gate shown -- passed and failed alike."""
    lines = [
        f"  comparison: {comparison['verdict']}",
        f"    metric        {comparison['primary_metric']} ({comparison['metric_direction']})",
        f"    control       {comparison['control_score']}",
        f"    challenger    {comparison['challenger_score']}",
        f"    improvement   {comparison['improvement']}",
        f"    effect size   {comparison['effect_size'] if comparison['effect_size'] is not None else 'undefined'}",
        f"    interval      {comparison['confidence_interval']} "
        f"(alpha={comparison['confidence_alpha']})",
        f"    p-value       {comparison['p_value']}",
        f"    seeds         {comparison['seed_count']}",
        "    gates:",
    ]
    for gate, passed in sorted(comparison["gates"].items()):
        lines.append(f"      {'PASS' if passed else 'FAIL'}  {gate}")
    for detail in comparison["gate_details"]:
        lines.append(f"    - {detail}")
    return "\n".join(lines)


def render_validation(reports: dict[str, ValidationReport]) -> str:
    """Validation across the registry, listing every unmet rule."""
    lines: list[str] = []
    invalid = 0
    for benchmark_id in sorted(reports):
        report = reports[benchmark_id]
        marker = "ok" if report.is_valid else "INVALID"
        if not report.is_valid:
            invalid += 1
        lines.append(
            f"{benchmark_id:<44} {marker:<8} "
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)  "
            f"declared={report.declared_status.value} permitted={report.permitted_status.value}"
        )
        for violation in report.violations:
            lines.append(f"    [{violation.severity.value}] {violation.rule} ({violation.field})")
            lines.append(f"      {violation.message}")
    lines.append("")
    lines.append(f"{len(reports)} contract(s), {invalid} failing validation")
    return "\n".join(lines)
