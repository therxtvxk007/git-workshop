"""Deduplication: synthetic tests, as the risk table requires.

Each test states the failure it guards against. The headline one is
`test_precursor_documents_survive`: dedup that quietly discards a document
carrying the only precursor for an event destroys recall in a way no downstream
stage can detect, let alone repair.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC

import pytest

from pramaan_x.stage0_ingest.dedup import Deduplicator, apply_dedup
from pramaan_x.stage0_ingest.pipeline import run_stage0
from pramaan_x.util.hashing import MinHasher, MinHashLSH, hamming, normalise, shingles, simhash


def test_exact_duplicates_collapse():
    from datetime import datetime

    from pramaan_x.types import Document

    t = datetime(2025, 1, 1, tzinfo=UTC)
    docs = [Document(doc_id=f"d{i}", source_id=f"s{i}",
                     text="the port authority raised dwell time limits again",
                     published_at=t) for i in range(5)]
    rep = Deduplicator().run(docs)
    assert rep.n_clusters == 1
    assert rep.n_exact == 4


def test_distinct_documents_are_not_merged():
    """The false-merge guard. A merge is unrecoverable: the merged document is
    never scored again."""
    from datetime import datetime, timedelta

    from pramaan_x.types import Document

    t = datetime(2025, 1, 1, tzinfo=UTC)
    texts = [
        "reservoir levels approached the seasonal spill threshold this week",
        "credential stuffing attempts against the portal rose sharply overnight",
        "union representatives rejected the revised wage offer at the depot",
        "engineers flagged deferred maintenance on the transmission corridor",
    ]
    docs = [Document(doc_id=f"d{i}", source_id="s", text=x,
                     published_at=t + timedelta(hours=i)) for i, x in enumerate(texts)]
    rep = Deduplicator().run(docs)
    assert rep.n_clusters == len(texts)


def test_earliest_publication_becomes_canonical():
    """Lead time is measured from the canonical document's timestamp. If a later
    republication won, every lead-time figure would be understated."""
    from datetime import datetime, timedelta

    from pramaan_x.types import Document

    t = datetime(2025, 3, 1, tzinfo=UTC)
    text = "border patrols reported increased movement after dark near the district"
    docs = [
        Document(doc_id="late", source_id="s2", text=text, published_at=t + timedelta(days=2)),
        Document(doc_id="first", source_id="s1", text=text, published_at=t),
    ]
    rep = Deduplicator().run(docs)
    assert rep.canonical == {"first"}


def test_simhash_catches_light_rewrite_on_realistic_length():
    """SimHash is the third pass and targets full-length wire copy. Its Hamming
    distance is not scale-free -- see `simhash`'s docstring -- so this asserts
    the behaviour at the length it is actually applied to."""
    body = (" the terminal operator warned of imminent capacity limits at the port "
            "while freight forwarders began rerouting cargo through alternate ports "
            "and warehouse occupancy exceeded ninety percent across the corridor "
            "with customs clearance backlogs lengthening for a fourth consecutive week "
            "as the chamber of commerce convened an emergency session on the matter ") * 2
    a = normalise(body)
    b = normalise(body.replace(" said ", " stated ") + " (Agency copy.)")
    assert hamming(simhash(a), simhash(b)) <= 3


def test_short_rewrite_is_caught_by_cleaning_not_simhash():
    """The short-document case SimHash cannot see is handled earlier: boilerplate
    stripping normalises the two texts and exact matching collapses them."""
    from datetime import datetime, timedelta

    from pramaan_x.stage0_ingest.pipeline import run_stage0
    from pramaan_x.types import Document

    t = datetime(2025, 1, 1, tzinfo=UTC)
    text = "the terminal operator warned of imminent capacity limits at the port today"
    docs = [
        Document(doc_id="orig", source_id="s1", text=text, published_at=t),
        Document(doc_id="copy", source_id="s2", text=text + " (Agency copy.)",
                 published_at=t + timedelta(hours=3)),
    ]
    res = run_stage0(docs)
    assert len(res.documents) == 1
    assert res.documents[0].doc_id == "orig"


def test_minhash_similarity_is_symmetric_and_bounded():
    h = MinHasher(64)
    a = h.signature(shingles("heavy rainfall warning extended across the northern districts"))
    b = h.signature(shingles("heavy rainfall warning extended across the southern districts"))
    s = MinHasher.similarity(a, b)
    assert 0.0 <= s <= 1.0
    assert s == MinHasher.similarity(b, a)
    assert MinHasher.similarity(a, a) == 1.0


def test_minhash_signatures_are_reproducible():
    """A dedup decision that changes between runs silently changes the corpus."""
    s1 = MinHasher(64).signature(shingles("the substation has operated above rated load"))
    s2 = MinHasher(64).signature(shingles("the substation has operated above rated load"))
    assert s1 == s2


def test_lsh_requires_bands_to_divide_permutations():
    with pytest.raises(ValueError):
        MinHashLSH(permutations=128, bands=7)


def test_precursor_documents_survive(documents, ground_truth):
    """The number stage 0 exists to protect."""
    res = run_stage0(list(documents))
    reachable = {d.doc_id for d in res.all_documents}
    canonical = {d.doc_id for d in res.documents}
    clusters = res.dedup.cluster_of
    total = kept = 0
    for doc_ids in ground_truth.precursor_docs.values():
        for d in doc_ids:
            if d not in reachable:
                continue
            total += 1
            if clusters.get(d, d) in canonical:
                kept += 1
    assert total > 0
    assert kept == total, f"{total - kept} precursor documents lost in dedup"


def test_false_merge_rate_stays_low(documents, ground_truth):
    """Regression guard. Measured at 0.4%; 3% is the point at which recall
    starts visibly degrading downstream."""
    docs = list(documents)
    rep = Deduplicator().run(docs)
    originals = [d.doc_id for d in docs if d.doc_id not in ground_truth.duplicate_of]
    counts = Counter(rep.cluster_of[o] for o in originals)
    false_merges = sum(v - 1 for v in counts.values() if v > 1)
    rate = false_merges / len(originals)
    assert rate < 0.03, f"false-merge rate {rate:.2%} exceeds tolerance"


def test_syndicated_copies_are_clustered(documents, ground_truth):
    docs = list(documents)
    rep = Deduplicator().run(docs)
    matched = sum(1 for copy, orig in ground_truth.duplicate_of.items()
                  if rep.cluster_of.get(copy) == rep.cluster_of.get(orig))
    rate = matched / max(len(ground_truth.duplicate_of), 1)
    assert rate > 0.70, f"only {rate:.1%} of known copies clustered with their original"


def test_apply_dedup_marks_documents(documents):
    docs = list(documents)
    rep = Deduplicator().run(docs)
    canonical = apply_dedup(docs, rep)
    assert all(d.is_canonical for d in canonical)
    assert all(d.cluster_id is not None for d in docs)
    assert len(canonical) == rep.n_clusters
