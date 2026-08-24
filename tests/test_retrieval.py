"""Retrieval regression guard.

The risk table forbids trusting this component without measuring Recall@K, so
the measurement is a test rather than a one-off script. The floors are set below
the values measured on the full corpus, which is the point: they catch a
regression without failing on ordinary run-to-run variation.

Measured on the 420-day corpus (98 held-out queries):
    heuristic ordering   R@10 0.199  nDCG@10 0.177  MRR 0.324
    learned fusion       R@10 0.535  nDCG@10 0.527  MRR 0.751
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from pramaan_x.config import Stage2Config
from pramaan_x.eval.retrieval_bench import build_queries, run_benchmark, stage_width, train_fusion
from pramaan_x.stage0_ingest.pipeline import run_stage0
from pramaan_x.stage1_scan.embed import HashingEmbedder
from pramaan_x.stage1_scan.lexical import LexicalIndicators
from pramaan_x.stage2_retrieve.cascade import RetrievalCascade
from pramaan_x.stage2_retrieve.rerank import LexicalReranker


@pytest.fixture(scope="module")
def bench():
    from pramaan_x.data.synth import SynthConfig, SyntheticCorpus

    docs, gt = SyntheticCorpus(SynthConfig(days=300, n_locations=8)).generate()
    corpus = run_stage0(docs).documents
    split = min(d.published_at for d in corpus) + timedelta(days=200)
    train = [d for d in corpus if d.published_at < split]

    labels, types = [], []
    for d in train:
        key = d.meta.get("synth_target", "none|none")
        _, event_type = key.split("|")
        y = 0
        if event_type != "none":
            for when in gt.events.get(key, []):
                if 0 < (when - d.published_at).days <= 21:
                    y = 1
                    break
        labels.append(y)
        types.append(event_type)

    lexicon = LexicalIndicators().fit([d.full_text for d in train], labels,
                                      event_types=types)
    embedder = HashingEmbedder(1024).fit([d.full_text for d in corpus])
    start = min(d.published_at for d in corpus)
    end = max(d.published_at for d in corpus)
    return {
        "corpus": corpus, "gt": gt, "lexicon": lexicon, "embedder": embedder,
        "train_q": build_queries(gt, lexicon, corpus, window=(start, split)),
        "test_q": build_queries(gt, lexicon, corpus, window=(split, end)),
    }


def test_query_set_is_non_trivial(bench):
    assert len(bench["test_q"]) >= 20
    assert all(q.relevant for q in bench["test_q"])


def test_reranking_improves_precision_at_the_top(bench):
    """The reranker's entire justification. If it does not beat fusion on
    nDCG@10 it is pure cost and should be removed from the cascade."""
    reports = run_benchmark(bench["corpus"], bench["test_q"], bench["embedder"],
                            LexicalReranker(), stages=("fusion", "rerank"))
    assert reports["rerank"].ndcg[10] > reports["fusion"].ndcg[10]
    assert reports["rerank"].mrr > reports["fusion"].mrr


def test_learned_fusion_beats_heuristic_ordering(bench):
    """The brief says not to hand-set the component weights. This is the
    measurement that backs the instruction."""
    heuristic = run_benchmark(bench["corpus"], bench["test_q"], bench["embedder"],
                              LexicalReranker(), stages=("rerank",))["rerank"]
    fusion = train_fusion(bench["corpus"], bench["train_q"], bench["embedder"],
                          LexicalReranker())
    learned = run_benchmark(bench["corpus"], bench["test_q"], bench["embedder"],
                            LexicalReranker(), stages=("rerank",),
                            fusion=fusion)["rerank"]
    assert learned.ndcg[10] > heuristic.ndcg[10] * 1.5
    assert learned.mrr > heuristic.mrr


def test_recall_floor_at_100(bench):
    """Recall@100 is the ceiling on everything downstream: an evidence document
    the cascade never returns cannot be recovered by any later stage."""
    rep = run_benchmark(bench["corpus"], bench["test_q"], bench["embedder"],
                        LexicalReranker(), stages=("rerank",))["rerank"]
    assert rep.recall[100] > 0.60, f"R@100 fell to {rep.recall[100]:.3f}"


def test_sparse_and_dense_contribute_differently(bench):
    """If both retrievers returned the same documents, one of them is dead
    weight. Overlap below 90% is what justifies running the pair."""
    cascade = RetrievalCascade(Stage2Config(), bench["embedder"],
                               LexicalReranker()).index(bench["corpus"])
    overlaps = []
    for q in bench["test_q"][:15]:
        s = {e.doc_id for e in cascade.retrieve(q.text, as_of=q.as_of, top_k=50,
                                                stop_after="sparse")[0]}
        d = {e.doc_id for e in cascade.retrieve(q.text, as_of=q.as_of, top_k=50,
                                                stop_after="dense")[0]}
        if s and d:
            overlaps.append(len(s & d) / len(s | d))
    assert overlaps
    assert sum(overlaps) / len(overlaps) < 0.9


def test_cutoff_is_enforced_in_the_cascade(bench):
    cascade = RetrievalCascade(Stage2Config(), bench["embedder"],
                               LexicalReranker()).index(bench["corpus"])
    published = {d.doc_id: d.published_at for d in bench["corpus"]}
    for q in bench["test_q"][:25]:
        evidence, _ = cascade.retrieve(q.text, as_of=q.as_of, top_k=100)
        assert all(published[e.doc_id] < q.as_of for e in evidence)


def test_stage_widths_bound_reported_recall():
    cfg = Stage2Config()
    assert stage_width(cfg, "late") == cfg.late_top_k
    assert stage_width(cfg, "sparse") == cfg.bm25_top_k
