"""Outcomes, and the difference between a zero and a gap.

The paper's phrase "explicit zero-risk rows" was ambiguous and the plan's review
found the ambiguity (S4, S26.1 defect 5). It means a row with **zero observed
events**. It never means a forecast probability of zero. So the column is
``y_observed`` and no row may carry ``p_occ == 0``; the probability half of that
rule is enforced in :mod:`pramaanx.verify`.

The other half is here, and it is the more dangerous one. ``fillna(0)`` over a
panel turns four different situations into the same number:

* a district that was observed and had no incidents -- a real zero;
* a district whose source release never arrived -- unknown;
* a district whose parser failed -- unknown, and a bug;
* a district nobody covers in that language -- unknown, and a coverage gap.

Only the first is a label. So ``y_observed`` is nullable, and observation and
maturity are separate fields rather than something inferred from a missing
value (S31.1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum

import polars as pl

from pramaanx.core.errors import ContractViolationError
from pramaanx.panel.families import IncidentLabels, check_union_invariant, family_counts
from pramaanx.panel.windows import Window

OUTCOME_COLUMNS: tuple[str, ...] = (
    "y_observed",
    "observation_status",
    "maturity_status",
    "label_manifest",
    "label_available_time",
)


class ObservationStatus(StrEnum):
    """Whether this row was observed at all, and how completely."""

    #: Covered for the whole window. A count of zero here is a real zero.
    OBSERVED = "observed"
    #: Covered for part of the window. A count is a lower bound, not a label.
    PARTIAL = "partial"
    #: No usable coverage: an outage, a missing release, a failed parser.
    UNAVAILABLE = "unavailable"
    #: The row is outside the target definition -- a district not in this
    #: family's eligible geography, say.
    NOT_APPLICABLE = "not_applicable"


class MaturityStatus(StrEnum):
    """Whether enough time has passed under the frozen maturation rule.

    Mature means old enough. It does not mean complete: late reporting is a
    measurement problem the delay model addresses, and calling a matured row
    "true" would hide it.
    """

    IMMATURE = "immature"
    MATURE = "mature"


def maturity_at(window: Window, *, maturation_days: int, as_of: datetime) -> MaturityStatus:
    """Maturity measured from the window's end, never from the origin."""
    return (
        MaturityStatus.MATURE
        if as_of >= window.matures_at(maturation_days)
        else MaturityStatus.IMMATURE
    )


def count_in_window(
    incidents: Iterable[IncidentLabels],
    *,
    window: Window,
    instants: Mapping[str, datetime],
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Per-district family counts and union counts inside one half-open window.

    Returns ``({district: {family: count}}, {district: union})``. The union is
    computed by deduplicating incidents across families, never by summing, and
    the invariant is checked for every district before returning.
    """
    inside = [
        incident
        for incident in incidents
        if incident.incident_id in instants and window.contains(instants[incident.incident_id])
    ]

    by_district: dict[str, list[IncidentLabels]] = {}
    for incident in inside:
        by_district.setdefault(incident.district_id, []).append(incident)

    counts: dict[str, dict[str, int]] = {}
    unions: dict[str, int] = {}
    for district, rows in sorted(by_district.items()):
        per_family = family_counts(rows)
        union = len({row.incident_id for row in rows})
        check_union_invariant(per_family, union)
        counts[district] = {str(family): value for family, value in per_family.items()}
        unions[district] = union
    return counts, unions


def attach_outcomes(
    panel: pl.DataFrame,
    *,
    counts: Mapping[str, Mapping[str, int]],
    coverage: Mapping[str, ObservationStatus],
    maturation_days: int,
    as_of: datetime,
    label_manifest: str,
    label_available_time: datetime,
) -> pl.DataFrame:
    """Attach labels to a built panel, leaving unobserved rows null.

    ``coverage`` is keyed by district and is required to be total: a district
    the caller forgot to describe is not silently observed. That is the check
    that stops a parser failure from becoming a quiet run of zeros.
    """
    if panel.is_empty():
        raise ContractViolationError("cannot attach outcomes to an empty panel")

    districts = set(panel["district_id"].to_list())
    undescribed = sorted(districts - set(coverage))
    if undescribed:
        raise ContractViolationError(
            "coverage status is missing for some districts; an undescribed "
            "district must not default to observed",
            districts=undescribed[:10],
            missing=len(undescribed),
        )

    def _label(district: str, family: str, status: ObservationStatus) -> int | None:
        if status is not ObservationStatus.OBSERVED:
            return None
        return int(counts.get(district, {}).get(family, 0))

    statuses = [coverage[district] for district in panel["district_id"].to_list()]
    labels = [
        _label(district, family, status)
        for district, family, status in zip(
            panel["district_id"].to_list(), panel["family"].to_list(), statuses, strict=True
        )
    ]
    maturities = [
        maturity_at(Window(start, end), maturation_days=maturation_days, as_of=as_of)
        for start, end in zip(
            panel["window_start"].to_list(), panel["window_end"].to_list(), strict=True
        )
    ]

    return panel.with_columns(
        pl.Series("y_observed", labels, dtype=pl.Int64),
        pl.Series("observation_status", [str(status) for status in statuses], dtype=pl.Utf8),
        pl.Series("maturity_status", [str(status) for status in maturities], dtype=pl.Utf8),
        pl.lit(label_manifest).alias("label_manifest"),
        pl.lit(label_available_time).alias("label_available_time"),
    )


def trainable(panel: pl.DataFrame, *, fit_cutoff: datetime) -> pl.DataFrame:
    """Rows a fit may learn from.

    Three conditions, all required (S31.1): the row was observed, its label is
    mature under the frozen rule, and that label's exact revision was already
    available when the fit ran. The third is the one that gets forgotten, and
    it is the one that lets a fit read a correction from the future.
    """
    return panel.filter(
        (pl.col("observation_status") == str(ObservationStatus.OBSERVED))
        & (pl.col("maturity_status") == str(MaturityStatus.MATURE))
        & (pl.col("label_available_time") <= fit_cutoff)
        & pl.col("y_observed").is_not_null()
    )


def scorable(panel: pl.DataFrame) -> pl.DataFrame:
    """Rows a metric may be computed over. Everything else is a denominator."""
    return panel.filter(
        (pl.col("observation_status") == str(ObservationStatus.OBSERVED))
        & (pl.col("maturity_status") == str(MaturityStatus.MATURE))
        & pl.col("y_observed").is_not_null()
    )


def coverage_report(panel: pl.DataFrame) -> dict[str, int]:
    """How many rows fall into each status. Belongs in every run manifest.

    A score computed over 60% of the panel is a different claim from one
    computed over all of it, and the only way a reader can tell is if the
    denominator travels with the number.
    """
    counts = (
        panel.group_by("observation_status").agg(pl.len().alias("rows")).sort("observation_status")
    )
    report = {str(row["observation_status"]): int(row["rows"]) for row in counts.to_dicts()}
    report["total"] = panel.height
    report["scorable"] = scorable(panel).height
    return dict(sorted(report.items()))
