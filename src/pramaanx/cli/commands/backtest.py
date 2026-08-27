"""Rolling-origin backtesting."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pramaanx.cli._app import (
    DryRunOption,
    OutputOption,
    _emit,
    app,
)
from pramaanx.hashing import utc_isoformat
from pramaanx.logging import configure_logging


@app.command()
def backtest(
    experiment: Annotated[Path, typer.Option("--experiment", help="Experiment YAML.")],
    dry_run: DryRunOption = False,
    output: OutputOption = None,
) -> None:
    """Run a rolling-cutoff backtest and write its report."""
    from pramaanx.evaluation.backtest import Backtester, load_experiment
    from pramaanx.evaluation.reports import write_report

    spec, settings = load_experiment(experiment)
    configure_logging(settings.log_level, settings.log_format)
    if dry_run:
        _emit(
            {
                "kind": "backtest_plan",
                "dry_run": True,
                "experiment": spec.fingerprint(),
                "cutoffs": [utc_isoformat(moment) for moment in spec.cutoffs()],
                "config_hash": settings.config_hash,
            },
            output,
        )
        return

    report = Backtester(settings).run(spec)
    paths = write_report(report, settings.storage.run_root)
    _emit(
        {
            "kind": "backtest",
            "run_id": report.run_id,
            "report_hash": report.report_hash,
            "folds": report.aggregate["folds"],
            "forecasts": report.aggregate["forecasts"],
            "outcomes_scored": report.aggregate["outcomes_scored"],
            "candidate_recall_mean": report.aggregate["candidate_recall"]["mean"],
            "pooled_brier": report.aggregate["pooled"]["brier"],
            "interpretation_limits": report.aggregate["interpretation_limits"],
            "report_json": str(paths["json"]),
            "report_markdown": str(paths["markdown"]),
        },
        output,
    )
