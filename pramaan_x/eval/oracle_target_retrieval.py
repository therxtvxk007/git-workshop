"""Oracle-target precursor-evidence retrieval.

**What this benchmark measures.** Given a target that is already known -- a
location and an event type handed to the retriever by an oracle -- how well does
the cascade surface the precursor documents for that target from everything
available at a forecast origin?

**What it does not measure.** Anything about forecasting. It never asks *which*
target will have an event, or *when*, or *whether*. The target is an input. No
number produced here -- Recall@K, Precision@K, nDCG@K, MRR -- is a statement
about event-forecasting performance, and describing it as one is the single
most likely way for this repository to mislead somebody.

The name says so on purpose. The previous name ("retrieval benchmark", reported
next to a forecasting narrative) did not.

Two methods are implemented, and both are meant to be run:

``contaminated_legacy_diagnostic``
    One index over the whole corpus, BM25 statistics and hashing IDF fitted on
    every document including documents from after every origin, availability
    decided by publication date alone. This is the method the repository used
    before; it is kept as a diagnostic so the size of the contamination can be
    quantified rather than asserted.

``strict_temporal``
    A snapshot index per forecast origin, fitted only on documents available
    strictly before that origin under the availability rule, with the learned
    fusion ranker trained only on training-window queries. Indexes are cached
    per origin -- caching is a performance decision and never widens what an
    index may see.
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import numpy as np

from ..config import Stage2Config
from ..data.synth import GroundTruth
from ..stage1_scan.embed import Embedder
from ..stage1_scan.lexical import LexicalIndicators
from ..stage2_retrieve.cascade import RetrievalCascade
from ..stage2_retrieve.rerank import Reranker
from ..types import Document
from .availability import (
    AvailabilityViolation,
    audit_returned,
    available_documents,
    to_utc,
)
from .metrics import RetrievalReport, evaluate_retrieval
from .protocol import TemporalProtocol

if TYPE_CHECKING:
    from ..stage2_retrieve.fusion import LearnedFusion

STAGES = ("sparse", "dense", "fusion", "late", "rerank")

#: The two methods, named exactly as the artefacts and tables label them.
STRICT = "strict_temporal"
LEGACY = "contaminated_legacy_diagnostic"


class Method(enum.StrEnum):
    STRICT_TEMPORAL = STRICT
    CONTAMINATED_LEGACY_DIAGNOSTIC = LEGACY


@dataclass(frozen=True)
class OracleTargetQuery:
    """One query whose target was given, not inferred.

    `target_key`, `location` and `event_type` are oracle inputs. `event_time`
    is used only to place the query on the origin grid and to select the
    relevant set; it never reaches the retriever.
    """

    query_id: str
    text: str
    origin: datetime
    event_time: datetime
    target_key: str
    location: str
    event_type: str
    relevant: frozenset[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "origin": to_utc(self.origin).isoformat(),
            "event_time": to_utc(self.event_time).isoformat(),
            "target_key": self.target_key,
            "n_relevant": len(self.relevant),
        }


# ------------------------------------------------------------- query build ---


def build_oracle_target_queries(
    gt: GroundTruth,
    lexicon: LexicalIndicators,
    docs: Sequence[Document],
    protocol: TemporalProtocol,
    window: str,
    *,
    method: str = STRICT,
    n_terms: int = 20,
    min_relevant: int = 1,
) -> list[OracleTargetQuery]:
    """Build the query set for one protocol window.

    The query text is ``"<location> <lexicon terms for event_type>"``. Both
    halves come from the oracle target; the lexicon must have been fitted on
    the training window only, which `run_*` enforces by construction.

    Under `strict_temporal` a query is placed at the last grid origin at or
    before its event, and its relevant set is the subset of precursor documents
    *available* at that origin. Under `contaminated_legacy_diagnostic` the
    origin is the event time itself and availability is publication-only --
    reproducing the earlier behaviour exactly so the two can be compared.
    """
    by_id = {d.doc_id: d for d in docs}
    out: list[OracleTargetQuery] = []
    for (key, iso), doc_ids in sorted(gt.precursor_docs.items()):
        event_time = to_utc(datetime.fromisoformat(iso))
        if not protocol.contains(window, event_time):
            continue
        if method == STRICT:
            origin = protocol.origin_for(window, event_time)
            if origin is None:
                continue
            available = {
                d.doc_id
                for d in available_documents((by_id[i] for i in doc_ids if i in by_id), origin)
            }
        else:
            origin = event_time
            available = {
                i for i in doc_ids if i in by_id and to_utc(by_id[i].published_at) < event_time
            }
        if len(available) < min_relevant:
            continue
        location, event_type = key.split("|", 1)
        terms = lexicon.query_for(event_type, n=n_terms)
        if not terms:
            continue
        out.append(
            OracleTargetQuery(
                query_id=f"{key}@{iso}",
                text=f"{location} {terms}",
                origin=origin,
                event_time=event_time,
                target_key=key,
                location=location,
                event_type=event_type,
                relevant=frozenset(available),
            )
        )
    return out


# ------------------------------------------------------------ index supply ---


@dataclass
class FitRecord:
    """What one fitted index was allowed to see. The audit trail behind the
    'no future document was fitted' invariant."""

    origin: str
    n_documents: int
    max_published_at: str | None
    max_available_at: str | None
    method: str


class IndexProvider:
    """Supplies the cascade to use at a forecast origin, and records what it
    was fitted on."""

    method: str = STRICT

    def __init__(self) -> None:
        self.fit_records: list[FitRecord] = []
        self.n_builds = 0

    def for_origin(self, origin: datetime) -> RetrievalCascade:  # pragma: no cover
        raise NotImplementedError

    def _record(self, origin: datetime, docs: Sequence[Document]) -> None:
        pubs = [to_utc(d.published_at) for d in docs]
        avail = [a for a in (_avail(d) for d in docs) if a is not None]
        self.fit_records.append(
            FitRecord(
                origin=to_utc(origin).isoformat(),
                n_documents=len(docs),
                max_published_at=max(pubs).isoformat() if pubs else None,
                max_available_at=max(avail).isoformat() if avail else None,
                method=self.method,
            )
        )


def _avail(doc: Document) -> datetime | None:
    from .availability import available_at

    return available_at(doc)


class SnapshotIndexProvider(IndexProvider):
    """One index per forecast origin, fitted on the corpus as it stood then.

    The cache is keyed by origin. It exists so a 20-origin run does not rebuild
    an index per query; it cannot widen what an index sees, because the key
    *is* the origin and the corpus is re-filtered for every miss.
    """

    method = STRICT

    def __init__(
        self,
        corpus: Sequence[Document],
        cfg: Stage2Config,
        embedder_factory: Callable[[], Embedder],
        reranker_factory: Callable[[], Reranker],
        *,
        fusion: LearnedFusion | None = None,
    ) -> None:
        super().__init__()
        self.corpus = list(corpus)
        self.cfg = cfg
        self.embedder_factory = embedder_factory
        self.reranker_factory = reranker_factory
        self.fusion = fusion
        self._cache: dict[datetime, RetrievalCascade] = {}

    def for_origin(self, origin: datetime) -> RetrievalCascade:
        origin = to_utc(origin)
        hit = self._cache.get(origin)
        if hit is not None:
            return hit
        visible = available_documents(self.corpus, origin)
        self._record(origin, visible)
        # A fresh embedder per origin: `HashingEmbedder.fit` learns an IDF
        # table, and reusing one fitted at a later origin is exactly the
        # contamination this class exists to prevent.
        embedder = self.embedder_factory()
        if hasattr(embedder, "fit"):
            embedder.fit([d.full_text for d in visible])
        cascade = RetrievalCascade(
            self.cfg, embedder, self.reranker_factory(), fusion=self.fusion
        ).index(visible)
        self.n_builds += 1
        self._cache[origin] = cascade
        return cascade

    def clear_cache(self) -> None:
        self._cache.clear()


class FullCorpusIndexProvider(IndexProvider):
    """The legacy method: one index over everything, origin ignored.

    Kept so the contamination can be measured. Do not use it for anything
    reported as a result.
    """

    method = LEGACY

    def __init__(
        self,
        corpus: Sequence[Document],
        cfg: Stage2Config,
        embedder: Embedder,
        reranker: Reranker,
        *,
        fusion: LearnedFusion | None = None,
    ) -> None:
        super().__init__()
        self.corpus = list(corpus)
        self._cascade = RetrievalCascade(cfg, embedder, reranker, fusion=fusion).index(self.corpus)

    def for_origin(self, origin: datetime) -> RetrievalCascade:
        self._record(origin, self.corpus)
        return self._cascade


# ------------------------------------------------------------------- runs ---


@dataclass
class RunOutcome:
    """Reports per stop point, plus everything needed to audit the run."""

    reports: dict[str, RetrievalReport]
    availability_violations: list[AvailabilityViolation] = field(default_factory=list)
    fit_records: list[FitRecord] = field(default_factory=list)
    n_index_builds: int = 0
    n_queries: int = 0

    def summary(self) -> dict[str, Any]:
        return {stage: rep.summary() for stage, rep in self.reports.items()}


def stage_width(cfg: Stage2Config, stage: str) -> int:
    """How many documents a stop point can return at most.

    Reported alongside the metrics because a recall figure at k above the stage
    width is bounded by the width, not by the retriever -- reading it as a
    quality difference is simply wrong.
    """
    return {
        "sparse": cfg.bm25_top_k,
        "dense": cfg.dense_top_k,
        "fusion": cfg.bm25_top_k + cfg.dense_top_k,
        "late": cfg.late_top_k,
        "rerank": cfg.bm25_top_k + cfg.dense_top_k,
    }[stage]


def run_oracle_target_retrieval(
    corpus: Sequence[Document],
    queries: Sequence[OracleTargetQuery],
    provider: IndexProvider,
    *,
    cfg: Stage2Config | None = None,
    ks: Sequence[int] = (10, 20, 50, 100),
    stages: Sequence[str] = STAGES,
    top_k: int = 200,
) -> RunOutcome:
    """Evaluate every stop point over `queries`, one index per origin.

    Every returned document is audited against the availability rule at its
    query's origin. The audit is independent of the filtering: a bug that
    reintroduces a future document downstream of the index is invisible to the
    index, and this is what would catch it.
    """
    cfg = cfg or Stage2Config()
    by_id = {d.doc_id: d for d in corpus}
    outcome = RunOutcome(reports={}, n_queries=len(queries))
    for stage in stages:
        runs: list[tuple[list[str], set[str]]] = []
        elapsed: list[float] = []
        for q in queries:
            cascade = provider.for_origin(q.origin)
            t0 = time.perf_counter()
            ev, _ = cascade.retrieve(q.text, as_of=q.origin, top_k=top_k, stop_after=stage)
            elapsed.append((time.perf_counter() - t0) * 1000.0)
            ids = [e.doc_id for e in ev]
            outcome.availability_violations.extend(audit_returned(by_id, ids, q.origin))
            runs.append((ids, set(q.relevant)))
        outcome.reports[stage] = evaluate_retrieval(runs, ks=ks, latency_ms=_latency(elapsed))
    outcome.fit_records = list(provider.fit_records)
    outcome.n_index_builds = provider.n_builds
    return outcome


def _latency(samples: Sequence[float]) -> dict[str, float]:
    if not samples:
        return {}
    arr = np.asarray(samples, dtype=float)
    return {
        "mean": float(arr.mean()),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
        "total": float(arr.sum()),
    }


def train_fusion(
    queries: Sequence[OracleTargetQuery],
    provider: IndexProvider,
    corpus: Sequence[Document],
    *,
    candidates_per_query: int = 60,
) -> LearnedFusion:
    """Fit LambdaMART on training-window queries only.

    Labels are graded, not binary: a relevant document retrieved is grade 3, a
    document from the same target but a different episode is grade 1, everything
    else 0. Binary labels would teach the ranker that a near-miss and a totally
    unrelated document are equally wrong, which is not what an analyst
    experiences.

    Candidates come from the same per-origin index the evaluation uses, so the
    ranker is fitted on features drawn from indexes that saw no future document
    either. `queries` must be training-window queries; callers get that from
    `TemporalProtocol` and the invariants check it.
    """
    from ..stage2_retrieve.fusion import LearnedFusion

    target_of = {d.doc_id: d.meta.get("synth_target", "") for d in corpus}
    features: list[dict[str, float]] = []
    labels: list[int] = []
    groups: list[int] = []
    for q in queries:
        cascade = provider.for_origin(q.origin)
        ev, _ = cascade.retrieve(q.text, as_of=q.origin, top_k=candidates_per_query)
        if not ev:
            continue
        groups.append(len(ev))
        for e in ev:
            if e.doc_id in q.relevant:
                grade = 3
            elif target_of.get(e.doc_id) == q.target_key:
                grade = 1
            else:
                grade = 0
            features.append(e.components)
            labels.append(grade)
    if not groups:
        raise ValueError("no training queries produced candidates")
    return LearnedFusion().fit(features, labels, groups)


# ----------------------------------------------------------------- tables ---


def format_table(
    reports: dict[str, RetrievalReport],
    ks: Sequence[int] = (10, 20, 50, 100),
    cfg: Stage2Config | None = None,
    *,
    method: str = STRICT,
) -> str:
    """Text table. The method label is part of the table, not a caption that
    can be separated from it."""
    cfg = cfg or Stage2Config()
    header = (
        f"{'stage':<10}{'width':>7}"
        + "".join(f"{'R@' + str(k):>9}" for k in ks)
        + f"{'P@10':>8}{'nDCG@10':>9}{'MRR':>7}{'ms/q':>8}"
    )
    lines = [
        f"oracle_target_retrieval [{method}]",
        "target location and event type are GIVEN; this is evidence retrieval,",
        "not event forecasting",
        "",
        header,
        "-" * len(header),
    ]
    for stage, rep in reports.items():
        width = stage_width(cfg, stage)
        row = f"{stage:<10}{width:>7}"
        for k in ks:
            v = rep.recall.get(k, float("nan"))
            # Mark figures the stage width caps, so a narrowing stage is not
            # misread as a worse retriever.
            row += f"{v:>8.3f}*" if k > width else f"{v:>9.3f}"
        row += (
            f"{rep.precision.get(10, float('nan')):>8.3f}"
            f"{rep.ndcg.get(10, float('nan')):>9.3f}"
            f"{rep.mrr:>7.3f}"
            f"{rep.latency_ms.get('mean', float('nan')):>8.1f}"
        )
        lines.append(row)
    lines.append("* bounded by the stage width, not by retrieval quality")
    return "\n".join(lines)
