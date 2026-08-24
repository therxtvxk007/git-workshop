"""Late interaction (MaxSim) scoring.

A single pooled vector per document throws away which *part* of the document
matched. For evidence retrieval that loss is expensive twice over: ranking gets
worse on long documents, and the analyst-facing system can no longer point at
the sentence that justified the retrieval.

MaxSim keeps token-level vectors and scores a query by summing, over query
tokens, the best match anywhere in the document. Cost is quadratic in tokens, so
it runs only over the shortlist that dense and sparse retrieval already agreed
on -- which is the entire reason it sits at stage 3 of the cascade rather than
stage 1.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..stage1_scan.bm25 import tokenize


@dataclass
class LateInteractionScorer:
    """Token-level scoring over an existing embedder.

    With a multi-vector checkpoint (ColBERT, Sentence Transformers 6 multi-vector
    heads) `token_vectors` comes straight from the model. With a single-vector
    embedder we encode sliding windows instead: coarser than true per-token
    vectors, but it preserves locality, which is the property that matters.
    """

    embedder: object
    window: int = 12
    stride: int = 6
    max_windows: int = 40
    native_multivector: bool = False

    def token_vectors(self, text: str) -> np.ndarray:
        if self.native_multivector:
            return np.asarray(self.embedder.encode_multivector([text])[0], dtype=np.float32)
        toks = tokenize(text)
        if not toks:
            return np.zeros((1, getattr(self.embedder, "dim", 1)), dtype=np.float32)
        spans = [" ".join(toks[i : i + self.window])
                 for i in range(0, max(len(toks) - self.window + 1, 1), self.stride)]
        return np.asarray(self.embedder.encode(spans[: self.max_windows]), dtype=np.float32)

    def maxsim(self, query_vecs: np.ndarray, doc_vecs: np.ndarray) -> float:
        if not len(query_vecs) or not len(doc_vecs):
            return 0.0
        sim = query_vecs @ doc_vecs.T           # (q_tokens, d_windows)
        return float(sim.max(axis=1).sum() / len(query_vecs))

    def score(self, query: str, texts: Sequence[str]) -> np.ndarray:
        qv = self.token_vectors(query)
        return np.array([self.maxsim(qv, self.token_vectors(t)) for t in texts],
                        dtype=np.float64)

    def best_span(self, query: str, text: str) -> tuple[str, float]:
        """The window that carried the match. This is what gets highlighted in
        the analyst view, and what goes in `supporting_span`."""
        qv = self.token_vectors(query)
        toks = tokenize(text)
        if not toks or not len(qv):
            return text[:160], 0.0
        spans = [" ".join(toks[i : i + self.window])
                 for i in range(0, max(len(toks) - self.window + 1, 1), self.stride)][: self.max_windows]
        dv = np.asarray(self.embedder.encode(spans), dtype=np.float32)
        per_span = (qv @ dv.T).max(axis=0)
        j = int(np.argmax(per_span))
        return spans[j], float(per_span[j])
