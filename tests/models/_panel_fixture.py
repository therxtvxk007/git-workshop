"""A small deterministic panel the model and verify tests share.

Three districts across two states, three families, twenty-four monthly origins.
District 101 is active, 102 is quiet, 201 is intermittent. Small enough to read
in a failure message, long enough for a twelve-month lookback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import polars as pl

from pramaanx.core.contexts import FitContext, ForecastContext, InformationProfile, OriginRole
from pramaanx.geo.roster import Roster, roster_from_districts
from pramaanx.panel.grid import PanelSpec, build_panel
from pramaanx.panel.outcomes import ObservationStatus, attach_outcomes, trainable
from pramaanx.panel.windows import CalendarContract, monthly_origins

IST = CalendarContract(timezone="Asia/Kolkata")
DISTRICTS = ("101", "102", "201")
FAMILIES = ("insurgency", "lwe", "terrorism")
AS_OF = datetime(2027, 1, 1, tzinfo=UTC)

#: Events per window, by district. Fixed rather than sampled so a failure names
#: a bug and not a seed.
PATTERN: dict[str, tuple[int, ...]] = {
    "101": (2, 1, 3, 2, 4, 1, 2, 3, 1, 2, 5, 2),
    "102": (0,) * 12,
    "201": (0, 0, 1, 0, 0, 0, 2, 0, 0, 1, 0, 0),
}


@dataclass(frozen=True)
class MiniPanel:
    panel: pl.DataFrame
    labelled: pl.DataFrame
    origins: tuple[datetime, ...]

    @property
    def issue_origin(self) -> datetime:
        return self.origins[-1]

    def issue_rows(self) -> pl.DataFrame:
        return self.panel.filter(pl.col("origin") == self.issue_origin)

    def training_rows(self, *, fit_cutoff: datetime | None = None) -> pl.DataFrame:
        return trainable(
            self.labelled.filter(pl.col("origin") < self.issue_origin),
            fit_cutoff=fit_cutoff or AS_OF,
        )

    def window(self) -> tuple[datetime, datetime]:
        rows = self.issue_rows()
        return rows["window_start"][0], rows["window_end"][0]

    def fit_context(self) -> FitContext:
        return FitContext(
            issue_time=self.issue_origin,
            cutoff_at=self.issue_origin,
            input_manifest="sha256:inputs",
            profile=InformationProfile.ENGINEERING_REPLAY,
            role=OriginRole.TRAIN,
            policy_hash="sha256:policy",
            boundary_version="fixture-v1",
            fit_cutoff=self.issue_origin,
            label_manifest="sha256:labels",
            maturation_days=14,
        )

    def forecast_context(self) -> ForecastContext:
        return self.fit_context().forecast_context()


def build(
    *, origins_count: int = 24, coverage_override: dict[str, ObservationStatus] | None = None
) -> MiniPanel:
    roster = Roster(
        versions=(
            roster_from_districts(
                "fixture-v1",
                date(2020, 1, 1),
                [("101", "bihar"), ("102", "bihar"), ("201", "odisha")],
            ),
        )
    )
    last = date(2024 + (origins_count - 1) // 12, 1 + (origins_count - 1) % 12, 1)
    origins = monthly_origins(date(2024, 1, 1), last, calendar=IST)
    spec = PanelSpec(origins=origins, roster=roster, calendar=IST, window_days=30)
    panel = build_panel(spec)

    coverage = coverage_override or dict.fromkeys(DISTRICTS, ObservationStatus.OBSERVED)
    frames = []
    for index, origin in enumerate(origins):
        counts = {
            district: dict.fromkeys(FAMILIES, PATTERN[district][index % 12])
            for district in DISTRICTS
        }
        frames.append(
            attach_outcomes(
                panel.filter(pl.col("origin") == origin),
                counts=counts,
                coverage=coverage,
                maturation_days=14,
                as_of=AS_OF,
                label_manifest="sha256:labels",
                label_available_time=origin,
            )
        )
    return MiniPanel(panel=panel, labelled=pl.concat(frames), origins=origins)
