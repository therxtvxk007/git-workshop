"""Dense text representations, with an offline default.

``huggingface.co`` is unreachable from many locked-down environments (including
the one this repo was developed in), so the default embedder must not require
downloading pretrained weights. ``HashingSVDEmbedder`` is therefore the
built-in: a character+word n-gram hashing vectoriser reduced by truncated SVD.
It is a strong classical baseline, deterministic, and needs no network.

``SentenceTransformerEmbedder`` swaps in a real pretrained encoder when weights
are available. The interface is identical, so the backtest harness measures the
difference between them rather than assuming it.
"""

from __future__ import annotations

from typing import Protocol, Sequence

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import HashingVectorizer, TfidfTransformer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import Normalizer

from .schema import Document


class Embedder(Protocol):
    dim: int

    def fit(self, texts: Sequence[str]) -> "Embedder": ...

    def transform(self, texts: Sequence[str]) -> np.ndarray: ...


class HashingSVDEmbedder:
    """Hashed word+char n-grams -> TF-IDF -> truncated SVD -> L2 norm.

    Hashing keeps the vocabulary unbounded and streaming-friendly, which is what
    the survey's scalability gap (G1) actually needs: no vocabulary fit pass
    over the whole corpus, so shards embed independently and in parallel.
    """

    def __init__(
        self,
        dim: int = 128,
        n_features: int = 2**16,
        word_ngram: tuple[int, int] = (1, 2),
        random_state: int = 0,
    ) -> None:
        self.dim = dim
        self.n_features = n_features
        self.word_ngram = word_ngram
        self.random_state = random_state
        self._pipe = None

    def fit(self, texts: Sequence[str]) -> "HashingSVDEmbedder":
        texts = list(texts)
        # SVD cannot produce more components than min(n_samples, n_features)-1.
        dim = max(2, min(self.dim, len(texts) - 1)) if len(texts) > 2 else 2
        self._pipe = make_pipeline(
            HashingVectorizer(
                n_features=self.n_features,
                ngram_range=self.word_ngram,
                alternate_sign=False,
                norm=None,
                lowercase=True,
                stop_words="english",
            ),
            TfidfTransformer(sublinear_tf=True),
            # n_iter=4 is enough for a rank-128 randomized SVD on this scale;
            # the default of 5 cost ~20% more time for no measurable change.
            TruncatedSVD(n_components=dim, n_iter=4, random_state=self.random_state),
            Normalizer(copy=False),
        )
        self._pipe.fit(texts)
        self.dim = dim
        return self

    def transform(self, texts: Sequence[str]) -> np.ndarray:
        if self._pipe is None:
            raise RuntimeError("call fit() before transform()")
        if not len(texts):
            return np.zeros((0, self.dim), dtype=np.float64)
        return np.asarray(self._pipe.transform(list(texts)), dtype=np.float64)

    def fit_transform(self, texts: Sequence[str]) -> np.ndarray:
        return self.fit(texts).transform(texts)


class SentenceTransformerEmbedder:  # pragma: no cover - needs model weights
    """Pretrained sentence encoder. Requires ``sentence-transformers`` + weights."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def fit(self, texts: Sequence[str]) -> "SentenceTransformerEmbedder":
        return self  # pretrained; nothing to fit

    def transform(self, texts: Sequence[str]) -> np.ndarray:
        if not len(texts):
            return np.zeros((0, self.dim), dtype=np.float64)
        return np.asarray(
            self._model.encode(list(texts), normalize_embeddings=True),
            dtype=np.float64,
        )


def embed_documents(
    documents: Sequence[Document],
    embedder: Embedder,
    *,
    fit: bool = False,
) -> np.ndarray:
    """Embed documents and cache the vectors on each ``Document``.

    ``fit`` must be False for anything at or after the forecast origin. The
    backtester only ever fits on the training slice, because fitting the
    vectoriser on test text leaks corpus statistics backwards in time -- a
    subtle version of the validation failure the survey flags as G6.
    """
    texts = [d.text for d in documents]
    if fit:
        embedder.fit(texts)
    matrix = embedder.transform(texts)
    for doc, vec in zip(documents, matrix):
        doc.embedding = vec
    return matrix


def get_embedder(kind: str = "hashing", **kwargs) -> Embedder:
    if kind == "hashing":
        return HashingSVDEmbedder(**kwargs)
    if kind == "sentence-transformer":
        return SentenceTransformerEmbedder(**kwargs)
    raise ValueError(f"unknown embedder kind: {kind!r}")
