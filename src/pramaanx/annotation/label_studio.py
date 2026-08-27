"""Label Studio tasks where humans verify model pre-annotations."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from pramaanx.extraction.gemini_stage import VerifiedMention
from pramaanx.hashing import hash_object, stable_id
from pramaanx.schemas.base import UtcDatetime, VersionedModel


class AnnotationDecision(StrEnum):
    ACCEPT = "accept"
    CORRECT = "correct"
    REJECT = "reject"


class VerificationTask(VersionedModel):
    task_id: str
    observation_id: str
    text: str
    preannotations: list[VerifiedMention]
    source_snapshot_hash: str
    required_blind_reviews: int = Field(default=2, ge=2)


class AnnotationReview(VersionedModel):
    task_id: str
    annotator_id: str
    decided_at: UtcDatetime
    decision: AnnotationDecision
    corrected_mentions: list[VerifiedMention] = Field(default_factory=list)
    blinded: bool = True

    @field_validator("task_id", "annotator_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task and annotator identities cannot be blank")
        return value

    @model_validator(mode="after")
    def _check_correction(self) -> AnnotationReview:
        if self.decision is AnnotationDecision.CORRECT and not self.corrected_mentions:
            raise ValueError("a correction decision requires corrected mentions")
        if self.decision is not AnnotationDecision.CORRECT and self.corrected_mentions:
            raise ValueError("corrected mentions are only valid for a correction decision")
        if not self.blinded:
            raise ValueError("gold-set verification reviews must be blinded")
        return self


class ReviewResolution(VersionedModel):
    task_id: str
    status: str
    review_hashes: list[str]
    accepted_mentions: list[VerifiedMention] = Field(default_factory=list)


def make_verification_task(
    *,
    observation_id: str,
    text: str,
    preannotations: list[VerifiedMention],
    source_snapshot_hash: str,
) -> VerificationTask:
    return VerificationTask(
        task_id=stable_id(
            "label-task",
            observation_id,
            source_snapshot_hash,
            [mention.model_dump(mode="json") for mention in preannotations],
        ),
        observation_id=observation_id,
        text=text,
        preannotations=preannotations,
        source_snapshot_hash=source_snapshot_hash,
    )


def export_label_studio_tasks(tasks: list[VerificationTask]) -> list[dict[str, object]]:
    """Export pre-annotations as reviewable Label Studio task data."""
    return [
        {
            "id": task.task_id,
            "data": {
                "observation_id": task.observation_id,
                "text": task.text,
                "source_snapshot_hash": task.source_snapshot_hash,
                "required_blind_reviews": task.required_blind_reviews,
            },
            "predictions": [
                {
                    "model_version": "pramaanx-preannotation@1",
                    "score": 0.0,
                    "result": [mention.model_dump(mode="json") for mention in task.preannotations],
                }
            ],
        }
        for task in tasks
    ]


def resolve_reviews(task: VerificationTask, reviews: list[AnnotationReview]) -> ReviewResolution:
    """Accept agreement; preserve disagreement for a separate adjudicator."""
    task_reviews = [review for review in reviews if review.task_id == task.task_id]
    annotators = {review.annotator_id for review in task_reviews}
    if len(annotators) < task.required_blind_reviews:
        return ReviewResolution(
            task_id=task.task_id,
            status="needs_more_reviews",
            review_hashes=sorted(review.content_hash() for review in task_reviews),
        )
    # Only the required first reviews are compared; additional adjudication is
    # recorded as a separate process rather than silently replacing them.
    selected = sorted(task_reviews, key=lambda review: review.annotator_id)[
        : task.required_blind_reviews
    ]
    signatures = [
        hash_object(
            {
                "decision": review.decision,
                "mentions": [
                    mention.model_dump(mode="json") for mention in review.corrected_mentions
                ],
            }
        )
        for review in selected
    ]
    if len(set(signatures)) != 1:
        return ReviewResolution(
            task_id=task.task_id,
            status="disputed",
            review_hashes=sorted(review.content_hash() for review in selected),
        )
    decision = selected[0].decision
    if decision is AnnotationDecision.ACCEPT:
        accepted = task.preannotations
    elif decision is AnnotationDecision.CORRECT:
        accepted = selected[0].corrected_mentions
    else:
        accepted = []
    return ReviewResolution(
        task_id=task.task_id,
        status="resolved",
        review_hashes=sorted(review.content_hash() for review in selected),
        accepted_mentions=accepted,
    )
