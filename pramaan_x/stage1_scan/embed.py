"""Embedding backends behind one interface.

The interface exists so the cascade never names a model. `HashingEmbedder` is
the offline default: real feature hashing with sublinear tf and L2
normalisation, weak but honest and completely deterministic. `JinaV5Embedder`
and `QwenVLEmbedder` are the deployment paths.

The hashing backend is not a mock. It is a legitimate (if dated) retrieval
method, which is exactly what makes it a usable floor: when the bake-off in
`eval/bakeoff.py` reports that Jina v5 beats it, that number means something.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np

from ..util.hashing import _stable_u64
from .bm25 import tokenize


class Embedder(Protocol):
    dim: int
    name: str

    def encode(self, texts: Sequence[str], *, batch_size: int = 32) -> np.ndarray: ...


class HashingEmbedder:
    """Signed feature hashing with sublinear tf weighting.

    Signed hashing keeps collisions unbiased in expectation, which matters at
    these widths where collisions are frequent rather than theoretical. Defaults
    are unigram at 1024 dimensions: a sweep over {256..2048} x {1,2}-grams put
    bigrams below unigrams at every width under 1024, because the bigram
    vocabulary collides far faster than it adds signal.
    """

    def __init__(self, dim: int = 1024, ngram: int = 1, seed: int = 20260824) -> None:
        self.dim = dim
        self.ngram = ngram
        self.seed = seed
        self.name = f"hashing-{dim}d"
        self._idf: dict[int, float] | None = None
        self._n_docs = 0

    def fit(self, texts: Sequence[str]) -> HashingEmbedder:
        """Optional idf pass. Retrieval quality is meaningfully better with it,
        and it costs one sweep over a corpus we are already sweeping."""
        df: dict[int, int] = {}
        for t in texts:
            for j in {j for j, _ in self._features(t)}:
                df[j] = df.get(j, 0) + 1
        self._n_docs = len(texts)
        self._idf = {j: np.log(1.0 + self._n_docs / (c + 1.0)) for j, c in df.items()}
        return self

    def _features(self, text: str):
        toks = tokenize(text)
        grams = list(toks)
        for n in range(2, self.ngram + 1):
            grams += [" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)]
        counts: dict[str, int] = {}
        for g in grams:
            counts[g] = counts.get(g, 0) + 1
        for g, c in counts.items():
            h = _stable_u64(f"{self.seed}:{g}")
            j = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            yield j, sign * (1.0 + np.log(c))

    def encode(self, texts: Sequence[str], *, batch_size: int = 32) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for j, v in self._features(text):
                w = self._idf.get(j, 1.0) if self._idf else 1.0
                out[i, j] += v * w
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)


class SentenceTransformerEmbedder:
    """Deployment backend: Jina v5, Qwen3-VL-Embedding, or any ST-compatible
    checkpoint. Imported lazily so the package stays installable without torch
    or a model download."""

    def __init__(self, model_name: str = "jinaai/jina-embeddings-v5-text-small",
                 dim: int | None = None, device: str | None = None,
                 trust_remote_code: bool = True, task: str | None = "retrieval.passage") -> None:
        self.model_name = model_name
        self.name = model_name
        self.task = task
        self._model = None
        self._device = device
        self._trust = trust_remote_code
        self.dim = dim or 1024

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name, device=self._device, trust_remote_code=self._trust
            )
            self.dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def encode(self, texts: Sequence[str], *, batch_size: int = 32) -> np.ndarray:
        model = self._load()
        kw = {"batch_size": batch_size, "normalize_embeddings": True,
              "convert_to_numpy": True, "show_progress_bar": False}
        if self.task:
            try:
                return model.encode(list(texts), task=self.task, **kw)
            except TypeError:
                pass    # checkpoint without task-conditioned encoding
        return model.encode(list(texts), **kw)


def build_embedder(name: str, dim: int = 1024) -> Embedder:
    if name == "hashing":
        return HashingEmbedder(dim=dim)
    aliases = {
        "jina-v5-small": "jinaai/jina-embeddings-v5-text-small",
        "jina-v5-nano": "jinaai/jina-embeddings-v5-text-nano",
        "qwen3-vl-embedding-8b": "Qwen/Qwen3-VL-Embedding-8B",
    }
    return SentenceTransformerEmbedder(aliases.get(name, name))


def cosine_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rows already L2-normalised by every backend here, so this is a matmul."""
    return a @ b.T
