"""Feature construction from the evidence graph.

Every builder here obeys the same two filters, and the order matters:

1. *Availability.* A cluster contributes only if ``first_observed_at <= as_of``.
   This is the leak guard, and it is applied first because it is the one that
   cannot be recovered from later.
2. *Relevance.* Of what was available, a cluster contributes to a window only
   if its *event window* falls inside it.

Conflating the two is the classic backtest bug. Counting by event time alone
credits January with an event the corpus only learned about in March; counting
by availability alone reports a burst of activity on the day a slow archive
finally published, which is a fact about the publisher rather than about the
world.

The reporting-lag features exist because that gap is itself signal. A series
whose evidence arrives three weeks late cannot support a seven-day forecast,
and a model that cannot see the lag will happily pretend otherwise.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import datetime, timedelta

from pramaanx.entities.dedupe import EventCluster
from pramaanx.features.spec import (
    REGISTRY,
    FeatureKind,
    FeatureSpec,
    FeatureVector,
    SeriesKey,
)
from pramaanx.graph.evidence_graph import EdgeRelation, EvidenceGraph
from pramaanx.logging import get_logger

log = get_logger(__name__)

#: Trailing windows, in days, that the count features are built over.
COUNT_WINDOWS: tuple[float, ...] = (7.0, 30.0, 90.0, 365.0)

#: Baseline window the escalation ratio compares the recent window against.
ESCALATION_BASELINE_DAYS = 365.0
ESCALATION_RECENT_DAYS = 30.0


def _register_all() -> dict[str, FeatureSpec]:
    """Declare every feature this module can produce."""
    specs: list[FeatureSpec] = [
        FeatureSpec(
            name=f"events_last_{int(window)}d",
            kind=FeatureKind.COUNT,
            description=f"Event clusters in the series whose window falls in the last {int(window)} days.",
            window_days=window,
        )
        for window in COUNT_WINDOWS
    ]
    specs.extend(
        [
            FeatureSpec(
                name="rate_per_30d",
                kind=FeatureKind.RATE,
                description="Events per 30 days over all available history.",
            ),
            FeatureSpec(
                name="days_since_last_event",
                kind=FeatureKind.DURATION,
                description="Days from the most recent event window to as_of.",
                # A long quiet stretch lowers the hazard for a recency-driven
                # process. Declared so a generator that treats it the other way
                # round has to say so explicitly.
                inverse=True,
                default=float(ESCALATION_BASELINE_DAYS),
            ),
            FeatureSpec(
                name="interval_mean_days",
                kind=FeatureKind.DURATION,
                description="Mean gap between consecutive event windows.",
            ),
            FeatureSpec(
                name="interval_dispersion",
                kind=FeatureKind.RATIO,
                description=(
                    "Coefficient of variation of inter-event gaps, squashed to [0, 1]. "
                    "0 is perfectly regular; near 1 is bursty."
                ),
            ),
            FeatureSpec(
                name="escalation_ratio",
                kind=FeatureKind.RATE,
                description=(
                    "Recent 30-day rate divided by the 365-day baseline rate. "
                    "1.0 means no change."
                ),
                default=1.0,
            ),
            FeatureSpec(
                name="effective_support_90d",
                kind=FeatureKind.COUNT,
                description="Independent stories behind the series in the last 90 days.",
                window_days=90.0,
            ),
            FeatureSpec(
                name="contested_ratio",
                kind=FeatureKind.RATIO,
                description="Fraction of available clusters that carry a denial.",
            ),
            FeatureSpec(
                name="co_actor_degree",
                kind=FeatureKind.COUNT,
                description="Distinct entities co-occurring with the series actor.",
            ),
            FeatureSpec(
                name="novelty",
                kind=FeatureKind.SCORE,
                description=(
                    "1.0 when the series has no prior history at all, decaying "
                    "toward 0 as observations accumulate."
                ),
                default=1.0,
            ),
            FeatureSpec(
                name="reporting_lag_mean_days",
                kind=FeatureKind.DURATION,
                description="Mean days between an event window ending and its first observation.",
            ),
            FeatureSpec(
                name="undated_ratio",
                kind=FeatureKind.RATIO,
                description="Fraction of contributing mentions that carried no event date.",
            ),
        ]
    )
    for spec in specs:
        REGISTRY.register(spec)
    return {spec.name: spec for spec in specs}


SPECS = _register_all()

FEATURE_NAMES: tuple[str, ...] = tuple(sorted(SPECS))
"""Stable ordering for anything that needs a dense vector."""


def _available(
    clusters: Sequence[EventCluster], series: SeriesKey, *, as_of: datetime
) -> list[EventCluster]:
    """Clusters in this series that were observable at ``as_of``."""
    return sorted(
        (
            cluster
            for cluster in clusters
            if cluster.first_observed_at <= as_of
            and series.matches(
                event_type=cluster.event_type,
                actor_ids=cluster.actor_ids,
                location_id=cluster.location_entity_id,
            )
        ),
        key=lambda item: (item.window_start, item.cluster_id),
    )


def _in_window(
    clusters: Sequence[EventCluster], *, as_of: datetime, window_days: float
) -> list[EventCluster]:
    start = as_of - timedelta(days=window_days)
    return [cluster for cluster in clusters if start <= cluster.window_start <= as_of]


def _dispersion(gaps: Sequence[float]) -> float:
    """Coefficient of variation, squashed into [0, 1].

    Squashed rather than clipped: a CV above 1 is common for bursty processes
    and clipping would make every bursty series look identically bursty.
    """
    if len(gaps) < 2:
        return 0.0
    mean = statistics.fmean(gaps)
    if mean <= 0.0:
        return 0.0
    coefficient = statistics.pstdev(gaps) / mean
    return float(coefficient / (1.0 + coefficient))


def build_features(
    series: SeriesKey,
    clusters: Sequence[EventCluster],
    graph: EvidenceGraph,
    *,
    as_of: datetime,
) -> FeatureVector:
    """Build the full feature vector for one series at one instant.

    ``as_of`` must equal the graph cutoff, and an earlier one is refused just as
    firmly as a later one. That is not pedantry, it is the leak guard.

    An :class:`EventCluster` is an artefact of the cutoff it was *built* at. Its
    ``first_observed_at`` is the earliest mention it holds, but its aggregates --
    ``effective_support``, ``window_end``, ``last_observed_at`` -- summarise
    every mention available at build time. So a cluster built in March and read
    as of January passes an availability filter on its first mention while
    carrying March's evidence in its counts. Filtering clusters by
    ``first_observed_at <= as_of`` looks like a cutoff check and is not one.

    One cutoff, one cluster set. Re-running deduplication per cutoff is the only
    honest way to ask what a January view actually contained.
    """
    if as_of != graph.cutoff_at:
        relation = "is after" if as_of > graph.cutoff_at else "predates"
        raise ValueError(
            f"cannot build features as of {as_of.isoformat()}: it {relation} the graph "
            f"cutoff {graph.cutoff_at.isoformat()}. Cluster aggregates belong to the "
            "cutoff they were built at; rebuild the cluster set for this instant."
        )

    available = _available(clusters, series, as_of=as_of)
    values: dict[str, float] = {}

    for window in COUNT_WINDOWS:
        values[f"events_last_{int(window)}d"] = float(
            len(_in_window(available, as_of=as_of, window_days=window))
        )

    if available:
        first_window = available[0].window_start
        span_days = max((as_of - first_window).total_seconds() / 86400.0, 1.0)
        values["rate_per_30d"] = float(len(available)) * 30.0 / span_days

        last_window = max(cluster.window_end for cluster in available)
        values["days_since_last_event"] = max(
            (as_of - last_window).total_seconds() / 86400.0, 0.0
        )

        starts = [cluster.window_start for cluster in available]
        gaps = [
            (later - earlier).total_seconds() / 86400.0
            for earlier, later in zip(starts, starts[1:], strict=False)
        ]
        values["interval_mean_days"] = float(statistics.fmean(gaps)) if gaps else 0.0
        values["interval_dispersion"] = _dispersion(gaps)

        recent = len(_in_window(available, as_of=as_of, window_days=ESCALATION_RECENT_DAYS))
        baseline = len(_in_window(available, as_of=as_of, window_days=ESCALATION_BASELINE_DAYS))
        baseline_rate = baseline * ESCALATION_RECENT_DAYS / ESCALATION_BASELINE_DAYS
        # A baseline of zero with a non-zero recent count is a genuine jump from
        # nothing. Reported as the recent count rather than as an infinity, and
        # never as 1.0, which would read as "no change".
        values["escalation_ratio"] = (
            float(recent) / baseline_rate if baseline_rate > 0.0 else float(recent)
        )

        window_90 = _in_window(available, as_of=as_of, window_days=90.0)
        values["effective_support_90d"] = float(
            sum(cluster.effective_support for cluster in window_90)
        )
        values["contested_ratio"] = float(
            sum(1 for cluster in available if cluster.contested)
        ) / float(len(available))

        lags = [
            (cluster.first_observed_at - cluster.window_end).total_seconds() / 86400.0
            for cluster in available
        ]
        values["reporting_lag_mean_days"] = max(float(statistics.fmean(lags)), 0.0)

        total_mentions = sum(len(cluster.mention_ids) for cluster in available)
        undated = sum(len(cluster.undated_mention_ids) for cluster in available)
        values["undated_ratio"] = float(undated) / float(total_mentions) if total_mentions else 0.0

        # Novelty decays with the number of independent stories, not with the
        # number of clusters: one event reported by twenty outlets does not make
        # a series well-established.
        independent = sum(cluster.effective_support for cluster in available)
        values["novelty"] = 1.0 / (1.0 + float(independent))
    else:
        for spec in (REGISTRY.get(name) for name in SPECS):
            values[spec.name] = spec.default
        for window in COUNT_WINDOWS:
            values[f"events_last_{int(window)}d"] = 0.0

    values["co_actor_degree"] = float(_co_actor_degree(series, graph, as_of=as_of))

    vector = FeatureVector(
        series=series,
        as_of=as_of,
        graph_cutoff_at=graph.cutoff_at,
        values=dict(sorted(values.items())),
        support=len(available),
        effective_support=sum(cluster.effective_support for cluster in available),
    )
    REGISTRY.validate(vector)
    return vector


def _co_actor_degree(series: SeriesKey, graph: EvidenceGraph, *, as_of: datetime) -> int:
    """How many distinct entities the series actor has co-occurred with."""
    if series.actor_id is None:
        return 0
    view = graph.as_of(as_of)
    if series.actor_id not in {node.node_id for node in view.nodes}:
        return 0
    return len(view.neighbours(series.actor_id, relations={EdgeRelation.CO_OCCURRED}))


def build_feature_table(
    series_keys: Sequence[SeriesKey],
    clusters: Sequence[EventCluster],
    graph: EvidenceGraph,
    *,
    as_of: datetime,
) -> list[FeatureVector]:
    """Build vectors for many series, in a deterministic order."""
    vectors = [
        build_features(series, clusters, graph, as_of=as_of)
        for series in sorted(series_keys, key=lambda item: item.key)
    ]
    log.info("features.built", series=len(vectors), as_of=as_of.isoformat())
    return vectors


def series_from_clusters(clusters: Sequence[EventCluster]) -> list[SeriesKey]:
    """Enumerate the (actor, location, event type) series present in a corpus.

    One series per actor rather than one per cluster: the question a generator
    asks is "what does this actor do in this place?", and a series keyed on the
    full actor set would fragment the moment two groups are reported jointly.
    """
    keys: set[tuple[str, str | None, str | None]] = set()
    for cluster in clusters:
        for actor_id in cluster.actor_ids or [None]:
            keys.add((cluster.event_type, actor_id, cluster.location_entity_id))
    return sorted(
        (
            SeriesKey(event_type=event_type, actor_id=actor_id, location_id=location_id)
            for event_type, actor_id, location_id in keys
        ),
        key=lambda item: item.key,
    )
