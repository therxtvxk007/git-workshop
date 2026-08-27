"""Entity resolution over event mentions.

Two mentions that name the same actor in different words must end up pointing
at the same identifier, or every downstream count is wrong: base rates split
across spellings, the evidence graph grows twins, and a generator that ranks by
recent activity ranks the fragments instead of the actor.

Three properties are non-negotiable here, and each of them is a test:

*Determinism.* Clustering runs in sorted order over a sorted candidate-pair
list. No dictionary iteration order, no wall clock, no random tie-break. The
same mentions produce the same identifiers on every machine.

*Cutoff safety.* Resolution reads ``EventMention.observed_at`` and refuses
anything after the cutoff. Resolution is a modelling stage, so a mention that
arrives tomorrow must not be allowed to improve a cluster that a forecast was
made from today.

*Auditability.* Every cluster records the surfaces that were folded into it and
the score that justified each merge. A resolution error should be visible in a
diff, not inferred from a downstream metric moving.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.entities.normalise import blocking_keys, normalise_name, similarity
from pramaanx.hashing import stable_id
from pramaanx.logging import get_logger
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel
from pramaanx.schemas.event import EventMention

log = get_logger(__name__)

#: Merge threshold. Chosen to accept inflection and abbreviation while
#: rejecting mere topical overlap; it is a default for a demo, not a tuned
#: value, and the sweep that would tune it belongs in the evaluation harness.
DEFAULT_MERGE_THRESHOLD = 0.72

#: A cluster is never allowed to grow past this many distinct surfaces without
#: being flagged. Runaway clusters are the classic entity-resolution failure --
#: one over-general token chains hundreds of unrelated names together -- and a
#: silent one, because the resulting entity looks merely popular.
RUNAWAY_SURFACE_COUNT = 50


class EntityKind(StrEnum):
    """What sort of thing an entity is.

    Deliberately coarse. A finer ontology (person, armed group, ministry) is a
    classification problem with its own error rate, and inventing one here
    would hide that error inside an identifier.
    """

    ACTOR = "actor"
    LOCATION = "location"


class EntityRole(StrEnum):
    """Where a surface form appeared in the mention it came from."""

    SUBJECT = "subject"
    OBJECT = "object"
    LOCATION = "location"


#: Subject and object positions resolve into one namespace on purpose. A group
#: that attacks in one report and is attacked in the next is one group; keying
#: identity on grammatical role would split it in two and halve both counts.
ROLE_KINDS: dict[EntityRole, EntityKind] = {
    EntityRole.SUBJECT: EntityKind.ACTOR,
    EntityRole.OBJECT: EntityKind.ACTOR,
    EntityRole.LOCATION: EntityKind.LOCATION,
}


class SurfaceForm(PramaanModel):
    """One occurrence of a name, before any merging."""

    surface: str
    kind: EntityKind
    role: EntityRole
    mention_id: str
    observed_at: UtcDatetime

    @property
    def key(self) -> str:
        """Normalised comparison key. Empty means the surface carries no identity."""
        return normalise_name(self.surface)


class MergeEvidence(PramaanModel):
    """Why two surfaces were judged to be the same entity."""

    left: str
    right: str
    score: float = Field(ge=0.0, le=1.0)


class Entity(VersionedModel):
    """A resolved entity: one identity, many surfaces.

    ``entity_id`` is derived from the canonical key, which makes it stable for
    as long as the canonical surface stays the most frequent one. It is
    therefore stable *within* a snapshot and may change *between* snapshots as
    a cluster grows. That is a real property of entity resolution rather than a
    defect to paper over, so ``absorbed_keys`` records every normalised key the
    cluster has swallowed: cross-snapshot linkage is reconstructed from that,
    not from an identifier pretending to a permanence it does not have.
    """

    entity_id: str
    kind: EntityKind
    canonical_name: str
    canonical_key: str
    surfaces: list[str] = Field(default_factory=list)
    absorbed_keys: list[str] = Field(default_factory=list)
    mention_ids: list[str] = Field(default_factory=list)
    first_observed_at: UtcDatetime
    last_observed_at: UtcDatetime
    merge_evidence: list[MergeEvidence] = Field(default_factory=list)
    runaway: bool = False

    @model_validator(mode="after")
    def _check_ordering(self) -> Entity:
        if self.last_observed_at < self.first_observed_at:
            raise ValueError("last_observed_at precedes first_observed_at")
        return self

    @property
    def support(self) -> int:
        """Number of mentions folded into this entity."""
        return len(self.mention_ids)

    @staticmethod
    def build_id(kind: EntityKind, canonical_key: str) -> str:
        return stable_id("ent", kind.value, canonical_key)


class EntityAssignment(PramaanModel):
    """The link from one mention slot to one resolved entity."""

    mention_id: str
    role: EntityRole
    entity_id: str
    surface: str


class EntityIndex(PramaanModel):
    """The resolved view of a mention set.

    Stored as two sorted lists rather than as dictionaries so that the whole
    index hashes canonically and a resolution change shows up as a diff.
    """

    entities: list[Entity] = Field(default_factory=list)
    assignments: list[EntityAssignment] = Field(default_factory=list)
    cutoff_at: UtcDatetime
    merge_threshold: float = Field(ge=0.0, le=1.0)

    def by_id(self) -> dict[str, Entity]:
        return {entity.entity_id: entity for entity in self.entities}

    def entity_ids_for(self, mention_id: str, *, role: EntityRole | None = None) -> list[str]:
        """Entity identifiers attached to one mention, optionally filtered by role."""
        return sorted(
            {
                assignment.entity_id
                for assignment in self.assignments
                if assignment.mention_id == mention_id and (role is None or assignment.role == role)
            }
        )

    def actors_for(self, mention_id: str) -> list[str]:
        return self.entity_ids_for(mention_id, role=EntityRole.SUBJECT)

    def targets_for(self, mention_id: str) -> list[str]:
        return self.entity_ids_for(mention_id, role=EntityRole.OBJECT)

    def location_for(self, mention_id: str) -> str | None:
        found = self.entity_ids_for(mention_id, role=EntityRole.LOCATION)
        return found[0] if found else None

    def mentions_for(self, entity_id: str) -> list[str]:
        return sorted(
            {
                assignment.mention_id
                for assignment in self.assignments
                if assignment.entity_id == entity_id
            }
        )

    def runaway_entities(self) -> list[Entity]:
        """Clusters that grew past the runaway guard, for the audit report."""
        return [entity for entity in self.entities if entity.runaway]


def _surfaces_from(mentions: Iterable[EventMention], *, cutoff_at: datetime) -> list[SurfaceForm]:
    """Collect every named slot from every mention available at the cutoff."""
    surfaces: list[SurfaceForm] = []
    for mention in mentions:
        if mention.observed_at > cutoff_at:
            # Not an error: a caller may hand over the full corpus and expect
            # the cutoff to do the filtering. Dropping silently here is the
            # same discipline the snapshot builder applies.
            continue
        slots: tuple[tuple[EntityRole, str | None], ...] = (
            (EntityRole.SUBJECT, mention.subject),
            (EntityRole.OBJECT, mention.object),
            (EntityRole.LOCATION, mention.location_text),
        )
        for role, raw in slots:
            if not raw or not normalise_name(raw):
                continue
            surfaces.append(
                SurfaceForm(
                    surface=str(raw).strip(),
                    kind=ROLE_KINDS[role],
                    role=role,
                    mention_id=mention.mention_id,
                    observed_at=mention.observed_at,
                )
            )
    surfaces.sort(key=lambda item: (item.kind.value, item.key, item.surface, item.mention_id))
    return surfaces


class _DisjointSet:
    """Union-find with deterministic representatives.

    The representative of a set is always its lexicographically smallest
    member, not whichever member happened to be unioned first. Without that,
    identifiers depend on input order.
    """

    def __init__(self, members: Iterable[str]) -> None:
        self._parent: dict[str, str] = {member: member for member in members}

    def find(self, member: str) -> str:
        root = member
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[member] != root:
            self._parent[member], member = root, self._parent[member]
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        low, high = sorted((left_root, right_root))
        self._parent[high] = low

    def groups(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for member in sorted(self._parent):
            grouped[self.find(member)].append(member)
        return {root: sorted(members) for root, members in sorted(grouped.items())}


def _candidate_pairs(keys_by_kind: dict[EntityKind, dict[str, set[str]]]) -> list[tuple[str, str]]:
    """Propose comparison pairs from shared blocking keys.

    Returned sorted and deduplicated so that the merge loop below is a pure
    function of the key set.
    """
    pairs: set[tuple[str, str]] = set()
    for blocks in keys_by_kind.values():
        for members in blocks.values():
            if len(members) < 2:
                continue
            ordered = sorted(members)
            for index, left in enumerate(ordered):
                for right in ordered[index + 1 :]:
                    pairs.add((left, right))
    return sorted(pairs)


def resolve_entities(
    mentions: Sequence[EventMention],
    *,
    cutoff_at: datetime,
    merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
) -> EntityIndex:
    """Resolve the named slots of ``mentions`` into entities.

    Only mentions with ``observed_at <= cutoff_at`` participate. The result is a
    pure function of that filtered set and ``merge_threshold``.
    """
    if not 0.0 <= merge_threshold <= 1.0:
        raise ValueError(f"merge_threshold must be in [0, 1], got {merge_threshold}")

    surfaces = _surfaces_from(mentions, cutoff_at=cutoff_at)
    if not surfaces:
        return EntityIndex(
            entities=[], assignments=[], cutoff_at=cutoff_at, merge_threshold=merge_threshold
        )

    # Group occurrences by (kind, exact normalised key) first. Exact-key matches
    # are free and unambiguous, so the expensive pairwise stage only ever sees
    # one representative per distinct key.
    occurrences: dict[tuple[EntityKind, str], list[SurfaceForm]] = defaultdict(list)
    for surface in surfaces:
        occurrences[(surface.kind, surface.key)].append(surface)

    keys_by_kind: dict[EntityKind, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for kind, key in occurrences:
        for block in blocking_keys(key):
            keys_by_kind[kind][block].add(key)

    scores: dict[tuple[str, str], float] = {}
    per_kind_groups: dict[EntityKind, dict[str, list[str]]] = {}
    for kind in sorted({kind for kind, _ in occurrences}, key=lambda item: item.value):
        kind_keys = sorted(key for kind_seen, key in occurrences if kind_seen == kind)
        union = _DisjointSet(kind_keys)
        for left, right in _candidate_pairs({kind: keys_by_kind[kind]}):
            score = similarity(left, right)
            if score >= merge_threshold:
                scores[(left, right)] = score
                union.union(left, right)
        per_kind_groups[kind] = union.groups()

    entities: list[Entity] = []
    assignments: list[EntityAssignment] = []
    for kind, groups in sorted(per_kind_groups.items(), key=lambda item: item[0].value):
        for member_keys in groups.values():
            members = [occurrence for key in member_keys for occurrence in occurrences[(kind, key)]]
            entity = _build_entity(kind, member_keys, members, scores)
            entities.append(entity)
            assignments.extend(
                EntityAssignment(
                    mention_id=occurrence.mention_id,
                    role=occurrence.role,
                    entity_id=entity.entity_id,
                    surface=occurrence.surface,
                )
                for occurrence in members
            )

    entities.sort(key=lambda item: (item.kind.value, item.entity_id))
    assignments.sort(key=lambda item: (item.mention_id, item.role.value, item.entity_id))

    runaway = [entity.entity_id for entity in entities if entity.runaway]
    if runaway:
        log.warning("entities.runaway_clusters", count=len(runaway), entity_ids=runaway[:10])
    log.info(
        "entities.resolved",
        entities=len(entities),
        assignments=len(assignments),
        surfaces=len(surfaces),
    )
    return EntityIndex(
        entities=entities,
        assignments=assignments,
        cutoff_at=cutoff_at,
        merge_threshold=merge_threshold,
    )


def _build_entity(
    kind: EntityKind,
    member_keys: Sequence[str],
    members: Sequence[SurfaceForm],
    scores: dict[tuple[str, str], float],
) -> Entity:
    """Assemble one entity from its member occurrences.

    The canonical name is the most frequent surface form, ties broken
    lexicographically. Frequency rather than first-seen because first-seen makes
    the identifier depend on ingestion order, which is exactly the dependency
    this module exists to remove.
    """
    counts = Counter(occurrence.surface for occurrence in members)
    canonical_name = min(sorted(counts), key=lambda surface: (-counts[surface], surface))
    canonical_key = normalise_name(canonical_name) or sorted(member_keys)[0]
    observed = sorted(occurrence.observed_at for occurrence in members)
    member_key_set = set(member_keys)
    evidence = [
        MergeEvidence(left=left, right=right, score=score)
        for (left, right), score in sorted(scores.items())
        if left in member_key_set and right in member_key_set
    ]
    surfaces = sorted(counts)
    return Entity(
        entity_id=Entity.build_id(kind, canonical_key),
        kind=kind,
        canonical_name=canonical_name,
        canonical_key=canonical_key,
        surfaces=surfaces,
        absorbed_keys=sorted(member_key_set),
        mention_ids=sorted({occurrence.mention_id for occurrence in members}),
        first_observed_at=observed[0],
        last_observed_at=observed[-1],
        merge_evidence=evidence,
        runaway=len(surfaces) > RUNAWAY_SURFACE_COUNT,
    )
