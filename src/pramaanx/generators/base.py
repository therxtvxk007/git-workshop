"""The candidate-generator contract.

Every generator implements one interface so that it can be evaluated alone,
removed in an ablation, or routed selectively. The union stage may merge
equivalent candidates, but it may never erase which branch proposed them: the
candidate-oracle diagnostic depends on being able to attribute a miss to
discovery rather than scoring.

M0 ships one generator (G0, base rates and hazards). G1-G7 from the build plan
plug in here without changing anything upstream of them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from pramaanx.schemas.base import PramaanModel, UtcDatetime
from pramaanx.schemas.event import EventHypothesis


class ForecastContext(PramaanModel):
    """Everything a generator is allowed to know at proposal time.

    Note what is absent: the true subject, relation, target or event question.
    Supplying those is permitted only inside reproduction tracks for structured
    baselines, never in the operational path.
    """

    cutoff_at: UtcDatetime
    evidence_snapshot_id: str
    proposal_budget: int = Field(gt=0)
    region_scope: list[str] | None = None
    horizon_days: int = Field(default=90, gt=0)

    @property
    def horizon_end(self) -> datetime:
        from datetime import timedelta

        return self.cutoff_at + timedelta(days=self.horizon_days)

    def in_scope(self, region: str | None) -> bool:
        if self.region_scope is None or region is None:
            return True
        return region in set(self.region_scope)


class CandidateProposal(PramaanModel):
    """One proposed future event, with the trace that justifies it."""

    hypothesis: EventHypothesis
    generator_name: str
    generator_score: float = Field(ge=0.0, le=1.0)
    trace: dict[str, Any] = Field(default_factory=dict)

    @property
    def candidate_key(self) -> str:
        """Structured identity, used for deduplication across generators."""
        return self.hypothesis.event_id


@runtime_checkable
class CandidateGenerator(Protocol):
    """Structural contract. Implementations need not inherit from anything."""

    name: str

    def propose(self, context: ForecastContext) -> Sequence[CandidateProposal]: ...


class BaseGenerator(ABC):
    """Convenience base class: registration, budget handling, version string."""

    name: str = ""

    def __init__(self, **options: Any) -> None:
        if not self.name:
            raise ValueError(f"{type(self).__name__} must define a name")
        self.options = options

    @property
    def version(self) -> str:
        """Recorded in ``ForecastRecord.model_versions`` for every forecast."""
        return f"{self.name}@{getattr(self, 'VERSION', '0.1.0')}"

    @abstractmethod
    def propose(self, context: ForecastContext) -> Sequence[CandidateProposal]:
        """Propose candidates for ``context``, at most ``proposal_budget`` of them."""

    @staticmethod
    def enforce_budget(
        proposals: Sequence[CandidateProposal], budget: int
    ) -> list[CandidateProposal]:
        """Rank by score and truncate, breaking ties deterministically."""
        ordered = sorted(
            proposals,
            key=lambda item: (-item.generator_score, item.hypothesis.event_id),
        )
        return ordered[:budget]


_REGISTRY: dict[str, type[BaseGenerator]] = {}


def register_generator(cls: type[BaseGenerator]) -> type[BaseGenerator]:
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a name before registration")
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"duplicate generator name: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def get_generator_class(name: str) -> type[BaseGenerator]:
    from pramaanx import generators  # noqa: F401  (populates the registry)

    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(f"unknown generator {name!r}; registered: {known}")
    return _REGISTRY[name]


def available_generators() -> dict[str, type[BaseGenerator]]:
    from pramaanx import generators  # noqa: F401

    return dict(sorted(_REGISTRY.items()))
