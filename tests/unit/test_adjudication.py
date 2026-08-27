from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeVar

import pytest
from pydantic import BaseModel

from pramaanx.adjudication import (
    DeterministicSupervisor,
    EvidencePack,
    ExpertRunner,
)
from pramaanx.llm import ProviderResponse, StructuredLLMEngine

T = TypeVar("T", bound=BaseModel)


def pack() -> EvidencePack:
    return EvidencePack(
        candidate_id="candidate-1",
        cutoff_at=datetime(2026, 1, 1, tzinfo=UTC),
        snapshot_hash="sha256:snapshot",
        observation_ids=["obs-1", "obs-2"],
        supporting_spans={"obs-1": ["supported span"]},
        contradiction_ids=["obs-2"],
        independence_clusters={"obs-1": "wire-a", "obs-2": "wire-b"},
        resolved_district_id="IND-D-1",
        coverage_completeness=0.8,
    )


class ExpertProvider:
    name = "fake"
    model = "fake/experts"

    def __init__(self, *, bad_ref: bool = False) -> None:
        self.bad_ref = bad_ref
        self.prompts: list[str] = []

    def generate_structured(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        request_id: str,
        temperature: float,
    ) -> ProviderResponse[T]:
        del request_id, temperature
        self.prompts.append(prompt)
        expert = prompt.splitlines()[0].split("=", 1)[1]
        payload = {
            "candidate_id": "candidate-1",
            "expert": expert,
            "supported_event_class": "insurgency",
            "support_score": 0.7,
            "contradiction_score": 0.2,
            "temporal_relevance": 0.8,
            "source_independence": 0.6,
            "location_resolution": 0.9,
            "coverage_completeness": 0.8,
            "ordinary_crime_risk": 0.1,
            "retrospective_risk": 0.1,
            "leakage_suspected": False,
            "unresolved_fields": [],
            "abstention_recommended": False,
            "evidence_refs": ["invented"] if self.bad_ref else ["obs-1"],
            "contradiction_refs": ["obs-2"],
        }
        return ProviderResponse(
            parsed=output_schema.model_validate(payload), model_version=self.model
        )


def test_workers_are_blind_and_supervisor_preserves_provenance() -> None:
    provider = ExpertProvider()
    runner = ExpertRunner(StructuredLLMEngine(provider))
    assessments = runner.run(pack())
    assert len(assessments) == 5
    # Each prompt contains only its own worker identity, not prior responses.
    assert all("mean_support" not in prompt for prompt in provider.prompts)

    result = DeterministicSupervisor().aggregate(pack(), assessments)
    assert len(result.worker_hashes) == 5
    assert result.evidence_refs == ["obs-1"]
    assert result.contradiction_refs == ["obs-2"]
    assert "probability" not in result.model_dump_json()


def test_worker_cannot_cite_outside_frozen_pack() -> None:
    runner = ExpertRunner(StructuredLLMEngine(ExpertProvider(bad_ref=True)))
    with pytest.raises(ValueError, match="outside the frozen pack"):
        runner.run(pack())


def test_supervisor_requires_every_worker_once() -> None:
    assessments = ExpertRunner(StructuredLLMEngine(ExpertProvider())).run(pack())
    with pytest.raises(ValueError, match="every worker"):
        DeterministicSupervisor().aggregate(pack(), assessments[:-1])
