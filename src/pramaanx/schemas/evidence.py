"""Evidence references.

Evidence carries a stance and an independence cluster because ten outlets
rewriting one wire story are one piece of evidence, not ten. M0 only needs the
reference type itself; the retrieval-side evidence pack arrives with Phase 6.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from pramaanx.schemas.base import PramaanModel

Stance = Literal["supports", "contradicts", "context"]


class EvidenceRef(PramaanModel):
    observation_id: str
    span_start: int | None = None
    span_end: int | None = None
    claim: str
    stance: Stance
    independence_cluster: str | None = None
    reliability: float = Field(ge=0.0, le=1.0)

    @property
    def cluster_key(self) -> str:
        """Independence cluster, falling back to the observation itself."""
        return self.independence_cluster or self.observation_id
