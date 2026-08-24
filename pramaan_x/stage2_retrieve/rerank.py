"""Reranking: the expensive, high-precision pass over a short list.

`LexicalReranker` is the offline default -- proximity-weighted term overlap with
coverage, which is a genuine reranking signal rather than a placeholder.
`CrossEncoderReranker` is the deployment path (Jina Reranker 3.5 for text,
Qwen3-VL-Reranker for multimodal), used on the cheaper text model by default and
the multimodal one only when the shortlist actually contains non-text evidence.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..stage1_scan.bm25 import tokenize


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, texts: Sequence[str]) -> np.ndarray: ...


@dataclass
class LexicalReranker:
    """Coverage x proximity.

    Coverage rewards documents containing more *distinct* query terms, which is
    what separates a document genuinely about the query from one that repeats a
    single term. Proximity rewards those terms appearing close together, which
    is what separates a real statement from two unrelated mentions.
    """

    name: str = "lexical"
    proximity_window: int = 25

    def rerank(self, query: str, texts: Sequence[str]) -> np.ndarray:
        q = list(dict.fromkeys(tokenize(query)))
        if not q:
            return np.zeros(len(texts))
        qset = set(q)
        out = np.zeros(len(texts))
        for i, text in enumerate(texts):
            toks = tokenize(text)
            if not toks:
                continue
            positions: dict[str, list[int]] = {}
            for j, t in enumerate(toks):
                if t in qset:
                    positions.setdefault(t, []).append(j)
            if not positions:
                continue
            coverage = len(positions) / len(qset)
            spread = self._min_span(positions)
            proximity = 1.0 / (1.0 + math.log1p(max(spread - len(positions), 0)))
            density = sum(len(v) for v in positions.values()) / math.sqrt(len(toks))
            out[i] = coverage * (0.6 + 0.4 * proximity) * (1.0 + 0.15 * density)
        return out

    @staticmethod
    def _min_span(positions: dict[str, list[int]]) -> int:
        """Smallest window containing one occurrence of every matched term."""
        items = [(p, term) for term, ps in positions.items() for p in ps]
        items.sort()
        need = len(positions)
        have: dict[str, int] = {}
        best = math.inf
        left = 0
        for pos, term in items:
            have[term] = have.get(term, 0) + 1
            while len(have) == need:
                best = min(best, pos - items[left][0] + 1)
                lterm = items[left][1]
                have[lterm] -= 1
                if not have[lterm]:
                    del have[lterm]
                left += 1
        return int(best) if best is not math.inf else 10**6


@dataclass
class CrossEncoderReranker:
    """Listwise/cross-encoder reranking against a served model."""

    model_name: str = "jinaai/jina-reranker-v3.5"
    name: str = "cross-encoder"
    batch_size: int = 16
    max_length: int = 1024
    device: str | None = None
    _model: object | None = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, max_length=self.max_length,
                                       device=self.device, trust_remote_code=True)
        return self._model

    def rerank(self, query: str, texts: Sequence[str]) -> np.ndarray:
        model = self._load()
        pairs = [(query, t) for t in texts]
        scores = model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        return np.asarray(scores, dtype=np.float64)


def build_reranker(name: str) -> Reranker:
    if name == "lexical":
        return LexicalReranker()
    aliases = {
        "jina-reranker-3.5": "jinaai/jina-reranker-v3.5",
        "qwen3-vl-reranker-2b": "Qwen/Qwen3-VL-Reranker-2B",
    }
    return CrossEncoderReranker(model_name=aliases.get(name, name), name=name)
