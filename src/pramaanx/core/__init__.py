"""Shared foundations: identity, chronology, and the as-of revision store.

Nothing in this package imports a workstream. The dependency direction is one
way -- registry, geo, panel, features, models and verify all depend on
:mod:`pramaanx.core`, and none of them may be imported from it (S28).
"""

from __future__ import annotations

from pramaanx.core.artifacts import ArtifactKeyInputs, ArtifactRef, LineageIndex
from pramaanx.core.asof import (
    AllowAllSources,
    CommitReceipt,
    EligibleTable,
    PartRef,
    RecoveryReport,
    RevisionStore,
    StoreManifest,
    WithheldSources,
)
from pramaanx.core.contexts import (
    STRICT_BASES,
    AvailabilityBasis,
    FitContext,
    ForecastContext,
    ForecastReader,
    InformationProfile,
    OriginRole,
    ReferenceReader,
    ScoreContext,
    TrainingLabelReader,
)
from pramaanx.core.errors import (
    CapabilityUnsupportedError,
    ContractViolationError,
    CutoffLeakageError,
    EligibilityError,
    IdempotencyConflictError,
    PramaanError,
    RedactedArtifactError,
    StoreCorruptionError,
    UnresolvedContractError,
    WriterLockError,
)
from pramaanx.core.revisions import Revision, RevisionOperation
from pramaanx.core.rng import RandomStreams

__all__ = [
    "STRICT_BASES",
    "AllowAllSources",
    "ArtifactKeyInputs",
    "ArtifactRef",
    "AvailabilityBasis",
    "CapabilityUnsupportedError",
    "CommitReceipt",
    "ContractViolationError",
    "CutoffLeakageError",
    "EligibilityError",
    "EligibleTable",
    "FitContext",
    "ForecastContext",
    "ForecastReader",
    "IdempotencyConflictError",
    "InformationProfile",
    "LineageIndex",
    "OriginRole",
    "PartRef",
    "PramaanError",
    "RandomStreams",
    "RecoveryReport",
    "RedactedArtifactError",
    "ReferenceReader",
    "Revision",
    "RevisionOperation",
    "RevisionStore",
    "ScoreContext",
    "StoreCorruptionError",
    "StoreManifest",
    "TrainingLabelReader",
    "UnresolvedContractError",
    "WithheldSources",
    "WriterLockError",
]
