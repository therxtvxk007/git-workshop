"""Feature declarations and the vectors built from them.

Every feature in this project is declared before it is computed. The
declaration carries the one thing a feature name cannot: what the number is
allowed to have seen. A feature called ``events_last_30d`` is only meaningful
alongside the instant the thirty days end at, and a feature store that does not
carry that instant is a leak waiting for someone to join on the wrong key.

So :class:`FeatureVector` is stamped with ``as_of``, and every builder is
handed that instant rather than reading a clock. A vector also records the
graph cutoff it was built under, which makes the audit question -- "could this
number have been computed on the day it claims?" -- answerable from the vector
alone, without re-running anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from pramaanx.hashing import stable_id
from pramaanx.schemas.base import PramaanModel, UtcDatetime


class FeatureKind(StrEnum):
    """What sort of quantity a feature is, for reporting and for scaling.

    COUNT and RATE features are non-negative and unbounded; RATIO and SCORE
    features live in [0, 1]; DURATION features are in days. Recording the kind
    means a downstream transform can be checked against it rather than guessing
    from the values it happens to see in one fold.
    """

    COUNT = "count"
    RATE = "rate"
    RATIO = "ratio"
    DURATION = "duration"
    SCORE = "score"


class FeatureSpec(PramaanModel):
    """The declaration of one feature."""

    name: str
    kind: FeatureKind
    description: str
    #: Trailing window the feature reads, in days. ``None`` means unbounded
    #: history up to ``as_of``.
    window_days: float | None = None
    #: Value used when the series has no history at all. Never ``None``:
    #: a missing feature that silently becomes null is a feature that silently
    #: becomes whatever the model imputes.
    default: float = 0.0
    #: True when a larger value should make an event *less* likely. Recorded so
    #: a sign error in a generator shows up as a contract violation rather than
    #: as a slightly worse Brier score.
    inverse: bool = False

    @model_validator(mode="after")
    def _check_bounds(self) -> FeatureSpec:
        if self.window_days is not None and self.window_days <= 0:
            raise ValueError(f"{self.name}: window_days must be positive")
        if self.kind in {FeatureKind.RATIO, FeatureKind.SCORE} and not 0.0 <= self.default <= 1.0:
            raise ValueError(f"{self.name}: {self.kind.value} default must be in [0, 1]")
        return self


class SeriesKey(PramaanModel):
    """What a feature vector is *about*.

    An event type in a place, optionally narrowed to an actor. Kept as a model
    rather than a tuple so that it validates, hashes canonically, and can gain
    a field without every call site changing shape.
    """

    event_type: str
    actor_id: str | None = None
    location_id: str | None = None

    @property
    def key(self) -> str:
        return stable_id("ser", self.event_type, self.actor_id or "", self.location_id or "")

    def matches(self, *, event_type: str, actor_ids: Iterable[str], location_id: str | None) -> bool:
        """Does one cluster belong to this series?"""
        if event_type != self.event_type:
            return False
        if self.actor_id is not None and self.actor_id not in set(actor_ids):
            return False
        return not (self.location_id is not None and location_id != self.location_id)


class FeatureVector(PramaanModel):
    """Computed features for one series, at one instant."""

    series: SeriesKey
    as_of: UtcDatetime
    graph_cutoff_at: UtcDatetime
    values: dict[str, float] = Field(default_factory=dict)
    #: Number of clusters that contributed, for the "is this number based on
    #: anything?" question that a bare feature value cannot answer.
    support: int = Field(default=0, ge=0)
    effective_support: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_availability(self) -> FeatureVector:
        if self.as_of > self.graph_cutoff_at:
            raise ValueError(
                f"feature vector as_of {self.as_of.isoformat()} is after the graph cutoff "
                f"{self.graph_cutoff_at.isoformat()}: the inputs did not exist yet"
            )
        return self

    def get(self, name: str, default: float = 0.0) -> float:
        return self.values.get(name, default)

    def as_ordered(self, names: Sequence[str]) -> list[float]:
        """Dense vector in a fixed order, for anything that wants an array.

        Missing names raise rather than defaulting. A model trained on twelve
        features and scored on eleven should fail loudly at the boundary, not
        quietly on a zero.
        """
        missing = [name for name in names if name not in self.values]
        if missing:
            raise KeyError(f"feature vector is missing {missing}")
        return [self.values[name] for name in names]


class FeatureRegistry:
    """The declared feature set.

    Registration is explicit and duplicate names are refused, so that two
    builders cannot quietly disagree about what ``events_last_30d`` means.
    """

    def __init__(self) -> None:
        self._specs: dict[str, FeatureSpec] = {}

    def register(self, spec: FeatureSpec) -> FeatureSpec:
        existing = self._specs.get(spec.name)
        if existing is not None and existing != spec:
            raise ValueError(f"feature {spec.name!r} is already registered with a different spec")
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> FeatureSpec:
        if name not in self._specs:
            known = ", ".join(sorted(self._specs)) or "<none>"
            raise KeyError(f"unknown feature {name!r}; registered: {known}")
        return self._specs[name]

    def names(self) -> list[str]:
        return sorted(self._specs)

    def specs(self) -> list[FeatureSpec]:
        return [self._specs[name] for name in self.names()]

    def validate(self, vector: FeatureVector) -> None:
        """Check a vector against the declarations.

        Catches the two failures that a plain dict cannot: a value outside the
        range its kind promises, and a feature nobody declared.
        """
        unknown = sorted(set(vector.values) - set(self._specs))
        if unknown:
            raise KeyError(f"vector carries undeclared features: {unknown}")
        for name, value in sorted(vector.values.items()):
            spec = self._specs[name]
            if spec.kind in {FeatureKind.RATIO, FeatureKind.SCORE} and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} is a {spec.kind.value} but has value {value}")
            if spec.kind in {FeatureKind.COUNT, FeatureKind.RATE, FeatureKind.DURATION}:
                if value < 0.0:
                    raise ValueError(f"{name} is a {spec.kind.value} but is negative: {value}")


REGISTRY = FeatureRegistry()
"""Process-wide declaration set. Builders register into it at import time."""
