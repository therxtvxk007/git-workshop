"""Content addressing and near-duplicate signatures.

News syndication produces dozens of copies of one report. Processing them
separately wastes compute *and* -- worse -- makes repetition look like
independent corroboration, which is exactly the failure mode a forecasting
system must not have. Everything here exists to collapse copies before they
reach a semantic model or an evidence count.
"""

from __future__ import annotations

import hashlib
import re
import struct
from collections.abc import Iterable, Iterator

_WORD = re.compile(r"[a-z0-9]+")
_MERSENNE = (1 << 61) - 1


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()


def normalise(text: str) -> str:
    """Aggressive normalisation for duplicate detection only. Never feed the
    output of this to an extractor -- it destroys casing and punctuation."""
    return " ".join(_WORD.findall(text.lower()))


def shingles(text: str, n: int = 5) -> set[str]:
    tokens = _WORD.findall(text.lower())
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _stable_u64(item: str) -> int:
    return struct.unpack("<Q", hashlib.blake2b(item.encode(), digest_size=8).digest())[0]


class MinHasher:
    """MinHash with universal hashing over a Mersenne prime field.

    Uses a fixed seed so signatures are reproducible across runs -- a dedup
    decision that changes between runs would silently change the corpus and
    make an experiment unrepeatable.
    """

    def __init__(self, permutations: int = 128, seed: int = 20260824) -> None:
        self.permutations = permutations
        rng = _lcg(seed)
        self._a = [next(rng) % (_MERSENNE - 1) + 1 for _ in range(permutations)]
        self._b = [next(rng) % _MERSENNE for _ in range(permutations)]

    def signature(self, items: Iterable[str]) -> tuple[int, ...]:
        hashes = [_stable_u64(i) for i in items]
        if not hashes:
            return tuple([_MERSENNE] * self.permutations)
        sig = []
        for a, b in zip(self._a, self._b, strict=True):
            sig.append(min(((a * h + b) % _MERSENNE) for h in hashes))
        return tuple(sig)

    @staticmethod
    def similarity(x: tuple[int, ...], y: tuple[int, ...]) -> float:
        if not x or len(x) != len(y):
            return 0.0
        return sum(1 for i, j in zip(x, y, strict=True) if i == j) / len(x)


class MinHashLSH:
    """Banded LSH index. Candidate pairs only -- exact Jaccard on the signature
    still gates membership, so the band count trades recall for work, not
    correctness."""

    def __init__(self, permutations: int = 128, bands: int = 32, threshold: float = 0.8):
        if permutations % bands:
            raise ValueError("bands must divide permutations")
        self.bands = bands
        self.rows = permutations // bands
        self.threshold = threshold
        self._buckets: dict[tuple[int, int], list[str]] = {}
        self._sigs: dict[str, tuple[int, ...]] = {}

    def add(self, key: str, sig: tuple[int, ...]) -> None:
        self._sigs[key] = sig
        for b in range(self.bands):
            band = sig[b * self.rows : (b + 1) * self.rows]
            self._buckets.setdefault((b, hash(band)), []).append(key)

    def query(self, sig: tuple[int, ...]) -> set[str]:
        out: set[str] = set()
        for b in range(self.bands):
            band = sig[b * self.rows : (b + 1) * self.rows]
            for key in self._buckets.get((b, hash(band)), ()):
                if MinHasher.similarity(sig, self._sigs[key]) >= self.threshold:
                    out.add(key)
        return out


def simhash(text: str, bits: int = 64) -> int:
    """SimHash over token frequencies. Complements MinHash: it catches the
    'same story, lightly rewritten by a wire desk' case that shingle overlap
    can miss once a subeditor has reordered clauses.

    Length sensitivity, measured: Hamming distance under SimHash is *not*
    scale-free. Appending two tokens to a 12-token document moves ~7 of 64 bits,
    while the same edit on a 200-token document moves ~1. A fixed threshold is
    therefore only meaningful above roughly 60 tokens, which is why the
    deduplicator runs SimHash last, after boilerplate stripping has already
    normalised away the short-document case, and why the threshold is kept
    conservative rather than tuned upward to catch short texts -- raising it
    would buy those at the cost of false merges, and a false merge is
    unrecoverable.
    """
    counts: dict[str, int] = {}
    for tok in _WORD.findall(text.lower()):
        counts[tok] = counts.get(tok, 0) + 1
    if not counts:
        return 0
    v = [0] * bits
    for tok, w in counts.items():
        h = _stable_u64(tok)
        for i in range(bits):
            v[i] += w if (h >> i) & 1 else -w
    out = 0
    for i in range(bits):
        if v[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _lcg(seed: int) -> Iterator[int]:
    x = seed & 0xFFFFFFFFFFFFFFFF
    while True:
        x = (6364136223846793005 * x + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        yield x
