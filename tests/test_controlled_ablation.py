"""The controlled ablation: one query set, one variable.

The defect these tests were written against: the harness described its two arms
as differing in exactly one respect, but `build_oracle_target_queries` branched
on the method and changed four things at once -- origin placement, availability
policy, the relevant set, and (as a consequence) which queries survived the
`min_relevant` filter at all. The committed artefacts show the arms evaluating
different numbers of queries, so the reported deltas were not paired and could
not be attributed to anything.

A comparison in which the two arms answer different questions is not a
comparison. These tests demand that the controlled arms be *identical* except
for the one thing under test, and that the unpaired historical reproduction be
kept somewhere it cannot be subtracted from anything.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from pramaan_x.config import Config
from pramaan_x.eval.harness import prepare, run_method
from pramaan_x.eval.oracle_target_retrieval import (
    ABLATION,
    CONTROLLED_METHODS,
    HISTORICAL,
    STRICT,
)

DAYS = 300
SEED = 20260824


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config().apply_profile()


@pytest.fixture(scope="module")
def prep(cfg):
    return prepare(cfg, days=DAYS, seed=SEED, n_locations=8, n_event_types=6)


@pytest.fixture(scope="module")
def runs(prep, cfg):
    """Strict first, then the ablation paired against it.

    The reference is passed explicitly rather than discovered, because the
    pairing is a real data dependency: a delta is only defined once the two
    arms are known to have answered the same questions.
    """
    # `select=False`: the operating point is not the variable under test here,
    # and this corpus is too short for the selection window. That both
    # controlled arms select identically is asserted in tests/test_selection.py.
    strict = run_method(prep, cfg, STRICT, stages=("rerank",), write=False, select=False)
    ablation = run_method(prep, cfg, ABLATION, stages=("rerank",), write=False, reference=strict)
    historical = run_method(prep, cfg, HISTORICAL, stages=("rerank",), write=False, select=False)
    return {STRICT: strict, ABLATION: ablation, HISTORICAL: historical}


def test_pairing_the_historical_arm_is_refused(prep, cfg, runs):
    """NEGATIVE CONTROL: the API must make the unsound comparison impossible,
    not merely discouraged in prose."""
    with pytest.raises(ValueError, match="cannot be paired"):
        run_method(
            prep,
            cfg,
            HISTORICAL,
            stages=("rerank",),
            write=False,
            select=False,
            reference=runs[STRICT],
        )


def _fingerprint(queries):
    """Everything about a query set that must not move between arms."""
    return [(q.query_id, q.text, q.origin.isoformat(), tuple(sorted(q.relevant))) for q in queries]


# ------------------------------------------------- the controlled arms match ---


def test_controlled_arms_share_a_byte_identical_test_query_set(runs):
    """END-TO-END NEGATIVE CONTROL for requirement 2.

    Fails on the committed implementation, where the arms built their query
    sets independently and disagreed on count, origins and relevant sets.
    """
    a = _fingerprint(runs[STRICT].test_queries)
    b = _fingerprint(runs[ABLATION].test_queries)
    assert a, "the canonical query set is empty"
    assert a == b, (
        "the controlled arms do not share a query set; "
        f"strict has {len(a)} queries, the ablation has {len(b)}"
    )


def test_controlled_arms_share_a_byte_identical_training_query_set(runs):
    assert _fingerprint(runs[STRICT].train_queries) == _fingerprint(runs[ABLATION].train_queries)


def test_controlled_arms_evaluate_the_same_number_of_queries(runs):
    for stage in runs[STRICT].outcome.reports:
        s = runs[STRICT].outcome.reports[stage]
        a = runs[ABLATION].outcome.reports[stage]
        assert s.n_queries == a.n_queries
        assert s.n_relevant == a.n_relevant


def test_controlled_arms_share_widths_ks_and_lexicon(runs, prep):
    """Anything the ablation is not testing must be held fixed, and the
    artefact has to say so rather than leaving it to be assumed."""
    s = runs[STRICT].payload["extra"]["controlled"]
    a = runs[ABLATION].payload["extra"]["controlled"]
    for field in (
        "query_set_fingerprint",
        "lexicon_fingerprint",
        "ks",
        "candidate_widths",
        "fusion_training_fingerprint",
    ):
        assert s[field] == a[field], f"{field} differs between the controlled arms"
    assert s["varies"] == "index_scope"
    assert a["varies"] == "index_scope"


def test_the_only_declared_difference_is_index_scope(runs):
    assert "available strictly before" in runs[STRICT].payload["extra"]["index_scope"]
    assert "every document in the corpus" in runs[ABLATION].payload["extra"]["index_scope"]


# ------------------------------------------------------- the ablation bites ---


def test_only_the_full_corpus_arm_breaks_future_append_invariance(prep, cfg, runs):
    """NEGATIVE CONTROL: the ablation must actually be contaminated.

    If both arms were invariant, the ablation would be testing nothing and the
    paired deltas would be measuring noise.
    """
    from pramaan_x.eval.invariants import (
        InvariantViolation,
        assert_future_append_invariance,
        synthesise_future_documents,
    )
    from pramaan_x.eval.oracle_target_retrieval import ranking_probe

    queries = runs[STRICT].test_queries[:8]
    latest = max(q.origin for q in queries)
    future = synthesise_future_documents(prep.corpus, 400, after=latest + timedelta(days=1), seed=1)
    assert_future_append_invariance(ranking_probe(cfg, queries, method=STRICT), prep.corpus, future)
    with pytest.raises(InvariantViolation, match="results changed"):
        assert_future_append_invariance(
            ranking_probe(cfg, queries, method=ABLATION), prep.corpus, future
        )


def test_the_ablation_arm_fails_the_fitting_invariant(runs):
    assert set(runs[STRICT].payload["invariants"].values()) == {"pass"}
    verdicts = runs[ABLATION].payload["invariants"]
    assert verdicts["no_future_document_fitted"].startswith("FAIL")


def test_the_ablation_arm_still_returns_only_available_documents(runs):
    """The ablation contaminates *fitting*, not the availability filter. If it
    also leaked post-origin documents into the results, the arms would differ
    in two ways again."""
    assert runs[ABLATION].payload["availability_violations"]["total"] == 0
    assert runs[STRICT].payload["availability_violations"]["total"] == 0


# ----------------------------------------------------------- paired deltas ---


def test_paired_per_query_deltas_are_reported(runs):
    """A difference of means over two different query sets is not a difference.
    Pairing is only meaningful because the previous tests hold."""
    paired = runs[ABLATION].payload["extra"]["paired_vs_strict"]
    assert paired["reference_method"] == STRICT
    assert paired["n_paired_queries"] == runs[STRICT].outcome.reports["rerank"].n_queries
    for metric in ("recall@10", "ndcg@10", "mrr"):
        d = paired["per_query_delta"][metric]
        assert {"mean", "sd", "median", "n_better", "n_worse", "n_equal"} <= set(d)
        assert d["n_better"] + d["n_worse"] + d["n_equal"] == paired["n_paired_queries"]
    assert len(paired["per_query"]) == paired["n_paired_queries"]
    sample = paired["per_query"][0]
    assert {"query_id", "recall@10", "ndcg@10", "mrr"} <= set(sample)


def test_the_strict_arm_computes_no_delta_against_itself(runs):
    assert "paired_vs_strict" not in runs[STRICT].payload["extra"]


# ------------------------------------- the historical reproduction is fenced ---


def test_the_historical_reproduction_is_named_unpaired(runs):
    assert HISTORICAL == "historical_legacy_reproduction_unpaired"
    assert runs[HISTORICAL].payload["method"] == HISTORICAL
    assert HISTORICAL not in CONTROLLED_METHODS
    assert set(CONTROLLED_METHODS) == {STRICT, ABLATION}


def test_the_historical_reproduction_computes_no_delta(runs):
    """NEGATIVE CONTROL: it changes several factors at once, so subtracting it
    from anything produces a number with no referent."""
    extra = runs[HISTORICAL].payload["extra"]
    assert "paired_vs_strict" not in extra
    assert extra["comparability"]["paired"] is False
    assert set(extra["comparability"]["factors_changed"]) >= {
        "index_scope",
        "availability_policy",
        "forecast_origin_placement",
        "relevant_document_set",
    }
    assert "no delta" in extra["comparability"]["note"].lower()


def test_the_historical_reproduction_really_does_differ(runs):
    """If its query set matched the canonical one, calling it unpaired would be
    over-cautious rather than accurate. It does not match."""
    assert _fingerprint(runs[HISTORICAL].test_queries) != _fingerprint(runs[STRICT].test_queries)


def test_summary_refuses_to_place_the_historical_arm_in_the_paired_table(runs, tmp_path):
    from pramaan_x.eval.artefact import controlled_comparison

    table = controlled_comparison(
        [runs[m].payload for m in (STRICT, ABLATION, HISTORICAL)], stage="rerank"
    )
    assert set(table["controlled"]) == {STRICT, ABLATION}
    assert HISTORICAL in table["unpaired"]
    assert "delta" not in table["unpaired"][HISTORICAL]
