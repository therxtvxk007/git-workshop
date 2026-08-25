"""Future-append invariance across the *whole* evaluated pipeline.

The earlier version of this property started after Stage 0. It compared
rankings built from an already-deduplicated corpus, so timestamp validation,
cleaning, deduplication, the canonical/cluster mapping, the lexicon and the
ground-truth relevant sets were all outside the invariant. A statistic fitted
over the whole corpus at any of those steps would have passed unnoticed.

These tests run the property from raw documents and compare every intermediate
an appended future document could perturb, not only the final order.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from pramaan_x.config import Config
from pramaan_x.data.synth import SynthConfig, SyntheticCorpus
from pramaan_x.eval.availability import available_at, is_available
from pramaan_x.eval.invariants import (
    InvariantViolation,
    assert_future_append_invariance,
    raw_pipeline_probe,
    synthesise_future_documents,
)
from pramaan_x.eval.protocol import TemporalProtocol

DAYS = 300
SEED = 20260824


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config().apply_profile()


@pytest.fixture(scope="module")
def raw(cfg):
    docs, gt = SyntheticCorpus(
        SynthConfig(days=DAYS, seed=SEED, n_locations=8, n_event_types=6)
    ).generate()
    return docs, gt


@pytest.fixture(scope="module")
def protocol(raw, cfg):
    from pramaan_x.eval.availability import to_utc

    docs, _ = raw
    start = min(to_utc(d.published_at) for d in docs)
    end = max(to_utc(d.published_at) for d in docs) + timedelta(seconds=1)
    return TemporalProtocol.from_span(start, end)


def _probe(cfg, protocol, gt, *, contaminate=False):
    fn = raw_pipeline_probe(cfg, protocol, "test", contaminate_preprocessing=contaminate)
    fn.ground_truth = gt
    return fn


def _future(docs, protocol, n=400):
    return synthesise_future_documents(docs, n, after=protocol.test_end + timedelta(days=1), seed=1)


# ------------------------------------------------------ the whole pipeline ---


def test_appending_future_raw_documents_changes_nothing_earlier(raw, cfg, protocol):
    """END-TO-END NEGATIVE CONTROL for requirement 5.

    Fails on any implementation that fits a preprocessing statistic over the
    whole corpus, which the committed probe could not have detected because it
    started after Stage 0.
    """
    docs, gt = raw
    baseline = assert_future_append_invariance(
        _probe(cfg, protocol, gt), docs, _future(docs, protocol)
    )
    assert baseline, "the probe evaluated no queries, so this proves nothing"
    sample = next(iter(baseline.values()))
    for key in (
        "n_admitted_raw_at_origin",
        "admitted_raw_at_origin",
        "canonical_ids_at_origin",
        "cluster_of_at_origin",
        "cluster_available_at",
        "query_text",
        "relevant",
        "ranking",
    ):
        assert key in sample, f"the probe does not compare {key}"
    assert sample["ranking"], "nothing ranked"


def test_the_invariant_catches_contaminated_preprocessing(raw, cfg, protocol):
    """NEGATIVE CONTROL: fit the lexicon on the whole corpus instead of the
    training window and the invariant must fire. If it did not, the test above
    would be proving nothing about preprocessing."""
    docs, gt = raw
    with pytest.raises(InvariantViolation):
        assert_future_append_invariance(
            _probe(cfg, protocol, gt, contaminate=True), docs, _future(docs, protocol)
        )


def test_each_stage_of_the_pipeline_is_actually_exercised(raw, cfg, protocol):
    """The probe must reach dedup and the cluster mapping, not stop at the index."""
    docs, gt = raw
    out = _probe(cfg, protocol, gt)(docs)
    sample = next(iter(out.values()))
    # Validation, cleaning and the availability rule between them admit fewer
    # raw documents at an origin than the corpus contains.
    assert 0 < sample["n_admitted_raw_at_origin"] < len(docs)
    assert len(sample["canonical_ids_at_origin"]) < sample["n_admitted_raw_at_origin"], (
        "deduplication collapsed nothing, so the probe is not reaching it"
    )
    multi = [ids for ids in sample["cluster_of_at_origin"].values() if len(ids) > 1]
    assert multi, "no multi-member clusters reached the probe, so dedup is untested"
    assert any(v is not None for v in sample["cluster_available_at"].values())


# ------------------------------------------------- cluster availability rules ---


def test_a_cluster_is_available_when_any_member_is(cfg):
    """The repair, stated directly.

    A canonical crawled late (or never) must not hide a syndicated copy that
    was in hand at the origin: deduplication exists to stop double-counting
    evidence, not to delete it.
    """
    from datetime import UTC, datetime

    from pramaan_x.eval.availability import CLUSTER_MEMBERS_KEY
    from pramaan_x.types import Document

    origin = datetime(2025, 6, 1, tzinfo=UTC)
    canonical = Document(
        doc_id="canon",
        source_id="wire_a_national",
        text="body",
        published_at=origin - timedelta(days=3),
        retrieved_at=origin + timedelta(days=2),  # crawled late
        meta={
            CLUSTER_MEMBERS_KEY: [
                {
                    "doc_id": "canon",
                    "published_at": (origin - timedelta(days=3)).isoformat(),
                    "retrieved_at": (origin + timedelta(days=2)).isoformat(),
                },
                {
                    "doc_id": "copy",
                    "published_at": (origin - timedelta(days=2)).isoformat(),
                    "retrieved_at": (origin - timedelta(days=1)).isoformat(),
                },
            ]
        },
    )
    assert is_available(canonical, origin), (
        "a syndicated copy was in hand at the origin; the cluster is available"
    )
    assert available_at(canonical) == origin - timedelta(days=1)


def test_a_cluster_whose_members_are_all_unavailable_is_rejected(cfg):
    from datetime import UTC, datetime

    from pramaan_x.eval.availability import CLUSTER_MEMBERS_KEY, Rejection, classify
    from pramaan_x.types import Document

    origin = datetime(2025, 6, 1, tzinfo=UTC)
    doc = Document(
        doc_id="canon",
        source_id="s",
        text="body",
        published_at=origin - timedelta(days=3),
        retrieved_at=origin + timedelta(days=2),
        meta={
            CLUSTER_MEMBERS_KEY: [
                {
                    "doc_id": "canon",
                    "published_at": (origin - timedelta(days=3)).isoformat(),
                    "retrieved_at": (origin + timedelta(days=2)).isoformat(),
                },
                {
                    "doc_id": "copy",
                    "published_at": (origin - timedelta(days=2)).isoformat(),
                    "retrieved_at": None,
                },
            ]
        },
    )
    assert not is_available(doc, origin)
    # The reported reason is the nearest miss: we had it, we crawled it late.
    assert classify(doc, origin) is Rejection.RETRIEVED_AFTER_ORIGIN


def test_cluster_provenance_survives_stage0(raw, cfg):
    from pramaan_x.eval.availability import CLUSTER_MEMBERS_KEY
    from pramaan_x.stage0_ingest.pipeline import run_stage0

    docs, _ = raw
    import copy

    result = run_stage0(copy.deepcopy(docs), cfg.stage0)
    multi = [d for d in result.documents if len(d.meta.get(CLUSTER_MEMBERS_KEY, [])) > 1]
    assert multi, "no clusters with more than one member"
    for d in multi[:20]:
        members = d.meta[CLUSTER_MEMBERS_KEY]
        assert d.doc_id in {m["doc_id"] for m in members}
        assert all("published_at" in m and "source_family" in m for m in members)


def test_cluster_availability_recovers_information_the_canonical_alone_loses(raw, cfg):
    """Quantifies the repair on the real corpus rather than a constructed pair."""
    import copy

    from pramaan_x.eval.availability import CLUSTER_MEMBERS_KEY, Member, member_available_at
    from pramaan_x.stage0_ingest.pipeline import run_stage0

    docs, _ = raw
    result = run_stage0(copy.deepcopy(docs), cfg.stage0)
    recovered = 0
    for d in result.documents:
        members = d.meta.get(CLUSTER_MEMBERS_KEY, [])
        if len(members) < 2:
            continue
        canonical_only = member_available_at(
            Member(d.doc_id, d.published_at, d.retrieved_at, False)
        )
        cluster = available_at(d)
        if cluster is not None and (canonical_only is None or cluster < canonical_only):
            recovered += 1
    assert recovered > 0, (
        "no cluster recovered availability from a member, so the repair is untested on this corpus"
    )


# ------------------------------------------------- ground-truth cluster mapping ---


def test_ground_truth_relevant_documents_are_mapped_through_clusters(cfg):
    from pramaan_x.eval.harness import prepare

    prep = prepare(cfg, days=DAYS, seed=SEED, n_locations=8, n_event_types=6)
    mapping = prep.label_mapping
    assert mapping["remapped_to_cluster_canonical"] > 0, (
        "no ground-truth id needed remapping, so the mapping is untested here"
    )
    assert mapping["dropped_no_canonical"] == 0, (
        "a ground-truth precursor was lost instead of mapped to its cluster"
    )
    canonical = {d.doc_id for d in prep.corpus}
    for ids in prep.ground_truth.precursor_docs.values():
        assert set(ids) <= canonical, "a relevant id is not a canonical document"
        assert len(ids) == len(set(ids)), "a syndicated copy was counted twice"


def test_deduplication_only_appends_when_the_corpus_grows(raw, cfg, protocol):
    """The property that makes the origin-restricted cluster view safe.

    Appending future documents *does* grow the stored member lists -- that is
    how deduplication works. What must never happen is a canonical changing, a
    document moving between clusters, or a member disappearing, because then
    restricting the view to an origin would not be enough and every cluster
    decision would have to be recomputed per origin.

    This is asserted rather than assumed: the invariance test above relies on it.
    """
    import copy

    from pramaan_x.eval.invariants import assert_cluster_growth_is_append_only
    from pramaan_x.stage0_ingest.pipeline import run_stage0

    docs, _ = raw
    future = _future(docs, protocol)
    before = run_stage0(copy.deepcopy(docs), cfg.stage0).dedup
    after = run_stage0(copy.deepcopy([*docs, *future]), cfg.stage0).dedup
    assert_cluster_growth_is_append_only(before, after, {d.doc_id for d in future})
    grew = [
        c
        for c in before.cluster_members
        if set(after.cluster_members.get(c, [])) != set(before.cluster_members[c])
    ]
    assert grew, "no cluster grew, so append-only is untested on this corpus"


def test_the_append_only_invariant_catches_a_reassignment(raw, cfg, protocol):
    """NEGATIVE CONTROL for the append-only property."""
    import copy

    from pramaan_x.eval.invariants import (
        InvariantViolation,
        assert_cluster_growth_is_append_only,
    )
    from pramaan_x.stage0_ingest.pipeline import run_stage0

    docs, _ = raw
    before = run_stage0(copy.deepcopy(docs), cfg.stage0).dedup
    after = copy.deepcopy(before)
    victim = next(iter(after.cluster_of))
    after.cluster_of[victim] = "somewhere-else"
    with pytest.raises(InvariantViolation, match="moved from cluster"):
        assert_cluster_growth_is_append_only(before, after, set())
