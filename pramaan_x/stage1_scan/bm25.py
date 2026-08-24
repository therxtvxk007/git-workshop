"""Okapi BM25 over a sparse term-document matrix.

Written out rather than pulled from `rank_bm25` for two reasons: that library
scores one query against the whole corpus in Python loops, which is far too slow
to run over every document at stage 1, and it gives no access to per-term
contributions -- which the learned fusion in stage 2 needs as features.

BM25 stays in the stack because dense retrieval reliably loses exact tokens:
place names, unit designations, case numbers. That failure is not fixable by a
larger embedding model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

import numpy as np
import scipy.sparse as sp

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75, min_df: int = 1) -> None:
        self.k1 = k1
        self.b = b
        self.min_df = min_df
        self.vocab: dict[str, int] = {}
        self.doc_ids: list[str] = []
        self._idf: np.ndarray = np.zeros(0)
        self._weights: sp.csc_matrix | None = None   # term-major for query time
        self.avgdl: float = 0.0
        self.doc_len: np.ndarray = np.zeros(0)

    def fit(self, doc_ids: Sequence[str], texts: Sequence[str]) -> BM25Index:
        if len(doc_ids) != len(texts):
            raise ValueError("doc_ids and texts must align")
        self.doc_ids = list(doc_ids)
        tokenised = [tokenize(t) for t in texts]
        self.doc_len = np.array([len(t) for t in tokenised], dtype=np.float64)
        self.avgdl = float(self.doc_len.mean()) if len(self.doc_len) else 0.0

        df: dict[str, int] = {}
        for toks in tokenised:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        self.vocab = {t: i for i, t in enumerate(sorted(t for t, c in df.items() if c >= self.min_df))}

        rows, cols, vals = [], [], []
        for d, toks in enumerate(tokenised):
            tf: dict[int, int] = {}
            for t in toks:
                j = self.vocab.get(t)
                if j is not None:
                    tf[j] = tf.get(j, 0) + 1
            for j, c in tf.items():
                rows.append(d)
                cols.append(j)
                vals.append(c)

        n_docs, n_terms = len(doc_ids), len(self.vocab)
        counts = sp.csr_matrix((vals, (rows, cols)), shape=(n_docs, n_terms), dtype=np.float64)

        # Robertson/Sparck-Jones idf with the +1 guard, so a term present in
        # every document gets a small positive weight rather than a negative one.
        doc_freq = np.asarray((counts > 0).sum(axis=0)).ravel()
        self._idf = np.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))

        # Precompute the full BM25 weight matrix. Saturation and length
        # normalisation depend only on the document, so this is done once.
        norm = self.k1 * (1 - self.b + self.b * (self.doc_len / (self.avgdl or 1.0)))
        coo = counts.tocoo()
        weights = (coo.data * (self.k1 + 1)) / (coo.data + norm[coo.row])
        weights *= self._idf[coo.col]
        self._weights = sp.csr_matrix(
            (weights, (coo.row, coo.col)), shape=(n_docs, n_terms)
        ).tocsc()
        return self

    def score(self, query: str | Iterable[str]) -> np.ndarray:
        toks = tokenize(query) if isinstance(query, str) else list(query)
        if self._weights is None:
            raise RuntimeError("BM25Index.fit must be called before scoring")
        out = np.zeros(len(self.doc_ids), dtype=np.float64)
        for t in toks:
            j = self.vocab.get(t)
            if j is None:
                continue
            col = self._weights[:, j]
            out[col.indices] += col.data
        return out

    def top_k(self, query: str, k: int = 100) -> list[tuple[str, float]]:
        scores = self.score(query)
        if not len(scores):
            return []
        k = min(k, len(scores))
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [(self.doc_ids[i], float(scores[i])) for i in idx if scores[i] > 0]

    def term_scores(self, doc_index: int, terms: Sequence[str]) -> dict[str, float]:
        """Per-term BM25 contribution for one document -- feature input for the
        learned fusion, and the basis of an explainable evidence highlight."""
        out = {}
        for t in terms:
            j = self.vocab.get(t)
            if j is not None:
                out[t] = float(self._weights[doc_index, j])
        return out

    @property
    def n_docs(self) -> int:
        return len(self.doc_ids)
