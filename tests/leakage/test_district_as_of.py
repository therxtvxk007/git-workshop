"""Negative controls for the district layer.

Each test here injects something that happened *after* a cutoff and asserts
that the cutoff's answer does not move. That is the only way to tell a correct
forecast from one that quietly read the future: both look identical in a
metric, and only an injection test separates them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pramaanx.geography import DistrictAdjacency, DistrictRegistry, DistrictResolver
from pramaanx.outcomes import build_district_panel, validate_panel
from pramaanx.schemas.district_panel import DistrictIncident, LabelStatus
from pramaanx.schemas.geography import AdjacencyEdge, DistrictRef, district_id_for, state_id_for

OLD_BV = "lgd-2024-01-01"
NEW_BV = "lgd-2025-07-01"
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
SPLIT = datetime(2025, 1, 1, tzinfo=UTC)
CUTOFF_2024 = datetime(2024, 6, 1, tzinfo=UTC)
CUTOFF_2025 = datetime(2025, 6, 1, tzinfo=UTC)


def district(
    code: int,
    name: str,
    *,
    valid_from: datetime = EPOCH,
    valid_until: datetime | None = None,
    boundary_version: str = OLD_BV,
) -> DistrictRef:
    return DistrictRef(
        district_id=district_id_for(code),
        district_name=name,
        state_id=state_id_for(28),
        state_name="Andhra Pradesh",
        boundary_version=boundary_version,
        valid_from=valid_from,
        valid_until=valid_until,
    )


@pytest.fixture
def before_split() -> DistrictRegistry:
    """The registry as it stood before anyone knew about the 2025 split."""
    return DistrictRegistry([district(532, "Guntur"), district(100, "Bastar")])


@pytest.fixture
def after_split() -> DistrictRegistry:
    """The same registry, with the 2025 split now recorded."""
    return DistrictRegistry(
        [
            district(532, "Guntur", valid_until=SPLIT),
            district(532, "Guntur", valid_from=SPLIT, boundary_version=NEW_BV),
            district(754, "Palnadu", valid_from=SPLIT, boundary_version=NEW_BV),
            district(100, "Bastar"),
        ]
    )


class TestABoundaryChangeCannotReachBackwards:
    def test_a_2025_split_does_not_change_the_2024_universe(
        self, before_split: DistrictRegistry, after_split: DistrictRegistry
    ) -> None:
        assert before_split.universe_ids(CUTOFF_2024) == after_split.universe_ids(CUTOFF_2024)
        assert "IND-D-754" not in after_split.universe_ids(CUTOFF_2024)
        assert "IND-D-754" in after_split.universe_ids(CUTOFF_2025)

    def test_a_2025_split_does_not_change_the_2024_panel(
        self, before_split: DistrictRegistry, after_split: DistrictRegistry
    ) -> None:
        def panel(registry: DistrictRegistry) -> list[str]:
            result = build_district_panel(
                registry=registry,
                incidents=[],
                cutoffs=[CUTOFF_2024],
                event_families=["terrorism"],
                horizon_days=30,
                as_of=datetime(2024, 9, 1, tzinfo=UTC),
                datasets=["acled"],
            )
            return [row.content_hash() for row in result.rows]

        assert panel(before_split) == panel(after_split)

    def test_a_district_created_later_cannot_be_resolved_earlier(
        self, after_split: DistrictRegistry
    ) -> None:
        resolver = DistrictResolver(after_split)
        assert not resolver.resolve("Palnadu", moment=CUTOFF_2024)
        assert resolver.resolve("Palnadu", moment=CUTOFF_2025)

    def test_a_panel_built_on_the_new_vintage_rejects_the_old_universe(
        self, before_split: DistrictRegistry, after_split: DistrictRegistry
    ) -> None:
        # The 2025 panel legitimately has a district the 2024 one lacks, so
        # validating 2025 rows against the pre-split registry must complain
        # rather than quietly accept a shrunken universe.
        result = build_district_panel(
            registry=after_split,
            incidents=[],
            cutoffs=[CUTOFF_2025],
            event_families=["terrorism"],
            horizon_days=30,
            as_of=datetime(2025, 9, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        report = validate_panel(result.rows, registry=before_split, event_families=["terrorism"])
        assert not report["ok"]
        assert any("outside the universe" in problem for problem in report["problems"])


class TestAdjacencyDoesNotCrossVintages:
    def test_a_neighbour_added_in_a_later_vintage_is_invisible_earlier(self) -> None:
        adjacency = DistrictAdjacency(
            [
                AdjacencyEdge(
                    boundary_version=OLD_BV, district_id="IND-D-532", neighbour_id="IND-D-100"
                ),
                AdjacencyEdge(
                    boundary_version=NEW_BV, district_id="IND-D-532", neighbour_id="IND-D-100"
                ),
                AdjacencyEdge(
                    boundary_version=NEW_BV, district_id="IND-D-532", neighbour_id="IND-D-754"
                ),
            ]
        )
        assert adjacency.neighbours("IND-D-532", boundary_version=OLD_BV) == ["IND-D-100"]
        assert adjacency.neighbours("IND-D-532", boundary_version=NEW_BV) == [
            "IND-D-100",
            "IND-D-754",
        ]


class TestFutureReportingCannotSettleALabel:
    def _incident(self, *, delay_days: float) -> DistrictIncident:
        occurred = datetime(2024, 6, 20, tzinfo=UTC)
        return DistrictIncident(
            incident_id="i1",
            source_dataset="acled",
            source_record_id="i1",
            district_id="IND-D-532",
            state_id="IND-S-28",
            boundary_version=OLD_BV,
            event_family="terrorism",
            occurred_at=occurred,
            first_resolvable_at=occurred + timedelta(days=delay_days),
        )

    def test_a_window_whose_reporting_has_not_settled_is_not_scorable(
        self, before_split: DistrictRegistry
    ) -> None:
        result = build_district_panel(
            registry=before_split,
            incidents=[self._incident(delay_days=1)],
            cutoffs=[CUTOFF_2024],
            event_families=["terrorism"],
            horizon_days=30,
            # One day past the horizon: ACLED has not published the tail yet.
            as_of=datetime(2024, 7, 2, tzinfo=UTC),
            datasets=["acled"],
        )
        assert all(row.label_status is LabelStatus.CENSORED for row in result.rows)
        assert not any(row.is_scorable for row in result.rows)

    def test_membership_uses_occurrence_time_not_availability(
        self, before_split: DistrictRegistry
    ) -> None:
        # A late-reported attack still belongs to the window it happened in.
        # Requiring knowability for membership would delete it into a quiet
        # district and reward the model for missing it.
        late = build_district_panel(
            registry=before_split,
            incidents=[self._incident(delay_days=300)],
            cutoffs=[CUTOFF_2024],
            event_families=["terrorism"],
            horizon_days=30,
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        prompt = build_district_panel(
            registry=before_split,
            incidents=[self._incident(delay_days=1)],
            cutoffs=[CUTOFF_2024],
            event_families=["terrorism"],
            horizon_days=30,
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            datasets=["acled"],
        )
        assert late.report.positive_rows == prompt.report.positive_rows == 1

    def test_an_incident_after_the_horizon_does_not_change_the_window(
        self, before_split: DistrictRegistry
    ) -> None:
        occurred = datetime(2024, 9, 1, tzinfo=UTC)
        future = DistrictIncident(
            incident_id="future",
            source_dataset="acled",
            source_record_id="future",
            district_id="IND-D-532",
            state_id="IND-S-28",
            boundary_version=OLD_BV,
            event_family="terrorism",
            occurred_at=occurred,
            first_resolvable_at=occurred,
        )

        def hashes(incidents: list[DistrictIncident]) -> list[str]:
            result = build_district_panel(
                registry=before_split,
                incidents=incidents,
                cutoffs=[CUTOFF_2024],
                event_families=["terrorism"],
                horizon_days=30,
                as_of=datetime(2026, 1, 1, tzinfo=UTC),
                datasets=["acled"],
            )
            return [row.content_hash() for row in result.rows]

        # Injecting a document from after the horizon must not move the forecast
        # target for that horizon.
        assert hashes([]) == hashes([future])
