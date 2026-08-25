"""Turning observations into event mentions.

M0 ships only :mod:`pramaanx.extraction.structured`, a deterministic mapping
for sources that are already coded. The learned cascade (GLiNER-Relex, an
event-type classifier, a constrained LLM verifier and consensus that preserves
disagreement) is Phase 2 and needs a manually audited gold set before it can be
justified, let alone evaluated.
"""

from __future__ import annotations

from pramaanx.extraction.structured import (
    CAMEO_ROOT_TYPES,
    EXTRACTORS,
    ExtractionError,
    extract_mentions,
    mentions_for_cutoff,
)

__all__ = [
    "CAMEO_ROOT_TYPES",
    "EXTRACTORS",
    "ExtractionError",
    "extract_mentions",
    "mentions_for_cutoff",
]
