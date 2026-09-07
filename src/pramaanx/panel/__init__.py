"""The forecast contract: which rows exist, what counts, and what a zero means."""

from __future__ import annotations

from pramaanx.panel.families import (
    ALL_FAMILIES,
    Family,
    IncidentLabels,
    check_union_invariant,
    family_counts,
    observed_counts,
    union_count,
    union_forecast,
)
from pramaanx.panel.grid import PANEL_COLUMNS, PanelSpec, build_panel, check_panel_shape
from pramaanx.panel.outcomes import (
    OUTCOME_COLUMNS,
    MaturityStatus,
    ObservationStatus,
    attach_outcomes,
    count_in_window,
    coverage_report,
    maturity_at,
    scorable,
    trainable,
)
from pramaanx.panel.windows import (
    CAST_PERIOD_DAYS,
    CAST_PERIODS_AHEAD,
    FRIDAY,
    CalendarContract,
    Window,
    cast_periods,
    monthly_origins,
    next_friday,
    weekly_origins,
)

__all__ = [
    "ALL_FAMILIES",
    "CAST_PERIODS_AHEAD",
    "CAST_PERIOD_DAYS",
    "FRIDAY",
    "OUTCOME_COLUMNS",
    "PANEL_COLUMNS",
    "CalendarContract",
    "Family",
    "IncidentLabels",
    "MaturityStatus",
    "ObservationStatus",
    "PanelSpec",
    "Window",
    "attach_outcomes",
    "build_panel",
    "cast_periods",
    "check_panel_shape",
    "check_union_invariant",
    "count_in_window",
    "coverage_report",
    "family_counts",
    "maturity_at",
    "monthly_origins",
    "next_friday",
    "observed_counts",
    "scorable",
    "trainable",
    "union_count",
    "union_forecast",
    "weekly_origins",
]
