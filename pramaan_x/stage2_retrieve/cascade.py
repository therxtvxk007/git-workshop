"""The four-stage retrieval cascade.

    sparse -> dense -> late interaction -> cross-encoder -> temporal/provenance

Each stage is narrower and more expensive than the last, which is the only
reason the expensive stages are affordable. The widths are the design: BM25 and
dense each return ~200 candidates, late interaction scores ~60, the cross-encoder
sees ~20. Every one of those numbers is a recall/cost trade-off that should be
re-measured per corpus, not inherited.

Component scores are all retained on the way through, because the learned fusion
needs them as features and the analyst view needs them as an explanation. A
cascade that returns only a final score cannot tell anyone why a document is
there.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..config import Stage2Config
from ..stage1_scan.bm25 import BM25Index
from ..stage1_scan.embed import Embedder
from ..types import Document, Evidence
from .engine import MemoryEngine, VectorEngine
from .fusion import LearnedFusion, reciprocal_rank_fusion
from .late_interaction import LateInteractionScorer
from .rerank import Reranker


@dataclass
class CascadeStats:
    n_corpus: int = 0
    n_sparse: int = 0
    n_dense: int = 0
    n_late: int = 0
    n_reranked: int = 0
    timings_ms: dict[str, float] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "corpus": self.n_corpus, "sparse": self.n_sparse, "dense": self.n_dense,
            "late": self.n_late, "reranked": self.n_reranked,
            "narrowing": [self.n_corpus, max(self.n_sparse, self.n_dense),
                          self.n_late, self.n_reranked],
            "timings_ms": {k: round(v, 2) for k, v in self.timings_ms.items()},
        }


class RetrievalCascade:
    def __init__(
        self,
        cfg: Stage2Config,
        embedder: Embedder,
        reranker: Reranker,
        *,
        engine: VectorEngine | None = None,
        fusion: LearnedFusion | None = None,
    ) -> None:
        self.cfg = cfg
        self.embedder = embedder
        self.reranker = reranker
        self.engine = engine or MemoryEngine()
        self.fusion = fusion
        self.late = LateInteractionScorer(embedder=embedder)
        self.bm25: BM25Index | None = None
        self._docs: dict[str, Document] = {}
        self._published: dict[str, datetime] = {}
        self._family: dict[str, str] = {}

    # ----------------------------------------------------------- index ---

    def index(self, docs: Sequence[Document]) -> RetrievalCascade:
        docs = list(docs)
        self._docs = {d.doc_id: d for d in docs}
        self._published = {d.doc_id: d.published_at for d in docs}
        self._family = {d.doc_id: d.meta.get("source_family", d.source_id) for d in docs}
        ids = [d.doc_id for d in docs]
        texts = [d.full_text for d in docs]
        self.bm25 = BM25Index().fit(ids, texts)
        if texts:
            vecs = self.embedder.encode(texts)
            self.engine = MemoryEngine() if isinstance(self.engine, MemoryEngine) else self.engine
            self.engine.add(ids, vecs, [{"published_at": t} for t in self._published.values()])
        return self

    # --------------------------------------------------------- retrieve ---

    def retrieve(
        self,
        query: str,
        *,
        as_of: datetime | None = None,
        top_k: int | None = None,
        allowed: set[str] | None = None,
        stop_after: str = "rerank",
    ) -> tuple[list[Evidence], CascadeStats]:
        """`stop_after` in {"sparse","dense","fusion","late","rerank"} lets the
        bake-off measure each stage's marginal contribution rather than assuming
        it."""
        cfg = self.cfg
        stats = CascadeStats(n_corpus=len(self._docs))
        components: dict[str, dict[str, float]] = {}

        # -- publication cutoff, applied once, before any scoring ----------
        if as_of is not None:
            visible = {d for d, t in self._published.items() if t < as_of}
            allowed = visible if allowed is None else (allowed & visible)

        # -- stage 1: sparse ------------------------------------------------
        t0 = time.perf_counter()
        sparse_hits = self.bm25.top_k(query, cfg.bm25_top_k * 3) if self.bm25 else []
        if allowed is not None:
            sparse_hits = [(d, s) for d, s in sparse_hits if d in allowed]
        sparse_hits = sparse_hits[: cfg.bm25_top_k]
        stats.timings_ms["sparse"] = (time.perf_counter() - t0) * 1000
        stats.n_sparse = len(sparse_hits)
        for d, s in sparse_hits:
            components.setdefault(d, {})["bm25"] = float(s)
        if stop_after == "sparse":
            return self._finish([d for d, _ in sparse_hits], components, stats, top_k), stats

        # -- stage 2: dense -------------------------------------------------
        t0 = time.perf_counter()
        qv = self.embedder.encode([query])[0]
        dense_hits = self.engine.search(qv, k=cfg.dense_top_k, allowed=allowed)
        stats.timings_ms["dense"] = (time.perf_counter() - t0) * 1000
        stats.n_dense = len(dense_hits)
        for h in dense_hits:
            components.setdefault(h.doc_id, {})["dense"] = float(h.score)
        if stop_after == "dense":
            return self._finish([h.doc_id for h in dense_hits], components, stats, top_k), stats

        # -- fusion: reciprocal rank ---------------------------------------
        t0 = time.perf_counter()
        fused = reciprocal_rank_fusion(
            {"bm25": [d for d, _ in sparse_hits], "dense": [h.doc_id for h in dense_hits]},
            k=cfg.rrf_k,
        )
        stats.timings_ms["fusion"] = (time.perf_counter() - t0) * 1000
        for rank, (d, s) in enumerate(fused, start=1):
            components.setdefault(d, {})["rrf"] = float(s)
            components[d]["rrf_rank"] = float(rank)
        if stop_after == "fusion":
            return self._finish([d for d, _ in fused], components, stats, top_k), stats

        # -- stage 3: late interaction --------------------------------------
        t0 = time.perf_counter()
        shortlist = [d for d, _ in fused[: cfg.late_top_k]]
        if shortlist:
            late_scores = self.late.score(query, [self._docs[d].full_text for d in shortlist])
            for d, s in zip(shortlist, late_scores, strict=True):
                components[d]["late"] = float(s)
        stats.timings_ms["late"] = (time.perf_counter() - t0) * 1000
        stats.n_late = len(shortlist)
        if stop_after == "late":
            ordered = sorted(shortlist, key=lambda d: -components[d].get("late", 0.0))
            return self._finish(ordered, components, stats, top_k), stats

        # -- stage 4: cross-encoder / listwise reranking ---------------------
        t0 = time.perf_counter()
        rr_list = sorted(shortlist, key=lambda d: -components[d].get("late", 0.0))
        rr_list = rr_list[: cfg.rerank_top_k]
        if rr_list:
            cross = self.reranker.rerank(query, [self._docs[d].full_text for d in rr_list])
            for d, s in zip(rr_list, cross, strict=True):
                components[d]["cross"] = float(s)
        stats.timings_ms["rerank"] = (time.perf_counter() - t0) * 1000
        stats.n_reranked = len(rr_list)

        # -- evidence spans --------------------------------------------------
        # The reranked set is what an analyst reads, so it gets the window that
        # actually matched rather than the document's opening sentence. Showing
        # the head of the document is worse than useless here: precursor text is
        # deliberately buried mid-document, so the head is almost always filler
        # and the reader concludes the retriever is broken.
        spans: dict[str, str] = {}
        for d in rr_list:
            try:
                span, _ = self.late.best_span(query, self._docs[d].full_text)
                spans[d] = span
            except Exception:                     # never fail a query on display
                spans[d] = self._docs[d].full_text[:240]

        # -- temporal and provenance scoring --------------------------------
        self._temporal_provenance(components, as_of)

        ordered = self._order(list(components), components)
        return self._finish(ordered, components, stats, top_k, spans=spans), stats

    # --------------------------------------------------------- scoring ---

    def _temporal_provenance(self, components: dict[str, dict[str, float]],
                             as_of: datetime | None) -> None:
        """Recency and source independence, applied to every scored candidate.

        Source independence is per-document here (how rare its family is within
        the candidate set); the aggregate independence of an evidence *set* is
        computed in stage 4, where the set is known.
        """
        if not components:
            return
        fam_counts: dict[str, int] = {}
        for d in components:
            fam = self._family.get(d, "")
            fam_counts[fam] = fam_counts.get(fam, 0) + 1
        n = len(components)
        for d, comp in components.items():
            pub = self._published.get(d)
            if as_of is not None and pub is not None:
                age = max((as_of - pub).days, 0)
                # Half-life of 30 days. Slower than a news-recency prior would
                # suggest, because a precursor is often weeks old by design.
                comp["recency"] = float(0.5 ** (age / 30.0))
            else:
                comp["recency"] = 0.0
            fam = self._family.get(d, "")
            comp["source_independence"] = float(1.0 - (fam_counts[fam] - 1) / max(n - 1, 1))

    def _order(self, ids: Sequence[str], components: dict[str, dict[str, float]]
               ) -> list[tuple[str, float]]:
        """Returns (doc_id, ranking score). The score that determined the order
        is the score reported: a response whose `score` field does not explain
        its own ordering is unreadable to anyone consuming the API."""
        if self.fusion is not None and self.fusion.fitted:
            scores = self.fusion.score([components[d] for d in ids])
            return sorted(zip(ids, scores.tolist(), strict=True), key=lambda kv: -kv[1])
        # Without a trained ranker, fall back to RRF order with the reranker
        # score as the dominant term where it exists. Explicitly a fallback:
        # these coefficients are not learned and are not claimed to be optimal.
        def key(d: str) -> float:
            c = components[d]
            return (2.0 * c.get("cross", 0.0) + 1.0 * c.get("late", 0.0)
                    + 60.0 * c.get("rrf", 0.0) + 0.2 * c.get("recency", 0.0))
        return sorted(((d, key(d)) for d in ids), key=lambda kv: -kv[1])

    @staticmethod
    def _stage_score(comp: dict[str, float]) -> float:
        for key in ("late", "rrf", "dense", "bm25"):
            if key in comp:
                return float(comp[key])
        return 0.0

    def _finish(self, ranked: Sequence[str] | Sequence[tuple[str, float]],
                components: dict[str, dict[str, float]],
                stats: CascadeStats, top_k: int | None,
                spans: dict[str, str] | None = None) -> list[Evidence]:
        k = top_k or self.cfg.rerank_top_k
        # Stop points before the final ordering pass hand in bare ids; their
        # ranking score is the score of the stage that produced them.
        pairs: list[tuple[str, float]] = [
            r if isinstance(r, tuple) else (r, self._stage_score(components.get(r, {})))
            for r in ranked
        ]
        out: list[Evidence] = []
        for d, score in pairs[:k]:
            doc = self._docs.get(d)
            comp = components.get(d, {})
            out.append(Evidence(
                doc_id=d,
                score=float(score),
                components=dict(comp),
                span=((spans or {}).get(d) or (doc.full_text[:240] if doc else "")),
                published_at=self._published.get(d),
                source_id=doc.source_id if doc else "",
            ))
        return out
