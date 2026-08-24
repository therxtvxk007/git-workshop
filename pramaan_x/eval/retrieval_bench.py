"""Retrieval benchmark.

Answers one question per cascade stage: what does this stage actually add?

The query set is built from the *learned* lexicon, not from hand-written
queries. A benchmark whose queries were written by the person who built the
retriever measures the author's memory of the corpus, not the retriever.

Relevance labels come from the generator's ground truth: for an event at time T,
the relevant documents are the precursor documents that produced it, restricted
to those published before T. Post-event reports of the same event are *not*
relevant -- they are the leakage trap, and a retriever that ranks them highly
should be penalised, not rewarded.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..config import Stage2Config
from ..data.synth import GroundTruth
from ..stage1_scan.embed import Embedder
from ..stage1_scan.lexical import LexicalIndicators
from ..stage2_retrieve.cascade import RetrievalCascade
from ..stage2_retrieve.rerank import Reranker
from ..types import Document
from .metrics import RetrievalReport, evaluate_retrieval

if TYPE_CHECKING:
    from ..stage2_retrieve.fusion import LearnedFusion

STAGES = ("sparse", "dense", "fusion", "late", "rerank")


@dataclass
class Query:
    text: str
    as_of: datetime
    relevant: set[str]
    target_key: str


def build_queries(
    gt: GroundTruth,
    lexicon: LexicalIndicators,
    docs: Sequence[Document],
    *,
    window: tuple[datetime, datetime],
    n_terms: int = 20,
    min_relevant: int = 1,
) -> list[Query]:
    visible = {d.doc_id for d in docs}
    published = {d.doc_id: d.published_at for d in docs}
    start, end = window
    out: list[Query] = []
    for (key, iso), doc_ids in gt.precursor_docs.items():
        event_time = datetime.fromisoformat(iso)
        if not (start <= event_time < end):
            continue
        location, event_type = key.split("|", 1)
        relevant = {
            d for d in doc_ids
            if d in visible and published.get(d) is not None and published[d] < event_time
        }
        if len(relevant) < min_relevant:
            continue
        terms = lexicon.query_for(event_type, n=n_terms)
        if not terms:
            continue
        out.append(Query(text=f"{location} {terms}", as_of=event_time,
                         relevant=relevant, target_key=key))
    return out


def stage_width(cfg: Stage2Config, stage: str) -> int:
    """How many documents a stop point can return at most.

    Reported alongside the metrics because a recall figure at k above the stage
    width is bounded by the width, not by the retriever -- reading it as a
    quality difference is simply wrong.
    """
    return {"sparse": cfg.bm25_top_k, "dense": cfg.dense_top_k,
            "fusion": cfg.bm25_top_k + cfg.dense_top_k,
            "late": cfg.late_top_k,
            "rerank": cfg.bm25_top_k + cfg.dense_top_k}[stage]


def run_benchmark(
    docs: Sequence[Document],
    queries: Sequence[Query],
    embedder: Embedder,
    reranker: Reranker,
    *,
    cfg: Stage2Config | None = None,
    ks: Sequence[int] = (10, 20, 50, 100),
    stages: Sequence[str] = STAGES,
    top_k: int = 200,
    fusion: Any = None,
) -> dict[str, RetrievalReport]:
    cfg = cfg or Stage2Config()
    cascade = RetrievalCascade(cfg, embedder, reranker, fusion=fusion).index(docs)
    out: dict[str, RetrievalReport] = {}
    for stage in stages:
        runs: list[tuple[list[str], set[str]]] = []
        for q in queries:
            ev, _ = cascade.retrieve(q.text, as_of=q.as_of, top_k=top_k, stop_after=stage)
            runs.append(([e.doc_id for e in ev], q.relevant))
        out[stage] = evaluate_retrieval(runs, ks=ks)
    return out


def train_fusion(
    docs: Sequence[Document],
    queries: Sequence[Query],
    embedder: Embedder,
    reranker: Reranker,
    *,
    cfg: Stage2Config | None = None,
    candidates_per_query: int = 60,
) -> LearnedFusion:
    """Fit LambdaMART on training-window queries.

    Labels are graded, not binary: a relevant document retrieved is grade 3, a
    document from the same target but a different episode is grade 1, everything
    else 0. Binary labels would teach the ranker that a near-miss and a totally
    unrelated document are equally wrong, which is not what an analyst
    experiences.
    """
    from ..stage2_retrieve.fusion import LearnedFusion

    cfg = cfg or Stage2Config()
    cascade = RetrievalCascade(cfg, embedder, reranker).index(docs)
    target_of = {d.doc_id: d.meta.get("synth_target", "") for d in docs}

    features: list[dict[str, float]] = []
    labels: list[int] = []
    groups: list[int] = []
    for q in queries:
        ev, _ = cascade.retrieve(q.text, as_of=q.as_of, top_k=candidates_per_query)
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


def format_table(reports: dict[str, RetrievalReport],
                 ks: Sequence[int] = (10, 20, 50, 100),
                 cfg: Stage2Config | None = None) -> str:
    cfg = cfg or Stage2Config()
    header = f"{'stage':<10}{'width':>7}" + "".join(f"{'R@'+str(k):>9}" for k in ks) + \
             f"{'nDCG@10':>10}{'MRR':>8}"
    lines = [header, "-" * len(header)]
    for stage, rep in reports.items():
        width = stage_width(cfg, stage)
        row = f"{stage:<10}{width:>7}"
        for k in ks:
            v = rep.recall.get(k, float("nan"))
            # Mark figures the stage width caps, so a narrowing stage is not
            # misread as a worse retriever.
            row += (f"{v:>8.3f}*" if k > width else f"{v:>9.3f}")
        row += f"{rep.ndcg.get(10, float('nan')):>10.3f}{rep.mrr:>8.3f}"
        lines.append(row)
    lines.append("* bounded by the stage width, not by retrieval quality")
    return "\n".join(lines)
