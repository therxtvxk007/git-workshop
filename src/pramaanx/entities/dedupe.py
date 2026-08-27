"""Event deduplication and independence clustering.

Two different failures are handled here, and conflating them is what makes
corroboration counts lie.

The first is *event duplication*: fifty mentions describe one attack, and a
count of mentions therefore reports fifty attacks. Clustering by resolved
actors, location and time window collapses them back to one.

The second is *evidence dependence*: those fifty mentions are not fifty
independent witnesses. Forty of them are one wire story reprinted, so the
cluster deserves the confidence of roughly ten sources, not fifty. Independence
clusters are computed from text overlap and every downstream confidence uses
:attr:`EventCluster.effective_support` -- the number of *independent* clusters
-- rather than the raw mention count.

A third thing is deliberately *not* done: contradicting mentions are never
merged away. A report that an attack was denied stays in the cluster, counted
separately, and marks the cluster contested. Averaging a denial into a
corroboration count is how a system reports high confidence in an event that
half its sources say never happened.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import Field, model_validator

from pramaanx.entities.normalise import jaccard, shingles
from pramaanx.entities.resolve import EntityIndex
from pramaanx.hashing import stable_id
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel
from pramaanx.schemas.event import EventMention

log = get_logger(__name__)

#: Two mentions of the same actors and place are treated as the same event if
#: their event-time windows are within this distance of each other. Reporting
#: dates drift by a day or two across timezones and filing deadlines.
DEFAULT_TIME_TOLERANCE_DAYS = 2.0

#: How long after an event a report may still arrive and be attached to it by
#: availability alone. Only used for mentions that carry no event time at all.
DEFAULT_REPORTING_LAG_DAYS = 7.0

#: Shingle overlap above which two spans are treated as one story.
DEFAULT_INDEPENDENCE_THRESHOLD = 0.6

#: Modalities that assert the event happened or will happen. Anything outside
#: this set contributes to the cluster without corroborating it.
CORROBORATING_MODALITIES: frozenset[str] = frozenset({"asserted", "planned"})


class IndependenceGroup(PramaanModel):
    """A set of mentions judged to derive from one another."""

    group_id: str
    mention_ids: list[str] = Field(default_factory=list)
    representative_span: str


class EventCluster(VersionedModel):
    """One candidate real-world event, assembled from many mentions."""

    cluster_id: str
    event_type: str
    actor_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    location_entity_id: str | None = None
    window_start: UtcDatetime
    window_end: UtcDatetime
    first_observed_at: UtcDatetime
    last_observed_at: UtcDatetime
    mention_ids: list[str] = Field(default_factory=list)
    independence_groups: list[IndependenceGroup] = Field(default_factory=list)
    modality_counts: dict[str, int] = Field(default_factory=dict)
    undated_mention_ids: list[str] = Field(default_factory=list)
    #: True when this cluster was asserted by a hypothetical scenario rather
    #: than extracted from evidence. Defaults to False so that nothing in the
    #: real path changes, and is checked wherever clusters cross back into
    #: persistence -- an assumed event that reaches the ledger unmarked is
    #: indistinguishable from a fabricated observation.
    hypothetical: bool = False

    @model_validator(mode="after")
    def _check_window(self) -> EventCluster:
        if self.window_end < self.window_start:
            raise ValueError("window_end precedes window_start")
        if self.last_observed_at < self.first_observed_at:
            raise ValueError("last_observed_at precedes first_observed_at")
        return self

    @property
    def support(self) -> int:
        """Raw mention count. Almost never the right number to reason with."""
        return len(self.mention_ids)

    @property
    def effective_support(self) -> int:
        """Number of independent stories behind this cluster.

        This is the count that confidence should scale with. It is bounded
        above by :attr:`support` and is frequently much smaller.
        """
        return len(self.independence_groups)

    @property
    def denial_count(self) -> int:
        return self.modality_counts.get("denied", 0)

    @property
    def corroboration_count(self) -> int:
        return sum(
            count
            for modality, count in self.modality_counts.items()
            if modality in CORROBORATING_MODALITIES
        )

    @property
    def contested(self) -> bool:
        """Does any source deny what the others assert?

        Exposed as a flag rather than folded into a score because a contested
        cluster needs a human decision, not a smaller number.
        """
        return self.denial_count > 0 and self.corroboration_count > 0

    @property
    def duration_days(self) -> float:
        return (self.window_end - self.window_start).total_seconds() / 86400.0

    @staticmethod
    def build_id(
        event_type: str,
        actor_ids: Sequence[str],
        target_ids: Sequence[str],
        location_entity_id: str | None,
        anchor: str,
    ) -> str:
        return stable_id(
            "clu",
            event_type,
            sorted(set(actor_ids)),
            sorted(set(target_ids)),
            location_entity_id or "",
            anchor,
        )


def assign_independence_groups(
    mentions: Sequence[EventMention],
    *,
    threshold: float = DEFAULT_INDEPENDENCE_THRESHOLD,
) -> list[IndependenceGroup]:
    """Group mentions whose supporting spans are substantially the same text.

    Single-link agglomeration over shingle overlap, walked in sorted order so
    the grouping is reproducible. Single-link is the right choice despite its
    chaining risk: syndication really is transitive -- A reprints B, B reprints
    C -- and treating the chain as one story is the correct answer.

    Mentions whose span produces no shingles at all (empty or punctuation-only)
    each become their own group. Treating them as one shared group would be a
    silent claim that two unparseable spans are the same story.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0, 1], got {threshold}")

    ordered = sorted(mentions, key=lambda item: item.mention_id)
    fingerprints = {mention.mention_id: shingles(mention.supporting_span) for mention in ordered}

    parent: dict[str, str] = {mention.mention_id: mention.mention_id for mention in ordered}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            low, high = sorted((left_root, right_root))
            parent[high] = low

    for index, left in enumerate(ordered):
        left_prints = fingerprints[left.mention_id]
        if not left_prints:
            continue
        for right in ordered[index + 1 :]:
            right_prints = fingerprints[right.mention_id]
            if not right_prints:
                continue
            if jaccard(left_prints, right_prints) >= threshold:
                union(left.mention_id, right.mention_id)

    grouped: dict[str, list[str]] = defaultdict(list)
    for mention in ordered:
        grouped[find(mention.mention_id)].append(mention.mention_id)

    spans = {mention.mention_id: mention.supporting_span for mention in ordered}
    groups: list[IndependenceGroup] = []
    for root, members in sorted(grouped.items()):
        member_ids = sorted(members)
        # The longest span is the most likely original; ties break on id.
        representative = min(member_ids, key=lambda item: (-len(spans[item]), item))
        groups.append(
            IndependenceGroup(
                group_id=stable_id("ind", root, member_ids),
                mention_ids=member_ids,
                representative_span=spans[representative][:512],
            )
        )
    return groups


def _event_window(mention: EventMention) -> tuple[datetime, datetime] | None:
    """The interval a mention places its event in, or None if it gives no date."""
    start = mention.event_time_start
    if start is None:
        return None
    return start, mention.event_time_end or start


def _windows_compatible(
    left: tuple[datetime, datetime],
    right: tuple[datetime, datetime],
    tolerance: timedelta,
) -> bool:
    """Do two event windows overlap once each is padded by the tolerance?"""
    left_start, left_end = left
    right_start, right_end = right
    return left_start - tolerance <= right_end and right_start - tolerance <= left_end


def deduplicate_mentions(
    mentions: Sequence[EventMention],
    index: EntityIndex,
    *,
    cutoff_at: datetime,
    time_tolerance_days: float = DEFAULT_TIME_TOLERANCE_DAYS,
    reporting_lag_days: float = DEFAULT_REPORTING_LAG_DAYS,
    independence_threshold: float = DEFAULT_INDEPENDENCE_THRESHOLD,
) -> list[EventCluster]:
    """Collapse ``mentions`` into event clusters.

    Blocking is exact on (event type, resolved actors, resolved targets,
    resolved location); merging within a block is by event-time overlap. Exact
    blocking is intentional -- the fuzzy part of the problem was already solved
    by entity resolution, and re-solving it here with a second, differently
    tuned similarity would make failures impossible to attribute.
    """
    tolerance = timedelta(days=time_tolerance_days)
    lag = timedelta(days=reporting_lag_days)

    available = sorted(
        (mention for mention in mentions if mention.observed_at <= cutoff_at),
        key=lambda item: item.mention_id,
    )
    if not available:
        return []

    group_of: dict[str, str] = {}
    all_groups = assign_independence_groups(available, threshold=independence_threshold)
    for group in all_groups:
        for mention_id in group.mention_ids:
            group_of[mention_id] = group.group_id
    groups_by_id = {group.group_id: group for group in all_groups}

    blocks: dict[tuple[str, tuple[str, ...], tuple[str, ...], str], list[EventMention]] = (
        defaultdict(list)
    )
    for mention in available:
        key = (
            mention.event_type,
            tuple(index.actors_for(mention.mention_id)),
            tuple(index.targets_for(mention.mention_id)),
            index.location_for(mention.mention_id) or "",
        )
        blocks[key].append(mention)

    clusters: list[EventCluster] = []
    for key, block in sorted(blocks.items()):
        event_type, actor_ids, target_ids, location_id = key
        for members in _merge_by_time(block, tolerance=tolerance, lag=lag):
            clusters.append(
                _build_cluster(
                    event_type=event_type,
                    actor_ids=list(actor_ids),
                    target_ids=list(target_ids),
                    location_entity_id=location_id or None,
                    members=members,
                    group_of=group_of,
                    groups_by_id=groups_by_id,
                )
            )

    clusters.sort(key=lambda item: (item.window_start, item.cluster_id))
    log.info(
        "entities.deduplicated",
        mentions=len(available),
        clusters=len(clusters),
        contested=sum(1 for cluster in clusters if cluster.contested),
    )
    return clusters


def _merge_by_time(
    block: Sequence[EventMention], *, tolerance: timedelta, lag: timedelta
) -> list[list[EventMention]]:
    """Split one block into time-coherent groups.

    Dated mentions drive the grouping. Undated ones attach to a group whose
    window their *availability* is plausibly downstream of, and otherwise form
    their own group rather than being dropped -- an undated claim is still a
    claim, and discarding it here would quietly bias the corpus toward sources
    that print dates.
    """
    dated = sorted(
        (mention for mention in block if _event_window(mention) is not None),
        key=lambda item: (_require_window(item)[0], item.mention_id),
    )
    undated = sorted(
        (mention for mention in block if _event_window(mention) is None),
        key=lambda item: (item.observed_at, item.mention_id),
    )

    groups: list[list[EventMention]] = []
    windows: list[tuple[datetime, datetime]] = []
    for mention in dated:
        window = _require_window(mention)
        placed = False
        for position, existing in enumerate(windows):
            if _windows_compatible(existing, window, tolerance):
                groups[position].append(mention)
                windows[position] = (
                    min(existing[0], window[0]),
                    max(existing[1], window[1]),
                )
                placed = True
                break
        if not placed:
            groups.append([mention])
            windows.append(window)

    for mention in undated:
        placed = False
        for position, existing in enumerate(windows):
            if existing[0] - tolerance <= mention.observed_at <= existing[1] + lag:
                groups[position].append(mention)
                placed = True
                break
        if not placed:
            groups.append([mention])
            # An undated mention anchors a zero-width window at its availability
            # instant. This is explicitly a weaker claim than a dated window and
            # is recorded as such through undated_mention_ids on the cluster.
            windows.append((mention.observed_at, mention.observed_at))

    return [sorted(group, key=lambda item: item.mention_id) for group in groups]


def _require_window(mention: EventMention) -> tuple[datetime, datetime]:
    window = _event_window(mention)
    if window is None:  # pragma: no cover - guarded by the caller
        raise ValueError(f"mention {mention.mention_id} has no event window")
    return window


def _build_cluster(
    *,
    event_type: str,
    actor_ids: list[str],
    target_ids: list[str],
    location_entity_id: str | None,
    members: Sequence[EventMention],
    group_of: dict[str, str],
    groups_by_id: dict[str, IndependenceGroup],
) -> EventCluster:
    """Assemble one cluster, restricting its independence groups to its members."""
    dated = [_require_window(item) for item in members if _event_window(item) is not None]
    if dated:
        window_start = min(start for start, _ in dated)
        window_end = max(end for _, end in dated)
    else:
        window_start = min(item.observed_at for item in members)
        window_end = max(item.observed_at for item in members)

    member_ids = sorted(item.mention_id for item in members)
    local_groups: dict[str, list[str]] = defaultdict(list)
    for mention_id in member_ids:
        local_groups[group_of[mention_id]].append(mention_id)

    independence = [
        IndependenceGroup(
            group_id=group_id,
            mention_ids=sorted(ids),
            representative_span=groups_by_id[group_id].representative_span,
        )
        for group_id, ids in sorted(local_groups.items())
    ]
    observed = sorted(item.observed_at for item in members)
    return EventCluster(
        cluster_id=EventCluster.build_id(
            event_type,
            actor_ids,
            target_ids,
            location_entity_id,
            window_start.isoformat(),
        ),
        event_type=event_type,
        actor_ids=sorted(set(actor_ids)),
        target_ids=sorted(set(target_ids)),
        location_entity_id=location_entity_id,
        window_start=window_start,
        window_end=window_end,
        first_observed_at=observed[0],
        last_observed_at=observed[-1],
        mention_ids=member_ids,
        independence_groups=independence,
        modality_counts=dict(sorted(Counter(item.modality for item in members).items())),
        undated_mention_ids=sorted(
            item.mention_id for item in members if _event_window(item) is None
        ),
    )
