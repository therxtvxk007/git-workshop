"""The composed offline run, and the store maintenance it depends on.

``offline run`` is the plan's first deliverable: a reproducible engineering run
over generated evidence, start to finish, with no network and no credentials
(S41). It is not a forecast of anything real and the manifest says so.

``store recover`` and ``store verify`` are the other half of that promise. A
pipeline whose crash recovery has never been exercised does not have crash
recovery; these make it a command a person can run rather than a claim.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from pramaanx.cli._app import OutputOption, _emit, app
from pramaanx.core.asof import RevisionStore
from pramaanx.panel.windows import CalendarContract
from pramaanx.runtime.offline import OfflineSpec, run_offline
from pramaanx.simlab.generators import WorldSpec

offline_app = typer.Typer(
    help="Composed offline runs over generated evidence.", no_args_is_help=True
)
store_app = typer.Typer(help="Inspect and recover the as-of revision store.", no_args_is_help=True)
app.add_typer(offline_app, name="offline")
app.add_typer(store_app, name="store")

RootOption = Annotated[Path, typer.Option("--root", help="Directory to write the run into.")]


@offline_app.command("run")
def offline_run(
    root: RootOption = Path("runs/offline"),
    seed: Annotated[int, typer.Option("--seed", help="Root seed for every stream.")] = 0,
    origins: Annotated[int, typer.Option("--origins", help="Monthly origins to build.")] = 16,
    window_days: Annotated[int, typer.Option("--window-days")] = 30,
    maturation_days: Annotated[int, typer.Option("--maturation-days")] = 14,
    outage: Annotated[
        str | None,
        typer.Option("--outage", help="District to mark unavailable, to exercise missingness."),
    ] = None,
    output: OutputOption = None,
) -> None:
    """Run the ladder end to end on a generated world. Offline, deterministic."""
    world = WorldSpec(
        districts=(("101", "bihar"), ("102", "bihar"), ("201", "odisha")),
        start=date(2024, 1, 1),
        days=31 * (origins + 2),
        rates={"101": 0.08, "102": 0.0, "201": 0.02},
        delays={"101": 3.0, "102": 0.0, "201": 9.0},
        calendar=CalendarContract(timezone="Asia/Kolkata"),
    )
    report = run_offline(
        root,
        OfflineSpec(
            world=world,
            seed=seed,
            n_origins=origins,
            window_days=window_days,
            maturation_days=maturation_days,
            unavailable_districts=(outage,) if outage else (),
        ),
    )
    _emit(
        {
            "kind": "offline_run",
            "synthetic": True,
            "claim": (
                "engineering reproducibility only; this is a generated world "
                "and says nothing about forecasting skill on real evidence"
            ),
            **report.to_dict(),
        },
        output,
    )


@store_app.command("recover")
def store_recover(
    root: RootOption = Path("runs/offline"),
    apply: Annotated[
        bool, typer.Option("--apply", help="Delete the litter rather than only report it.")
    ] = False,
    output: OutputOption = None,
) -> None:
    """Classify what a crash left behind. Deletes litter only, never data."""
    report = RevisionStore(Path(root) / "store").recover(dry_run=not apply)
    _emit({"kind": "store_recover", **report.to_dict()}, output)


@store_app.command("verify")
def store_verify(
    root: RootOption = Path("runs/offline"),
    manifest: Annotated[
        str | None, typer.Option("--manifest", help="Manifest hash. Defaults to the head.")
    ] = None,
    output: OutputOption = None,
) -> None:
    """Replay a pinned manifest and confirm every blob still matches its hash."""
    store = RevisionStore(Path(root) / "store")
    target = manifest or store.head
    if target is None:
        _emit({"kind": "store_verify", "verified": False, "detail": "the store is empty"}, output)
        raise typer.Exit(code=1)

    tables = store.replay(target)
    _emit(
        {
            "kind": "store_verify",
            "verified": True,
            "manifest": target,
            "tables": {name: frame.height for name, frame in sorted(tables.items())},
        },
        output,
    )
