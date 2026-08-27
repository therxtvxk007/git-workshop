"""Normalized external forecasts from ACLED CAST and VIEWS."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from pramaanx.hashing import stable_id
from pramaanx.schemas.base import Probability, UtcDatetime, VersionedModel


class GeographyLevel(StrEnum):
    COUNTRY = "country"
    ADMIN1 = "admin1"
    GRID = "grid"


class ExternalForecast(VersionedModel):
    external_forecast_id: str
    provider: str
    model_version: str
    issued_at: UtcDatetime
    horizon_start: UtcDatetime
    horizon_end: UtcDatetime
    geography_level: GeographyLevel
    geography_id: str
    event_family: str
    expected_count: float | None = Field(default=None, ge=0.0)
    occurrence_probability: Probability | None = None
    source_hash: str

    @field_validator(
        "external_forecast_id",
        "provider",
        "model_version",
        "geography_id",
        "event_family",
        "source_hash",
    )
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("external forecast identifiers and provenance cannot be blank")
        return value

    @model_validator(mode="after")
    def _check_forecast(self) -> ExternalForecast:
        if self.horizon_start < self.issued_at:
            raise ValueError("external forecast horizon cannot start before issue time")
        if self.horizon_end < self.horizon_start:
            raise ValueError("external forecast horizon end precedes start")
        if self.expected_count is None and self.occurrence_probability is None:
            raise ValueError("external forecast requires a count or probability")
        return self


def _month_window(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end


def cast_forecasts_from_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    issued_at: datetime,
    model_version: str,
    source_hash: str,
) -> list[ExternalForecast]:
    """Normalize CAST forecasts; observed outcome columns are ignored by design."""
    forecasts: list[ExternalForecast] = []
    for index, row in enumerate(rows):
        required = {"country", "admin1", "year", "month", "total_forecast"}
        missing = required - row.keys()
        if missing:
            raise ValueError(f"CAST row {index} is missing columns: {sorted(missing)}")
        year, month = int(str(row["year"])), int(str(row["month"]))
        start, end = _month_window(year, month)
        geography_id = f"{row['country']}::{row['admin1']}"
        forecasts.append(
            ExternalForecast(
                external_forecast_id=stable_id(
                    "ext", "acled-cast", model_version, geography_id, year, month
                ),
                provider="acled-cast",
                model_version=model_version,
                issued_at=issued_at,
                horizon_start=start,
                horizon_end=end,
                geography_level=GeographyLevel.ADMIN1,
                geography_id=geography_id,
                event_family="political_violence",
                expected_count=float(str(row["total_forecast"])),
                source_hash=source_hash,
            )
        )
    return forecasts


def views_forecasts_from_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    issued_at: datetime,
    model_version: str,
    source_hash: str,
    geography_id_column: str,
    year_column: str,
    month_column: str,
    expected_count_column: str | None = None,
    probability_column: str | None = None,
    geography_level: GeographyLevel = GeographyLevel.GRID,
) -> list[ExternalForecast]:
    """Normalize one explicitly mapped VIEWS release without header guessing."""
    if expected_count_column is None and probability_column is None:
        raise ValueError("map at least one VIEWS count or probability column")
    forecasts: list[ExternalForecast] = []
    for index, row in enumerate(rows):
        required = {geography_id_column, year_column, month_column}
        if expected_count_column:
            required.add(expected_count_column)
        if probability_column:
            required.add(probability_column)
        missing = required - row.keys()
        if missing:
            raise ValueError(f"VIEWS row {index} is missing columns: {sorted(missing)}")
        year, month = int(str(row[year_column])), int(str(row[month_column]))
        start, end = _month_window(year, month)
        geography_id = str(row[geography_id_column])
        forecasts.append(
            ExternalForecast(
                external_forecast_id=stable_id(
                    "ext", "views", model_version, geography_id, year, month
                ),
                provider="views",
                model_version=model_version,
                issued_at=issued_at,
                horizon_start=start,
                horizon_end=end,
                geography_level=geography_level,
                geography_id=geography_id,
                event_family="state_based_conflict",
                expected_count=(
                    float(str(row[expected_count_column])) if expected_count_column else None
                ),
                occurrence_probability=(
                    float(str(row[probability_column])) if probability_column else None
                ),
                source_hash=source_hash,
            )
        )
    return forecasts
