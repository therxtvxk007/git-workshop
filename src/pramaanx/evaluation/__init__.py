"""Backtesting, matching and metrics.

M0 provides the rolling-cutoff skeleton and the metrics that the implemented
components can honestly support. The counterfactual track (entity replacement,
date shifts), the prospective forecast ledger and the candidate-oracle
diagnostic are later phases; naming them here rather than approximating them
keeps the reports from implying evidence that does not exist.
"""

from __future__ import annotations

from pramaanx.evaluation.backtest import (
    Backtester,
    BacktestReport,
    ExperimentSpec,
    FoldResult,
    load_experiment,
    outcomes_in_window,
)
from pramaanx.evaluation.matcher import MatchContext, OutcomeMatcher
from pramaanx.evaluation.reports import render_markdown, write_report

__all__ = [
    "BacktestReport",
    "Backtester",
    "ExperimentSpec",
    "FoldResult",
    "MatchContext",
    "OutcomeMatcher",
    "load_experiment",
    "outcomes_in_window",
    "render_markdown",
    "write_report",
]
