"""Vector search behind one interface.

`MemoryEngine` is exact brute-force search in numpy. At the corpus sizes a
single analyst desk handles it is not merely adequate, it is *better* than an
approximate index: exact recall, no build step, no tuning, and no separate
service to keep alive. Qdrant and Vespa exist here for when that stops being
true, which is a scale decision, not a sophistication decision.

The interface is deliberately narrow -- add, search, and search with a
pre-filter -- because anything wider starts leaking engine-specific concepts
into the cascade.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


@dataclass
class Hit:
    doc_id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


class VectorEngine(Protocol):
    name: str

    def add(self, doc_ids: Sequence[str], vectors: np.ndarray,
            payloads: Sequence[dict] | None = None) -> None: ...

    def search(self, query: np.ndarray, k: int = 50,
               allowed: set[str] | None = None) -> list[Hit]: ...


class MemoryEngine:
    """Exact cosine search. Vectors are assumed L2-normalised on the way in."""

    name = "memory"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim
        self._ids: list[str] = []
        self._index: dict[str, int] = {}
        self._vecs: np.ndarray | None = None
        self._payloads: list[dict] = []

    def add(self, doc_ids: Sequence[str], vectors: np.ndarray,
            payloads: Sequence[dict] | None = None) -> None:
        if len(doc_ids) != len(vectors):
            raise ValueError("doc_ids and vectors must align")
        if not len(doc_ids):
            return
        vectors = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-9)
        self.dim = self.dim or vectors.shape[1]
        base = len(self._ids)
        self._ids.extend(doc_ids)
        for i, d in enumerate(doc_ids):
            self._index[d] = base + i
        self._payloads.extend(payloads or [{} for _ in doc_ids])
        self._vecs = vectors if self._vecs is None else np.vstack([self._vecs, vectors])

    def search(self, query: np.ndarray, k: int = 50,
               allowed: set[str] | None = None) -> list[Hit]:
        if self._vecs is None or not len(self._ids):
            return []
        q = np.asarray(query, dtype=np.float32).ravel()
        q = q / max(float(np.linalg.norm(q)), 1e-9)
        scores = self._vecs @ q

        if allowed is not None:
            mask = np.zeros(len(self._ids), dtype=bool)
            for d in allowed:
                i = self._index.get(d)
                if i is not None:
                    mask[i] = True
            if not mask.any():
                return []
            scores = np.where(mask, scores, -np.inf)

        k = min(k, int(np.isfinite(scores).sum()))
        if k <= 0:
            return []
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [Hit(self._ids[i], float(scores[i]), self._payloads[i])
                for i in idx if np.isfinite(scores[i])]

    def vector(self, doc_id: str) -> np.ndarray | None:
        i = self._index.get(doc_id)
        return None if i is None or self._vecs is None else self._vecs[i]

    def __len__(self) -> int:
        return len(self._ids)


class QdrantEngine:
    """Deployment backend. Named vectors carry dense and late-interaction
    representations in one collection so a single round trip serves both."""

    name = "qdrant"

    def __init__(self, collection: str = "pramaan", url: str = "http://localhost:6333",
                 dim: int = 1024, distance: str = "Cosine") -> None:
        self.collection = collection
        self.url = url
        self.dim = dim
        self.distance = distance
        self._client = None

    def _connect(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = QdrantClient(url=self.url)
            existing = {c.name for c in self._client.get_collections().collections}
            if self.collection not in existing:
                self._client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(
                        size=self.dim, distance=Distance[self.distance.upper()]
                    ),
                )
        return self._client

    def add(self, doc_ids: Sequence[str], vectors: np.ndarray,
            payloads: Sequence[dict] | None = None) -> None:
        from qdrant_client.models import PointStruct

        client = self._connect()
        points = [
            PointStruct(id=abs(hash(d)) % (1 << 62), vector=v.tolist(),
                        payload={"doc_id": d, **(payloads[i] if payloads else {})})
            for i, (d, v) in enumerate(zip(doc_ids, vectors, strict=True))
        ]
        for start in range(0, len(points), 256):
            client.upsert(collection_name=self.collection, points=points[start : start + 256])

    def search(self, query: np.ndarray, k: int = 50,
               allowed: set[str] | None = None) -> list[Hit]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        client = self._connect()
        flt = None
        if allowed is not None:
            flt = Filter(must=[FieldCondition(key="doc_id", match=MatchAny(any=list(allowed)))])
        res = client.query_points(
            collection_name=self.collection, query=np.asarray(query).ravel().tolist(),
            limit=k, query_filter=flt, with_payload=True,
        ).points
        return [Hit(p.payload["doc_id"], float(p.score), dict(p.payload)) for p in res]


class VespaEngine:
    """Deployment backend for when ranking needs to move server-side.

    Vespa earns its complexity only when the ranking expression itself belongs
    next to the data -- multi-phase ranking over tensors that would otherwise be
    shipped to the client. Below that, it is a large amount of configuration to
    reproduce what `MemoryEngine` already does exactly.
    """

    name = "vespa"

    def __init__(self, endpoint: str = "http://localhost:8080",
                 schema: str = "evidence", rank_profile: str = "hybrid") -> None:
        self.endpoint = endpoint
        self.schema = schema
        self.rank_profile = rank_profile
        self._session = None

    def _connect(self):
        if self._session is None:
            import httpx

            self._session = httpx.Client(base_url=self.endpoint, timeout=30.0)
        return self._session

    def add(self, doc_ids: Sequence[str], vectors: np.ndarray,
            payloads: Sequence[dict] | None = None) -> None:
        s = self._connect()
        for i, (d, v) in enumerate(zip(doc_ids, vectors, strict=True)):
            s.post(
                f"/document/v1/{self.schema}/{self.schema}/docid/{d}",
                json={"fields": {"doc_id": d, "embedding": {"values": v.tolist()},
                                 **(payloads[i] if payloads else {})}},
            )

    def search(self, query: np.ndarray, k: int = 50,
               allowed: set[str] | None = None) -> list[Hit]:
        s = self._connect()
        yql = f"select * from {self.schema} where {{targetHits:{k}}}nearestNeighbor(embedding, q)"
        if allowed:
            ids = ", ".join(f'"{d}"' for d in allowed)
            yql += f" and doc_id in ({ids})"
        r = s.post("/search/", json={
            "yql": yql, "ranking.profile": self.rank_profile,
            "input.query(q)": {"values": np.asarray(query).ravel().tolist()},
            "hits": k,
        })
        r.raise_for_status()
        children = r.json().get("root", {}).get("children", [])
        return [Hit(c["fields"]["doc_id"], float(c.get("relevance", 0.0)), c["fields"])
                for c in children]


def build_engine(name: str, dim: int = 1024, **kwargs) -> VectorEngine:
    if name == "memory":
        return MemoryEngine(dim=dim)
    if name == "qdrant":
        return QdrantEngine(dim=dim, **kwargs)
    if name == "vespa":
        return VespaEngine(**kwargs)
    raise ValueError(f"unknown retrieval engine {name!r}")
