from __future__ import annotations

from collections.abc import Sequence

from _phase2_builders import observation

from pramaanx.extraction import GLiNERStage, SpanEntity


class FakeGLiNER:
    model_version = "fake-gliner@1"

    def predict(self, text: str, labels: Sequence[str]) -> Sequence[SpanEntity]:
        del text, labels
        return [
            SpanEntity(text="Security forces", label="security force", score=0.9),
            SpanEntity(text="Maoist fighters", label="armed group", score=0.8),
            SpanEntity(text="Bastar", label="district", score=0.95),
        ]


def test_gliner_fills_spans_without_deciding_event_type() -> None:
    stage = GLiNERStage(FakeGLiNER())
    candidates = stage.propose(
        observation(observed_days=10),
        "Security forces clashed with Maoist fighters in Bastar.",
    )
    assert candidates
    assert candidates[0].event_type == "armed_clash"
    assert candidates[0].subject == "Security forces"
    assert candidates[0].location_text == "Bastar"
    assert stage.version.endswith("fake-gliner@1")
