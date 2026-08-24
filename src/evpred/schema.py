"""Core data structures for the event-prediction pipeline.

The pipeline is organised around a *nested multiple-instance* view of the
forecasting problem, which is the formulation the surveyed nMIL work uses and
the only one that supports honest validation against events that actually
occurred:

    Document (instance)  ->  Bag (region-day)  ->  BagGroup (region-window)

Labels are observed at the ``BagGroup`` level only -- a Gold Standard Report
says "a protest happened in region R during window W", never "article 47 caused
it". Precursor evidence therefore has to be *recovered* by the model rather
than supervised directly.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Sequence

Date = _dt.date


@dataclass(frozen=True, slots=True)
class Event:
    """A structured event tuple extracted from unstructured text.

    Deliberately close to the CAMEO/ICEWS actor-action-target shape so that
    extracted events line up with the public ground-truth catalogues used for
    validation, while staying loose enough for an LLM to fill in reliably.
    """

    actor: str
    action: str
    target: str = ""
    location: str = ""
    time_ref: str = ""
    polarity: float = 0.0
    """Signed intensity in [-1, 1]; negative = conflictual, positive = cooperative."""
    confidence: float = 1.0
    quote: str = ""
    """Verbatim span the event was read off, used for evidence display."""

    def key(self) -> str:
        """Coarse type key used for count features and cross-source dedup."""
        return f"{self.action.lower().strip()}"


@dataclass(slots=True)
class Document:
    """One unstructured text instance plus everything derived from it."""

    doc_id: str
    text: str
    date: Date
    region: str
    source: str = "unknown"
    events: list[Event] = field(default_factory=list)
    embedding: Any = None  # np.ndarray once embedded
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_events(self) -> int:
        return len(self.events)


@dataclass(slots=True)
class Bag:
    """All documents for one (region, day). The MIL instance-container."""

    region: str
    date: Date
    documents: list[Document] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.documents)

    def __iter__(self) -> Iterator[Document]:
        return iter(self.documents)


@dataclass(slots=True)
class BagGroup:
    """A labelled forecasting unit: region + history window + outcome window.

    ``origin`` is the forecast origin. Every document in ``bags`` is dated
    strictly before ``origin``; the label describes what happened in
    ``[origin, origin + horizon)``. This split is enforced in
    :func:`evpred.features.assert_no_lookahead`, because silent lookahead is the
    single most common way text-based forecasting results turn out to be wrong.
    """

    region: str
    origin: Date
    horizon_days: int
    bags: list[Bag] = field(default_factory=list)
    label: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def documents(self) -> list[Document]:
        return [d for b in self.bags for d in b.documents]

    @property
    def n_documents(self) -> int:
        return sum(len(b) for b in self.bags)

    @property
    def outcome_end(self) -> Date:
        return self.origin + _dt.timedelta(days=self.horizon_days)


@dataclass(slots=True)
class Precursor:
    """One piece of supporting evidence behind a forecast."""

    doc_id: str
    region: str
    date: Date
    score: float
    """Attribution weight: how much this instance drove the bag-level score."""
    snippet: str
    events: list[Event] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"[{self.date} {self.region} w={self.score:.3f}] {self.snippet[:120]}"


@dataclass(slots=True)
class Forecast:
    """A calibrated prediction with its evidence and abstention decision."""

    region: str
    origin: Date
    horizon_days: int
    probability: float
    raw_score: float
    precursors: list[Precursor] = field(default_factory=list)
    conformal_set: tuple[int, ...] = ()
    """Conformal prediction set. ``(0, 1)`` means the model abstains."""
    label: int | None = None

    @property
    def abstained(self) -> bool:
        return len(self.conformal_set) != 1


def group_documents(
    documents: Iterable[Document],
) -> dict[tuple[str, Date], Bag]:
    """Group loose documents into (region, day) bags."""
    bags: dict[tuple[str, Date], Bag] = {}
    for doc in documents:
        key = (doc.region, doc.date)
        bag = bags.get(key)
        if bag is None:
            bag = bags[key] = Bag(region=doc.region, date=doc.date)
        bag.documents.append(doc)
    return bags


def build_bag_groups(
    documents: Sequence[Document],
    origins: Sequence[Date],
    regions: Sequence[str],
    lookback_days: int,
    horizon_days: int,
    labels: dict[tuple[str, Date], int] | None = None,
) -> list[BagGroup]:
    """Assemble labelled forecasting units under a strict causal cut.

    A document enters the group for ``(region, origin)`` only if
    ``origin - lookback_days <= doc.date < origin``.
    """
    by_bag = group_documents(documents)
    groups: list[BagGroup] = []
    for region in regions:
        for origin in origins:
            window = [
                by_bag[(region, origin - _dt.timedelta(days=k))]
                for k in range(1, lookback_days + 1)
                if (region, origin - _dt.timedelta(days=k)) in by_bag
            ]
            group = BagGroup(
                region=region,
                origin=origin,
                horizon_days=horizon_days,
                bags=sorted(window, key=lambda b: b.date),
            )
            if labels is not None:
                group.label = labels.get((region, origin))
            groups.append(group)
    return groups
