"""Cheap relevance model for the stage-1 gate.

Gradient boosting over a handful of cheap features. Deliberately not a
transformer: this model sees every surviving document in the corpus, so its cost
multiplies by the corpus size, and the features that matter at this stage --
lexicon weight, source reliability, entity density -- are tabular.

Tuned for recall. The operating point is chosen as the threshold that retains a
target recall on held-out data, not the one that maximises F1; stage 1 losing a
document is unrecoverable, whereas passing a useless one costs a few
milliseconds downstream.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from ..types import Document
from .bm25 import tokenize
from .lexical import LexicalIndicators

FEATURE_NAMES = (
    "lexical_score", "lexical_max_type", "n_tokens", "n_sentences",
    "source_reliability", "has_location", "digit_ratio", "unique_ratio",
    "type_margin", "title_lexical",
)


def cheap_features(
    doc: Document,
    lexicon: LexicalIndicators,
    event_types: Sequence[str],
    source_reliability: dict[str, float],
    gazetteer: set[str],
) -> np.ndarray:
    text = doc.full_text
    toks = tokenize(text)
    n = max(len(toks), 1)
    per_type = sorted((lexicon.score(text, et) for et in event_types), reverse=True)
    best = per_type[0] if per_type else 0.0
    runner = per_type[1] if len(per_type) > 1 else 0.0
    digits = sum(c.isdigit() for c in text)
    return np.array([
        lexicon.score(text),
        best,
        float(n),
        float(text.count(".") + 1),
        source_reliability.get(doc.meta.get("source_family", ""), 0.6),
        1.0 if any(g.lower() in text.lower() for g in gazetteer) else 0.0,
        digits / max(len(text), 1),
        len(set(toks)) / n,
        best - runner,
        lexicon.score(doc.title) if doc.title else 0.0,
    ], dtype=np.float64)


@dataclass
class RelevanceModel:
    """LightGBM when available, logistic regression otherwise. Both are real
    choices; the bake-off decides which ships."""

    backend: str = "lightgbm"
    threshold: float = 0.12
    target_recall: float = 0.98
    _model: object | None = field(default=None, repr=False)
    _scaler_mean: np.ndarray | None = field(default=None, repr=False)
    _scaler_std: np.ndarray | None = field(default=None, repr=False)
    fitted: bool = False

    def fit(self, X: np.ndarray, y: np.ndarray, *, seed: int = 20260824) -> RelevanceModel:
        y = np.asarray(y).astype(int)
        if len(np.unique(y)) < 2:
            raise ValueError("relevance model needs both classes in training data")
        if self.backend == "lightgbm":
            try:
                import lightgbm as lgb

                pos = float((y == 1).sum())
                neg = float((y == 0).sum())
                self._model = lgb.LGBMClassifier(
                    n_estimators=300, learning_rate=0.06, num_leaves=31,
                    min_child_samples=20, subsample=0.9, subsample_freq=1,
                    colsample_bytree=0.9, random_state=seed, verbose=-1,
                    # Recall is what this stage is for; the class weight makes
                    # the loss reflect that rather than the base rate.
                    scale_pos_weight=max(neg / max(pos, 1.0), 1.0),
                )
                self._model.fit(X, y)
                self.fitted = True
                return self
            except ImportError:
                self.backend = "logistic"
        from sklearn.linear_model import LogisticRegression

        self._scaler_mean = X.mean(axis=0)
        self._scaler_std = np.maximum(X.std(axis=0), 1e-9)
        Z = (X - self._scaler_mean) / self._scaler_std
        self._model = LogisticRegression(
            max_iter=2000, class_weight="balanced", random_state=seed
        ).fit(Z, y)
        self.fitted = True
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.fitted or self._model is None:
            raise RuntimeError("RelevanceModel.fit must be called first")
        if self.backend != "lightgbm":
            X = (X - self._scaler_mean) / self._scaler_std
        return self._model.predict_proba(X)[:, 1]

    def calibrate_threshold(self, X: np.ndarray, y: np.ndarray,
                            target_recall: float | None = None) -> float:
        """Pick the highest threshold that still holds the recall target on
        held-out data. This is the operating point, and it is chosen on data the
        model did not see -- picking it on the training fold is how a stage-1
        gate silently starts dropping events in production."""
        target = target_recall if target_recall is not None else self.target_recall
        p = self.predict_proba(X)
        y = np.asarray(y).astype(int)
        pos = p[y == 1]
        if pos.size == 0:
            self.threshold = 0.0
            return 0.0
        # The quantile of positive scores that leaves `target` fraction above.
        self.threshold = float(np.quantile(pos, max(0.0, 1.0 - target)))
        return self.threshold

    def feature_importance(self) -> dict[str, float]:
        if not self.fitted:
            return {}
        if self.backend == "lightgbm":
            imp = np.asarray(self._model.feature_importances_, dtype=float)
        else:
            imp = np.abs(np.asarray(self._model.coef_).ravel())
        total = imp.sum() or 1.0
        return {n: float(v / total) for n, v in zip(FEATURE_NAMES, imp, strict=True)}
