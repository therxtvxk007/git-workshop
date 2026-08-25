"""Rendering backtest reports.

Reports are written twice: canonical JSON for machines and Markdown for people.
Both are deterministic, and both lead with what the numbers do not mean. A
report that states a Brier score without stating that nothing was calibrated is
a report that will eventually be quoted without its caveats.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pramaanx.evaluation.backtest import BacktestReport
from pramaanx.hashing import canonical_json
from pramaanx.logging import get_logger

log = get_logger(__name__)


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(report: BacktestReport) -> str:
    """Human-readable summary, deterministic given the report."""
    spec = report.experiment
    aggregate = report.aggregate
    pooled = aggregate["pooled"]
    registry = aggregate["outcome_registry"]

    lines: list[str] = [
        f"# Backtest: {spec.name}",
        "",
        f"- Run id: `{report.run_id}`",
        f"- Report hash: `{report.report_hash}`",
        f"- Config hash: `{report.settings.config_hash}`",
        f"- Code hash: `{report.provenance['code_hash']}`",
        f"- Window: {spec.start.date()} to {spec.end.date()}, every {spec.step_days}d, "
        f"horizon {spec.horizon_days}d",
        f"- Folds: {aggregate['folds']} | forecasts: {aggregate['forecasts']} | "
        f"outcomes scored: {aggregate['outcomes_scored']}",
        "",
        "## What these numbers are not",
        "",
    ]
    lines.extend(f"- {limit}" for limit in aggregate["interpretation_limits"])
    lines.extend(
        [
            "",
            "## Discovery",
            "",
            f"- Candidate recall (mean across folds): {_fmt(aggregate['candidate_recall']['mean'])}",
            f"- Range: {_fmt(aggregate['candidate_recall']['min'])} to "
            f"{_fmt(aggregate['candidate_recall']['max'])} "
            f"over {aggregate['candidate_recall']['folds_with_outcomes']} scored folds",
            "",
            "## Probability quality (pooled)",
            "",
            f"- Brier: {_fmt(pooled['brier'])} (base rate {_fmt(pooled['base_rate'])})",
            f"- ROC AUC (ranking quality): {_fmt(pooled['roc_auc'])}",
            f"- Brier skill vs base rate: {_fmt(pooled['brier_skill_score'])}",
            f"- Log loss: {_fmt(pooled['log_loss'])}",
            f"- Expected calibration error: {_fmt(pooled['expected_calibration_error'])}",
            f"- Calibration slope / intercept: {_fmt(pooled['calibration_slope'])} / "
            f"{_fmt(pooled['calibration_intercept'])}",
            "",
            "## Outcome registry",
            "",
            f"- Outcomes: {registry['total']}",
            f"- Unadjudicated fraction: {_fmt(registry['unadjudicated_fraction'])}",
            f"- Matches queued for human review: {aggregate['human_review_queue']}",
            "",
            "## Folds",
            "",
            "| cutoff | obs | forecasts | outcomes | cand. recall | brier | alerts |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for fold in report.folds:
        data = fold.to_dict()
        lines.append(
            f"| {data['cutoff_at'][:10]} | {data['observations']} | {data['forecasts']} | "
            f"{data['outcomes_in_window']} | "
            f"{_fmt(data['metrics']['discovery']['candidate_recall'])} | "
            f"{_fmt(data['metrics']['probability']['brier'])} | "
            f"{data['metrics']['alerts']['count']} |"
        )
    lines.extend(
        [
            "",
            "## Reliability curve (pooled)",
            "",
            "| predicted | observed | n |",
            "| ---: | ---: | ---: |",
        ]
    )
    for entry in pooled["reliability_curve"]:
        lines.append(
            f"| {_fmt(entry['mean_predicted'])} | {_fmt(entry['observed_frequency'])} | "
            f"{entry['count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: BacktestReport, run_root: Path) -> dict[str, Path]:
    """Write ``report.json`` and ``report.md`` under ``runs/<run_id>/``."""
    target = Path(run_root) / report.run_id
    target.mkdir(parents=True, exist_ok=True)

    json_path = target / "report.json"
    json_path.write_text(canonical_json(report.to_dict()), encoding="utf-8")

    markdown_path = target / "report.md"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    log.info("report.written", run_id=report.run_id, path=str(target))
    return {"json": json_path, "markdown": markdown_path, "directory": target}
