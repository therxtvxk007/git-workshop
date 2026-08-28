"""``python -m pramaanx.benchmarks`` -- the benchmark command surface.

Deliberately a separate application from the main ``pramaanx`` CLI. WP-B0 owns
the benchmark contract and nothing else; registering a shared top-level command
would couple it to whichever integration package lands first. A later package
can mount this app as a subcommand when there is something to mount.

Every command holds to the same contract:

* ``--dry-run`` wherever a write or network access would otherwise occur, and a
  dry run performs no network access, no clone, no download, no container
  execution and no filesystem write;
* an explicit ``--registry`` path, so nothing depends on the current directory;
* deterministic output -- canonical JSON with sorted keys, and no timestamps or
  wall-clock values anywhere in the rendering;
* ``--json`` for machines and the default rendering for people, both built from
  the same structure;
* an immutable run manifest for anything that runs;
* refusal to overwrite an existing artefact;
* a clear, non-zero exit when a benchmark is blocked.

Exit codes: ``0`` success, ``1`` usage or lookup error, ``2`` the registry or a
contract failed validation, ``3`` the benchmark is blocked and cannot proceed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from pramaanx.benchmarks.comparison import ComparisonError, compare
from pramaanx.benchmarks.environment import EnvironmentProbe
from pramaanx.benchmarks.manifests import ManifestStore
from pramaanx.benchmarks.registry import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_REPRODUCTION_DIR,
    RegistryError,
    emit_json,
    load_registry,
)
from pramaanx.benchmarks.reporting import (
    benchmark_report,
    registry_report,
    render_benchmark,
    render_comparison,
    render_registry_table,
    render_validation,
)
from pramaanx.benchmarks.runner import (
    BlockedExecutor,
    ReproductionRefusedError,
    ReproductionRunner,
    build_plan,
)
from pramaanx.benchmarks.schemas import BenchmarkStatus
from pramaanx.benchmarks.verification import validate_contract, verify_source

EXIT_USAGE = 1
EXIT_INVALID = 2
EXIT_BLOCKED = 3

app = typer.Typer(
    name="pramaanx-benchmarks",
    help="Benchmark registry and exact-reproduction harness (WP-B0).",
    no_args_is_help=True,
    add_completion=False,
)

RegistryOption = Annotated[
    Path,
    typer.Option("--registry", "-r", help="Path to the benchmark registry index."),
]
RunsOption = Annotated[
    Path,
    typer.Option("--runs", help="Directory of immutable run manifests."),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Emit machine-readable canonical JSON.")]
DryRunOption = Annotated[
    bool,
    typer.Option(
        "--dry-run/--execute",
        help="Plan only: no network, no clone, no download, no container, no writes.",
    ),
]
OutputOption = Annotated[
    Path | None,
    typer.Option("--output", "-o", help="Also write the JSON result here (refuses to overwrite)."),
]


def _emit(payload: dict[str, Any], human: str, *, as_json: bool, output: Path | None) -> None:
    """Print one rendering and optionally persist the JSON, never overwriting."""
    text = emit_json(payload)
    typer.echo(text if as_json else human)
    if output is not None:
        if output.exists():
            typer.echo(
                f"refusing to overwrite {output}: benchmark artefacts are immutable",
                err=True,
            )
            raise typer.Exit(code=EXIT_USAGE)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def _load(registry_path: Path) -> Any:
    try:
        return load_registry(registry_path)
    except RegistryError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=EXIT_USAGE) from error


def _contract(registry_path: Path, benchmark_id: str) -> Any:
    registry = _load(registry_path)
    try:
        return registry.get(benchmark_id)
    except KeyError as error:
        typer.echo(str(error).strip('"'), err=True)
        raise typer.Exit(code=EXIT_USAGE) from error


@app.callback()
def main_callback() -> None:
    """Benchmark contracts, source verification and reproduction runs."""


@app.command("list")
def list_benchmarks(
    registry: RegistryOption = DEFAULT_REGISTRY_PATH,
    as_json: JsonOption = False,
    status: Annotated[
        str | None, typer.Option("--status", help="Filter to one benchmark status.")
    ] = None,
    output: OutputOption = None,
) -> None:
    """List every benchmark contract, blocked ones included."""
    loaded = _load(registry)
    if status is not None:
        try:
            wanted = BenchmarkStatus(status)
        except ValueError as error:
            typer.echo(f"unknown status {status!r}", err=True)
            raise typer.Exit(code=EXIT_USAGE) from error
        loaded = type(loaded)(version=loaded.version, contracts=loaded.by_status(wanted))
    report = registry_report(loaded, loaded.validate_all())
    _emit(report, render_registry_table(report), as_json=as_json, output=output)


@app.command("validate")
def validate(
    registry: RegistryOption = DEFAULT_REGISTRY_PATH,
    runs: RunsOption = DEFAULT_REPRODUCTION_DIR,
    as_json: JsonOption = False,
    output: OutputOption = None,
) -> None:
    """Apply every strict rule to every contract. Exits non-zero if any fails."""
    loaded = _load(registry)
    store = ManifestStore(runs)
    reports = loaded.validate_all(store)
    payload = {
        "registry_hash": loaded.registry_hash(),
        "count": len(reports),
        "invalid": sorted(bid for bid, report in reports.items() if not report.is_valid),
        "reports": {bid: report.to_dict() for bid, report in sorted(reports.items())},
    }
    _emit(payload, render_validation(reports), as_json=as_json, output=output)
    if payload["invalid"]:
        raise typer.Exit(code=EXIT_INVALID)


@app.command("show")
def show(
    benchmark_id: Annotated[str, typer.Argument(help="Benchmark to display.")],
    registry: RegistryOption = DEFAULT_REGISTRY_PATH,
    runs: RunsOption = DEFAULT_REPRODUCTION_DIR,
    as_json: JsonOption = False,
    output: OutputOption = None,
) -> None:
    """Show one benchmark contract with its runs, blockers and costs."""
    contract = _contract(registry, benchmark_id)
    store = ManifestStore(runs)
    recorded = store.for_benchmark(benchmark_id)
    report = benchmark_report(contract, recorded, validate_contract(contract, recorded), None)
    _emit(report, render_benchmark(report), as_json=as_json, output=output)


@app.command("verify-source")
def verify_source_command(
    benchmark_id: Annotated[str, typer.Argument(help="Benchmark to verify.")],
    registry: RegistryOption = DEFAULT_REGISTRY_PATH,
    as_json: JsonOption = False,
    output: OutputOption = None,
) -> None:
    """Check the official source claims. Offline, and never executes fetched code."""
    contract = _contract(registry, benchmark_id)
    verification = verify_source(contract, offline=True)
    payload = verification.to_dict()
    lines = [f"{benchmark_id}: source verification (offline)"]
    for check in verification.checks:
        mark = "ok  " if check.satisfied else "MISS"
        lines.append(f"  {mark} {check.name:<34} {check.observed or '—'}")
        if not check.satisfied:
            lines.append(f"       expected: {check.detail}")
    lines.append("")
    lines.append(
        "verified" if verification.verified else f"unmet: {', '.join(verification.unmet())}"
    )
    _emit(payload, "\n".join(lines), as_json=as_json, output=output)
    if not verification.verified:
        raise typer.Exit(code=EXIT_BLOCKED)


@app.command("plan")
def plan_command(
    benchmark_id: Annotated[str, typer.Argument(help="Benchmark to plan.")],
    registry: RegistryOption = DEFAULT_REGISTRY_PATH,
    as_json: JsonOption = False,
    output: OutputOption = None,
) -> None:
    """Build a reproduction plan. Touches nothing; works for blocked benchmarks too."""
    contract = _contract(registry, benchmark_id)
    plan = build_plan(contract, probe=EnvironmentProbe())
    payload = {
        "plan": plan.canonical_dict(),
        "plan_hash": plan.plan_hash(),
        "environment_hash": plan.environment_hash(),
        "run_ids": {str(seed): plan.run_id(seed) for seed in plan.seeds},
        "blocked": plan.blocked,
    }
    lines = [
        f"{benchmark_id}: reproduction plan",
        f"  contract hash    {plan.contract_hash}",
        f"  plan hash        {plan.plan_hash()}",
        f"  official commit  {plan.official_commit or '—'}",
        f"  data             {plan.data_version or '—'} ({plan.data_hash or 'no hash'})",
        f"  command          {' '.join(plan.command) or '—'}",
        f"  seeds            {', '.join(str(seed) for seed in plan.seeds) or '—'}",
        f"  timeout          {plan.timeout_seconds}s",
        f"  environment      {plan.environment.container_image or '—'}",
    ]
    if plan.blocked:
        lines.append(f"  BLOCKED ({len(plan.blockers)}):")
        lines.extend(f"    - {blocker}" for blocker in plan.blockers)
    _emit(payload, "\n".join(lines), as_json=as_json, output=output)
    if plan.blocked:
        raise typer.Exit(code=EXIT_BLOCKED)


@app.command("reproduce")
def reproduce(
    benchmark_id: Annotated[str, typer.Argument(help="Benchmark to reproduce.")],
    registry: RegistryOption = DEFAULT_REGISTRY_PATH,
    runs: RunsOption = DEFAULT_REPRODUCTION_DIR,
    dry_run: DryRunOption = True,
    as_json: JsonOption = False,
    output: OutputOption = None,
) -> None:
    """Run an official reproduction.

    Defaults to ``--dry-run``: executing a third party's benchmark code is an
    explicit act, not something a bare command does by accident. No executor is
    configured in this package, so ``--execute`` reports the blocker rather than
    pretending to have run anything.
    """
    contract = _contract(registry, benchmark_id)
    plan = build_plan(contract, probe=EnvironmentProbe())
    store = ManifestStore(runs)
    runner = ReproductionRunner(BlockedExecutor(plan.blockers), store)
    payload: dict[str, Any] = {
        "benchmark_id": benchmark_id,
        "dry_run": dry_run,
        "plan_hash": plan.plan_hash(),
        "blocked": plan.blocked,
        "blockers": [blocker.canonical_dict() for blocker in plan.blockers],
        "would_write": [str(store.path_for(plan.run_id(seed))) for seed in plan.seeds],
        "runs": [],
    }
    lines = [f"{benchmark_id}: reproduce ({'dry run' if dry_run else 'execute'})"]
    try:
        produced = runner.run(contract, plan, dry_run=dry_run)
    except ReproductionRefusedError as error:
        payload["refused"] = str(error)
        lines.append(f"  REFUSED: {error}")
        _emit(payload, "\n".join(lines), as_json=as_json, output=output)
        raise typer.Exit(code=EXIT_BLOCKED) from error
    payload["runs"] = [run.canonical_dict() for run in produced]
    if dry_run:
        lines.append("  no network, no clone, no download, no container, no writes")
        lines.extend(f"  would write {path}" for path in payload["would_write"])
    else:
        lines.extend(f"  wrote run {run.run_id}" for run in produced)
    _emit(payload, "\n".join(lines), as_json=as_json, output=output)


@app.command("compare")
def compare_command(
    benchmark_id: Annotated[str, typer.Argument(help="Benchmark to compare.")],
    control_run: Annotated[str, typer.Option("--control-run", help="Control run id.")],
    challenger_run: Annotated[
        list[str], typer.Option("--challenger-run", help="Challenger run id (repeatable).")
    ],
    registry: RegistryOption = DEFAULT_REGISTRY_PATH,
    runs: RunsOption = DEFAULT_REPRODUCTION_DIR,
    as_json: JsonOption = False,
    output: OutputOption = None,
) -> None:
    """Decide whether a challenger exceeded a control, and say which gate refused."""
    contract = _contract(registry, benchmark_id)
    store = ManifestStore(runs)
    try:
        control = store.read(control_run)
        challengers = [store.read(run_id) for run_id in challenger_run]
    except FileNotFoundError as error:
        typer.echo(f"run manifest not found: {error}", err=True)
        raise typer.Exit(code=EXIT_USAGE) from error
    try:
        result = compare(contract, control, challengers)
    except ComparisonError as error:
        typer.echo(f"comparison refused: {error}", err=True)
        raise typer.Exit(code=EXIT_INVALID) from error
    payload = result.canonical_dict()
    _emit(payload, render_comparison(payload), as_json=as_json, output=output)
    if not result.exceeded:
        raise typer.Exit(code=EXIT_INVALID)


@app.command("report")
def report_command(
    benchmark_id: Annotated[str, typer.Argument(help="Benchmark to report on.")],
    registry: RegistryOption = DEFAULT_REGISTRY_PATH,
    runs: RunsOption = DEFAULT_REPRODUCTION_DIR,
    as_json: JsonOption = False,
    output: OutputOption = None,
) -> None:
    """Full report: contract, every run including failures, and total cost."""
    contract = _contract(registry, benchmark_id)
    store = ManifestStore(runs)
    recorded = store.for_benchmark(benchmark_id)
    report = benchmark_report(contract, recorded, validate_contract(contract, recorded))
    _emit(report, render_benchmark(report), as_json=as_json, output=output)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
