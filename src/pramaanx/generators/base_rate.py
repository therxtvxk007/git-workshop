"""G0: base-rate and discrete-time hazard generator.

The plainest branch in the build plan, and deliberately the first one built.
Elaborate models routinely lose to a well-estimated base rate on common events,
so a base rate is both a strong prior for later stages and the floor every
later generator has to clear.

Estimation is empirical-Bayes: counts per ``(event_type, region)`` are pooled
toward a global rate through a Gamma-Poisson posterior. Rare pairs therefore
get a shrunk, honest rate with a credible interval rather than a rate of zero
or a rate of one-in-one-day from a single sighting.

Everything here reads only mentions that were admissible at the cutoff.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from scipy import stats  # type: ignore[import-untyped]

from pramaanx.generators.base import (
    BaseGenerator,
    CandidateProposal,
    ForecastContext,
    register_generator,
)
from pramaanx.logging import get_logger
from pramaanx.schemas.event import EventHypothesis, EventMention
from pramaanx.schemas.evidence import EvidenceRef

if TYPE_CHECKING:
    from pramaanx.config import Settings
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.timeguard.snapshots import Snapshot

log = get_logger(__name__)

FORWARD_LOOKING = frozenset({"planned", "possible"})
OCCURRED = frozenset({"asserted"})
MAX_EVIDENCE_PER_CANDIDATE = 8

UNKNOWN_REGION = "UNKNOWN_REGION"
UNKNOWN_ACTOR = "UNKNOWN_ACTOR"

StreamKey = tuple[str, str, str]
"""``(event_type, region, actor)`` -- the granularity a candidate is proposed at."""


def stream_key(mention: EventMention) -> StreamKey:
    """The stream a mention belongs to.

    Missing fields become explicit ``UNKNOWN_*`` markers rather than being
    dropped: an actor the extractor could not resolve is still a stream, and
    silently merging all of them into one would inflate its base rate.
    """
    return (
        mention.event_type,
        mention.location_text or UNKNOWN_REGION,
        mention.subject or UNKNOWN_ACTOR,
    )


def parse_buckets(labels: Sequence[str]) -> list[tuple[str, float, float]]:
    """Turn ``["0-1d", "2-3d", ...]`` into contiguous day intervals.

    The printed labels describe whole days ("2-3d" means the second and third
    day), so as continuous time the intervals butt against each other: the
    previous bucket's end is the next bucket's start. Reading the printed start
    literally would leave uncovered gaps and the bucket probabilities would not
    sum to one.
    """
    parsed: list[tuple[str, float]] = []
    for label in labels:
        cleaned = label.strip().lower().removesuffix("d")
        _, _, end_text = cleaned.partition("-")
        try:
            parsed.append((label, float(end_text)))
        except ValueError as error:
            raise ValueError(f"cannot parse time bucket {label!r}; expected 'a-bd'") from error

    parsed.sort(key=lambda item: item[1])
    buckets: list[tuple[str, float, float]] = []
    previous = 0.0
    for label, end_day in parsed:
        if end_day <= previous:
            raise ValueError(f"time bucket {label!r} does not extend past {previous}d")
        buckets.append((label, previous, end_day))
        previous = end_day
    return buckets


@dataclass(frozen=True)
class RateEstimate:
    """A Gamma-Poisson posterior over the daily rate of one event stream."""

    event_type: str
    region: str
    actor: str
    count: int
    exposure_days: float
    alpha: float
    beta: float
    lower: float
    upper: float

    @property
    def rate(self) -> float:
        """Posterior mean daily rate."""
        return self.alpha / self.beta

    def occurrence_probability(self, horizon_days: float, rate: float | None = None) -> float:
        """P(at least one event within the horizon) under a Poisson process."""
        lam = self.rate if rate is None else rate
        return -math.expm1(-lam * horizon_days)

    def probability_interval(self, horizon_days: float, multiplier: float) -> tuple[float, float]:
        return (
            self.occurrence_probability(horizon_days, self.lower * multiplier),
            self.occurrence_probability(horizon_days, self.upper * multiplier),
        )


def estimate_rates(
    mentions: Sequence[EventMention],
    *,
    cutoff_at: datetime,
    lookback_days: int,
    confidence_level: float = 0.9,
    prior_strength_days: float = 30.0,
) -> dict[StreamKey, RateEstimate]:
    """Estimate per-stream daily rates from events that already occurred.

    A *stream* is ``(event_type, region, actor)``. Coarser keys -- dropping the
    actor, say -- produce candidates so broad that "at least one protest
    somewhere in this region within 90 days" is true almost by definition, and
    a forecast that is always right is not a forecast.
    """
    window_start = cutoff_at - timedelta(days=lookback_days)
    counts: dict[StreamKey, int] = defaultdict(int)

    for mention in mentions:
        if mention.modality not in OCCURRED:
            continue
        moment = mention.event_time_start
        if moment is None or moment < window_start or moment > cutoff_at:
            continue
        counts[stream_key(mention)] += 1

    exposure = float(lookback_days)
    total_count = sum(counts.values())
    # Pooled rate across all streams; the prior every individual stream is
    # shrunk toward. With no history at all this is zero, and the posterior
    # correctly reports "no idea" through a wide interval.
    global_rate = total_count / (exposure * max(len(counts), 1)) if total_count else 0.0
    alpha0 = max(global_rate * prior_strength_days, 1e-6)
    beta0 = prior_strength_days

    tail = (1.0 - confidence_level) / 2.0
    estimates: dict[StreamKey, RateEstimate] = {}
    for key, count in counts.items():
        alpha = alpha0 + count
        beta = beta0 + exposure
        lower = float(stats.gamma.ppf(tail, a=alpha, scale=1.0 / beta))
        upper = float(stats.gamma.ppf(1.0 - tail, a=alpha, scale=1.0 / beta))
        estimates[key] = RateEstimate(
            event_type=key[0],
            region=key[1],
            actor=key[2],
            count=count,
            exposure_days=exposure,
            alpha=alpha,
            beta=beta,
            lower=lower,
            upper=upper,
        )
    return dict(sorted(estimates.items()))


def seasonal_multiplier(
    mentions: Sequence[EventMention],
    event_type: str,
    month: int,
    *,
    cutoff_at: datetime,
    lookback_days: int,
    pseudo_count: float = 5.0,
) -> float:
    """How much more common this event type is in this calendar month.

    Shrunk toward 1.0 by ``pseudo_count``, because one wet monsoon in the
    history is not evidence that floods are four times as likely every July.
    """
    window_start = cutoff_at - timedelta(days=lookback_days)
    in_month = 0
    total = 0
    for mention in mentions:
        if mention.event_type != event_type or mention.modality not in OCCURRED:
            continue
        moment = mention.event_time_start
        if moment is None or moment < window_start or moment > cutoff_at:
            continue
        total += 1
        if moment.month == month:
            in_month += 1
    if total == 0:
        return 1.0
    expected_share = 1.0 / 12.0
    observed_share = (in_month + pseudo_count * expected_share) / (total + pseudo_count)
    return observed_share / expected_share


@register_generator
class BaseRateGenerator(BaseGenerator):
    """Proposes ``(event_type, region)`` candidates ranked by hazard."""

    name = "base_rate"
    VERSION = "0.1.0"

    def __init__(
        self,
        mentions: Sequence[EventMention],
        *,
        time_buckets: Sequence[str],
        lookback_days: int = 365,
        recent_activity_days: int = 30,
        confidence_level: float = 0.9,
        activity_weight: float = 0.35,
        max_activity_multiplier: float = 3.0,
        source_reliability: Mapping[str, float] | None = None,
        observation_sources: Mapping[str, str] | None = None,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        self.mentions = list(mentions)
        self.buckets = parse_buckets(time_buckets)
        self.lookback_days = lookback_days
        self.recent_activity_days = recent_activity_days
        self.confidence_level = confidence_level
        self.activity_weight = activity_weight
        self.max_activity_multiplier = max_activity_multiplier
        self.source_reliability = dict(source_reliability or {})
        self.observation_sources = dict(observation_sources or {})

    # -- construction -----------------------------------------------------
    @classmethod
    def from_snapshot(
        cls, ledger: EvidenceLedger, settings: Settings, snapshot: Snapshot
    ) -> BaseRateGenerator:
        from pramaanx.extraction.structured import extract_mentions

        observations = list(snapshot.observations)
        mentions = extract_mentions(ledger, observations)
        reliability = {
            record.source_id: record.reliability_prior for record in ledger.read_source_records()
        }
        return cls(
            mentions,
            time_buckets=settings.evaluation.time_buckets,
            lookback_days=settings.generators.lookback_days,
            recent_activity_days=settings.generators.recent_activity_days,
            source_reliability=reliability,
            observation_sources={item.observation_id: item.source_id for item in observations},
        )

    # -- proposal ---------------------------------------------------------
    def _recent_activity(self, cutoff_at: datetime) -> dict[StreamKey, list[EventMention]]:
        """Forward-looking chatter per stream in the trailing window.

        Denials are collected too. A denial is evidence that somebody thought
        the event plausible enough to deny, and the adjudicator should see it,
        so it is retained as contradicting evidence rather than dropped.
        """
        window_start = cutoff_at - timedelta(days=self.recent_activity_days)
        activity: dict[StreamKey, list[EventMention]] = defaultdict(list)
        for mention in self.mentions:
            if mention.modality not in FORWARD_LOOKING and mention.modality != "denied":
                continue
            activity[stream_key(mention)].append(mention)
        # Recency is judged by when the claim was made, which for these sources
        # is the mention's own observation; mentions carry no separate
        # observation time, so the trailing filter uses the event time when the
        # source supplied one and keeps the mention otherwise.
        trimmed: dict[StreamKey, list[EventMention]] = {}
        for key, items in activity.items():
            kept = [
                item
                for item in items
                if item.event_time_start is None
                or (window_start <= item.event_time_start <= cutoff_at)
            ]
            if kept:
                trimmed[key] = sorted(kept, key=lambda item: item.mention_id)
        return trimmed

    def _activity_multiplier(self, mentions: Sequence[EventMention]) -> float:
        supporting = [item for item in mentions if item.modality in FORWARD_LOOKING]
        weight = sum(item.extraction_probability for item in supporting)
        multiplier = 1.0 + self.activity_weight * math.log1p(weight)
        return min(multiplier, self.max_activity_multiplier)

    def _evidence(self, mentions: Sequence[EventMention]) -> list[EvidenceRef]:
        refs: list[EvidenceRef] = []
        for mention in mentions[:MAX_EVIDENCE_PER_CANDIDATE]:
            source = self.observation_sources.get(mention.observation_id, "")
            source_reliability = self.source_reliability.get(source, 0.5)
            refs.append(
                EvidenceRef(
                    observation_id=mention.observation_id,
                    claim=mention.supporting_span,
                    stance="contradicts" if mention.modality == "denied" else "supports",
                    independence_cluster=source or None,
                    reliability=round(source_reliability * mention.extraction_probability, 6),
                )
            )
        return refs

    def _bucket_probabilities(self, rate: float, horizon_days: float) -> dict[str, float]:
        """Discrete-time hazard over the configured buckets, given occurrence."""
        masses: dict[str, float] = {}
        for label, start, end in self.buckets:
            if start >= horizon_days:
                continue
            capped_end = min(end, horizon_days)
            masses[label] = math.exp(-rate * start) - math.exp(-rate * capped_end)
        total = sum(masses.values())
        if total <= 0.0:
            # Degenerate rate: spread mass uniformly rather than emitting an
            # invalid distribution that the schema would reject downstream.
            share = 1.0 / len(self.buckets)
            return {label: share for label, _, _ in self.buckets}
        return {label: value / total for label, value in masses.items()}

    def propose(self, context: ForecastContext) -> list[CandidateProposal]:
        estimates = estimate_rates(
            self.mentions,
            cutoff_at=context.cutoff_at,
            lookback_days=self.lookback_days,
            confidence_level=self.confidence_level,
        )
        activity = self._recent_activity(context.cutoff_at)
        # Streams with fresh chatter but no history still deserve a candidate:
        # excluding them would build a generator that can only predict repeats.
        keys = sorted(set(estimates) | set(activity))
        horizon = float(context.horizon_days)

        proposals: list[CandidateProposal] = []
        for key in keys:
            event_type, region, actor = key
            if not context.in_scope(region):
                continue
            estimate = estimates.get(
                key,
                # No history at all: a near-zero prior with a wide interval,
                # which is the honest description of a stream first seen today.
                RateEstimate(
                    event_type, region, actor, 0, float(self.lookback_days), 1e-6, 30.0, 0.0, 1e-4
                ),
            )
            related = activity.get(key, [])
            multiplier = self._activity_multiplier(related)
            multiplier *= seasonal_multiplier(
                self.mentions,
                event_type,
                context.cutoff_at.month,
                cutoff_at=context.cutoff_at,
                lookback_days=self.lookback_days,
            )
            rate = estimate.rate * multiplier
            probability = estimate.occurrence_probability(horizon, rate)
            lower, upper = estimate.probability_interval(horizon, multiplier)

            hypothesis = EventHypothesis(
                event_id=EventHypothesis.build_id(
                    event_type, [actor], [], f"{region}|{context.cutoff_at.isoformat()}"
                ),
                event_type=event_type,
                actor_ids=[actor] if actor != UNKNOWN_ACTOR else [],
                target_ids=[],
                location_cells={region: 1.0},
                time_bucket_probabilities=self._bucket_probabilities(max(rate, 1e-9), horizon),
                severity_distribution={},
                evidence=self._evidence(related),
                generated_by={self.name},
                # Novelty is high where history is thin: an unseen stream is
                # exactly the case a closed-set guarantee should not cover.
                novelty_score=round(1.0 / (1.0 + estimate.count), 6),
            )
            proposals.append(
                CandidateProposal(
                    hypothesis=hypothesis,
                    generator_name=self.name,
                    generator_score=round(min(max(probability, 0.0), 1.0), 9),
                    trace={
                        "posterior_rate_per_day": round(estimate.rate, 9),
                        "activity_multiplier": round(multiplier, 6),
                        "effective_rate_per_day": round(rate, 9),
                        "historical_count": estimate.count,
                        "exposure_days": estimate.exposure_days,
                        "probability_lower": round(min(lower, upper), 9),
                        "probability_upper": round(max(lower, upper), 9),
                        "forward_looking_mentions": sum(
                            1 for item in related if item.modality in FORWARD_LOOKING
                        ),
                        "denials": sum(1 for item in related if item.modality == "denied"),
                        "horizon_days": context.horizon_days,
                    },
                )
            )

        selected = self.enforce_budget(proposals, context.proposal_budget)
        log.info(
            "generator.propose",
            generator=self.name,
            candidates=len(selected),
            considered=len(proposals),
            budget=context.proposal_budget,
        )
        return selected


def epistemic_uncertainty(proposal: CandidateProposal) -> float:
    """Interval width on the occurrence probability, in [0, 1].

    This is the generator's own statistical uncertainty about the rate. It is
    not the full epistemic picture -- generator disagreement, evidence
    insufficiency and distribution shift belong to Phase 8 -- and it is recorded
    under that narrower meaning.
    """
    lower = float(proposal.trace.get("probability_lower", 0.0))
    upper = float(proposal.trace.get("probability_upper", 1.0))
    return round(min(max(upper - lower, 0.0), 1.0), 9)
