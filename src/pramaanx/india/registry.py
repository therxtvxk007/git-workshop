"""The incident registry, and the one reason it is safe to backtest on.

Most retrospective event datasets are unusable for honest backtesting because
they are *coded* long after the fact: a row's content reflects investigation,
attribution and revision that no contemporaneous observer had. ACLED says so of
itself, and the project's own source table records it.

Mass-casualty attacks are the exception, and the exception is narrow enough to
state precisely. The *occurrence*, *date*, *city* and *broad target class* of an
attack of this size are public within hours through ordinary news reporting.
Those four fields -- and only those -- are therefore admissible at
``event_date + reporting_lag`` without back-dating anything.

Everything else such a dataset usually carries is **not** admissible on that
basis and is deliberately absent here: no attribution, no perpetrator group, no
casualty revisions, no investigative findings. Fatality counts are retained for
description only and are never a model input, because early counts are revised
for weeks.

So the registry is not exempt from cutoff discipline; it is a case where
availability time is computable from event time, which is the property
:func:`admissible_at` enforces.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

#: Days after an incident before it is treated as publicly known. One day is
#: conservative for this event class -- reporting is same-day -- and exists so
#: that a cutoff falling hours after an attack does not admit it.
DEFAULT_REPORTING_LAG_DAYS = 1

#: The registry ships with the repository rather than under ``data/``, which is
#: git-ignored. It is public-record description, not licensed evidence.
DEFAULT_REGISTRY = Path("research/datasets/india_incidents.csv")

_REQUIRED_COLUMNS = frozenset({"date", "state", "city", "target_class", "fatalities", "note"})

#: The closed target-class taxonomy, fixed a priori rather than read off the
#: data. Declaring it up front is what lets a fit represent a class a region has
#: never seen: if the vocabulary were inferred from history, the first
#: hospitality attack in a state would be unrankable rather than merely
#: unlikely, and the model would score a discovery failure as if it were a
#: probability failure.
TARGET_CLASS_TAXONOMY: tuple[str, ...] = (
    "government",
    "hospitality",
    "market",
    "religious",
    "security",
    "transit",
)


class RegistryError(ValueError):
    """The registry file is malformed in a way that must not be guessed past."""


@dataclass(frozen=True, slots=True)
class Incident:
    """One publicly reported mass-casualty incident.

    ``occurred_at`` is the event instant; ``first_known_at`` is when it is
    treated as publicly available. The two differ by the reporting lag, and the
    model only ever reads the second.
    """

    occurred_at: datetime
    state: str
    city: str
    target_class: str
    fatalities: int
    note: str
    reporting_lag_days: int = DEFAULT_REPORTING_LAG_DAYS

    @property
    def first_known_at(self) -> datetime:
        """The instant this incident becomes admissible evidence."""
        return self.occurred_at + timedelta(days=self.reporting_lag_days)

    @property
    def cell(self) -> tuple[str, str]:
        """The ``(state, target_class)`` cell this incident falls in."""
        return (self.state, self.target_class)


def load_incidents(
    path: Path | str = DEFAULT_REGISTRY,
    *,
    reporting_lag_days: int = DEFAULT_REPORTING_LAG_DAYS,
) -> tuple[Incident, ...]:
    """Read the registry, sorted by occurrence.

    Raises rather than skipping on a malformed row: a registry that silently
    drops rows changes every rate it feeds, in a direction nobody chose.
    """
    path = Path(path)
    if not path.exists():
        raise RegistryError(f"registry not found: {path}")

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = frozenset(reader.fieldnames or ())
        missing = _REQUIRED_COLUMNS - columns
        if missing:
            raise RegistryError(f"{path}: missing columns {sorted(missing)}")

        incidents: list[Incident] = []
        for lineno, row in enumerate(reader, start=2):
            try:
                occurred = datetime.strptime(row["date"].strip(), "%Y-%m-%d").replace(tzinfo=UTC)
            except (ValueError, AttributeError) as exc:
                raise RegistryError(f"{path}:{lineno}: bad date {row.get('date')!r}") from exc
            try:
                fatalities = int(row["fatalities"])
            except (ValueError, TypeError) as exc:
                raise RegistryError(
                    f"{path}:{lineno}: bad fatalities {row.get('fatalities')!r}"
                ) from exc
            for field in ("state", "city", "target_class"):
                if not (row.get(field) or "").strip():
                    raise RegistryError(f"{path}:{lineno}: empty {field}")
            incidents.append(
                Incident(
                    occurred_at=occurred,
                    state=row["state"].strip(),
                    city=row["city"].strip(),
                    target_class=row["target_class"].strip(),
                    fatalities=fatalities,
                    note=(row.get("note") or "").strip(),
                    reporting_lag_days=reporting_lag_days,
                )
            )

    if not incidents:
        raise RegistryError(f"{path}: no rows")
    return tuple(sorted(incidents, key=lambda i: (i.occurred_at, i.state, i.city)))


def admissible_at(incidents: tuple[Incident, ...], cutoff: datetime) -> tuple[Incident, ...]:
    """The incidents publicly known at ``cutoff``.

    This is the registry's whole cutoff guard, and it filters on
    :attr:`Incident.first_known_at`, never on the occurrence instant.
    """
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    return tuple(i for i in incidents if i.first_known_at <= cutoff)


def states(incidents: tuple[Incident, ...]) -> tuple[str, ...]:
    """Sorted distinct states present in ``incidents``."""
    return tuple(sorted({i.state for i in incidents}))


def target_classes(incidents: tuple[Incident, ...]) -> tuple[str, ...]:
    """Sorted distinct target classes present in ``incidents``."""
    return tuple(sorted({i.target_class for i in incidents}))
