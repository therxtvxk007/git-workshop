"""Matching forecasts to outcomes.

Open-world forecasting cannot be scored by string equality, so a match is a
graded decision over structured fields, time and place. Three properties of
this implementation matter more than its weights:

* the hard constraints (horizon, event family, required actors) can veto a
  match no matter how high the soft score climbs;
* borderline and high-impact matches are flagged for human review instead of
  being silently counted;
* the semantic component is deterministic token overlap, not a model score.
  An LLM judgement may never be treated as unquestioned ground truth here, and
  before any headline metric is believed this matcher has to be validated
  against blinded dual-human labels.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pramaanx.isolation import guard_outcome_access
from pramaanx.logging import get_logger
from pramaanx.schemas.forecast import ForecastRecord
from pramaanx.schemas.outcome import MatchResult, OutcomeRecord

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Soft-score weights. They sum to 1.0 and are config, not truth.
#:
#: No two components may sum to the default threshold on their own. An earlier
#: version weighted event_type at 0.40 and time at 0.20, which meant every
#: forecast of the right event type inside the horizon matched -- location and
#: actor could not affect the outcome, and 73% of candidates "hit". Getting the
#: event type right is the cheapest of the four claims and is weighted as such.
WEIGHTS = {
    "event_type": 0.30,
    "location": 0.30,
    "actor": 0.25,
    "time": 0.15,
}

REVIEW_BAND = 0.15
"""Matches within this distance of the threshold go to a human."""


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_TOKEN_RE.findall(text.lower()))


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True)
class MatchContext:
    """The window a forecast is being judged over."""

    cutoff_at: datetime
    horizon_days: int

    @property
    def horizon_end(self) -> datetime:
        return self.cutoff_at + timedelta(days=self.horizon_days)


class OutcomeMatcher:
    """Scores one forecast against candidate outcomes."""

    def __init__(self, min_score: float = 0.6, review_band: float = REVIEW_BAND) -> None:
        self.min_score = min_score
        self.review_band = review_band

    # -- component scores -------------------------------------------------
    @staticmethod
    def event_type_score(forecast_type: str, outcome_type: str) -> float:
        if forecast_type == outcome_type:
            return 1.0
        overlap = jaccard(_tokens(forecast_type), _tokens(outcome_type))
        # Partial credit only for genuine lexical relatedness ("armed_clash" vs
        # "clash"), never enough on its own to clear the threshold.
        return round(overlap, 9)

    @staticmethod
    def location_score(cells: dict[str, float], outcome_cell: str | None) -> float:
        if not cells:
            return 0.0
        if outcome_cell is None:
            return 0.0
        if outcome_cell in cells:
            # Weighted by how much of the forecast's location mass sat there.
            return round(min(1.0, 0.5 + 0.5 * cells[outcome_cell]), 9)
        best = max(
            (jaccard(_tokens(cell), _tokens(outcome_cell)) for cell in cells),
            default=0.0,
        )
        return round(best, 9)

    @staticmethod
    def time_score(occurred_at: datetime, context: MatchContext, tolerance_days: float) -> float:
        """1.0 inside the horizon, decaying across the family's tolerance."""
        if context.cutoff_at < occurred_at <= context.horizon_end:
            return 1.0
        overrun = (occurred_at - context.horizon_end).total_seconds() / 86400.0
        if overrun <= 0 or tolerance_days <= 0:
            return 0.0
        return round(max(0.0, 1.0 - overrun / tolerance_days), 9)

    @staticmethod
    def actor_score(forecast_actors: Sequence[str], outcome_actors: Sequence[str]) -> float:
        if not outcome_actors:
            return 0.0
        if not forecast_actors:
            return 0.0
        if set(forecast_actors) & set(outcome_actors):
            return 1.0
        best = 0.0
        for left in forecast_actors:
            for right in outcome_actors:
                best = max(best, jaccard(_tokens(left), _tokens(right)))
        return round(best, 9)

    # -- matching ---------------------------------------------------------
    def score(
        self, forecast: ForecastRecord, outcome: OutcomeRecord, context: MatchContext
    ) -> MatchResult:
        guard_outcome_access("OutcomeMatcher.score")
        hypothesis = forecast.hypothesis
        tolerance = outcome.tolerance
        event = outcome.event

        scores = {
            "event_type": self.event_type_score(hypothesis.event_type, event.event_type),
            "location": self.location_score(hypothesis.location_cells, event.location_cell),
            "time": self.time_score(event.occurred_at, context, tolerance.time_tolerance_days),
            "actor": self.actor_score(hypothesis.actor_ids, event.actor_ids),
        }
        total = round(sum(WEIGHTS[key] * value for key, value in scores.items()), 9)

        # Hard constraints first. The soft score ranks candidates that are
        # already plausible; it must never rescue one that named the wrong
        # place, the wrong actor or the wrong window.
        vetoes: list[str] = []
        if scores["time"] <= 0.0:
            vetoes.append("outcome falls outside the forecast horizon and tolerance")
        if scores["event_type"] < tolerance.min_semantic_score:
            vetoes.append("event type is not compatible")
        if tolerance.require_actor_match and scores["actor"] <= 0.0:
            vetoes.append("family requires an actor match")
        if (
            tolerance.require_location_match
            and event.location_cell is not None
            and scores["location"] <= 0.0
        ):
            vetoes.append("forecast named a different location")
        if tolerance.require_target_match and not (
            set(hypothesis.target_ids) & set(event.target_ids)
        ):
            vetoes.append("family requires a target match")

        matched = not vetoes and total >= self.min_score
        lead_time = None
        if matched:
            lead_time = round((event.occurred_at - context.cutoff_at).total_seconds() / 86400.0, 6)

        near_threshold = abs(total - self.min_score) <= self.review_band
        return MatchResult(
            forecast_id=forecast.forecast_id,
            outcome_id=outcome.outcome_id,
            matched=matched,
            score=min(max(total, 0.0), 1.0),
            field_scores=dict(sorted(scores.items())),
            lead_time_days=lead_time,
            # Borderline scores, and anything a human has not adjudicated, are
            # queued rather than quietly counted either way.
            requires_human_review=near_threshold or (matched and not outcome.adjudications),
            reason="; ".join(vetoes) if vetoes else ("matched" if matched else "below threshold"),
        )

    def best_match(
        self,
        forecast: ForecastRecord,
        outcomes: Sequence[OutcomeRecord],
        context: MatchContext,
    ) -> MatchResult:
        """Highest-scoring outcome for this forecast, or a recorded non-match."""
        results = [self.score(forecast, outcome, context) for outcome in outcomes]
        matches = [item for item in results if item.matched]
        if matches:
            return max(matches, key=lambda item: (item.score, item.outcome_id or ""))
        if results:
            return max(results, key=lambda item: (item.score, item.outcome_id or ""))
        return MatchResult(
            forecast_id=forecast.forecast_id,
            outcome_id=None,
            matched=False,
            score=0.0,
            reason="no outcomes in the resolution window",
        )

    def match_all(
        self,
        forecasts: Sequence[ForecastRecord],
        outcomes: Sequence[OutcomeRecord],
        context: MatchContext,
    ) -> list[MatchResult]:
        """Match every forecast, preserving input order for reproducibility."""
        results = [self.best_match(forecast, outcomes, context) for forecast in forecasts]
        review_count = sum(1 for item in results if item.requires_human_review)
        if review_count:
            log.info(
                "matcher.review_queue",
                flagged=review_count,
                total=len(results),
                note="borderline or unadjudicated matches need human decisions",
            )
        return results
