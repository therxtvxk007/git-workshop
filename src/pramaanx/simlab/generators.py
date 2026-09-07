"""A small synthetic world, with reporting delay built in.

Not a claim about India. This exists so the engineering pipeline can be run
end to end offline, with a known answer, and so the tests that matter -- future
invariance, boundary crossing, crash recovery -- have something to run over
(S39). Synthetic data is not evidence of forecasting skill and nothing here
should be read as one.

The one feature worth having is the reporting delay. An incident that occurred
inside a window but was not reported until after it is invisible at an earlier
cutoff and visible later, which is the entire reason maturation exists. A
generator without it would make the as-of store look like an expensive way of
doing nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from pramaanx.core.contexts import AvailabilityBasis
from pramaanx.core.errors import ContractViolationError
from pramaanx.core.revisions import Revision
from pramaanx.core.rng import RandomStreams
from pramaanx.hashing import utc_isoformat
from pramaanx.panel.families import ALL_FAMILIES, Family, IncidentLabels
from pramaanx.panel.windows import CalendarContract

INCIDENT_TABLE = "incidents"


@dataclass(frozen=True)
class WorldSpec:
    """A generated world: who, how often, and how late the news arrives."""

    #: ``(district_id, state_id)`` pairs.
    districts: tuple[tuple[str, str], ...]
    start: date
    days: int
    #: District -> incidents per day. Zero is allowed and means a quiet
    #: district, which is a real thing and the interesting case.
    rates: dict[str, float]
    #: District -> mean reporting delay in days.
    delays: dict[str, float]
    source_id: str = "synthetic"
    calendar: CalendarContract = field(default_factory=CalendarContract)

    def __post_init__(self) -> None:
        codes = {code for code, _ in self.districts}
        missing = sorted(codes - set(self.rates))
        if missing:
            raise ContractViolationError("every district needs a rate", districts=missing)
        if self.days <= 0:
            raise ContractViolationError("a world needs at least one day")


@dataclass(frozen=True)
class SyntheticIncident:
    """One generated incident, with the two times that matter."""

    incident_id: str
    district_id: str
    families: frozenset[Family]
    occurred_at: datetime
    available_at: datetime

    def labels(self) -> IncidentLabels:
        return IncidentLabels(
            incident_id=self.incident_id,
            district_id=self.district_id,
            families=self.families,
        )


def generate(spec: WorldSpec, *, rng: RandomStreams) -> tuple[SyntheticIncident, ...]:
    """Draw a world. Deterministic given the seed and the spec."""
    incidents: list[SyntheticIncident] = []
    for district, _state in spec.districts:
        generator = rng.stream("simlab", "incidents", district)
        rate = spec.rates[district]
        delay_mean = spec.delays.get(district, 0.0)
        for offset in range(spec.days):
            day = spec.start + timedelta(days=offset)
            for index in range(int(generator.poisson(rate))):
                occurred = spec.calendar.instant(day) + timedelta(
                    hours=float(generator.uniform(0, 24))
                )
                delay = float(generator.exponential(delay_mean)) if delay_mean > 0 else 0.0
                # Multi-label on purpose: the union rule needs incidents that
                # belong to more than one family or it is never exercised.
                size = 1 + int(generator.integers(0, 2))
                families = frozenset(
                    ALL_FAMILIES[int(pick)]
                    for pick in generator.choice(len(ALL_FAMILIES), size=size, replace=False)
                )
                incidents.append(
                    SyntheticIncident(
                        incident_id=f"inc_{district}_{offset:04d}_{index}",
                        district_id=district,
                        families=families,
                        occurred_at=occurred,
                        available_at=occurred + timedelta(days=delay),
                    )
                )
    return tuple(sorted(incidents, key=lambda item: (item.available_at, item.incident_id)))


def to_revisions(
    incidents: tuple[SyntheticIncident, ...], *, spec: WorldSpec, ingested_at: datetime
) -> list[Revision]:
    """One upsert per incident, available when the report arrives.

    ``retrieved_time`` equals ``available_time``: this world is collected as it
    happens. A retrospective reconstruction would set them apart, and the
    store's prospective profile would then judge eligibility on the later one.
    """
    return [
        Revision(
            table=INCIDENT_TABLE,
            source_id=spec.source_id,
            entity_id=incident.incident_id,
            source_revision_order=0,
            valid_time_start=incident.occurred_at,
            valid_time_end=incident.occurred_at,
            publish_time=incident.available_at,
            available_time=incident.available_at,
            retrieved_time=incident.available_at,
            ingested_at=max(ingested_at, incident.available_at),
            availability_basis=AvailabilityBasis.OBSERVED_RETRIEVAL,
            availability_evidence_ref=f"simlab:{incident.incident_id}",
            payload={
                "district_id": incident.district_id,
                "families": sorted(str(family) for family in incident.families),
                "occurred_at": utc_isoformat(incident.occurred_at),
            },
        )
        for incident in incidents
    ]


def labels_from_records(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[IncidentLabels], dict[str, datetime]]:
    """Turn stored payloads back into labels and their occurrence instants.

    The identifier comes from ``entity_id``, which is what
    :meth:`EligibleTable.payloads` names it: the store's key for the thing a
    source made statements about. Reading it from the payload instead would
    trust a field the store does not enforce the uniqueness of.
    """
    labels: list[IncidentLabels] = []
    instants: dict[str, datetime] = {}
    for record in records:
        if "entity_id" not in record:
            raise ContractViolationError(
                "incident records must carry the store's entity_id",
                keys=sorted(str(key) for key in record),
            )
        incident_id = str(record["entity_id"])
        families: Iterable[Any] = record["families"]
        labels.append(
            IncidentLabels(
                incident_id=incident_id,
                district_id=str(record["district_id"]),
                families=frozenset(Family(str(item)) for item in families),
            )
        )
        instants[incident_id] = datetime.fromisoformat(
            str(record["occurred_at"]).replace("Z", "+00:00")
        )
    return labels, instants
