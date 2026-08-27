"""G1: temporal rules over the evidence graph.

G0 asks one question -- how often does this stream fire? -- and answers it with
a shrunk base rate. That is a strong floor precisely because it ignores
structure, and anything that claims to beat it has to earn the difference from
structure it can name.

So this generator is three named rules, each of which contributes its own score
and its own trace entry:

*Recurrence.* A stream that fires at regular intervals is due when the time
since the last event approaches the mean interval. Regularity is measured, not
assumed: a bursty stream gets almost nothing from this rule.

*Escalation.* A stream whose recent rate exceeds its own baseline is elevated.
Compared against itself rather than against a global rate, so a chronically
active stream does not read as permanently escalating.

*Diffusion.* An actor active in one place, co-occurring with actors active in
another, proposes candidates in the second place. This is the only rule that
uses the graph as a graph, and the only one that can propose a candidate for a
series with no history at all.

Every rule is separately switchable. That is not a convenience: the candidate
oracle diagnostic needs to attribute a miss to a specific branch, and a
generator that produces one undifferentiated score cannot support that.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from pramaanx.entities.dedupe import EventCluster, deduplicate_mentions
from pramaanx.entities.resolve import EntityIndex, resolve_entities
from pramaanx.features.builders import build_features, series_from_clusters
from pramaanx.features.spec import FeatureVector, SeriesKey
from pramaanx.generators.base import (
    BaseGenerator,
    CandidateProposal,
    ForecastContext,
    register_generator,
)
from pramaanx.generators.base_rate import parse_buckets
from pramaanx.graph.evidence_graph import EdgeRelation, EvidenceGraph, build_graph
from pramaanx.graph.retrieval import RetrievalQuery, retrieve_evidence
from pramaanx.logging import get_logger
from pramaanx.schemas.event import EventHypothesis, EventMention

if TYPE_CHECKING:
    from pramaanx.config import Settings
    from pramaanx.ingest.ledger import EvidenceLedger
    from pramaanx.timeguard.snapshots import Snapshot

log = get_logger(__name__)

#: Rule names, used as trace keys and as ablation switches.
RULE_RECURRENCE = "recurrence"
RULE_ESCALATION = "escalation"
RULE_DIFFUSION = "diffusion"
ALL_RULES: tuple[str, ...] = (RULE_RECURRENCE, RULE_ESCALATION, RULE_DIFFUSION)

#: A stream needs this many prior events before recurrence will say anything.
#: Two events define one interval, which is not evidence of a period.
MIN_EVENTS_FOR_RECURRENCE = 3

#: Dispersion above this means the stream is too bursty for recurrence to help.
MAX_DISPERSION_FOR_RECURRENCE = 0.6

#: Evidence items attached to each proposal.
MAX_EVIDENCE_PER_CANDIDATE = 8


class TemporalRuleGenerator(BaseGenerator):
    """Proposes candidates from recurrence, escalation and diffusion."""

    name = "temporal_rules"
    VERSION = "0.1.0"

    def __init__(
        self,
        mentions: Sequence[EventMention],
        clusters: Sequence[EventCluster],
        index: EntityIndex,
        graph: EvidenceGraph,
        *,
        time_buckets: Sequence[str],
        rules: Sequence[str] = ALL_RULES,
        max_probability: float = 0.95,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        unknown = sorted(set(rules) - set(ALL_RULES))
        if unknown:
            raise ValueError(f"unknown rules: {unknown}; known: {list(ALL_RULES)}")
        self.mentions = list(mentions)
        self.clusters = list(clusters)
        self.index = index
        self.graph = graph
        self.buckets = parse_buckets(time_buckets)
        self.rules = tuple(sorted(set(rules)))
        self.max_probability = max_probability

    @property
    def version(self) -> str:
        """Version string carries the active rule set.

        An ablation that disables diffusion is a different model, and a forecast
        record that says only ``temporal_rules@0.1.0`` cannot tell you which one
        produced it.
        """
        return f"{self.name}@{self.VERSION}+{'|'.join(self.rules)}"

    @classmethod
    def from_snapshot(
        cls, ledger: EvidenceLedger, settings: Settings, snapshot: Snapshot
    ) -> TemporalRuleGenerator:
        from pramaanx.extraction.structured import extract_mentions

        observations = list(snapshot.observations)
        mentions = extract_mentions(ledger, observations)
        cutoff = snapshot.cutoff_at
        index = resolve_entities(mentions, cutoff_at=cutoff)
        clusters = deduplicate_mentions(mentions, index, cutoff_at=cutoff)
        graph = build_graph(clusters, index, cutoff_at=cutoff)
        return cls(
            mentions,
            clusters,
            index,
            graph,
            time_buckets=settings.evaluation.time_buckets,
            rules=ALL_RULES,
        )

    # -- rules ------------------------------------------------------------
    def _recurrence_score(self, features: FeatureVector) -> tuple[float, dict[str, Any]]:
        """Due-ness of a regularly spaced stream.

        Peaks when the elapsed time equals the mean interval and decays either
        side of it, so a stream that has just fired is not immediately proposed
        again and one long overdue is not proposed forever.
        """
        events = features.get("events_last_365d")
        interval = features.get("interval_mean_days")
        dispersion = features.get("interval_dispersion")
        elapsed = features.get("days_since_last_event")
        if events < MIN_EVENTS_FOR_RECURRENCE or interval <= 0.0:
            return 0.0, {"fired": False, "reason": "insufficient_history"}
        if dispersion > MAX_DISPERSION_FOR_RECURRENCE:
            return 0.0, {"fired": False, "reason": "too_bursty", "dispersion": dispersion}
        phase = elapsed / interval
        # Gaussian around one full period. Width scales with the observed
        # dispersion, so a tightly periodic stream gets a sharp peak and a
        # loosely periodic one a broad, weaker bump.
        width = max(0.25 + dispersion, 0.25)
        score = math.exp(-((phase - 1.0) ** 2) / (2.0 * width * width))
        # Regular streams deserve more of the peak than irregular ones.
        score *= 1.0 - dispersion
        return float(min(max(score, 0.0), 1.0)), {
            "fired": True,
            "phase": round(phase, 4),
            "interval_mean_days": round(interval, 3),
            "dispersion": round(dispersion, 4),
        }

    def _escalation_score(self, features: FeatureVector) -> tuple[float, dict[str, Any]]:
        """Elevation of the recent rate over the stream's own baseline."""
        ratio = features.get("escalation_ratio", 1.0)
        recent = features.get("events_last_30d")
        if recent <= 0.0:
            return 0.0, {"fired": False, "reason": "no_recent_activity"}
        if ratio <= 1.0:
            return 0.0, {"fired": False, "reason": "not_escalating", "ratio": round(ratio, 4)}
        # Saturating: three times the baseline is a strong signal, ten times is
        # usually a reporting artefact rather than ten times the danger.
        score = 1.0 - (1.0 / ratio)
        return float(min(max(score, 0.0), 1.0)), {
            "fired": True,
            "ratio": round(ratio, 4),
            "recent_events": recent,
        }

    def _diffusion_score(
        self, series: SeriesKey, features: FeatureVector, as_of: datetime
    ) -> tuple[float, dict[str, Any]]:
        """Spread along co-occurrence edges from an active neighbour.

        The only rule that can speak about a stream with no history, which is
        also the only rule that can invent a candidate out of nothing. It is
        therefore the most heavily discounted, and it never fires without a
        named neighbour in the trace.
        """
        if series.actor_id is None:
            return 0.0, {"fired": False, "reason": "no_actor"}
        view = self.graph.as_of(as_of)
        if series.actor_id not in {node.node_id for node in view.nodes}:
            return 0.0, {"fired": False, "reason": "actor_absent_from_graph"}
        neighbours = view.neighbours(series.actor_id, relations={EdgeRelation.CO_OCCURRED})
        if not neighbours:
            return 0.0, {"fired": False, "reason": "no_co_actors"}

        window_start = as_of - timedelta(days=90.0)
        active: list[str] = []
        for neighbour in neighbours:
            for cluster in self.clusters:
                if cluster.first_observed_at > as_of or cluster.window_start < window_start:
                    continue
                if cluster.event_type != series.event_type:
                    continue
                if neighbour in cluster.actor_ids and neighbour not in active:
                    active.append(neighbour)
        if not active:
            return 0.0, {"fired": False, "reason": "no_active_co_actors"}

        # Saturating in the number of active neighbours, discounted hard, and
        # further discounted when the series itself already has history -- in
        # that case recurrence and escalation are the better-evidenced rules and
        # diffusion should not double-count them.
        breadth = 1.0 - (1.0 / (1.0 + float(len(active))))
        discount = 0.35 if features.get("events_last_365d") > 0.0 else 0.6
        return float(min(breadth * discount, 1.0)), {
            "fired": True,
            "active_co_actors": sorted(active)[:8],
            "count": len(active),
        }

    # -- proposal ---------------------------------------------------------
    def propose(self, context: ForecastContext) -> list[CandidateProposal]:
        """Score every series and emit the best candidates within budget."""
        as_of = context.cutoff_at
        if as_of > self.graph.cutoff_at:
            raise ValueError(
                f"context cutoff {as_of.isoformat()} is after the graph cutoff "
                f"{self.graph.cutoff_at.isoformat()}"
            )
        if as_of < self.graph.cutoff_at:
            # Caught here rather than three frames down in the feature builder,
            # where the same mistake surfaces as a confusing message about a
            # cluster set nobody in this call chose.
            raise ValueError(
                f"context cutoff {as_of.isoformat()} predates the graph cutoff "
                f"{self.graph.cutoff_at.isoformat()}; rebuild the cluster set and "
                "graph for this cutoff rather than reusing a later one"
            )
        entities = self.index.by_id()
        proposals: list[CandidateProposal] = []

        for series in series_from_clusters(self.clusters):
            location_name = None
            if series.location_id and series.location_id in entities:
                location_name = entities[series.location_id].canonical_name
            if not context.in_scope(location_name):
                continue

            features = build_features(series, self.clusters, self.graph, as_of=as_of)
            contributions: dict[str, float] = {}
            trace: dict[str, Any] = {"series": series.key, "rules": {}}

            if RULE_RECURRENCE in self.rules:
                score, detail = self._recurrence_score(features)
                contributions[RULE_RECURRENCE] = score
                trace["rules"][RULE_RECURRENCE] = detail
            if RULE_ESCALATION in self.rules:
                score, detail = self._escalation_score(features)
                contributions[RULE_ESCALATION] = score
                trace["rules"][RULE_ESCALATION] = detail
            if RULE_DIFFUSION in self.rules:
                score, detail = self._diffusion_score(series, features, as_of)
                contributions[RULE_DIFFUSION] = score
                trace["rules"][RULE_DIFFUSION] = detail

            combined = _combine(contributions)
            if combined <= 0.0:
                continue

            hypothesis = self._hypothesis(series, features, combined, context, as_of)
            trace["contributions"] = {name: round(value, 6) for name, value in
                                      sorted(contributions.items())}
            trace["features"] = {
                name: round(features.get(name), 6)
                for name in (
                    "events_last_30d",
                    "events_last_365d",
                    "days_since_last_event",
                    "interval_mean_days",
                    "interval_dispersion",
                    "escalation_ratio",
                    "novelty",
                )
            }
            proposals.append(
                CandidateProposal(
                    hypothesis=hypothesis,
                    generator_name=self.name,
                    generator_score=min(combined, self.max_probability),
                    trace=trace,
                )
            )

        selected = self.enforce_budget(proposals, context.proposal_budget)
        log.info(
            "generators.temporal_rules.proposed",
            scored=len(proposals),
            selected=len(selected),
            rules=list(self.rules),
        )
        return selected

    def _hypothesis(
        self,
        series: SeriesKey,
        features: FeatureVector,
        score: float,
        context: ForecastContext,
        as_of: datetime,
    ) -> EventHypothesis:
        """Assemble the hypothesis, including its retrieved evidence pack."""
        actors = [series.actor_id] if series.actor_id else []
        location_cells = {series.location_id: 1.0} if series.location_id else {}

        evidence = []
        if actors or series.event_type:
            query = RetrievalQuery(
                seed_entity_ids=actors,
                event_types=[series.event_type],
                as_of=as_of,
                limit=MAX_EVIDENCE_PER_CANDIDATE,
            )
            pack = retrieve_evidence(self.graph, self.clusters, self.mentions, query)
            evidence = pack.refs()[:MAX_EVIDENCE_PER_CANDIDATE]

        return EventHypothesis(
            event_id=EventHypothesis.build_id(
                series.event_type, actors, [], series.location_id or ""
            ),
            event_type=series.event_type,
            actor_ids=actors,
            target_ids=[],
            location_cells=location_cells,
            time_bucket_probabilities=self._buckets(score, context.horizon_days),
            severity_distribution={},
            evidence=evidence,
            generated_by={self.name},
            novelty_score=features.get("novelty", 0.0),
        )

    def _buckets(self, score: float, horizon_days: int) -> dict[str, float]:
        """Spread the score across time buckets by exposure.

        Proportional to each bucket's width inside the horizon. A flat split
        would put as much mass in a two-day bucket as in a sixty-day one, which
        is a claim about timing that no rule here actually makes.
        """
        if not self.buckets:
            return {}
        widths: dict[str, float] = {}
        for label, start, end in self.buckets:
            overlap = max(min(end, float(horizon_days)) - start, 0.0)
            if overlap > 0.0:
                widths[label] = overlap
        total = sum(widths.values())
        if total <= 0.0:
            return {}
        return {label: width / total for label, width in sorted(widths.items())}


def _combine(contributions: dict[str, float]) -> float:
    """Combine rule scores as a noisy-OR.

    Additive combination lets three weak rules manufacture a confident
    candidate; taking the maximum throws away genuine corroboration between
    independent rules. Noisy-OR does neither, and has the property that matters
    here: adding a rule can never *lower* the score, so an ablation reads
    cleanly in one direction.
    """
    product = 1.0
    for value in contributions.values():
        product *= 1.0 - min(max(value, 0.0), 1.0)
    return float(1.0 - product)


register_generator(TemporalRuleGenerator)
