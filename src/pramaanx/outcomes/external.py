"""ACLED CAST and VIEWS forecasts, as benchmarks and nothing else.

Two systems already publish subnational conflict forecasts covering India.
Beating a district base rate is a low bar; beating a funded, peer-reviewed
forecaster that publishes on a schedule is the claim that would actually mean
something, so both are mandatory rungs on the baseline ladder rather than
optional extras.

The whole design problem here is keeping them on the right side of one line.
An external forecast may be:

* a baseline the system is scored against;
* a feature the ensemble is allowed to use, subject to publication time.

It may never be a label. :func:`assert_not_used_as_labels` exists because the
mistake is one import away: the records have a district, a horizon and a
number, so they will happily flow into anything that expects outcomes, and the
resulting metrics would show a system that has learned to reproduce CAST.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from pramaanx.geography.resolver import DistrictResolver, Resolution
from pramaanx.schemas.district_panel import DistrictIncident, ExternalForecastRecord


class ExternalForecastError(ValueError):
    """An external forecast row could not be normalised, or was misused."""


def _parse_moment(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ExternalForecastError(f"{field_name} must be timezone-aware")
        return value.astimezone(UTC)
    text = str(value).strip()
    if not text:
        raise ExternalForecastError(f"{field_name} is empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ExternalForecastError(f"{field_name} is not ISO-8601: {text!r}") from error
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _optional_float(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ExternalForecastError(f"{key} is not numeric: {value!r}") from error


def normalise_cast_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    resolver: DistrictResolver,
    provider_version: str,
    retrieved_at: datetime,
    licence: str = "ACLED terms of use",
    strict: bool = False,
) -> list[ExternalForecastRecord]:
    """Normalise ACLED CAST rows.

    CAST forecasts a calendar month, so the horizon is the month itself and the
    cutoff is the moment the forecast was made -- which is *before* the month
    starts but *after* the previous month's data closed. Both are carried
    verbatim from the export; deriving one from the other would put the cutoff
    wherever the arithmetic happened to land.

    ``strict`` is False by default here, unlike the outcome normalisers: a CAST
    row that cannot be placed is a missing benchmark point, which weakens a
    comparison. A dropped *outcome* row is a manufactured negative, which
    corrupts the target. The two failures do not deserve the same default.
    """
    return _normalise_external(
        rows,
        resolver=resolver,
        provider="acled_cast",
        provider_version=provider_version,
        retrieved_at=retrieved_at,
        licence=licence,
        strict=strict,
        district_key="admin2",
        state_key="admin1",
        probability_key="probability",
        count_key="prediction",
    )


def normalise_views_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    resolver: DistrictResolver,
    provider_version: str,
    retrieved_at: datetime,
    licence: str = "CC BY 4.0",
    strict: bool = False,
) -> list[ExternalForecastRecord]:
    """Normalise VIEWS rows.

    VIEWS predicts on its own PRIO-GRID and country-month units; a district-level
    comparison needs its export already aggregated to ADM2, which is why this
    reads district names rather than grid cells. If an export carries grid ids
    instead, aggregate it before calling here -- doing it inside this function
    would hide an area-weighting choice inside a normaliser.
    """
    return _normalise_external(
        rows,
        resolver=resolver,
        provider="views",
        provider_version=provider_version,
        retrieved_at=retrieved_at,
        licence=licence,
        strict=strict,
        district_key="adm_2",
        state_key="adm_1",
        probability_key="probability",
        count_key="expected_count",
    )


def _normalise_external(
    rows: Iterable[Mapping[str, Any]],
    *,
    resolver: DistrictResolver,
    provider: str,
    provider_version: str,
    retrieved_at: datetime,
    licence: str,
    strict: bool,
    district_key: str,
    state_key: str,
    probability_key: str,
    count_key: str,
) -> list[ExternalForecastRecord]:
    records: list[ExternalForecastRecord] = []
    for index, row in enumerate(rows):
        try:
            cutoff_at = _parse_moment(row.get("cutoff_at"), field_name="cutoff_at")
            horizon_start = _parse_moment(row.get("horizon_start"), field_name="horizon_start")
            horizon_end = _parse_moment(row.get("horizon_end"), field_name="horizon_end")
            published_at = _parse_moment(row.get("published_at"), field_name="published_at")
            family = str(row.get("event_family") or "").strip()
            if not family:
                raise ExternalForecastError("event_family is required")
            district_name = str(row.get(district_key) or "").strip()
            state_name = str(row.get(state_key) or "").strip() or None
            placed = resolver.resolve(district_name, moment=cutoff_at, state_name=state_name)
            if not isinstance(placed, Resolution):
                raise ExternalForecastError(f"could not place {district_name!r} ({placed.reason})")
            records.append(
                ExternalForecastRecord(
                    provider=provider,
                    provider_version=provider_version,
                    district_id=placed.district_id,
                    cutoff_at=cutoff_at,
                    horizon_start=horizon_start,
                    horizon_end=horizon_end,
                    event_family=family,
                    predicted_probability=_optional_float(row, probability_key),
                    predicted_count=_optional_float(row, count_key),
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    licence=licence,
                )
            )
        except (ExternalForecastError, ValueError) as error:
            if strict:
                raise ExternalForecastError(f"{provider} row {index}: {error}") from error
            continue
    return sorted(
        records,
        key=lambda item: (item.cutoff_at, item.district_id, item.event_family),
    )


def assert_not_used_as_labels(records: Sequence[object]) -> None:
    """Refuse a collection that mixes external forecasts into outcome data.

    Called wherever incidents are accepted. The check is cheap and the failure
    it prevents is not detectable by any metric: a panel labelled from CAST
    scores beautifully and means nothing.
    """
    offenders = [record for record in records if isinstance(record, ExternalForecastRecord)]
    if offenders:
        raise ExternalForecastError(
            f"{len(offenders)} external forecast records were passed where outcomes were "
            f"expected (first: {offenders[0].provider}/{offenders[0].district_id}). "
            "An external forecast is a benchmark and may be a feature; it is never a label."
        )


def available_at(
    records: Iterable[ExternalForecastRecord], *, moment: datetime
) -> list[ExternalForecastRecord]:
    """The subset that had been published by ``moment``.

    The join key people reach for is the cutoff, and it is wrong: CAST for
    March is released in March, so joining on cutoff hands the ensemble a
    March forecast at a 1 March cutoff it could not have had.
    """
    return [record for record in records if record.is_available_at(moment)]


def benchmark_alignment(
    records: Sequence[ExternalForecastRecord],
    incidents: Sequence[DistrictIncident],
    *,
    tolerance: timedelta = timedelta(days=1),
) -> dict[str, Any]:
    """How much of the external benchmark can actually be scored here.

    A benchmark covering a different district universe or a different horizon
    is not a comparison, and reporting a headline against it without saying so
    is the quietest way to claim an improvement that was never measured.
    """
    covered = {incident.district_id for incident in incidents}
    horizons = {
        round((record.horizon_end - record.horizon_start).total_seconds() / 86400.0)
        for record in records
    }
    districts = {record.district_id for record in records}
    return {
        "records": len(records),
        "providers": sorted({record.provider for record in records}),
        "districts": len(districts),
        "districts_without_outcome_history": len(districts - covered),
        "horizon_lengths_days": sorted(horizons),
        "horizon_is_uniform": len(horizons) <= 1,
        "tolerance_days": tolerance.total_seconds() / 86400.0,
    }
