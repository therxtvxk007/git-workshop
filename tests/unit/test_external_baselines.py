from __future__ import annotations

from datetime import UTC, datetime

from pramaanx.outcomes import cast_forecasts_from_rows, views_forecasts_from_rows

ISSUED = datetime(2026, 7, 1, tzinfo=UTC)


def test_cast_observed_outcomes_are_never_copied_into_forecast() -> None:
    forecasts = cast_forecasts_from_rows(
        [
            {
                "country": "India",
                "admin1": "Chhattisgarh",
                "year": 2026,
                "month": 8,
                "total_forecast": 12,
                "total_observed": 999999,
            }
        ],
        issued_at=ISSUED,
        model_version="cast@2026-07",
        source_hash="sha256:cast",
    )
    assert forecasts[0].expected_count == 12
    assert "observed" not in forecasts[0].model_dump_json()


def test_views_columns_must_be_explicitly_mapped() -> None:
    forecasts = views_forecasts_from_rows(
        [{"priogrid_gid": 123, "year": 2026, "month": 8, "prob": 0.2}],
        issued_at=ISSUED,
        model_version="fatalities003_2026_06_t01",
        source_hash="sha256:views",
        geography_id_column="priogrid_gid",
        year_column="year",
        month_column="month",
        probability_column="prob",
    )
    assert forecasts[0].occurrence_probability == 0.2
