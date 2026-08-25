"""Point-in-time correctness.

Three pieces, in dependency order:

* :mod:`pramaanx.timeguard.cutoff` -- the admission rule and its edge cases;
* :mod:`pramaanx.timeguard.snapshots` -- immutable, hashed cutoff manifests;
* :mod:`pramaanx.timeguard.leakage_audit` -- mechanical leak screening.
"""

from __future__ import annotations

from pramaanx.timeguard.cutoff import (
    AdmissionReport,
    CutoffGuard,
    CutoffViolation,
    LeakageError,
    ViolationKind,
    partition_by_cutoff,
)
from pramaanx.timeguard.leakage_audit import (
    FindingKind,
    LeakageAuditor,
    LeakageFinding,
    LeakageReport,
    Severity,
)
from pramaanx.timeguard.snapshots import (
    Snapshot,
    SnapshotBuilder,
    SnapshotManifest,
    code_hash,
    parse_cutoff,
)

__all__ = [
    "AdmissionReport",
    "CutoffGuard",
    "CutoffViolation",
    "FindingKind",
    "LeakageAuditor",
    "LeakageError",
    "LeakageFinding",
    "LeakageReport",
    "Severity",
    "Snapshot",
    "SnapshotBuilder",
    "SnapshotManifest",
    "ViolationKind",
    "code_hash",
    "parse_cutoff",
    "partition_by_cutoff",
]
