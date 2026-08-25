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

Three methods, of which exactly two may be compared with each other.

**The controlled pair.** Both evaluate the *same* canonical query set: same
query ids, same text, same origins, same relevant sets, same lexicon, same
fusion training data, same K values, same candidate widths. One thing differs
between them and it is named in the artefact:

``strict_temporal``
    A snapshot index per forecast origin, fitted only on documents available
    strictly before that origin. Indexes are cached per origin -- caching is a
    performance decision and never widens what an index may see.

``future_fitted_index_ablation``
    Byte-identical inputs, but BM25 statistics, hashing IDF and the vector
    index are deliberately fitted on the whole corpus, including documents
    from after every origin. The availability filter still applies to what is
    *returned*, so the contamination is in the fitted statistics and nowhere
    else. This is what makes a paired per-query delta mean something.

**The unpaired reproduction.**

``historical_legacy_reproduction_unpaired``
    What this repository did before the firewall work: full-corpus fitting,
    publication-only availability, and each query placed at its own event time
    rather than on the origin grid. It changes several factors simultaneously
    and therefore builds a *different query set* -- different origins,
    different relevant sets, sometimes a different number of surviving
    queries. It is kept so the old numbers can be reproduced, and no delta is
    computed against it. Subtracting it from a strict result would produce a
    number with no referent, which is precisely what the earlier version of
    this file did.
"""

from __future__ import annotations

import enum
import hashlib
import json
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
from .metrics import (
    RetrievalReport,
    evaluate_retrieval,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from .protocol import TemporalProtocol

if TYPE_CHECKING:
    from ..stage2_retrieve.fusion import LearnedFusion

STAGES = ("sparse", "dense", "fusion", "late", "rerank")

#: The two methods, named exactly as the artefacts and tables label them.
STRICT = "strict_temporal"
ABLATION = "future_fitted_index_ablation"
HISTORICAL = "historical_legacy_reproduction_unpaired"

#: The only two methods whose results may be subtracted from one another.
CONTROLLED_METHODS = (STRICT, ABLATION)
ALL_METHODS = (STRICT, ABLATION, HISTORICAL)

#: What the historical reproduction changes relative to the controlled pair.
#: Recorded in its artefact so nobody has to rediscover why it is fenced off.
HISTORICAL_FACTORS_CHANGED = (
    "index_scope",
    "availability_policy",
    "forecast_origin_placement",
    "relevant_document_set",
)


class Method(enum.StrEnum):
    STRICT_TEMPORAL = STRICT
    FUTURE_FITTED_INDEX_ABLATION = ABLATION
    HISTORICAL_LEGACY_REPRODUCTION_UNPAIRED = HISTORICAL


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
    n_terms: int = 20,
    min_relevant: int = 1,
) -> list[OracleTargetQuery]:
    """The canonical query set. One definition, shared by both controlled arms.

    There is deliberately no `method` parameter. The previous version branched
    on the method here and, in doing so, changed the origin, the availability
    policy and the relevant set at the same time as the thing under test -- so
    the two arms evaluated different query sets and the deltas between them
    were unattributable. Any arm that wants a different query set is not a
    controlled arm and must say so somewhere else.

    A query is placed at the last grid origin at or before its event, and its
    relevant set is the subset of precursor documents *available* at that
    origin under the availability rule. The query text is
    ``"<location> <lexicon terms for event_type>"``: both halves come from the
    oracle target, and the lexicon must have been fitted on the training window
    only, which `harness.prepare` enforces.
    """
    by_id = {d.doc_id: d for d in docs}
    out: list[OracleTargetQuery] = []
    for (key, iso), doc_ids in sorted(gt.precursor_docs.items()):
        event_time = to_utc(datetime.fromisoformat(iso))
        if not protocol.contains(window, event_time):
            continue
        origin = protocol.origin_for(window, event_time)
        if origin is None:
            continue
        available = {
            d.doc_id for d in available_documents((by_id[i] for i in doc_ids if i in by_id), origin)
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


def build_historical_legacy_queries(
    gt: GroundTruth,
    lexicon: LexicalIndicators,
    docs: Sequence[Document],
    protocol: TemporalProtocol,
    window: str,
    *,
    n_terms: int = 20,
    min_relevant: int = 1,
) -> list[OracleTargetQuery]:
    """The old query set, reproduced exactly, for the unpaired arm only.

    Each query sits at its own event time rather than on the origin grid, and
    relevance is decided by publication date alone. Both differences change
    which documents count as relevant and which queries survive the
    `min_relevant` filter, which is why nothing may be subtracted from a run
    built on this.
    """
    by_id = {d.doc_id: d for d in docs}
    out: list[OracleTargetQuery] = []
    for (key, iso), doc_ids in sorted(gt.precursor_docs.items()):
        event_time = to_utc(datetime.fromisoformat(iso))
        if not protocol.contains(window, event_time):
            continue
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
                origin=event_time,
                event_time=event_time,
                target_key=key,
                location=location,
                event_type=event_type,
                relevant=frozenset(available),
            )
        )
    return out


def query_set_fingerprint(queries: Sequence[OracleTargetQuery]) -> str:
    """Digest of everything about a query set that must not move between the
    controlled arms. Recorded in both artefacts so equality is checkable from
    the files alone, not only from a test that ran once."""
    blob = json.dumps(
        [[q.query_id, q.text, to_utc(q.origin).isoformat(), sorted(q.relevant)] for q in queries],
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


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
    #: "ranker_training" or "evaluation". The controlled ablation trains the
    #: ranker from snapshot indexes in *both* arms and only varies the
    #: evaluation index, so a fit record that does not say which phase it came
    #: from cannot be read correctly.
    phase: str = "evaluation"


class IndexProvider:
    """Supplies the cascade to use at a forecast origin, and records what it
    was fitted on."""

    method: str = STRICT

    def __init__(self, phase: str = "evaluation") -> None:
        self.fit_records: list[FitRecord] = []
        self.n_builds = 0
        self.phase = phase

    def for_origin(self, origin: datetime) -> RetrievalCascade:  # pragma: no cover
        raise NotImplementedError

    def allowed_at(self, origin: datetime) -> set[str] | None:
        """Doc ids the retriever may return at `origin`, or None for no extra
        filter beyond whatever the index already contains."""
        return None

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
                phase=self.phase,
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
        phase: str = "evaluation",
    ) -> None:
        super().__init__(phase)
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
    """One index over everything, origin ignored: the contamination itself.

    Used by two methods for two different reasons. In
    `future_fitted_index_ablation` it is the single variable under test, with
    every other input held byte-identical to the strict arm. In
    `historical_legacy_reproduction_unpaired` it is one of several differences
    and no delta is computed. Never use it for a reported result.
    """

    method = ABLATION

    def __init__(
        self,
        corpus: Sequence[Document],
        cfg: Stage2Config,
        embedder: Embedder,
        reranker: Reranker,
        *,
        fusion: LearnedFusion | None = None,
        enforce_availability: bool = False,
        phase: str = "evaluation",
    ) -> None:
        super().__init__(phase)
        self.corpus = list(corpus)
        # The ablation contaminates *fitting* and nothing else. Without this
        # the full-corpus index would also hand back documents that were
        # published before the origin but not yet crawled, which is a second
        # difference from the strict arm and would break the pairing again.
        # The historical reproduction leaves it off, because returning those
        # documents is one of the things it is reproducing.
        self.enforce_availability = enforce_availability
        self.method = ABLATION if enforce_availability else HISTORICAL
        self._cascade = RetrievalCascade(cfg, embedder, reranker, fusion=fusion).index(self.corpus)
        self._allowed: dict[datetime, set[str]] = {}

    def for_origin(self, origin: datetime) -> RetrievalCascade:
        self._record(origin, self.corpus)
        return self._cascade

    def allowed_at(self, origin: datetime) -> set[str] | None:
        if not self.enforce_availability:
            return None
        origin = to_utc(origin)
        hit = self._allowed.get(origin)
        if hit is None:
            hit = {d.doc_id for d in available_documents(self.corpus, origin)}
            self._allowed[origin] = hit
        return hit


# ------------------------------------------------------------------- runs ---


@dataclass
class RunOutcome:
    """Reports per stop point, plus everything needed to audit the run."""

    reports: dict[str, RetrievalReport]
    availability_violations: list[AvailabilityViolation] = field(default_factory=list)
    fit_records: list[FitRecord] = field(default_factory=list)
    n_index_builds: int = 0
    n_queries: int = 0
    #: stage -> query_id -> {metric: value}. The paired comparison needs these:
    #: a difference of two means over two query sets is not a difference, and
    #: even over one query set it hides how many queries moved which way.
    per_query: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)

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
        per_query: dict[str, dict[str, float]] = {}
        for q in queries:
            cascade = provider.for_origin(q.origin)
            allowed = provider.allowed_at(q.origin)
            t0 = time.perf_counter()
            ev, _ = cascade.retrieve(
                q.text, as_of=q.origin, top_k=top_k, stop_after=stage, allowed=allowed
            )
            elapsed.append((time.perf_counter() - t0) * 1000.0)
            ids = [e.doc_id for e in ev]
            outcome.availability_violations.extend(audit_returned(by_id, ids, q.origin))
            relevant = set(q.relevant)
            runs.append((ids, relevant))
            per_query[q.query_id] = per_query_metrics(ids, relevant, ks=ks)
        outcome.per_query[stage] = per_query
        outcome.reports[stage] = evaluate_retrieval(runs, ks=ks, latency_ms=_latency(elapsed))
    outcome.fit_records = list(provider.fit_records)
    outcome.n_index_builds = provider.n_builds
    return outcome


def per_query_metrics(
    ranked: Sequence[str], relevant: set[str], *, ks: Sequence[int] = (10, 20, 50, 100)
) -> dict[str, float]:
    """The same metrics the aggregate report computes, kept per query.

    Aggregates are means over these. Reporting only the means answers "did the
    average move" and never "how many queries moved, and by how much", which
    is the question a paired ablation exists to answer.
    """
    rel_map = dict.fromkeys(relevant, 1.0)
    out: dict[str, float] = {}
    for k in ks:
        out[f"recall@{k}"] = recall_at_k(ranked, relevant, k)
        out[f"precision@{k}"] = precision_at_k(ranked, relevant, k)
        out[f"ndcg@{k}"] = ndcg_at_k(ranked, rel_map, k)
    out["mrr"] = mrr(ranked, relevant)
    return out


def paired_delta(
    reference: dict[str, dict[str, float]],
    variant: dict[str, dict[str, float]],
    *,
    metrics: Sequence[str] = ("recall@10", "recall@100", "precision@10", "ndcg@10", "mrr"),
) -> dict[str, Any]:
    """Per-query differences between two arms over the *same* queries.

    Refuses to compare query sets that are not identical. That refusal is the
    point: the previous version of this comparison silently differenced two
    different query sets, and a mean difference computed that way is not a
    difference of anything.
    """
    ref_ids, var_ids = set(reference), set(variant)
    if ref_ids != var_ids:
        raise ValueError(
            "paired_delta requires identical query sets; "
            f"{len(ref_ids - var_ids)} only in the reference, "
            f"{len(var_ids - ref_ids)} only in the variant"
        )
    ids = sorted(ref_ids)
    rows: list[dict[str, Any]] = []
    for qid in ids:
        row: dict[str, Any] = {"query_id": qid}
        for m in metrics:
            row[m] = float(variant[qid][m] - reference[qid][m])
        rows.append(row)
    summary: dict[str, Any] = {}
    for m in metrics:
        vals = np.array([r[m] for r in rows], dtype=float)
        summary[m] = {
            "mean": float(vals.mean()) if vals.size else float("nan"),
            "sd": float(vals.std(ddof=1)) if vals.size > 1 else 0.0,
            "median": float(np.median(vals)) if vals.size else float("nan"),
            "min": float(vals.min()) if vals.size else float("nan"),
            "max": float(vals.max()) if vals.size else float("nan"),
            "n_better": int((vals > 0).sum()),
            "n_worse": int((vals < 0).sum()),
            "n_equal": int((vals == 0).sum()),
        }
    return {"n_paired_queries": len(ids), "per_query_delta": summary, "per_query": rows}


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
) -> tuple[LearnedFusion, str]:
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

    Returns the fitted ranker and a fingerprint of the training data. Both
    controlled arms call this with the same inputs and the same provider type,
    so the fingerprints must match -- and a test asserts they do rather than
    trusting that they will.
    """
    from ..stage2_retrieve.fusion import COMPONENTS, LearnedFusion

    target_of = {d.doc_id: d.meta.get("synth_target", "") for d in corpus}
    features: list[dict[str, float]] = []
    labels: list[int] = []
    groups: list[int] = []
    for q in queries:
        cascade = provider.for_origin(q.origin)
        ev, _ = cascade.retrieve(
            q.text,
            as_of=q.origin,
            top_k=candidates_per_query,
            allowed=provider.allowed_at(q.origin),
        )
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
    # Fingerprint the training data itself, so "the two arms trained the ranker
    # on the same thing" is a checkable property of the artefacts rather than
    # something a reader has to infer from the code path.
    blob = json.dumps(
        {
            "labels": list(labels),
            "groups": list(groups),
            "features": [[round(float(f.get(c, 0.0)), 9) for c in COMPONENTS] for f in features],
        },
        sort_keys=True,
    )
    fingerprint = hashlib.sha256(blob.encode()).hexdigest()
    return LearnedFusion().fit(features, labels, groups), fingerprint


def ranking_probe(
    cfg: Any,
    queries: Sequence[OracleTargetQuery],
    *,
    method: str = STRICT,
    top_k: int = 50,
):
    """A `build_and_rank` callable for the future-append invariance check.

    Returns a function that takes a corpus, builds whatever the given method
    builds from it, and ranks a fixed query set. Living here rather than in the
    test keeps the probe honest: it exercises the same provider classes the
    benchmark uses, so an invariance test cannot pass against a simplified
    stand-in that the real pipeline does not resemble.
    """
    from ..stage1_scan.embed import build_embedder
    from ..stage2_retrieve.rerank import build_reranker

    def build_and_rank(corpus: Sequence[Document]) -> dict[str, list[str]]:
        if method == STRICT:
            provider: IndexProvider = SnapshotIndexProvider(
                corpus,
                cfg.stage2,
                lambda: build_embedder(cfg.stage1.embedder, cfg.stage1.embed_dim),
                lambda: build_reranker(cfg.stage2.reranker),
            )
        else:
            embedder = build_embedder(cfg.stage1.embedder, cfg.stage1.embed_dim)
            if hasattr(embedder, "fit"):
                embedder.fit([d.full_text for d in corpus])
            provider = FullCorpusIndexProvider(
                corpus,
                cfg.stage2,
                embedder,
                build_reranker(cfg.stage2.reranker),
                enforce_availability=(method == ABLATION),
            )
        return {
            q.query_id: [
                e.doc_id
                for e in provider.for_origin(q.origin).retrieve(
                    q.text, as_of=q.origin, top_k=top_k, allowed=provider.allowed_at(q.origin)
                )[0]
            ]
            for q in queries
        }

    return build_and_rank


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
