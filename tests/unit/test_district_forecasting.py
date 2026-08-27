from datetime import UTC, datetime, timedelta
import numpy as np
from pramaanx.adjudication import ExpertAssessment, supervise
from pramaanx.district_pipeline import DistrictSignal, compare_spatial_and_semantic, run_district_cutoff
from pramaanx.geography import DistrictRegistry
from pramaanx.models import DistrictHistory, GradientBoostedSpatialModel, LogisticSpatialModel, historical_rate, recency_score
from pramaanx.outcomes import DistrictIncident, build_district_panel
from pramaanx.schemas.district import DistrictRef

NOW = datetime(2026, 1, 1, tzinfo=UTC)
def district(i: str) -> DistrictRef:
    return DistrictRef(district_id=i, district_name=i, state_id="s", state_name="S",
        boundary_version="v1", valid_from=datetime(2000, 1, 1, tzinfo=UTC))

def test_registry_panel_models_and_pipeline() -> None:
    a, b = district("a"), district("b")
    registry = DistrictRegistry([a, b], adjacency={"a": {"b"}, "b": {"a"}})
    assert registry.neighbours("a") == {"b"}
    incidents = [DistrictIncident(incident_id="i", district_id="a", event_family="terrorism",
        occurred_at=NOW+timedelta(days=5), first_resolvable_at=NOW+timedelta(days=6))]
    panel = build_district_panel([a, b], incidents, [NOW], ["terrorism"])
    assert [row.incident_count for row in panel] == [1, 0]
    history = DistrictHistory("a", ((NOW-timedelta(days=10)).timestamp(),))
    assert 0 < historical_rate(history, NOW.timestamp()) <= 1
    assert 0 < recency_score(history, NOW.timestamp()) <= 1
    x, y = np.array([[0.0], [1.0], [0.1], [0.9]]), np.array([0, 1, 0, 1])
    assert LogisticSpatialModel().fit(x, y).predict_proba(x).shape == (4,)
    assert GradientBoostedSpatialModel().fit(x, y).predict_proba(x).shape == (4,)
    run = run_district_cutoff(cutoff_at=NOW, snapshot_hash="h", event_family="terrorism",
        signals=[DistrictSignal(a, 0.2, 0.1), DistrictSignal(b, 0.7, 0.8)])
    assert len(run.forecasts) == 2
    assert compare_spatial_and_semantic([0, 1], [0.2, 0.7], [0.1, 0.8])["brier_delta"] > 0

def test_supervisor() -> None:
    assessments = [ExpertAssessment(role=str(i), candidate_id="c", support_strength=0.8,
        contradiction_strength=0.1, temporal_relevance=0.9, source_independence=0.8,
        coverage_completeness=0.7) for i in range(5)]
    result = supervise(assessments)
    assert result.semantic_score > 0.6
    assert not result.abstain
