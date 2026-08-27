"""ACLED and UCDP rows -> district incidents.

Both adapters do the same four things and refuse in the same way:

1. classify the row into an event family, or drop it as out of scope;
2. read the *availability* timestamp, never the event date, for
   ``first_resolvable_at``;
3. place the row in a district as of the date it occurred, using the district
   structure that was in effect then;
4. when placement fails, emit an :class:`UnplacedIncident` rather than a guess
   or a silent drop.

Point (2) is the one that matters most. ACLED's ``timestamp`` is documented as
the moment the current version of the row was uploaded; ``event_date`` is when
the event happened and says nothing about when anyone knew. Building labels
from ``event_date`` gives every model perfect knowledge of the last two weeks
of every horizon.

Point (3) is the one most likely to be got wrong quietly. A 2019 incident in
what is now Palnadu district belonged to Guntur in 2019. Placing it in Palnadu
because that is where the coordinates fall today moves an incident between
districts, and the model learns a base rate for a district that did not exist.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from pramaanx.geography.resolver import DistrictResolver, Resolution
from pramaanx.outcomes.ontology import EventFamily, classify_acled, classify_ucdp
from pramaanx.schemas.district_panel import DistrictIncident, UnplacedIncident


class NormalisationError(ValueError):
    """A source row was structurally unusable."""


@dataclass
class NormalisationReport:
    """What happened to every row, so coverage can be stated rather than assumed."""

    dataset: str
    rows_seen: int = 0
    out_of_scope: int = 0
    placed: int = 0
    unplaced: int = 0
    #: Rows dropped because a required column was missing or malformed. These
    #: are a data-quality signal, not an outcome, and are never zero-filled.
    malformed: int = 0
    families: dict[str, int] = field(default_factory=dict)
    unplaced_reasons: dict[str, int] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "rows_seen": self.rows_seen,
            "out_of_scope": self.out_of_scope,
            "placed": self.placed,
            "unplaced": self.unplaced,
            "malformed": self.malformed,
            "families": dict(sorted(self.families.items())),
            "unplaced_reasons": dict(sorted(self.unplaced_reasons.items())),
            "placement_rate": (
                round(self.placed / (self.placed + self.unplaced), 6)
                if (self.placed + self.unplaced)
                else None
            ),
        }


@dataclass(frozen=True)
class NormalisationResult:
    incidents: tuple[DistrictIncident, ...]
    unplaced: tuple[UnplacedIncident, ...]
    report: NormalisationReport


def _text(row: Mapping[str, Any], key: str, *, default: str = "") -> str:
    value = row.get(key)
    return default if value is None else str(value).strip()


def _optional_int(row: Mapping[str, Any], key: str) -> int | None:
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise NormalisationError(f"{key} is not an integer: {value!r}") from error
    return max(parsed, 0)


def _parse_date(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise NormalisationError(f"{field_name} must be timezone-aware")
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    text = str(value).strip()
    if not text:
        raise NormalisationError(f"{field_name} is empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise NormalisationError(f"{field_name} is not ISO-8601: {text!r}") from error
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse_unix(value: Any, *, field_name: str) -> datetime:
    try:
        seconds = int(value)
    except (TypeError, ValueError) as error:
        raise NormalisationError(f"{field_name} is not a Unix timestamp: {value!r}") from error
    if seconds <= 0:
        raise NormalisationError(f"{field_name} must be positive, got {seconds}")
    return datetime.fromtimestamp(seconds, tz=UTC)


def _place(
    resolver: DistrictResolver,
    *,
    district_name: str,
    state_name: str | None,
    occurred_at: datetime,
) -> Resolution | None:
    if not district_name:
        return None
    outcome = resolver.resolve(district_name, moment=occurred_at, state_name=state_name)
    return outcome if isinstance(outcome, Resolution) else None


def _record_unplaced(
    resolver: DistrictResolver,
    *,
    dataset: str,
    record_id: str,
    family: EventFamily,
    occurred_at: datetime,
    first_resolvable_at: datetime,
    district_name: str,
    state_name: str | None,
) -> UnplacedIncident:
    if not district_name:
        return UnplacedIncident(
            source_dataset=dataset,
            source_record_id=record_id,
            event_family=family.value,
            occurred_at=occurred_at,
            first_resolvable_at=first_resolvable_at,
            reason="unknown",
            location_text="",
            state_hint=state_name,
        )
    outcome = resolver.resolve(district_name, moment=occurred_at, state_name=state_name)
    reason = getattr(outcome, "reason", "unknown")
    candidates = list(getattr(outcome, "candidates", ()))
    return UnplacedIncident(
        source_dataset=dataset,
        source_record_id=record_id,
        event_family=family.value,
        occurred_at=occurred_at,
        first_resolvable_at=first_resolvable_at,
        reason=reason,
        location_text=district_name,
        state_hint=state_name,
        candidates=candidates,
    )


def normalise_acled_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    resolver: DistrictResolver,
    strict: bool = True,
) -> NormalisationResult:
    """Normalise ACLED export rows.

    ``strict`` decides what a malformed row does. Strict is the default because
    a row with an unparseable timestamp is a row whose availability is unknown,
    and an unknown availability cannot be given a safe value: too early leaks,
    too late deletes a real incident.
    """
    dataset = "acled"
    report = NormalisationReport(dataset=dataset)
    incidents: list[DistrictIncident] = []
    unplaced: list[UnplacedIncident] = []

    for row in rows:
        report.rows_seen += 1
        record_id = _text(row, "event_id_cnty") or _text(row, "event_id")
        try:
            if not record_id:
                raise NormalisationError("row has no event_id_cnty")
            actors = tuple(
                value
                for value in (
                    _text(row, "actor1"),
                    _text(row, "actor2"),
                    _text(row, "assoc_actor_1"),
                )
                if value
            )
            family = classify_acled(
                event_type=_text(row, "event_type"),
                sub_event_type=_text(row, "sub_event_type"),
                actors=actors,
            )
            if family is None:
                report.out_of_scope += 1
                continue
            occurred_at = _parse_date(row.get("event_date"), field_name="event_date")
            # ACLED documents `timestamp` as the upload time of the current row
            # body. It is the only field in the export that answers "when could
            # we have seen this?".
            first_resolvable_at = _parse_unix(row.get("timestamp"), field_name="timestamp")
            if first_resolvable_at < occurred_at:
                raise NormalisationError("timestamp precedes event_date")
            fatalities = _optional_int(row, "fatalities")
        except NormalisationError:
            report.malformed += 1
            if strict:
                raise
            continue

        district_name = _text(row, "admin2")
        state_name = _text(row, "admin1") or None
        placed = _place(
            resolver,
            district_name=district_name,
            state_name=state_name,
            occurred_at=occurred_at,
        )
        if placed is None:
            entry = _record_unplaced(
                resolver,
                dataset=dataset,
                record_id=record_id,
                family=family,
                occurred_at=occurred_at,
                first_resolvable_at=first_resolvable_at,
                district_name=district_name,
                state_name=state_name,
            )
            unplaced.append(entry)
            report.unplaced += 1
            report.unplaced_reasons[entry.reason] = report.unplaced_reasons.get(entry.reason, 0) + 1
            continue

        incidents.append(
            DistrictIncident(
                incident_id=DistrictIncident.build_id(dataset, record_id),
                source_dataset=dataset,
                source_record_id=record_id,
                district_id=placed.district_id,
                state_id=placed.district.state_id,
                boundary_version=placed.district.boundary_version,
                event_family=family.value,
                occurred_at=occurred_at,
                first_resolvable_at=first_resolvable_at,
                fatalities=fatalities,
                actor_names=list(actors),
            )
        )
        report.placed += 1
        report.families[family.value] = report.families.get(family.value, 0) + 1

    return _finalise(incidents, unplaced, report)


def normalise_ucdp_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    resolver: DistrictResolver,
    release_dates: Mapping[int, datetime],
    strict: bool = True,
) -> NormalisationResult:
    """Normalise UCDP GED rows.

    UCDP carries no per-row availability timestamp: a row becomes knowable when
    the dataset version containing it is released. ``release_dates`` maps GED
    version year to its release moment, and a row from a version with no
    declared release date is refused -- inventing one would put an availability
    date on a row nobody can vouch for.

    Only rows UCDP itself considers well located are placed: ``where_prec``
    above 3 means the coordinates are no finer than the province, which is not
    a district-level outcome however precisely it is stored.
    """
    dataset = "ucdp_ged"
    report = NormalisationReport(dataset=dataset)
    incidents: list[DistrictIncident] = []
    unplaced: list[UnplacedIncident] = []

    for row in rows:
        report.rows_seen += 1
        record_id = _text(row, "id")
        try:
            if not record_id:
                raise NormalisationError("row has no id")
            actors = tuple(
                value
                for value in (
                    _text(row, "side_a"),
                    _text(row, "side_b"),
                    _text(row, "conflict_name"),
                )
                if value
            )
            violence = _optional_int(row, "type_of_violence")
            if violence is None:
                raise NormalisationError("type_of_violence is missing")
            family = classify_ucdp(type_of_violence=violence, actors=actors)
            if family is None:
                report.out_of_scope += 1
                continue

            where_precision = _optional_int(row, "where_prec")
            date_precision = _optional_int(row, "date_prec")
            if where_precision is not None and where_precision > 3:
                report.out_of_scope += 1
                continue
            if date_precision is not None and date_precision > 3:
                # Precision worse than "within a week" cannot be assigned to a
                # 30-day horizon without possibly moving it across the boundary.
                report.out_of_scope += 1
                continue

            occurred_at = _parse_date(row.get("date_start"), field_name="date_start")
            version = _optional_int(row, "ged_version_year")
            if version is None:
                raise NormalisationError("ged_version_year is missing")
            if version not in release_dates:
                raise NormalisationError(
                    f"no release date declared for GED version {version}; "
                    "availability cannot be inferred"
                )
            first_resolvable_at = release_dates[version].astimezone(UTC)
            if first_resolvable_at < occurred_at:
                raise NormalisationError("GED release predates the event")
            fatalities = _optional_int(row, "best")
        except NormalisationError:
            report.malformed += 1
            if strict:
                raise
            continue

        district_name = _text(row, "adm_2")
        state_name = _text(row, "adm_1") or None
        placed = _place(
            resolver,
            district_name=district_name,
            state_name=state_name,
            occurred_at=occurred_at,
        )
        if placed is None:
            entry = _record_unplaced(
                resolver,
                dataset=dataset,
                record_id=record_id,
                family=family,
                occurred_at=occurred_at,
                first_resolvable_at=first_resolvable_at,
                district_name=district_name,
                state_name=state_name,
            )
            unplaced.append(entry)
            report.unplaced += 1
            report.unplaced_reasons[entry.reason] = report.unplaced_reasons.get(entry.reason, 0) + 1
            continue

        incidents.append(
            DistrictIncident(
                incident_id=DistrictIncident.build_id(dataset, record_id),
                source_dataset=dataset,
                source_record_id=record_id,
                district_id=placed.district_id,
                state_id=placed.district.state_id,
                boundary_version=placed.district.boundary_version,
                event_family=family.value,
                occurred_at=occurred_at,
                first_resolvable_at=first_resolvable_at,
                fatalities=fatalities,
                actor_names=list(actors),
            )
        )
        report.placed += 1
        report.families[family.value] = report.families.get(family.value, 0) + 1

    return _finalise(incidents, unplaced, report)


def deduplicate_incidents(
    incidents: Sequence[DistrictIncident],
) -> tuple[list[DistrictIncident], int]:
    """Collapse the same incident reported by both datasets.

    ACLED and UCDP overlap heavily. Counting one attack twice inflates the count
    target and the base rate for exactly the districts that are already the most
    active, which is the worst place for a systematic error.

    The key is (district, family, calendar day). Where two datasets disagree on
    availability the *later* one wins: an incident is only knowable once, and
    the earlier claim is the one this project could not actually have relied on
    if the deduplicated row is attributed to the surviving dataset.
    """
    by_key: dict[tuple[str, str, str], DistrictIncident] = {}
    duplicates = 0
    for incident in sorted(
        incidents, key=lambda item: (item.occurred_at, item.district_id, item.incident_id)
    ):
        key = (
            incident.district_id,
            incident.event_family,
            incident.occurred_at.date().isoformat(),
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = incident
            continue
        duplicates += 1
        if incident.first_resolvable_at > existing.first_resolvable_at:
            by_key[key] = incident.model_copy(
                update={"notes": f"duplicate of {existing.incident_id}"}
            )
        else:
            by_key[key] = existing.model_copy(
                update={"notes": f"duplicate of {incident.incident_id}"}
            )
    return sorted(by_key.values(), key=lambda item: item.incident_id), duplicates


def _finalise(
    incidents: list[DistrictIncident],
    unplaced: list[UnplacedIncident],
    report: NormalisationReport,
) -> NormalisationResult:
    return NormalisationResult(
        incidents=tuple(sorted(incidents, key=lambda item: item.incident_id)),
        unplaced=tuple(
            sorted(unplaced, key=lambda item: (item.source_dataset, item.source_record_id))
        ),
        report=report,
    )
