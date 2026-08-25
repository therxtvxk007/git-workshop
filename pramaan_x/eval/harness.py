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

import hashlib
import json
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
from ..timestamps import require_strict
from ..types import Document
from . import invariants as inv
from .artefact import (
    BENCHMARK_RESULTS_DIR,
    BackendIdentity,
    DatasetIdentity,
    backend_versions,
    build_artefact,
    write_artefact,
)
from .availability import to_utc
from .oracle_target_retrieval import (
    ALL_METHODS,
    CONTROLLED_METHODS,
    HISTORICAL,
    HISTORICAL_FACTORS_CHANGED,
    STRICT,
    FullCorpusIndexProvider,
    OracleTargetQuery,
    RunOutcome,
    SnapshotIndexProvider,
    build_historical_legacy_queries,
    build_oracle_target_queries,
    paired_delta,
    query_set_fingerprint,
    run_oracle_target_retrieval,
    train_fusion,
)
from .protocol import TemporalProtocol
from .selection import (
    CANDIDATE_GRID,
    SelectionError,
    evaluator,
    measure_regression_floor,
    select_operating_point,
)


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
    label_mapping: dict[str, Any] = field(default_factory=dict)


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
    # The benchmark ingestion path is a reported path, so it takes the strict
    # timestamp policy or it takes nothing. Without this the `assume_utc`
    # escape hatch would silently be reachable from `strict_temporal`.
    require_strict(cfg.stage0.timestamp_policy, "the oracle_target_retrieval benchmark")
    synth = SynthConfig(days=days, seed=seed, n_locations=n_locations, n_event_types=n_event_types)
    docs, gt = SyntheticCorpus(synth).generate()
    stage0 = run_stage0(docs, cfg.stage0)
    corpus = stage0.documents
    gt, mapping = _map_ground_truth_through_clusters(gt, stage0)

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
        label_mapping=mapping,
    )


def _map_ground_truth_through_clusters(
    gt: GroundTruth, stage0
) -> tuple[GroundTruth, dict[str, Any]]:
    """Rewrite ground-truth precursor ids to the canonical they were merged into.

    Two failures this prevents, both silent.

    A precursor document that deduplication absorbed into some other cluster no
    longer appears in the canonical stream, so an unmapped relevant set simply
    loses it: recall is computed against a document the retriever was never
    given the chance to return.

    In the other direction, a story that appears as several syndicated copies
    must count once. Mapping every member to its canonical and then taking the
    set does both at once -- and the counts are recorded so the effect is
    visible in the artefact rather than inferred.
    """
    cluster_of = stage0.dedup.cluster_of
    canonical = {d.doc_id for d in stage0.documents}
    mapped: dict[tuple[str, str], list[str]] = {}
    n_before = n_after = n_remapped = n_collapsed = n_dropped = 0
    for key, ids in gt.precursor_docs.items():
        n_before += len(ids)
        resolved: list[str] = []
        for doc_id in ids:
            target = cluster_of.get(doc_id, doc_id)
            if target not in canonical:
                n_dropped += 1
                continue
            if target != doc_id:
                n_remapped += 1
            resolved.append(target)
        unique = sorted(dict.fromkeys(resolved))
        n_collapsed += len(resolved) - len(unique)
        n_after += len(unique)
        if unique:
            mapped[key] = unique
    gt.precursor_docs = mapped
    return gt, {
        "precursor_ids_before": n_before,
        "precursor_ids_after": n_after,
        "remapped_to_cluster_canonical": n_remapped,
        "collapsed_duplicate_members": n_collapsed,
        "dropped_no_canonical": n_dropped,
        "note": (
            "Ground-truth precursor ids are mapped through the dedup clusters "
            "before any query is built: a document absorbed into a cluster is "
            "counted as its canonical rather than lost, and syndicated copies "
            "of one story count once rather than as independent precursors."
        ),
    }


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
    reference: MethodResult | None = None,
    select: bool = True,
    require_clean_source: bool = True,
) -> MethodResult:
    """Run one method end to end and return its artefact.

    `reference` is the strict run to pair against. Supplying it for
    `future_fitted_index_ablation` produces the per-query delta table; it is
    refused for the historical reproduction, whose query set is different by
    construction.
    """
    if method not in ALL_METHODS:
        raise ValueError(f"unknown method {method!r}; expected one of {list(ALL_METHODS)}")
    protocol, corpus, gt = prep.protocol, prep.corpus, prep.ground_truth

    if method == HISTORICAL:
        if reference is not None:
            raise ValueError(
                f"{HISTORICAL} cannot be paired against anything: it changes "
                f"{', '.join(HISTORICAL_FACTORS_CHANGED)} at once and builds a "
                "different query set, so a delta against it has no referent"
            )
        build = build_historical_legacy_queries
    else:
        # Both controlled arms take the *same* canonical query set. This is the
        # whole reason the ablation is interpretable.
        build = build_oracle_target_queries
    train_q = build(gt, prep.lexicon, corpus, protocol, "train")
    test_q = build(gt, prep.lexicon, corpus, protocol, "test")

    def embedder_factory():
        return build_embedder(cfg.stage1.embedder, cfg.stage1.embed_dim)

    def reranker_factory():
        return build_reranker(cfg.stage2.reranker)

    fusion = None
    fusion_weights: dict[str, float] = {}
    fusion_fingerprint = ""
    trainer = None

    if method in CONTROLLED_METHODS:
        # The ranker is trained the same way for both controlled arms: on the
        # canonical training queries, from snapshot indexes. Training it on the
        # ablation's contaminated index would make the ranker a second
        # difference between the arms, and the comparison would stop being an
        # ablation of one variable.
        if use_fusion and train_q:
            trainer = SnapshotIndexProvider(
                corpus,
                cfg.stage2,
                embedder_factory,
                reranker_factory,
                phase="ranker_training",
            )
            fusion, fusion_fingerprint = train_fusion(train_q, trainer, corpus)
            fusion_weights = fusion.weights()
        if method == STRICT:
            provider = SnapshotIndexProvider(
                corpus, cfg.stage2, embedder_factory, reranker_factory, fusion=fusion
            )
        else:
            full_embedder = embedder_factory()
            if hasattr(full_embedder, "fit"):
                full_embedder.fit([d.full_text for d in corpus])
            provider = FullCorpusIndexProvider(
                corpus,
                cfg.stage2,
                full_embedder,
                reranker_factory(),
                fusion=fusion,
                enforce_availability=True,
            )
    else:
        # The historical reproduction, exactly as it was: one embedder fitted on
        # every document, one index over every document, and the ranker trained
        # on that same contaminated index.
        legacy_embedder = embedder_factory()
        if hasattr(legacy_embedder, "fit"):
            legacy_embedder.fit([d.full_text for d in corpus])
        if use_fusion and train_q:
            trainer = FullCorpusIndexProvider(
                corpus,
                cfg.stage2,
                legacy_embedder,
                reranker_factory(),
                phase="ranker_training",
            )
            fusion, fusion_fingerprint = train_fusion(train_q, trainer, corpus)
            fusion_weights = fusion.weights()
        provider = FullCorpusIndexProvider(
            corpus, cfg.stage2, legacy_embedder, reranker_factory(), fusion=fusion
        )
    fitted_documents = corpus

    # -- operating point, chosen on the selection window --------------------
    # Everything above is fitted; this is chosen. The two must not touch the
    # same data, and neither may touch the test window.
    stage2 = cfg.stage2
    selection_record: dict[str, Any] | None = None
    floors: dict[str, Any] | None = None
    if select:
        selection_record, floors, stage2 = _choose_operating_point(
            prep, cfg, corpus, embedder_factory, reranker_factory, fusion, ks, top_k
        )

    outcome = run_oracle_target_retrieval(
        corpus, test_q, provider, cfg=stage2, ks=ks, stages=stages, top_k=top_k
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
            versions=backend_versions(),
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
            "timestamp_policy": str(cfg.stage0.timestamp_policy),
            "stage0": prep.stage0_summary,
            "lexicon_fit": asdict(prep.lexicon_fit) if prep.lexicon_fit else None,
            "label_mapping": prep.label_mapping,
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
            "selection": selection_record,
            "regression_floors": floors,
            "operating_point": {k: getattr(stage2, k) for k in CANDIDATE_GRID},
            **_comparability(method, train_q, test_q, ks, cfg, fusion_fingerprint, prep),
            **_paired(method, reference, outcome, stages),
        },
    )
    path = (
        write_artefact(payload, results_dir, require_clean_source=require_clean_source)
        if write
        else None
    )
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

    def summarise(rows):
        sizes = [r.n_documents for r in rows]
        if not sizes:
            return {}
        return {
            "n_fitted_indexes": len(sizes),
            "min": min(sizes),
            "max": max(sizes),
            "mean": sum(sizes) / len(sizes),
            "distinct": len(set(sizes)),
        }

    out = summarise(records)
    if not out:
        return {}
    # Split by phase as well as overall: both controlled arms train the ranker
    # from snapshot indexes, so an unsplit summary makes the ablation look
    # partially uncontaminated when only its evaluation index is at issue.
    out["by_phase"] = {
        phase: summarise([r for r in records if r.phase == phase])
        for phase in sorted({r.phase for r in records})
    }
    return out


def _choose_operating_point(
    prep, cfg, corpus, embedder_factory, reranker_factory, fusion, ks, top_k
):
    """Select widths on the selection window, then measure CI floors on the
    regression window. Neither touches the locked test window."""
    protocol = prep.protocol
    selection_q = build_oracle_target_queries(
        prep.ground_truth, prep.lexicon, corpus, protocol, "selection"
    )
    regression_q = build_oracle_target_queries(
        prep.ground_truth, prep.lexicon, corpus, protocol, "regression"
    )
    if not selection_q or not regression_q:
        # Refusing is the honest outcome. Falling back to the test window is
        # exactly the failure this machinery exists to prevent, and falling
        # back to hand-set values silently would restore the old state.
        raise SelectionError(
            f"the selection window produced {len(selection_q)} queries and the "
            f"regression window {len(regression_q)}; both must be non-empty. "
            "Lengthen the corpus rather than selecting on the test window."
        )

    evaluate = evaluator(
        corpus,
        lambda: SnapshotIndexProvider(
            corpus,
            cfg.stage2,
            embedder_factory,
            reranker_factory,
            fusion=fusion,
            phase="selection",
        ),
        ks=ks,
        top_k=top_k,
    )
    result = select_operating_point(protocol, selection_q, evaluate, base=cfg.stage2)
    chosen = result.apply(cfg.stage2)
    floors = measure_regression_floor(protocol, regression_q, evaluate, cfg=chosen)
    return result.to_dict(), floors, chosen


def _comparability(
    method: str,
    train_q: Sequence[OracleTargetQuery],
    test_q: Sequence[OracleTargetQuery],
    ks: Sequence[int],
    cfg: Config,
    fusion_fingerprint: str,
    prep: Prepared,
) -> dict[str, Any]:
    """What this arm holds fixed, and what (if anything) it varies.

    For the controlled pair this is the evidence that they are comparable: two
    artefacts can be checked against each other without re-running anything.
    For the historical reproduction it is the record of why they cannot.
    """
    widths = {
        "bm25_top_k": cfg.stage2.bm25_top_k,
        "dense_top_k": cfg.stage2.dense_top_k,
        "late_top_k": cfg.stage2.late_top_k,
        "rerank_top_k": cfg.stage2.rerank_top_k,
        "rrf_k": cfg.stage2.rrf_k,
    }
    if method in CONTROLLED_METHODS:
        return {
            "controlled": {
                "pair": list(CONTROLLED_METHODS),
                "varies": "index_scope",
                "held_fixed": [
                    "query_ids",
                    "query_text",
                    "forecast_origins",
                    "relevant_sets",
                    "lexicon",
                    "fusion_training_data",
                    "ks",
                    "candidate_widths",
                ],
                "query_set_fingerprint": query_set_fingerprint(test_q),
                "train_query_set_fingerprint": query_set_fingerprint(train_q),
                "lexicon_fingerprint": _lexicon_fingerprint(prep),
                "fusion_training_fingerprint": fusion_fingerprint,
                "ks": list(ks),
                "candidate_widths": widths,
            }
        }
    return {
        "comparability": {
            "paired": False,
            "factors_changed": list(HISTORICAL_FACTORS_CHANGED),
            "note": (
                "This arm changes several factors at once and evaluates a "
                "different query set, so no delta is computed against it and "
                "none should be. Use future_fitted_index_ablation for a "
                "controlled comparison against strict_temporal."
            ),
            "query_set_fingerprint": query_set_fingerprint(test_q),
            "ks": list(ks),
            "candidate_widths": widths,
        }
    }


def _lexicon_fingerprint(prep: Prepared) -> str:
    """Digest of the fitted lexicon's per-event-type query terms.

    The lexicon decides every query's text, so "both arms used the same
    lexicon" has to be checkable rather than asserted.
    """
    table = {et: prep.lexicon.query_for(et, n=40) for et in sorted(prep.lexicon.per_event_type)}
    blob = json.dumps(table, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _paired(
    method: str,
    reference: MethodResult | None,
    outcome: RunOutcome,
    stages: Sequence[str],
) -> dict[str, Any]:
    """The paired per-query delta against the strict arm, when one is offered."""
    if reference is None:
        return {}
    if method not in CONTROLLED_METHODS or reference.method != STRICT:
        raise ValueError(
            f"a paired delta may only be computed between {list(CONTROLLED_METHODS)} "
            f"with {STRICT!r} as the reference; got method={method!r}, "
            f"reference={reference.method!r}"
        )
    stage = stages[-1]
    delta = paired_delta(reference.outcome.per_query[stage], outcome.per_query[stage])
    return {
        "paired_vs_strict": {
            "reference_method": reference.method,
            "stage": stage,
            **delta,
        }
    }
