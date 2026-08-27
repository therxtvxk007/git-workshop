"""Building the district x cutoff x family outcome panel.

The panel is a rectangle with no holes. For each cutoff, every district in the
universe *in effect at that cutoff* gets a row for every configured family,
whether or not anything happened there. The zero rows are not padding: they are
the negative class, they outnumber the positives by two or three orders of
magnitude, and a panel that only contains districts with incidents teaches a
model that incidents are universal.

Three rules keep the rectangle honest.

**The universe is as of the cutoff.** Not today's district list. A district
created after the cutoff has no row, and a district abolished before it has no
row either. This is what makes a later boundary change unable to alter an
earlier panel.

**Membership is decided on occurrence time; knowability is separate.** An
incident belongs to the window ``(cutoff, cutoff + horizon]`` by when it
happened. Whether the label may be *scored* is decided by ``label_settles_at``.
Conflating the two either leaks (score early, using reports that had not
arrived) or silently deletes real incidents (require knowability for
membership, and every late-reported attack becomes a quiet district).

**Failure to place is not absence.** A cutoff-window with unplaceable incidents
is marked, not zeroed.

Building the panel touches outcome data, so it is refused inside a forecasting
pass by the same guard that protects every other outcome read.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pramaanx.geography.registry import DistrictRegistry, GeographyError
from pramaanx.isolation import guard_outcome_access
from pramaanx.outcomes.reporting_delay import ReportingDelayPolicy
from pramaanx.schemas.district_panel import (
    DistrictIncident,
    DistrictPanelRow,
    LabelStatus,
    UnplacedIncident,
)


class PanelError(ValueError):
    """The panel could not be built as specified."""


@dataclass
class PanelReport:
    """Shape and health of the panel, emitted with every build."""

    cutoffs: int = 0
    districts: int = 0
    families: int = 0
    rows: int = 0
    positive_rows: int = 0
    resolved_rows: int = 0
    censored_rows: int = 0
    pending_rows: int = 0
    unresolved_location_rows: int = 0
    incidents_in_scope: int = 0
    incidents_outside_every_window: int = 0
    incidents_in_unknown_districts: int = 0
    base_rate_by_family: dict[str, float] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "cutoffs": self.cutoffs,
            "districts": self.districts,
            "families": self.families,
            "rows": self.rows,
            "positive_rows": self.positive_rows,
            "resolved_rows": self.resolved_rows,
            "censored_rows": self.censored_rows,
            "pending_rows": self.pending_rows,
            "unresolved_location_rows": self.unresolved_location_rows,
            "incidents_in_scope": self.incidents_in_scope,
            "incidents_outside_every_window": self.incidents_outside_every_window,
            "incidents_in_unknown_districts": self.incidents_in_unknown_districts,
            "base_rate_by_family": dict(sorted(self.base_rate_by_family.items())),
        }


@dataclass(frozen=True)
class PanelResult:
    rows: tuple[DistrictPanelRow, ...]
    report: PanelReport


def build_district_panel(
    *,
    registry: DistrictRegistry,
    incidents: Sequence[DistrictIncident],
    cutoffs: Iterable[datetime],
    event_families: Sequence[str],
    horizon_days: int,
    as_of: datetime,
    datasets: Sequence[str],
    delay_policy: ReportingDelayPolicy | None = None,
    unplaced: Sequence[UnplacedIncident] = (),
) -> PanelResult:
    """Build the panel.

    ``as_of`` is the moment the panel is being built -- "now" for a live build,
    the end of the data for a frozen backtest. It decides which labels are
    resolved, which are still censored and which horizons have not closed. It is
    an explicit argument rather than a call to the clock so that rebuilding a
    frozen panel gives byte-identical output.
    """
    guard_outcome_access("build_district_panel")

    families = sorted({family.strip() for family in event_families if family.strip()})
    if not families:
        raise PanelError("at least one event family is required")
    if horizon_days <= 0:
        raise PanelError("horizon_days must be positive")
    if as_of.tzinfo is None:
        raise PanelError("as_of must be timezone-aware")

    moments = sorted(set(cutoffs))
    if not moments:
        raise PanelError("at least one cutoff is required")
    for moment in moments:
        if moment.tzinfo is None:
            raise PanelError("every cutoff must be timezone-aware")

    policy = delay_policy or ReportingDelayPolicy.default()
    settle_delay = policy.worst_delay(datasets)
    horizon = timedelta(days=horizon_days)

    known_families = set(families)
    in_scope = [incident for incident in incidents if incident.event_family in known_families]
    by_district: dict[tuple[str, str], list[DistrictIncident]] = defaultdict(list)
    for incident in in_scope:
        by_district[(incident.district_id, incident.event_family)].append(incident)
    for group in by_district.values():
        group.sort(key=lambda item: (item.occurred_at, item.incident_id))

    unplaced_in_scope = [entry for entry in unplaced if entry.event_family in known_families]

    report = PanelReport(
        cutoffs=len(moments),
        families=len(families),
        incidents_in_scope=len(in_scope),
    )
    universe_ids: set[str] = set()
    rows: list[DistrictPanelRow] = []
    matched_incidents: set[str] = set()

    for cutoff in moments:
        universe = registry.as_of(cutoff)
        if not universe:
            raise PanelError(
                f"no districts are in effect at cutoff {cutoff.isoformat()}; "
                "the registry does not cover this period"
            )
        horizon_end = cutoff + horizon
        settles_at = horizon_end + settle_delay
        if as_of < horizon_end:
            status = LabelStatus.PENDING
        elif as_of < settles_at:
            status = LabelStatus.CENSORED
        else:
            status = LabelStatus.RESOLVED

        # Counted once per cutoff rather than per district: the unplaced set is
        # a property of the window, not of any one district in it.
        unplaced_by_family = {
            family: sum(
                1
                for entry in unplaced_in_scope
                if entry.event_family == family and cutoff < entry.occurred_at <= horizon_end
            )
            for family in families
        }

        for district in universe:
            universe_ids.add(district.district_id)
            for family in families:
                window = [
                    incident
                    for incident in by_district.get((district.district_id, family), ())
                    # Half-open on the left, closed on the right: an incident at
                    # the cutoff instant is already known and is not a forecast.
                    if cutoff < incident.occurred_at <= horizon_end
                ]
                matched_incidents.update(incident.incident_id for incident in window)
                unplaced_for_family = unplaced_by_family[family]
                row_status = status
                if status is not LabelStatus.PENDING and not window and unplaced_for_family:
                    # Nothing placed here, but incidents in this window went
                    # unplaced somewhere. This district's zero is not confirmed.
                    row_status = LabelStatus.UNRESOLVED_LOCATION

                rows.append(
                    DistrictPanelRow(
                        district_id=district.district_id,
                        state_id=district.state_id,
                        boundary_version=district.boundary_version,
                        cutoff_at=cutoff,
                        horizon_start=cutoff,
                        horizon_end=horizon_end,
                        event_family=family,
                        incident_occurred=1 if window else 0,
                        incident_count=len(window),
                        first_incident_at=window[0].occurred_at if window else None,
                        first_resolvable_at=(
                            min(incident.first_resolvable_at for incident in window)
                            if window
                            else None
                        ),
                        label_status=row_status,
                        label_settles_at=settles_at,
                        unplaced_incidents=unplaced_for_family,
                        fatalities=sum(incident.fatalities or 0 for incident in window),
                    )
                )

    report.districts = len(universe_ids)
    report.rows = len(rows)
    report.positive_rows = sum(1 for row in rows if row.incident_occurred)
    report.resolved_rows = sum(1 for row in rows if row.label_status is LabelStatus.RESOLVED)
    report.censored_rows = sum(1 for row in rows if row.label_status is LabelStatus.CENSORED)
    report.pending_rows = sum(1 for row in rows if row.label_status is LabelStatus.PENDING)
    report.unresolved_location_rows = sum(
        1 for row in rows if row.label_status is LabelStatus.UNRESOLVED_LOCATION
    )
    report.incidents_outside_every_window = len(
        {incident.incident_id for incident in in_scope} - matched_incidents
    )
    report.incidents_in_unknown_districts = sum(
        1 for incident in in_scope if incident.district_id not in universe_ids
    )
    report.base_rate_by_family = _base_rates(rows)

    return PanelResult(rows=tuple(rows), report=report)


def _base_rates(rows: Sequence[DistrictPanelRow]) -> dict[str, float]:
    """Positive share among scorable rows only.

    Censored and pending rows are excluded rather than counted as negatives:
    including them would report a base rate diluted by windows whose incidents
    have not been published yet, and every baseline calibrated to that rate
    would start out under-confident.
    """
    totals: dict[str, int] = defaultdict(int)
    positives: dict[str, int] = defaultdict(int)
    for row in rows:
        if not row.is_scorable:
            continue
        totals[row.event_family] += 1
        positives[row.event_family] += row.incident_occurred
    return {
        family: round(positives[family] / totals[family], 8)
        for family in sorted(totals)
        if totals[family]
    }


def validate_panel(
    rows: Sequence[DistrictPanelRow],
    *,
    registry: DistrictRegistry,
    event_families: Sequence[str],
) -> dict[str, Any]:
    """Check the invariants a panel must satisfy before anything trains on it.

    Every check here has a failure mode that is silent downstream: a missing
    negative row looks like a smaller dataset, a duplicated row looks like a
    stronger signal, and a district outside the cutoff's universe looks like an
    ordinary observation until somebody asks why a 2019 fold mentions a district
    created in 2022.
    """
    families = sorted(set(event_families))
    problems: list[str] = []
    by_cutoff: dict[datetime, list[DistrictPanelRow]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()

    for row in rows:
        key = (row.district_id, row.cutoff_at.isoformat(), row.event_family)
        if key in seen:
            problems.append(f"duplicate row for {key}")
        seen.add(key)
        by_cutoff[row.cutoff_at].append(row)

    for cutoff, group in sorted(by_cutoff.items()):
        try:
            expected = {district.district_id for district in registry.as_of(cutoff)}
        except GeographyError as error:
            problems.append(f"{cutoff.isoformat()}: {error}")
            continue
        present = {row.district_id for row in group}
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        if missing:
            problems.append(
                f"{cutoff.isoformat()}: {len(missing)} districts in the universe have no row "
                f"(first: {missing[:3]}); the negative class is incomplete"
            )
        if extra:
            problems.append(
                f"{cutoff.isoformat()}: {len(extra)} rows for districts outside the universe "
                f"(first: {extra[:3]}); a later boundary vintage has leaked in"
            )
        for district_id in sorted(present & expected):
            got = sorted(row.event_family for row in group if row.district_id == district_id)
            if got != families:
                problems.append(f"{cutoff.isoformat()} {district_id}: families {got} != {families}")

    return {
        "rows": len(rows),
        "cutoffs": len(by_cutoff),
        "ok": not problems,
        "problems": problems[:50],
        "problem_count": len(problems),
    }
