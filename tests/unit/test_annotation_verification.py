from __future__ import annotations

from datetime import UTC, datetime

from pramaanx.annotation import (
    AnnotationDecision,
    AnnotationReview,
    export_label_studio_tasks,
    resolve_reviews,
)
from pramaanx.annotation.label_studio import make_verification_task
from pramaanx.extraction import VerifiedMention


def task() -> object:
    mention = VerifiedMention(
        observation_id="obs-1",
        span="Forces clashed in Bastar.",
        event_type="armed_clash",
        location_text="Bastar",
        support="supported",
        explicit_fields={"event_type", "location"},
    )
    return make_verification_task(
        observation_id="obs-1",
        text=mention.span,
        preannotations=[mention],
        source_snapshot_hash="sha256:snapshot",
    )


def review(task_id: str, annotator: str, decision: AnnotationDecision) -> AnnotationReview:
    return AnnotationReview(
        task_id=task_id,
        annotator_id=annotator,
        decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        decision=decision,
    )


def test_label_studio_export_contains_zero_confidence_preannotation() -> None:
    verification_task = task()
    exported = export_label_studio_tasks([verification_task])  # type: ignore[list-item]
    assert exported[0]["predictions"][0]["score"] == 0.0  # type: ignore[index]
    assert exported[0]["data"]["required_blind_reviews"] == 2  # type: ignore[index]


def test_two_blind_agreements_resolve_and_disagreement_is_preserved() -> None:
    verification_task = task()
    task_id = verification_task.task_id  # type: ignore[attr-defined]
    agreed = resolve_reviews(
        verification_task,  # type: ignore[arg-type]
        [
            review(task_id, "annotator-a", AnnotationDecision.ACCEPT),
            review(task_id, "annotator-b", AnnotationDecision.ACCEPT),
        ],
    )
    assert agreed.status == "resolved"
    assert agreed.accepted_mentions

    disputed = resolve_reviews(
        verification_task,  # type: ignore[arg-type]
        [
            review(task_id, "annotator-a", AnnotationDecision.ACCEPT),
            review(task_id, "annotator-b", AnnotationDecision.REJECT),
        ],
    )
    assert disputed.status == "disputed"
    assert len(disputed.review_hashes) == 2
