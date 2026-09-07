"""Windows, calendars and origins.

Three decisions live here that the plan makes explicitly, and each one is a bug
if it is left implicit.

**Half-open.** Every window is ``[start, end)``. An event at ``end`` belongs to
the next window. Closed intervals double-count the boundary day, which on a
rare-event panel is a measurable fraction of the positives.

**The calendar is pinned, not assumed.** Storage is UTC; that does not make the
reporting day UTC. A 30-day window over Indian districts is 30 local days, and
which instants those are depends on a timezone the target contract has to name
(S29.1).

**Maturation starts at the end of the outcome window, not at the origin.** A
30-day window issued on 1 January is not mature 30 days later; it is mature 30
days after 31 January plus whatever the maturation rule adds.

The CAST comparator gets its own construction because it is not a calendar
month: four weeks ending on a Friday, published weekly, six periods ahead
(S24.4). The mechanics are here; the *alignment* -- which Friday the first
period ends on -- has to come from the comparator contract, so this module
refuses to guess it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pramaanx.core.errors import ContractViolationError
from pramaanx.hashing import utc_isoformat

#: ``date.weekday()`` for Friday. Named because a bare 4 in a slice test is the
#: kind of thing that survives a rewrite as a 5.
FRIDAY = 4

CAST_PERIOD_DAYS = 28
CAST_PERIODS_AHEAD = 6


@dataclass(frozen=True)
class Window:
    """A half-open outcome window, ``[start, end)``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ContractViolationError("window bounds must be timezone-aware")
        if self.end <= self.start:
            raise ContractViolationError(
                "window end must be after its start",
                start=utc_isoformat(self.start),
                end=utc_isoformat(self.end),
            )

    def contains(self, instant: datetime) -> bool:
        """``start <= instant < end``. The end belongs to the next window."""
        return self.start <= instant < self.end

    @property
    def days(self) -> float:
        return (self.end - self.start) / timedelta(days=1)

    def matures_at(self, maturation_days: int) -> datetime:
        """When this window's outcome may be treated as settled.

        Measured from the window's end. Measuring from the origin would call a
        30-day window mature before its last day had happened.
        """
        if maturation_days < 0:
            raise ContractViolationError("maturation_days must not be negative")
        return self.end + timedelta(days=maturation_days)

    def to_dict(self) -> dict[str, str]:
        return {"start": utc_isoformat(self.start), "end": utc_isoformat(self.end)}


@dataclass(frozen=True)
class CalendarContract:
    """Which local calendar defines a day, and where its boundary falls.

    Pinned in the target contract and carried into every window this builds.
    UTC storage does not force UTC calendar days, and two runs that disagree
    about the day boundary produce two different panels over the same evidence.
    """

    timezone: str = "Asia/Kolkata"
    day_boundary: time = time(0, 0)

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def instant(self, day: date) -> datetime:
        """The UTC instant at which ``day`` begins in this calendar."""
        local = datetime.combine(day, self.day_boundary, tzinfo=self.zone)
        return local.astimezone(UTC)

    def local_date(self, instant: datetime) -> date:
        """Which local day an instant falls in, honouring the boundary."""
        local = instant.astimezone(self.zone)
        shifted = local - timedelta(hours=self.day_boundary.hour, minutes=self.day_boundary.minute)
        return shifted.date()

    def window(self, start_day: date, length_days: int) -> Window:
        """A window of whole local days, expressed as UTC instants."""
        if length_days <= 0:
            raise ContractViolationError("window length must be positive")
        return Window(
            self.instant(start_day), self.instant(start_day + timedelta(days=length_days))
        )

    def daily_edges(self, window: Window) -> tuple[datetime, ...]:
        """The bin edges a daily path is indexed on, ends included.

        A path model has to know exactly which instants separate its days, or
        ``window(start, end)`` cannot check alignment and will silently
        truncate instead of refusing (S32.1).
        """
        edges = [window.start]
        cursor = self.local_date(window.start)
        while edges[-1] < window.end:
            cursor = cursor + timedelta(days=1)
            edges.append(self.instant(cursor))
        if edges[-1] != window.end:
            raise ContractViolationError(
                "window does not end on a day boundary in this calendar",
                end=utc_isoformat(window.end),
                timezone=self.timezone,
            )
        return tuple(edges)

    def identity(self) -> dict[str, str]:
        return {"timezone": self.timezone, "day_boundary": self.day_boundary.isoformat()}


def monthly_origins(first: date, last: date, *, calendar: CalendarContract) -> tuple[datetime, ...]:
    """Issue instants on the first local day of each month, inclusive."""
    origins: list[datetime] = []
    year, month = first.year, first.month
    while True:
        day = date(year, month, 1)
        if day > last:
            break
        if day >= first:
            origins.append(calendar.instant(day))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return tuple(origins)


def weekly_origins(
    first: date, last: date, *, calendar: CalendarContract, weekday: int = FRIDAY
) -> tuple[datetime, ...]:
    """Issue instants on one weekday each week.

    CAST publishes weekly, so its replay needs weekly origins rather than the
    flagship's monthly ones. Reusing monthly origins would compare a weekly
    product at a twelfth of its update rate (S24.4).
    """
    if not 0 <= weekday <= 6:
        raise ContractViolationError("weekday must be 0 (Monday) to 6 (Sunday)")
    cursor = first + timedelta(days=(weekday - first.weekday()) % 7)
    origins: list[datetime] = []
    while cursor <= last:
        origins.append(calendar.instant(cursor))
        cursor += timedelta(days=7)
    return tuple(origins)


def next_friday(on_or_after: date) -> date:
    return on_or_after + timedelta(days=(FRIDAY - on_or_after.weekday()) % 7)


def cast_periods(
    first_period_end: date,
    *,
    calendar: CalendarContract,
    count: int = CAST_PERIODS_AHEAD,
) -> tuple[Window, ...]:
    """The comparator's four-week Friday-aligned rolling periods.

    ``first_period_end`` comes from the ``acled_cast`` contract, not from a
    guess here. Which Friday period one ends on is a property of the published
    product; inventing an offset would produce a comparison that looks aligned
    and is not.
    """
    if first_period_end.weekday() != FRIDAY:
        raise ContractViolationError(
            "a CAST period ends on a Friday; pin the correct date in the "
            "comparator contract rather than shifting it here",
            given=first_period_end.isoformat(),
            weekday=first_period_end.strftime("%A"),
        )
    if count <= 0:
        raise ContractViolationError("count must be positive")

    windows: list[Window] = []
    for index in range(count):
        end_day = first_period_end + timedelta(days=7 * index)
        start_day = end_day - timedelta(days=CAST_PERIOD_DAYS)
        windows.append(Window(calendar.instant(start_day), calendar.instant(end_day)))
    return tuple(windows)
