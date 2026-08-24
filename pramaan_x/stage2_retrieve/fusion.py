"""Rank fusion: reciprocal rank first, then a learned ranker.

RRF is the robust default. It uses only ranks, so it cannot be destabilised by
one retriever whose scores are on a different scale -- the failure that makes
naive score averaging unreliable the moment a new retriever is added.

LambdaMART is layered on top because RRF cannot learn that, for this corpus,
BM25 outranks dense retrieval on place names while the reverse holds for
paraphrased description. The weights in the brief's scoring formula are
*learned here*, from relevance labels under temporal cross-validation, and never
hand-set.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

COMPONENTS = ("bm25", "dense", "late", "cross", "recency",
              "long_history", "novelty", "source_independence")


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]],
    *,
    k: int = 60,
    weights: Mapping[str, float] | None = None,
) -> list[tuple[str, float]]:
    """RRF over named rankings. `k` damps the contribution of deep ranks; 60 is
    the value from Cormack et al. and behaves well without tuning."""
    scores: dict[str, float] = {}
    for name, ranked in rankings.items():
        w = float(weights.get(name, 1.0)) if weights else 1.0
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
    # doc_id breaks ties, so the fused order is a function of the inputs and
    # not of dict insertion order.
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


@dataclass
class LearnedFusion:
    """LightGBM LambdaMART over the component scores.

    Trained with per-query groups and NDCG objective, which is the whole point:
    a pointwise regressor optimises absolute score error, whereas retrieval only
    cares about the order within a query.
    """

    components: tuple[str, ...] = COMPONENTS
    n_estimators: int = 300
    learning_rate: float = 0.06
    num_leaves: int = 31
    label_gain: tuple[int, ...] = (0, 1, 3, 7)
    random_state: int = 20260824
    _model: object | None = field(default=None, repr=False)
    fitted: bool = False
    backend: str = "lambdarank"

    def _matrix(self, rows: Sequence[Mapping[str, float]]) -> np.ndarray:
        return np.array([[float(r.get(c, 0.0)) for c in self.components] for r in rows],
                        dtype=np.float64)

    def fit(
        self,
        features: Sequence[Mapping[str, float]],
        labels: Sequence[int],
        groups: Sequence[int],
    ) -> LearnedFusion:
        """`groups` gives the number of candidates per query, in order."""
        X = self._matrix(features)
        y = np.asarray(labels, dtype=int)
        if X.shape[0] != y.shape[0] or int(np.sum(groups)) != X.shape[0]:
            raise ValueError("features, labels and groups must describe the same rows")
        try:
            import lightgbm as lgb

            self._model = lgb.LGBMRanker(
                objective="lambdarank", metric="ndcg",
                n_estimators=self.n_estimators, learning_rate=self.learning_rate,
                num_leaves=self.num_leaves, random_state=self.random_state,
                label_gain=list(self.label_gain), verbose=-1,
                min_child_samples=5,
                # Reproducibility, not speed. LightGBM's default histogram
                # construction is thread-count dependent: the same data and the
                # same seed give different trees on a machine with a different
                # core count or a different load, which for a benchmark whose
                # whole claim is reproducibility is fatal. `deterministic` plus
                # `force_row_wise` plus a single thread fixes the result at the
                # cost of wall-clock time we can afford at this corpus size.
                deterministic=True, force_row_wise=True, num_threads=1,
            )
            self._model.fit(X, y, group=list(groups))
            self.backend = "lambdarank"
        except ImportError:
            # Ridge on rank-normalised targets. Weaker, but it still *learns*
            # the component weights rather than reverting to hand-set ones.
            from sklearn.linear_model import Ridge

            self._model = Ridge(alpha=1.0).fit(X, y.astype(float))
            self.backend = "ridge"
        self.fitted = True
        return self

    def score(self, features: Sequence[Mapping[str, float]]) -> np.ndarray:
        if not self.fitted or self._model is None:
            raise RuntimeError("LearnedFusion.fit must be called before scoring")
        return np.asarray(self._model.predict(self._matrix(features)), dtype=np.float64)

    def weights(self) -> dict[str, float]:
        """Learned component importance -- the empirical answer to 'what are the
        alphas in the scoring formula'."""
        if not self.fitted:
            return {}
        if self.backend == "lambdarank":
            imp = np.asarray(self._model.feature_importances_, dtype=float)
        else:
            imp = np.abs(np.asarray(self._model.coef_).ravel())
        total = imp.sum() or 1.0
        return {c: float(v / total) for c, v in zip(self.components, imp, strict=True)}
