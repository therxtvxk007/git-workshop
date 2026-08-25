"""Stage 0 deduplication: exact, near-duplicate, and rewrite-tolerant.

Three passes because they fail differently. Exact hashing catches verbatim
reposts for free. MinHash/LSH catches shingle-level overlap. SimHash catches
the wire-desk rewrite that reorders clauses enough to thin the shingle overlap
but keeps the term distribution. Anything that survives all three is treated as
a genuinely distinct report -- and, critically, as independent evidence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..types import Document
from ..util.hashing import MinHasher, MinHashLSH, hamming, normalise, shingles, simhash


@dataclass
class DedupReport:
    n_input: int = 0
    n_exact: int = 0
    n_near: int = 0
    n_simhash: int = 0
    n_clusters: int = 0
    cluster_of: dict[str, str] = field(default_factory=dict)   # doc_id -> canonical
    canonical: set[str] = field(default_factory=set)
    cluster_members: dict[str, list[str]] = field(default_factory=dict)

    @property
    def n_removed(self) -> int:
        return self.n_exact + self.n_near + self.n_simhash

    @property
    def reduction(self) -> float:
        return self.n_removed / self.n_input if self.n_input else 0.0

    def summary(self) -> dict[str, float | int]:
        return {
            "input": self.n_input, "exact": self.n_exact, "near": self.n_near,
            "simhash": self.n_simhash, "clusters": self.n_clusters,
            "removed": self.n_removed, "reduction": round(self.reduction, 4),
        }


class Deduplicator:
    def __init__(
        self,
        permutations: int = 128,
        bands: int = 32,
        threshold: float = 0.80,
        simhash_bits: int = 64,
        simhash_threshold: int = 3,
    ) -> None:
        self.hasher = MinHasher(permutations)
        self.lsh = MinHashLSH(permutations, bands, threshold)
        self.simhash_bits = simhash_bits
        self.simhash_threshold = simhash_threshold

    def run(self, docs: Iterable[Document]) -> DedupReport:
        docs = list(docs)
        rep = DedupReport(n_input=len(docs))

        seen_exact: dict[str, str] = {}
        # SimHash buckets keyed on 16-bit prefixes so we compare a few hundred
        # candidates rather than the whole corpus; the Hamming test still gates.
        sim_index: dict[int, list[tuple[int, str]]] = {}

        # Earliest publication wins as canonical: the first outlet to carry a
        # story is the one whose timestamp the lead-time calculation must use.
        for doc in sorted(docs, key=lambda d: (d.published_at, d.doc_id)):
            norm = normalise(doc.full_text)
            if not norm:
                rep.cluster_of[doc.doc_id] = doc.doc_id
                rep.canonical.add(doc.doc_id)
                rep.cluster_members.setdefault(doc.doc_id, []).append(doc.doc_id)
                continue

            # Pass 1: exact.
            if norm in seen_exact:
                self._attach(rep, doc.doc_id, seen_exact[norm])
                rep.n_exact += 1
                continue

            sig = self.hasher.signature(shingles(norm))

            # Pass 2: MinHash LSH.
            near = self.lsh.query(sig)
            if near:
                best = max(near, key=lambda k: (MinHasher.similarity(sig, self.lsh._sigs[k]), k))
                self._attach(rep, doc.doc_id, rep.cluster_of.get(best, best))
                rep.n_near += 1
                self.lsh.add(doc.doc_id, sig)
                seen_exact[norm] = rep.cluster_of[doc.doc_id]
                continue

            # Pass 3: SimHash.
            sh = simhash(norm, self.simhash_bits)
            bucket_keys = self._sim_buckets(sh)
            match = None
            for bk in bucket_keys:
                for other_sh, other_id in sim_index.get(bk, ()):
                    if hamming(sh, other_sh) <= self.simhash_threshold:
                        match = other_id
                        break
                if match:
                    break
            if match is not None:
                self._attach(rep, doc.doc_id, rep.cluster_of.get(match, match))
                rep.n_simhash += 1
            else:
                rep.cluster_of[doc.doc_id] = doc.doc_id
                rep.canonical.add(doc.doc_id)
                rep.cluster_members.setdefault(doc.doc_id, []).append(doc.doc_id)

            self.lsh.add(doc.doc_id, sig)
            seen_exact[norm] = rep.cluster_of[doc.doc_id]
            for bk in bucket_keys:
                sim_index.setdefault(bk, []).append((sh, doc.doc_id))

        rep.n_clusters = len(rep.canonical)
        return rep

    def _sim_buckets(self, sh: int) -> list[int]:
        """Banded SimHash prefixes. With a Hamming threshold of 3 over 64 bits,
        four 16-bit bands guarantee at least one band matches exactly."""
        return [(b << 16) | ((sh >> (16 * b)) & 0xFFFF) for b in range(4)]

    @staticmethod
    def _attach(rep: DedupReport, doc_id: str, canonical: str) -> None:
        rep.cluster_of[doc_id] = canonical
        rep.cluster_members.setdefault(canonical, []).append(doc_id)


#: Meta key carrying each cluster member's own timestamps onto the canonical.
CLUSTER_MEMBERS_KEY = "cluster_members"


def apply_dedup(docs: list[Document], rep: DedupReport) -> list[Document]:
    """Annotate documents in place and return the canonical stream.

    The canonical carries its cluster's *provenance*, not just its id. Without
    it, collapsing thirty copies of a wire story into one document also
    collapses thirty acquisition times into one -- and if the canonical (the
    earliest *published* member) happens to have been crawled late or not
    crawled at all, the whole cluster reads as unavailable at an origin where a
    syndicated copy was sitting in the index. That is real information thrown
    away by a deduplication step whose only job was to avoid double-counting
    it.

    Availability is derived from the members in `eval.availability`; what
    happens here is only that the members are preserved.
    """
    by_id = {d.doc_id: d for d in docs}
    for d in docs:
        d.cluster_id = rep.cluster_of.get(d.doc_id, d.doc_id)
        d.is_canonical = d.doc_id in rep.canonical
    for canonical_id, member_ids in rep.cluster_members.items():
        canonical = by_id.get(canonical_id)
        if canonical is None:
            continue
        canonical.meta[CLUSTER_MEMBERS_KEY] = [
            {
                "doc_id": m,
                "published_at": _iso(by_id[m].published_at),
                "retrieved_at": _iso(by_id[m].retrieved_at),
                "source_family": by_id[m].meta.get("source_family", ""),
                "trusted_historical_snapshot": by_id[m].meta.get(
                    "trusted_historical_snapshot", False
                )
                is True,
            }
            for m in sorted(member_ids)
            if m in by_id
        ]
    return [d for d in docs if d.is_canonical]


def _iso(ts) -> str | None:
    return ts.isoformat() if ts is not None else None
