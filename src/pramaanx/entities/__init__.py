"""Entity resolution and event deduplication.

Mentions arrive as free-text names attached to free-text places. Everything
downstream -- base rates, the evidence graph, feature construction, matching a
forecast to an outcome -- needs stable identifiers instead, and needs to know
how many *independent* sources stand behind a claim rather than how many times
it was reprinted.

Two stages, deliberately separate:

:mod:`pramaanx.entities.resolve`
    Surface forms to entity identifiers. Fuzzy, auditable, cutoff-safe.

:mod:`pramaanx.entities.dedupe`
    Mentions to event clusters, with independence groups so that corroboration
    is counted in stories rather than in column inches.

Splitting them means a failure is attributable. If a base rate looks wrong, the
question "did resolution merge two groups, or did deduplication merge two
events?" has a separate answer and a separate test for each half.
"""

from __future__ import annotations

from pramaanx.entities.dedupe import (
    CORROBORATING_MODALITIES,
    DEFAULT_INDEPENDENCE_THRESHOLD,
    DEFAULT_REPORTING_LAG_DAYS,
    DEFAULT_TIME_TOLERANCE_DAYS,
    EventCluster,
    IndependenceGroup,
    assign_independence_groups,
    deduplicate_mentions,
)
from pramaanx.entities.normalise import (
    blocking_keys,
    containment,
    initials_match,
    jaccard,
    name_tokens,
    normalise_name,
    shingles,
    similarity,
    stem_token,
    strip_accents,
)
from pramaanx.entities.resolve import (
    DEFAULT_MERGE_THRESHOLD,
    RUNAWAY_SURFACE_COUNT,
    Entity,
    EntityAssignment,
    EntityIndex,
    EntityKind,
    EntityRole,
    MergeEvidence,
    SurfaceForm,
    resolve_entities,
)

__all__ = [
    "CORROBORATING_MODALITIES",
    "DEFAULT_INDEPENDENCE_THRESHOLD",
    "DEFAULT_MERGE_THRESHOLD",
    "DEFAULT_REPORTING_LAG_DAYS",
    "DEFAULT_TIME_TOLERANCE_DAYS",
    "RUNAWAY_SURFACE_COUNT",
    "Entity",
    "EntityAssignment",
    "EntityIndex",
    "EntityKind",
    "EntityRole",
    "EventCluster",
    "IndependenceGroup",
    "MergeEvidence",
    "SurfaceForm",
    "assign_independence_groups",
    "blocking_keys",
    "containment",
    "deduplicate_mentions",
    "initials_match",
    "jaccard",
    "name_tokens",
    "normalise_name",
    "resolve_entities",
    "shingles",
    "similarity",
    "stem_token",
    "strip_accents",
]
