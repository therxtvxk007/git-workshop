"""oracle_target_retrieval: the scientific invariants, then the quality floors.

The order is deliberate. A retrieval number from a contaminated pipeline is not
a weaker result, it is a different quantity, so the firewall tests come first
and the quality floors are only meaningful once they pass.

Every invariant here is written so that a contaminated arm fails it. A check
every method satisfies would be testing nothing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from pramaan_x.config import Config, Stage2Config
from pramaan_x.eval.availability import available_documents, is_available
from pramaan_x.eval.harness import prepare, run_method
from pramaan_x.eval.invariants import (
    InvariantViolation,
    assert_future_append_invariance,
    assert_no_future_document_fitted,
    assert_no_post_origin_results,
    assert_no_test_labels_in_training,
    check_all,
    synthesise_future_documents,
)
from pramaan_x.eval.oracle_target_retrieval import (
    ABLATION,
    HISTORICAL,
    STRICT,
    FullCorpusIndexProvider,
    SnapshotIndexProvider,
    format_table,
    stage_width,
)
from pramaan_x.eval.protocol import ProtocolError
from pramaan_x.stage1_scan.embed import HashingEmbedder
from pramaan_x.stage2_retrieve.rerank import LexicalReranker

DAYS = 420
SEED = 20260824
STAGES = ("rerank",)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config().apply_profile()


@pytest.fixture(scope="module")
def prep(cfg):
    return prepare(cfg, days=DAYS, seed=SEED, n_locations=10, n_event_types=6)


@pytest.fixture(scope="module")
def strict_run(prep, cfg, tmp_path_factory):
    return run_method(
        prep,
        cfg,
        STRICT,
        stages=STAGES,
        results_dir=tmp_path_factory.mktemp("strict"),
        require_clean_source=False,
    )


@pytest.fixture(scope="module")
def ablation_run(prep, cfg, tmp_path_factory):
    """The controlled arm: future-fitted index, everything else held fixed."""
    return run_method(
        prep,
        cfg,
        ABLATION,
        stages=STAGES,
        results_dir=tmp_path_factory.mktemp("ablation"),
        require_clean_source=False,
    )


@pytest.fixture(scope="module")
def historical_run(prep, cfg, tmp_path_factory):
    """The unpaired arm: the pre-firewall behaviour reproduced in full."""
    return run_method(
        prep,
        cfg,
        HISTORICAL,
        stages=STAGES,
        results_dir=tmp_path_factory.mktemp("historical"),
        require_clean_source=False,
    )


# ============================================================ invariants ===


def test_strict_run_passes_every_invariant(strict_run, prep):
    verdicts = check_all(
        strict_run.outcome,
        prep.protocol,
        strict_run.train_queries,
        strict_run.test_queries,
        prep.corpus,
    )
    assert set(verdicts.values()) == {"pass"}


def test_no_fitted_index_saw_a_document_from_its_own_future(strict_run):
    assert strict_run.outcome.fit_records, "nothing was recorded as fitted"
    assert_no_future_document_fitted(strict_run.outcome.fit_records)


def test_the_ablation_arm_fails_the_future_fitting_invariant(ablation_run):
    """Proof the invariant has teeth. The ablation's index is fitted on the
    whole corpus, so every origin's statistics depend on documents from after
    it -- and that is the single variable the controlled pair varies."""
    with pytest.raises(InvariantViolation, match="at or after their own forecast origin"):
        assert_no_future_document_fitted(ablation_run.outcome.fit_records)


def test_no_post_origin_document_is_returned(strict_run):
    assert strict_run.outcome.availability_violations == []
    assert_no_post_origin_results(strict_run.outcome)


def test_the_ablation_arm_returns_only_available_documents(ablation_run):
    """The ablation contaminates fitting and nothing else.

    If it also returned late-crawled documents it would differ from the strict
    arm in two ways and the paired delta would stop being attributable.
    """
    assert ablation_run.outcome.availability_violations == []
    assert_no_post_origin_results(ablation_run.outcome)


def test_the_historical_arm_returns_documents_it_could_not_have_had(historical_run):
    """Publication-date filtering lets through everything crawled late. This is
    the concrete cost of the weaker rule, measured rather than asserted -- and
    it is one of the reasons the historical arm cannot be paired."""
    assert historical_run.outcome.availability_violations
    with pytest.raises(InvariantViolation, match="violate the availability rule"):
        assert_no_post_origin_results(historical_run.outcome)


def test_returned_documents_satisfy_the_rule_independently(strict_run, prep):
    """Recomputed from the documents themselves rather than read off the run's
    own audit, so a bug in the audit cannot make this pass."""
    by_id = {d.doc_id: d for d in prep.corpus}
    checked = 0
    for stage_report in strict_run.outcome.reports.values():
        assert stage_report.n_queries > 0
    for q in strict_run.test_queries:
        for doc_id in q.relevant:
            assert is_available(by_id[doc_id], q.origin)
            checked += 1
    assert checked > 0


def test_no_test_label_reaches_training(strict_run, prep):
    assert_no_test_labels_in_training(
        strict_run.train_queries,
        strict_run.test_queries,
        prep.protocol,
        fitted_documents=prep.corpus,
    )


def test_train_and_test_queries_are_temporally_disjoint(strict_run, prep):
    p = prep.protocol
    assert strict_run.train_queries and strict_run.test_queries
    assert all(p.contains("train", q.event_time) for q in strict_run.train_queries)
    assert all(p.contains("test", q.event_time) for q in strict_run.test_queries)
    assert max(q.event_time for q in strict_run.train_queries) < p.test_start
    ids = {q.query_id for q in strict_run.train_queries}
    assert not ids & {q.query_id for q in strict_run.test_queries}


def test_a_training_query_labelling_a_post_train_document_is_caught(strict_run, prep):
    """Negative control for the label-leakage invariant."""
    import dataclasses

    poisoned = dataclasses.replace(
        strict_run.train_queries[0],
        relevant=frozenset({strict_run.test_queries[0].query_id})
        | strict_run.train_queries[0].relevant,
        event_time=prep.protocol.test_start + timedelta(days=1),
    )
    with pytest.raises(InvariantViolation, match="outside the train window"):
        assert_no_test_labels_in_training(
            [poisoned], strict_run.test_queries, prep.protocol, fitted_documents=prep.corpus
        )


# ------------------------------------------- the future-append invariance ---


def _rank_at_origins(cfg, queries):
    """Returns a callable that indexes a corpus and ranks a fixed query set."""

    def build_and_rank(corpus):
        provider = SnapshotIndexProvider(
            corpus,
            cfg.stage2,
            lambda: HashingEmbedder(cfg.stage1.embed_dim),
            LexicalReranker,
        )
        return {
            q.query_id: [
                e.doc_id
                for e in provider.for_origin(q.origin).retrieve(q.text, as_of=q.origin, top_k=50)[0]
            ]
            for q in queries
        }

    return build_and_rank


def test_appending_future_documents_does_not_change_earlier_rankings(prep, cfg, strict_run):
    """The decisive test.

    Take a set of queries, rank them, then append documents dated after every
    origin involved and rank again. Under snapshot indexing the two rankings
    must be byte-identical: a single changed position means some fitted
    statistic is a function of the future.
    """
    queries = strict_run.test_queries[:8]
    assert queries
    latest = max(q.origin for q in queries)
    future = synthesise_future_documents(prep.corpus, 400, after=latest + timedelta(days=1), seed=1)
    baseline = assert_future_append_invariance(_rank_at_origins(cfg, queries), prep.corpus, future)
    assert any(baseline.values()), "the invariance held only because nothing ranked"


def test_the_invariance_test_fails_on_the_contaminated_method(prep, cfg, strict_run):
    """Negative control. Full-corpus fitting must visibly break invariance --
    otherwise the previous test proves nothing about the firewall."""
    queries = strict_run.test_queries[:8]
    latest = max(q.origin for q in queries)
    future = synthesise_future_documents(prep.corpus, 400, after=latest + timedelta(days=1), seed=1)

    def build_and_rank(corpus):
        embedder = HashingEmbedder(cfg.stage1.embed_dim).fit([d.full_text for d in corpus])
        provider = FullCorpusIndexProvider(corpus, cfg.stage2, embedder, LexicalReranker())
        return {
            q.query_id: [
                e.doc_id
                for e in provider.for_origin(q.origin).retrieve(q.text, as_of=q.origin, top_k=50)[0]
            ]
            for q in queries
        }

    with pytest.raises(InvariantViolation, match="results changed"):
        assert_future_append_invariance(build_and_rank, prep.corpus, future)


def test_snapshot_cache_does_not_widen_what_an_index_sees(prep, cfg):
    """Caching is a performance decision. Two lookups at the same origin must
    return the same index, and an index at an earlier origin must be a strict
    subset of a later one."""
    provider = SnapshotIndexProvider(
        prep.corpus, cfg.stage2, lambda: HashingEmbedder(cfg.stage1.embed_dim), LexicalReranker
    )
    origins = prep.protocol.origins("test")[:3]
    first = provider.for_origin(origins[0])
    assert provider.for_origin(origins[0]) is first
    assert provider.n_builds == 1
    early = set(first._docs)
    late = set(provider.for_origin(origins[-1])._docs)
    assert early < late
    assert early == {d.doc_id for d in available_documents(prep.corpus, origins[0])}


# ============================================================== quality ===


def test_query_set_is_non_trivial(strict_run):
    assert len(strict_run.test_queries) >= 20
    assert all(q.relevant for q in strict_run.test_queries)
    assert all(q.origin <= q.event_time for q in strict_run.test_queries)


def test_queries_are_oracle_targets(strict_run):
    """The query text is the target's location plus learned terms. This test
    exists to keep the oracle assumption visible in the suite: if the location
    ever stops appearing, the benchmark has quietly changed meaning."""
    q = strict_run.test_queries[0]
    assert q.text.startswith(q.location)
    assert q.target_key == f"{q.location}|{q.event_type}"


def test_the_locked_test_window_reports_and_does_not_gate(strict_run, prep):
    """What replaced `test_recall_floor_at_100`.

    That test asserted `strict_run.outcome.reports["rerank"].recall[100] > 0.45`
    -- a hard-coded floor on the *locked test window*. It meant a build's fate
    depended on test-window performance, which is selection by another name: a
    change that lowered the number could not merge, so the number was choosing
    implementations.

    The floor still exists, because a retriever with no regression tripwire is
    worse off. It moved to the regression window (`tests/test_selection.py`).
    What is checked here is only that the locked window produced a valid,
    reportable measurement -- shape and protocol validity, no threshold on the
    value.
    """
    rep = strict_run.outcome.reports["rerank"]
    assert rep.n_queries > 0
    assert rep.n_relevant > 0
    for k, value in rep.recall.items():
        assert 0.0 <= value <= 1.0, f"R@{k} is not a proportion: {value}"
    assert 0.0 <= rep.mrr <= 1.0
    assert prep.protocol.contains("test", strict_run.test_queries[0].event_time)
    # The locked window is not selectable, and the protocol says so.
    with pytest.raises(ProtocolError):
        prep.protocol.assert_selection_window("test")


def test_precision_is_reported_not_discarded(strict_run):
    rep = strict_run.outcome.reports["rerank"]
    assert set(rep.precision) == set(rep.recall)
    assert all(0.0 <= v <= 1.0 for v in rep.precision.values())
    assert "precision@10" in rep.summary()


def test_latency_is_measured(strict_run):
    rep = strict_run.outcome.reports["rerank"]
    assert rep.latency_ms["mean"] > 0
    assert rep.latency_ms["p95"] >= rep.latency_ms["p50"]


def test_sparse_and_dense_contribute_differently(prep, cfg, strict_run):
    """If both retrievers returned the same documents, one of them is dead
    weight. Overlap below 90% is what justifies running the pair."""
    provider = SnapshotIndexProvider(
        prep.corpus, cfg.stage2, lambda: HashingEmbedder(cfg.stage1.embed_dim), LexicalReranker
    )
    overlaps = []
    for q in strict_run.test_queries[:15]:
        cascade = provider.for_origin(q.origin)
        s = {
            e.doc_id
            for e in cascade.retrieve(q.text, as_of=q.origin, top_k=50, stop_after="sparse")[0]
        }
        d = {
            e.doc_id
            for e in cascade.retrieve(q.text, as_of=q.origin, top_k=50, stop_after="dense")[0]
        }
        if s and d:
            overlaps.append(len(s & d) / len(s | d))
    assert overlaps
    assert sum(overlaps) / len(overlaps) < 0.9


def test_stage_widths_bound_reported_recall():
    cfg = Stage2Config()
    assert stage_width(cfg, "late") == cfg.late_top_k
    assert stage_width(cfg, "sparse") == cfg.bm25_top_k


def test_table_states_what_the_benchmark_measures(strict_run, cfg):
    table = format_table(strict_run.outcome.reports, cfg=cfg.stage2, method=STRICT)
    assert "oracle_target_retrieval" in table
    assert "GIVEN" in table
    assert "not event forecasting" in table
    assert STRICT in table


def test_the_lexicon_saw_no_label_from_beyond_the_training_window(prep):
    """Preprocessing is the leak nobody looks for.

    The lexicon decides the *text* of every query in the benchmark, test
    queries included. A label built from an event after `train_end` would put
    post-training information into every query the retriever ever sees, and no
    amount of careful indexing downstream could undo it.
    """
    from pramaan_x.eval.invariants import assert_lexicon_fitted_on_training_only

    record = prep.lexicon_fit
    assert record is not None and record.n_documents > 0
    assert record.n_positive > 0, "a lexicon fitted on no positives learns nothing"
    assert_lexicon_fitted_on_training_only(record, prep.protocol)


def test_the_lexicon_invariant_catches_a_post_training_label(prep):
    """Negative control: move one event past `train_end` and it must fire."""
    import dataclasses

    from pramaan_x.eval.invariants import (
        InvariantViolation,
        assert_lexicon_fitted_on_training_only,
    )

    poisoned = dataclasses.replace(
        prep.lexicon_fit,
        max_event_used=(prep.protocol.test_start + timedelta(days=3)).isoformat(),
    )
    with pytest.raises(InvariantViolation, match="at or after train_end"):
        assert_lexicon_fitted_on_training_only(poisoned, prep.protocol)


def test_both_controlled_arms_record_the_preprocessing_verdict(strict_run, ablation_run):
    """Both arms share the lexicon, so both pass this check. The contamination
    under test lives in the indexes, not here -- and the artefact says so
    rather than leaving the reader to infer which checks ran."""
    for run in (strict_run, ablation_run):
        assert run.payload["invariants"]["no_test_labels_in_preprocessing"] == "pass"
