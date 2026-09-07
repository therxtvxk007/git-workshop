"""What may be collected, what may move a probability, and what may run.

Sources and models are registered the same way and for the same reason: both
can leak, and neither leak is visible in the input rows. A source leaks through
terms nobody checked; a model leaks through its weights.
"""

from __future__ import annotations

from pramaanx.registry.models import (
    IntendedUse,
    ModelDecision,
    ModelEntry,
    ModelRegistry,
    Verdict,
    may_use_model,
)
from pramaanx.registry.policy import ReadPurpose, RegistryReadPolicy
from pramaanx.registry.sources import (
    ApprovalStatus,
    CollectionApproval,
    SourceEntry,
    SourceRegistry,
    SourceTier,
    may_alter_probability,
    may_collect,
    may_create_candidate,
    may_inform_coverage,
)

__all__ = [
    "ApprovalStatus",
    "CollectionApproval",
    "IntendedUse",
    "ModelDecision",
    "ModelEntry",
    "ModelRegistry",
    "ReadPurpose",
    "RegistryReadPolicy",
    "SourceEntry",
    "SourceRegistry",
    "SourceTier",
    "Verdict",
    "may_alter_probability",
    "may_collect",
    "may_create_candidate",
    "may_inform_coverage",
    "may_use_model",
]
