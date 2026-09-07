"""Artifact identity and lineage.

Content hashing does not give you caching. It gives you a name; the rest --
lookup, publication, invalidation, retention -- is work, and the part that goes
wrong is invalidation (S36.2).

Two failure modes this module exists to prevent. Hashing the whole config makes
every artifact rebuild when an unrelated key moves, so nobody keeps the cache
on. Hashing too little is worse: a corrected incident linkage, a new boundary
version or a changed shadow-source assignment leaves a stale feature table
looking valid, and the run reports a number built on withdrawn evidence.

So an artifact key names its *semantic* dependencies explicitly, and lineage is
stored, so that "which of my outputs depended on this source?" is a query
rather than an afternoon.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import Field

from pramaanx.hashing import hash_object
from pramaanx.schemas.base import PramaanModel, UtcDatetime, VersionedModel

#: Bumped when the key derivation changes. Part of every key, so an artifact
#: built under an older derivation can never be mistaken for a current one.
KEY_SCHEME_VERSION = 1


class ArtifactRef(PramaanModel):
    """A pointer to something a stage produced, by identity rather than path.

    ``artifact_key`` answers "would rebuilding this produce the same thing?".
    ``content_digest`` answers "are these the bytes I published?". They are
    different questions: a non-deterministic stage can produce two different
    contents under one key, and the ledger has to be able to say so.
    """

    model_config = PramaanModel.model_config | {"frozen": True}

    kind: str
    artifact_key: str
    content_digest: str
    path: str | None = None

    def short(self) -> str:
        return f"{self.kind}:{self.artifact_key.removeprefix('sha256:')[:12]}"


class ArtifactKeyInputs(PramaanModel):
    """Everything that must change the key when it changes (S36.2).

    Absolute paths are deliberately absent: where a file sits on one machine is
    not part of what it means. Numerical environment is present, because a
    result that depends on thread count or float precision is not the same
    result when those move.
    """

    stage: str
    stage_version: int = Field(ge=0)
    #: Hash of the code that runs the stage.
    code_hash: str
    #: The stage's own semantic config, canonicalised. Not the whole run config.
    config: Mapping[str, Any] = Field(default_factory=dict)
    #: Ordered: a stage that consumes A then B is not the stage that consumes
    #: B then A when order carries meaning.
    inputs: tuple[str, ...] = ()
    schema_version: int = Field(default=1, ge=0)
    serializer_version: int = Field(default=1, ge=0)
    #: Fitted models and transforms this stage applies but did not fit here.
    fitted: tuple[str, ...] = ()
    #: The RNG derivation, from :meth:`RandomStreams.describe`.
    rng: Mapping[str, Any] = Field(default_factory=dict)
    #: Information profile, origin role and registry policy, together. A source
    #: that moved tier changes this even over identical bytes.
    policy_hash: str = ""
    #: Threads, precision, device -- only where the result depends on them.
    numeric_environment: Mapping[str, Any] = Field(default_factory=dict)

    def key(self) -> str:
        return hash_object({"scheme": KEY_SCHEME_VERSION, **self.canonical_dict()})


class LineageEdge(PramaanModel):
    """``child`` was built from ``parent``."""

    model_config = PramaanModel.model_config | {"frozen": True}

    parent: str
    child: str


class LineageIndex(VersionedModel):
    """Transitive dependency graph over artifact keys.

    Kept so that a deleted input or a withdrawn permission can name the
    artifacts it invalidates. Withholding a source by id is not enough: its
    translated copy, its cached extraction and the features built over it are
    all descendants, and only lineage finds them (S33.1, S35).
    """

    edges: tuple[LineageEdge, ...] = ()
    recorded_at: UtcDatetime | None = None

    def record(self, child: str, parents: Iterable[str]) -> LineageIndex:
        new = tuple(LineageEdge(parent=parent, child=child) for parent in sorted(set(parents)))
        merged = tuple(sorted(set(self.edges + new), key=lambda e: (e.parent, e.child)))
        return self.model_copy(update={"edges": merged})

    def descendants(self, artifact_key: str) -> tuple[str, ...]:
        """Everything that would have to be rebuilt if this input changed."""
        children: dict[str, list[str]] = {}
        for edge in self.edges:
            children.setdefault(edge.parent, []).append(edge.child)

        seen: set[str] = set()
        frontier = list(children.get(artifact_key, ()))
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(children.get(current, ()))
        return tuple(sorted(seen))

    def ancestors(self, artifact_key: str) -> tuple[str, ...]:
        """Everything this artifact was built from, transitively."""
        parents: dict[str, list[str]] = {}
        for edge in self.edges:
            parents.setdefault(edge.child, []).append(edge.parent)

        seen: set[str] = set()
        frontier = list(parents.get(artifact_key, ()))
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(parents.get(current, ()))
        return tuple(sorted(seen))
