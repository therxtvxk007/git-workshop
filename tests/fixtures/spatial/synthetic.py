"""A deterministic synthetic district panel.

The generator has a known ground truth -- a per-district log-rate driven by its
own history and its neighbours -- so a test can ask whether a model recovers a
signal that is genuinely there. That is a statement about the estimator, never
about real districts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np

from pramaanx.geography.adjacency import AdjacencyEdge, DistrictAdjacencyGraph
from pramaanx.geography.registry import DistrictRegistry, DistrictRegistryEntry
from pramaanx.outcomes.models import LocationStatus, NormalizedIncident
from pramaanx.schemas.geography import DistrictRef

BOUNDARY = "v1"
FAMILY = "insurgency"
ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SyntheticPanel:
    registry: DistrictRegistry
    adjacency: DistrictAdjacencyGraph
    incidents: tuple[NormalizedIncident, ...]
    cutoffs: tuple[datetime, ...]
    district_ids: tuple[str, ...]


def district_ref(code: int, state: int) -> DistrictRef:
    return DistrictRef(
        district_id=f"IND-D-{code}",
        district_name=f"District {code}",
        state_id=f"IND-S-{state}",
        state_name=f"State {state}",
        boundary_version=BOUNDARY,
    )


def build_registry(district_count: int, *, states: int = 2) -> DistrictRegistry:
    return DistrictRegistry(
        [
            DistrictRegistryEntry(
                district=district_ref(code, code % states + 1),
                lgd_district_code=str(code),
                valid_from=date(2020, 1, 1),
                source_hash="sha256:synthetic-lgd",
            )
            for code in range(1, district_count + 1)
        ]
    )


def build_adjacency(district_count: int) -> DistrictAdjacencyGraph:
    """A ring, so every district has exactly two neighbours."""
    edges = []
    for code in range(1, district_count + 1):
        nxt = code % district_count + 1
        if code == nxt:
            continue
        edges.append(
            AdjacencyEdge(
                left_district_id=f"IND-D-{code}",
                right_district_id=f"IND-D-{nxt}",
                boundary_version=BOUNDARY,
                weight=1.0,
            )
        )
    return DistrictAdjacencyGraph(edges)


def build_incidents(
    *,
    district_count: int,
    days: int,
    seed: int = 20260115,
    reporting_lag_days: int = 3,
    base_rate: float = 0.0035,
) -> tuple[NormalizedIncident, ...]:
    """Poisson incidents whose rate rises with the district's own recent history."""
    rng = np.random.default_rng(seed)
    incidents: list[NormalizedIncident] = []
    recent: dict[str, float] = {f"IND-D-{code}": 0.0 for code in range(1, district_count + 1)}

    for day in range(days):
        moment = ORIGIN + timedelta(days=day)
        for code in range(1, district_count + 1):
            district_id = f"IND-D-{code}"
            # Districts with a higher index are intrinsically busier, and
            # recent activity raises the rate: a real, recoverable signal.
            intensity = base_rate * (1.0 + 0.09 * code) * (1.0 + 0.45 * recent[district_id])
            draws = int(rng.poisson(min(intensity, 3.0)))
            for index in range(draws):
                incidents.append(
                    NormalizedIncident(
                        incident_id=f"inc-{code}-{day}-{index}",
                        source="synthetic",
                        source_version="v1",
                        event_family=FAMILY,
                        occurred_at=moment,
                        first_resolvable_at=moment + timedelta(days=reporting_lag_days),
                        district_id=district_id,
                        location_status=LocationStatus.RESOLVED,
                        correction_version="original",
                        source_record_id=f"rec-{code}-{day}-{index}",
                    )
                )
            recent[district_id] = 0.85 * recent[district_id] + draws
    return tuple(incidents)


def monthly_cutoffs(count: int, *, start_day: int = 400) -> tuple[datetime, ...]:
    """Issue dates one month apart, after enough history to fill a year window."""
    return tuple(ORIGIN + timedelta(days=start_day + 30 * index) for index in range(count))


def build_panel(
    *, district_count: int = 30, cutoff_count: int = 12, days: int = 900, seed: int = 20260115
) -> SyntheticPanel:
    return SyntheticPanel(
        registry=build_registry(district_count),
        adjacency=build_adjacency(district_count),
        incidents=build_incidents(district_count=district_count, days=days, seed=seed),
        cutoffs=monthly_cutoffs(cutoff_count),
        district_ids=tuple(f"IND-D-{code}" for code in range(1, district_count + 1)),
    )


def observation_end(cutoffs: Sequence[datetime], *, horizon_days: int, delay_days: int) -> datetime:
    """Late enough that every cutoff's label is resolvable."""
    return max(cutoffs) + timedelta(days=horizon_days + delay_days + 1)
