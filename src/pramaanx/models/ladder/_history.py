"""Shared history extraction for the ladder.

Every rung needs the same three numbers per district-family: how many events
were observed, over how many windows, and how long a window is. Computing them
once, from the *trainable* rows only, keeps every rung honest about the same
eligibility rule rather than each re-deriving it slightly differently.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from pramaanx.core.errors import ContractViolationError
from pramaanx.models.samples import PanelKey

REQUIRED_COLUMNS: tuple[str, ...] = (
    "origin",
    "district_id",
    "family",
    "window_start",
    "window_end",
)


@dataclass(frozen=True)
class History:
    """Observed history for one panel cell."""

    key: PanelKey
    total_events: int
    windows: int
    window_days: float
    #: Window counts, oldest first. What an empirical distribution needs.
    counts: tuple[int, ...]

    @property
    def rate_per_day(self) -> float:
        """Long-run events per day. Zero windows means no estimate, not zero."""
        exposure = self.windows * self.window_days
        return self.total_events / exposure if exposure > 0 else 0.0


def require_columns(frame: pl.DataFrame, extra: tuple[str, ...] = ()) -> None:
    missing = sorted(set(REQUIRED_COLUMNS + extra) - set(frame.columns))
    if missing:
        raise ContractViolationError("panel frame is missing required columns", missing=missing)


def build_history(trainable_panel: pl.DataFrame) -> dict[tuple[str, str], History]:
    """History per district-family, from rows already filtered for eligibility."""
    require_columns(trainable_panel, ("y_observed",))
    if trainable_panel.is_empty():
        return {}

    ordered = trainable_panel.sort(["district_id", "family", "origin"])
    histories: dict[tuple[str, str], History] = {}
    for (district, family), group in ordered.group_by(
        ["district_id", "family"], maintain_order=True
    ):
        counts = [int(value) for value in group["y_observed"].to_list() if value is not None]
        span = group.select(
            ((pl.col("window_end") - pl.col("window_start")).dt.total_seconds() / 86400.0).alias(
                "days"
            )
        )["days"].mean()
        histories[(str(district), str(family))] = History(
            key=PanelKey(district_id=str(district), family=str(family)),
            total_events=sum(counts),
            windows=len(counts),
            window_days=float(span) if span is not None else 0.0,  # type: ignore[arg-type]
            counts=tuple(counts),
        )
    return histories


def issue_keys(issue_rows: pl.DataFrame) -> tuple[PanelKey, ...]:
    """Panel keys in a fixed order, so draws line up with rows deterministically."""
    require_columns(issue_rows)
    ordered = issue_rows.sort(["district_id", "family"])
    return tuple(
        PanelKey(district_id=str(district), family=str(family))
        for district, family in zip(
            ordered["district_id"].to_list(), ordered["family"].to_list(), strict=True
        )
    )


def issue_window(issue_rows: pl.DataFrame) -> tuple[object, object]:
    """The one window an issue batch forecasts.

    Every row in a batch shares an origin and therefore a window. A batch that
    does not is two batches, and merging them would produce one artifact
    claiming a window half its rows do not have.
    """
    require_columns(issue_rows)
    starts = set(issue_rows["window_start"].to_list())
    ends = set(issue_rows["window_end"].to_list())
    if len(starts) != 1 or len(ends) != 1:
        raise ContractViolationError(
            "an issue batch must share one outcome window",
            distinct_starts=len(starts),
            distinct_ends=len(ends),
        )
    return starts.pop(), ends.pop()
