"""Service layer.

Sits between the HTTP surface and the cascade so the API module contains no
analysis logic and the CLI can drive exactly the same code path. Indexes are
built once and held; rebuilding per request would make every query pay the
corpus-wide cost the cascade exists to avoid.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import Config
from .data.store import DocumentStore
from .data.synth import SynthConfig, SyntheticCorpus
from .stage0_ingest.pipeline import Stage0Result, run_stage0
from .stage1_scan.embed import build_embedder
from .stage1_scan.lexical import LexicalIndicators
from .stage2_retrieve.cascade import RetrievalCascade
from .stage2_retrieve.rerank import build_reranker
from .types import Document
from .util.logging import get_logger, timed

log = get_logger("service")


class NotReady(RuntimeError):
    """Raised when an endpoint needs an index that has not been built."""


@dataclass
class ServiceState:
    config: Config
    store: DocumentStore | None = None
    stage0: Stage0Result | None = None
    cascade: RetrievalCascade | None = None
    lexicon: LexicalIndicators | None = None
    documents: list[Document] = field(default_factory=list)
    built_at: datetime | None = None
    build_seconds: float = 0.0


class PramaanService:
    def __init__(self, config: Config | None = None) -> None:
        self.config = (config or Config()).apply_profile()
        self.state = ServiceState(config=self.config)
        self._lock = threading.Lock()

    # ------------------------------------------------------------ build ---

    def load_synthetic(self, days: int = 240, seed: int | None = None) -> dict[str, Any]:
        cfg = SynthConfig(days=days, seed=seed or self.config.seed)
        docs, gt = SyntheticCorpus(cfg).generate()
        self._ground_truth = gt
        return self.ingest(docs)

    def ingest(self, docs: list[Document]) -> dict[str, Any]:
        with self._lock:
            t0 = time.perf_counter()
            with timed(log, "stage0", documents=len(docs)):
                stage0 = run_stage0(docs, self.config.stage0)

            corpus = stage0.documents
            texts = [d.full_text for d in corpus]

            with timed(log, "index", documents=len(corpus)):
                embedder = build_embedder(self.config.stage1.embedder,
                                          self.config.stage1.embed_dim)
                if hasattr(embedder, "fit"):
                    embedder.fit(texts)
                cascade = RetrievalCascade(
                    self.config.stage2, embedder,
                    build_reranker(self.config.stage2.reranker),
                ).index(corpus)

            store = DocumentStore.from_documents(stage0.all_documents)
            store.apply_clusters(stage0.dedup.cluster_of, stage0.dedup.canonical)

            self.state.store = store
            self.state.stage0 = stage0
            self.state.cascade = cascade
            self.state.documents = corpus
            self.state.built_at = datetime.now(UTC)
            self.state.build_seconds = time.perf_counter() - t0

        return self.status()

    def fit_lexicon(self, labels: list[int], event_types: list[str]) -> dict[str, Any]:
        if not self.state.documents:
            raise NotReady("ingest a corpus before fitting the lexicon")
        lx = LexicalIndicators().fit(
            [d.full_text for d in self.state.documents], labels, event_types=event_types
        )
        self.state.lexicon = lx
        return {"terms": len(lx.scores), "event_types": sorted(lx.per_event_type)}

    # ------------------------------------------------------------ reads ---

    def status(self) -> dict[str, Any]:
        s = self.state
        return {
            "ready": s.cascade is not None,
            "profile": self.config.hardware_profile,
            "config_fingerprint": self.config.fingerprint(),
            "documents_raw": len(s.stage0.all_documents) if s.stage0 else 0,
            "documents_canonical": len(s.documents),
            "built_at": s.built_at.isoformat() if s.built_at else None,
            "build_seconds": round(s.build_seconds, 2),
            "stage0": s.stage0.summary() if s.stage0 else None,
        }

    def search(self, query: str, *, as_of: datetime | None = None, k: int = 20,
               stop_after: str = "rerank") -> dict[str, Any]:
        if self.state.cascade is None:
            raise NotReady("no corpus indexed")
        evidence, stats = self.state.cascade.retrieve(
            query, as_of=as_of, top_k=k, stop_after=stop_after
        )
        docs = {d.doc_id: d for d in self.state.documents}
        return {
            "query": query,
            "as_of": as_of.isoformat() if as_of else None,
            # Say which rule was actually applied. The served index is built
            # once over the whole corpus, so this path enforces the publication
            # cutoff and nothing else; calling it a backtest would be false.
            "cutoff_rule": "publication_only",
            "measures": (
                "evidence retrieval for the query as written; not a forecast, "
                "not a calibrated score, and not a backtest measurement"
            ),
            "cascade": stats.summary(),
            "results": [
                {
                    "doc_id": e.doc_id,
                    "score": round(e.score, 6),
                    "components": {k2: round(v, 6) for k2, v in e.components.items()},
                    "published_at": e.published_at.isoformat() if e.published_at else None,
                    "source_id": e.source_id,
                    "source_family": docs[e.doc_id].meta.get("source_family", "")
                                     if e.doc_id in docs else "",
                    "title": docs[e.doc_id].title if e.doc_id in docs else "",
                    "span": e.span,
                }
                for e in evidence
            ],
        }

    def document(self, doc_id: str) -> dict[str, Any]:
        for d in self.state.documents:
            if d.doc_id == doc_id:
                return {
                    "doc_id": d.doc_id, "title": d.title, "text": d.text,
                    "source_id": d.source_id,
                    "source_family": d.meta.get("source_family", ""),
                    "published_at": d.published_at.isoformat(),
                    "language": d.language, "cluster_id": d.cluster_id,
                    "is_canonical": d.is_canonical,
                }
        raise KeyError(doc_id)

    def cluster(self, doc_id: str) -> dict[str, Any]:
        """Every document that was collapsed into this one. This is what an
        analyst needs to see before treating a story as corroborated."""
        if self.state.stage0 is None:
            raise NotReady("no corpus ingested")
        rep = self.state.stage0.dedup
        canonical = rep.cluster_of.get(doc_id, doc_id)
        members = rep.cluster_members.get(canonical, [canonical])
        by_id = {d.doc_id: d for d in self.state.stage0.all_documents}
        families = {by_id[m].meta.get("source_family", "")
                    for m in members if m in by_id}
        return {
            "canonical": canonical,
            "members": members,
            "size": len(members),
            "distinct_source_families": len(families),
            "independence": round(len(families) / max(len(members), 1), 4),
        }

    def timeline(self, days: int = 90) -> dict[str, Any]:
        if self.state.store is None:
            raise NotReady("no corpus ingested")
        counts = self.state.store.daily_counts()
        rows = counts.tail(days).to_dicts()
        return {"days": len(rows),
                "series": [{"day": str(r["day"]), "n": int(r["n"])} for r in rows]}
