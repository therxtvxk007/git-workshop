"""Benchmark orchestration.

One entry point builds the corpus, derives the locked protocol from its span,
fits everything that is allowed to be fitted on the training window only, runs
one of the two methods, checks the invariants and writes the artefact.

The two methods differ in exactly one respect and it is stated here rather than
buried: what an index at a forecast origin is permitted to see. Everything else
-- corpus, seed, protocol windows, lexicon, query text, graded labels, stop
points -- is held identical, so the difference between the two sets of numbers
is attributable to the contamination and to nothing else.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..config import Config
from ..data.store import DocumentStore
from ..data.synth import GroundTruth, SynthConfig, SyntheticCorpus
from ..data.versioning import hash_frame
from ..stage0_ingest.pipeline import run_stage0
from ..stage1_scan.embed import build_embedder
from ..stage1_scan.lexical import LexicalIndicators
from ..stage2_retrieve.rerank import build_reranker
from ..types import Document
from . import invariants as inv
from .artefact import (
    BENCHMARK_RESULTS_DIR,
    BackendIdentity,
    DatasetIdentity,
    build_artefact,
    write_artefact,
)
from .availability import to_utc
from .oracle_target_retrieval import (
    LEGACY,
    STRICT,
    FullCorpusIndexProvider,
    OracleTargetQuery,
    RunOutcome,
    SnapshotIndexProvider,
    build_oracle_target_queries,
    run_oracle_target_retrieval,
    train_fusion,
)
from .protocol import TemporalProtocol


@dataclass(frozen=True)
class LexiconFitRecord:
    """What the learned lexicon -- the only fitted preprocessing step whose
    output reaches every query -- was permitted to see."""

    n_documents: int
    n_positive: int
    max_published_at: str | None
    max_event_used: str | None
    label_cutoff: str
    train_end: str


@dataclass
class Prepared:
    """Everything the two methods share, built once per seed."""

    corpus: list[Document]
    all_documents: list[Document]
    ground_truth: GroundTruth
    protocol: TemporalProtocol
    lexicon: LexicalIndicators
    dataset: DatasetIdentity
    seed: int
    synth: SynthConfig
    lexicon_fit: LexiconFitRecord | None = None
    stage0_summary: dict[str, Any] = field(default_factory=dict)


def prepare(
    cfg: Config,
    *,
    days: int,
    seed: int,
    n_locations: int = 12,
    n_event_types: int = 6,
    embargo_days: int = 7,
    label_lookahead_days: int = 21,
    origin_stride_days: int = 7,
    train_frac: float = 0.55,
    calibration_frac: float = 0.15,
    artefact_dir: str | Path | None = None,
) -> Prepared:
    """Corpus, protocol and the training-window lexicon.

    The lexicon is the only fitted object shared by both methods, and it is
    fitted on training-window documents with labels whose forward lookahead
    stays inside the training window. That is why the protocol carries
    `label_cutoff`: a document within `label_lookahead_days` of the training
    window's end cannot be labelled without reading past it.
    """
    synth = SynthConfig(days=days, seed=seed, n_locations=n_locations, n_event_types=n_event_types)
    docs, gt = SyntheticCorpus(synth).generate()
    stage0 = run_stage0(docs, cfg.stage0)
    corpus = stage0.documents

    start = min(to_utc(d.published_at) for d in corpus)
    end = max(to_utc(d.published_at) for d in corpus) + timedelta(seconds=1)
    protocol = TemporalProtocol.from_span(
        start,
        end,
        train_frac=train_frac,
        calibration_frac=calibration_frac,
        embargo_days=embargo_days,
        label_lookahead_days=label_lookahead_days,
        origin_stride_days=origin_stride_days,
        notes=("synthetic corpus; no real-world validity is claimed",),
    )

    lexicon, lexicon_fit = _fit_training_lexicon(corpus, gt, protocol)

    store = DocumentStore.from_documents(stage0.all_documents)
    store.apply_clusters(stage0.dedup.cluster_of, stage0.dedup.canonical)
    dataset = _identify(store, synth, artefact_dir)

    return Prepared(
        corpus=corpus,
        all_documents=stage0.all_documents,
        ground_truth=gt,
        protocol=protocol,
        lexicon=lexicon,
        dataset=dataset,
        seed=seed,
        synth=synth,
        lexicon_fit=lexicon_fit,
        stage0_summary=stage0.summary(),
    )


def _fit_training_lexicon(
    corpus: Sequence[Document], gt: GroundTruth, protocol: TemporalProtocol
) -> tuple[LexicalIndicators, LexiconFitRecord]:
    """Fit the lexicon and record exactly what it was allowed to see.

    The record is the evidence for the "no test label reaches preprocessing"
    invariant. The lexicon is preprocessing -- it decides the query text -- so
    a label from beyond the training window leaking into it would contaminate
    every query in the benchmark, including the test ones.
    """
    cutoff = protocol.label_cutoff
    train_end = protocol.train_end
    texts: list[str] = []
    labels: list[int] = []
    types: list[str] = []
    max_published: datetime | None = None
    max_event: datetime | None = None
    for d in corpus:
        pub = to_utc(d.published_at)
        if not (protocol.train_start <= pub < cutoff):
            continue
        key = d.meta.get("synth_target", "none|none")
        _, event_type = key.split("|", 1)
        y = 0
        if event_type != "none":
            for when in gt.events.get(key, []):
                when = to_utc(when)
                # The lookahead must not cross the training window: a label
                # that depends on an event after `train_end` is a test label.
                if when >= train_end:
                    continue
                if 0 < (when - pub).days <= protocol.label_lookahead_days:
                    y = 1
                    max_event = when if max_event is None else max(max_event, when)
                    break
        texts.append(d.full_text)
        labels.append(y)
        types.append(event_type)
        max_published = pub if max_published is None else max(max_published, pub)
    record = LexiconFitRecord(
        n_documents=len(texts),
        n_positive=sum(labels),
        max_published_at=max_published.isoformat() if max_published else None,
        max_event_used=max_event.isoformat() if max_event else None,
        label_cutoff=cutoff.isoformat(),
        train_end=train_end.isoformat(),
    )
    return LexicalIndicators().fit(texts, labels, event_types=types), record


def _identify(
    store: DocumentStore, synth: SynthConfig, artefact_dir: str | Path | None
) -> DatasetIdentity:
    """Both dataset hashes. The parquet is written only to be hashed; it is a
    build product, not a tracked artefact, so it goes to a temp directory
    unless the caller asks for somewhere durable."""
    generator = {
        "generator": "pramaan_x.data.synth.SyntheticCorpus",
        "seed": synth.seed,
        "days": synth.days,
        "n_locations": synth.n_locations,
        "n_event_types": synth.n_event_types,
        "backfill_fraction": synth.backfill_fraction,
        "missing_retrieval_fraction": synth.missing_retrieval_fraction,
        "synthetic": True,
    }
    if artefact_dir is not None:
        path = Path(artefact_dir) / f"corpus-seed{synth.seed}-{synth.days}d.parquet"
        store.write(path)
        return DatasetIdentity.from_frame(
            "synthetic_corpus", store.frame, generator=generator, parquet_path=path
        )
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "corpus.parquet"
        store.write(path)
        return DatasetIdentity.from_frame(
            "synthetic_corpus", store.frame, generator=generator, parquet_path=path
        )


# ----------------------------------------------------------------- methods ---


@dataclass
class MethodResult:
    method: str
    outcome: RunOutcome
    payload: dict[str, Any]
    path: Path | None
    train_queries: list[OracleTargetQuery]
    test_queries: list[OracleTargetQuery]
    fusion_weights: dict[str, float] = field(default_factory=dict)


def run_method(
    prep: Prepared,
    cfg: Config,
    method: str,
    *,
    stages: Sequence[str] = ("sparse", "dense", "fusion", "late", "rerank"),
    ks: Sequence[int] = (10, 20, 50, 100),
    top_k: int = 200,
    use_fusion: bool = True,
    results_dir: str | Path = BENCHMARK_RESULTS_DIR,
    write: bool = True,
) -> MethodResult:
    """Run one method end to end and return its artefact."""
    if method not in (STRICT, LEGACY):
        raise ValueError(f"unknown method {method!r}; expected {STRICT!r} or {LEGACY!r}")
    protocol, corpus, gt = prep.protocol, prep.corpus, prep.ground_truth

    train_q = build_oracle_target_queries(
        gt, prep.lexicon, corpus, protocol, "train", method=method
    )
    test_q = build_oracle_target_queries(gt, prep.lexicon, corpus, protocol, "test", method=method)

    def embedder_factory():
        return build_embedder(cfg.stage1.embedder, cfg.stage1.embed_dim)

    def reranker_factory():
        return build_reranker(cfg.stage2.reranker)

    fusion = None
    fusion_weights: dict[str, float] = {}
    trainer = None
    if method == STRICT:
        if use_fusion and train_q:
            trainer = SnapshotIndexProvider(corpus, cfg.stage2, embedder_factory, reranker_factory)
            fusion = train_fusion(train_q, trainer, corpus)
            fusion_weights = fusion.weights()
        provider = SnapshotIndexProvider(
            corpus, cfg.stage2, embedder_factory, reranker_factory, fusion=fusion
        )
        fitted_documents = corpus
    else:
        # The legacy method, reproduced: one embedder fitted on every document
        # in the corpus, one BM25 index over every document in the corpus, and
        # availability decided by publication date alone.
        legacy_embedder = embedder_factory()
        if hasattr(legacy_embedder, "fit"):
            legacy_embedder.fit([d.full_text for d in corpus])
        if use_fusion and train_q:
            trainer = FullCorpusIndexProvider(
                corpus, cfg.stage2, legacy_embedder, reranker_factory()
            )
            fusion = train_fusion(train_q, trainer, corpus)
            fusion_weights = fusion.weights()
        provider = FullCorpusIndexProvider(
            corpus, cfg.stage2, legacy_embedder, reranker_factory(), fusion=fusion
        )
        fitted_documents = corpus

    outcome = run_oracle_target_retrieval(
        corpus, test_q, provider, cfg=cfg.stage2, ks=ks, stages=stages, top_k=top_k
    )
    if trainer is not None:
        # The ranker's own training indexes are fitted objects too, and the
        # "no future document fitted" invariant has to cover them: a leak
        # while learning the weights is a leak.
        outcome.fit_records = [*trainer.fit_records, *outcome.fit_records]
        outcome.n_index_builds += trainer.n_builds

    verdicts = inv.report_all(outcome, protocol, train_q, test_q, fitted_documents)
    verdicts["no_test_labels_in_preprocessing"] = _lexicon_verdict(prep)
    if method == STRICT:
        # The strict path is a result, not a diagnostic: a firewall breach
        # there invalidates the numbers, so it must not be reportable-and-
        # ignored.
        inv.check_all(outcome, protocol, train_q, test_q, fitted_documents)

    payload = build_artefact(
        method=method,
        protocol=protocol,
        dataset=prep.dataset,
        backends=BackendIdentity(
            embedder=f"{cfg.stage1.embedder} ({cfg.stage1.embed_dim}d)",
            reranker=cfg.stage2.reranker,
            vector_engine=cfg.stage2.engine,
            fusion_backend=(fusion.backend if fusion is not None else "none (heuristic ordering)"),
        ),
        config_fingerprint=cfg.fingerprint(),
        seed=prep.seed,
        reports=outcome.reports,
        availability_violations=outcome.availability_violations,
        n_train_queries=len(train_q),
        n_test_queries=len(test_q),
        n_index_builds=outcome.n_index_builds,
        invariants=verdicts,
        extra={
            "stage0": prep.stage0_summary,
            "lexicon_fit": asdict(prep.lexicon_fit) if prep.lexicon_fit else None,
            "fusion_component_weights": fusion_weights,
            "corpus_logical_hash_recheck": hash_frame(
                DocumentStore.from_documents(prep.corpus).frame
            ),
            "fitted_corpus_sizes": _fit_summary(outcome.fit_records),
            "index_scope": (
                "documents available strictly before each forecast origin"
                if method == STRICT
                else "every document in the corpus, including documents from after "
                "every forecast origin"
            ),
        },
    )
    path = write_artefact(payload, results_dir) if write else None
    if path is not None:
        payload["_path"] = str(path)
    return MethodResult(
        method=method,
        outcome=outcome,
        payload=payload,
        path=path,
        train_queries=train_q,
        test_queries=test_q,
        fusion_weights=fusion_weights,
    )


def _lexicon_verdict(prep: Prepared) -> str:
    """Verdict string for the preprocessing half of the label-leakage rule.

    Both arms share this lexicon, so both are expected to pass this particular
    check -- the legacy method's contamination is in its indexes, not here.
    Reporting it anyway keeps the artefact self-contained: a reader should not
    have to know which checks were run to know that this one was.
    """
    rec = prep.lexicon_fit
    if rec is None:
        return "FAIL: no lexicon fitting record was produced"
    try:
        inv.assert_lexicon_fitted_on_training_only(rec, prep.protocol)
    except inv.InvariantViolation as exc:
        return f"FAIL: {exc}"[:400]
    return "pass"


def _fit_summary(records) -> dict[str, Any]:
    """How large the fitted corpora actually were.

    This is the number that explains most of the gap between the two methods.
    The legacy index is the whole corpus at every origin; a snapshot index is
    the prefix available at its own origin, which early in the test window is a
    fraction of that. Fewer documents means fewer distractors competing for the
    top-k slots, so contamination does not reliably *inflate* a retrieval
    metric -- it makes the metric mean something else. Recording the sizes lets
    a reader check that reading instead of taking it on trust.
    """
    sizes = [r.n_documents for r in records]
    if not sizes:
        return {}
    return {
        "n_fitted_indexes": len(sizes),
        "min": min(sizes),
        "max": max(sizes),
        "mean": sum(sizes) / len(sizes),
        "distinct": len(set(sizes)),
    }
