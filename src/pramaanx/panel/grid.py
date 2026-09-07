"""The complete forecast panel: every district x family x origin row exists.

A panel with missing rows is a panel that has quietly decided some districts
are not worth forecasting, and a model evaluated on it is being scored on a
selection nobody wrote down. So the grid is built from the roster, not from the
evidence.

The one change the revision makes to this (S31.1): the row count is validated
against the *sum of per-origin roster sizes*, not against a constant Cartesian
product. A district that was notified in 2022 does not exist at a 2019 origin,
and forcing a constant roster would either invent it early or drop it late. A
fixed analysis geography still validates as a constant, because then every
origin's roster is the same one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

from pramaanx.core.errors import ContractViolationError
from pramaanx.geo.roster import Roster
from pramaanx.hashing import hash_object, utc_isoformat
from pramaanx.panel.families import ALL_FAMILIES, Family
from pramaanx.panel.windows import CalendarContract, Window

PANEL_COLUMNS: tuple[str, ...] = (
    "origin",
    "district_id",
    "state_id",
    "family",
    "boundary_version",
    "window_start",
    "window_end",
)


@dataclass(frozen=True)
class PanelSpec:
    """What a panel build needs, and nothing that a model would choose."""

    origins: tuple[datetime, ...]
    roster: Roster
    calendar: CalendarContract
    window_days: int
    families: tuple[Family, ...] = ALL_FAMILIES

    def __post_init__(self) -> None:
        if not self.origins:
            raise ContractViolationError("a panel needs at least one origin")
        if self.window_days <= 0:
            raise ContractViolationError("window_days must be positive")
        if not self.families:
            raise ContractViolationError("a panel needs at least one family")
        if list(self.origins) != sorted(self.origins):
            raise ContractViolationError("origins must be given in chronological order")

    def window_for(self, origin: datetime) -> Window:
        """The outcome window an origin forecasts.

        Starts at the origin's own local day: the window is what happens
        *after* the forecast is issued.
        """
        start_day = self.calendar.local_date(origin)
        return self.calendar.window(start_day, self.window_days)

    def expected_rows(self) -> int:
        """Sum over origins of that origin's roster size, times families."""
        return sum(
            len(self.roster.codes_on(self.calendar.local_date(origin))) for origin in self.origins
        ) * len(self.families)

    def identity(self) -> str:
        return hash_object(
            {
                "origins": [utc_isoformat(origin) for origin in self.origins],
                "families": [str(family) for family in self.families],
                "window_days": self.window_days,
                "calendar": self.calendar.identity(),
                "boundary_versions": [version.version for version in self.roster.versions],
            }
        )


def build_panel(spec: PanelSpec) -> pl.DataFrame:
    """The full grid. Deterministic order, no outcome columns.

    Outcomes are attached separately (:mod:`pramaanx.panel.outcomes`) so that
    building the grid cannot accidentally become the step that invents a label.
    """
    rows: list[dict[str, object]] = []
    for origin in spec.origins:
        day = spec.calendar.local_date(origin)
        version = spec.roster.in_force_on(day)
        window = spec.window_for(origin)
        for district in sorted(version.districts, key=lambda d: d.district_id):
            for family in spec.families:
                rows.append(
                    {
                        "origin": origin,
                        "district_id": district.district_id,
                        "state_id": district.state_id,
                        "family": str(family),
                        "boundary_version": version.version,
                        "window_start": window.start,
                        "window_end": window.end,
                    }
                )

    frame = pl.DataFrame(rows).select(PANEL_COLUMNS)
    check_panel_shape(frame, spec)
    return frame.sort(["origin", "district_id", "family"])


def check_panel_shape(frame: pl.DataFrame, spec: PanelSpec) -> None:
    """Every expected row present, exactly once."""
    expected = spec.expected_rows()
    if frame.height != expected:
        raise ContractViolationError(
            "panel row count does not match the roster",
            expected=expected,
            found=frame.height,
        )
    keys = frame.select(["origin", "district_id", "family"])
    if keys.n_unique() != frame.height:
        raise ContractViolationError(
            "the panel contains duplicate logical rows",
            rows=frame.height,
            distinct=keys.n_unique(),
        )
