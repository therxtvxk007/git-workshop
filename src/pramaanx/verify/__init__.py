"""Scoring and run lints.

Separate from :mod:`pramaanx.evaluation`, which scores the existing candidate
pipeline and clips its log loss. These follow the revision plan's rules
instead: endpoints are kept, denominators travel with every number, and the
states that are not numbers stay distinguishable from zero.
"""

from __future__ import annotations

from pramaanx.verify.lints import (
    LintFinding,
    LintReport,
    check_coherence,
    check_monte_carlo_zeros,
    check_nested_windows,
    check_no_hard_zero,
    run_all,
)
from pramaanx.verify.scores import (
    Orientation,
    ScoreResult,
    ScoreState,
    brier,
    count_crps,
    log_loss,
    skill,
)

__all__ = [
    "LintFinding",
    "LintReport",
    "Orientation",
    "ScoreResult",
    "ScoreState",
    "brier",
    "check_coherence",
    "check_monte_carlo_zeros",
    "check_nested_windows",
    "check_no_hard_zero",
    "count_crps",
    "log_loss",
    "run_all",
    "skill",
]
