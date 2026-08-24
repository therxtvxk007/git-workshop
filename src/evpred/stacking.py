"""The hybrid: a semantic MIL branch stacked with a classical tabular branch.

Why two branches rather than one model
--------------------------------------
They fail differently, which is the only reason stacking helps. The MIL branch
reads *what the text says* -- it can fire on a single article announcing a
called strike, in a region with no prior activity. The gradient-boosted branch
reads *the shape of the stream* -- volume bursts, negativity acceleration,
source diversity -- and is robust when individual articles are noisy or the
extractor misfires. Averaging correlated models buys nothing; these two are
decorrelated by construction, and the meta-learner is what discovers the
weighting from data instead of a hand-set constant.

Leakage discipline
------------------
Out-of-fold predictions for the meta-learner come from **forward-chaining**
folds, never random K-fold. With random folds the meta-features for an early
window are produced by base models that saw later windows, the meta-learner
learns on impossibly good inputs, and the whole stack is optimistic in a way no
downstream metric reveals. Every split in this module is by forecast origin.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from .calibration import Calibrator, SplitConformal
from .features import DecayConfig, build_group_matrix, instance_matrix
from .nmil import NestedMIL, NestedMILConfig, PooledGroup
from .schema import BagGroup, Forecast


@dataclass(slots=True)
class HybridConfig:
    lookback_days: int = 14
    half_life_days: float = 5.0
    nmil: NestedMILConfig = field(default_factory=NestedMILConfig)
    gb_max_iter: int = 200
    gb_learning_rate: float = 0.06
    gb_max_leaf_nodes: int = 15
    gb_min_samples_leaf: int = 10
    n_meta_folds: int = 4
    calibration_method: str = "isotonic"
    conformal_alpha: float = 0.1
    random_state: int = 0

    @property
    def decay(self) -> DecayConfig:
        return DecayConfig(half_life_days=self.half_life_days)


def to_pooled(group: BagGroup, decay: DecayConfig) -> PooledGroup:
    """Flatten a ``BagGroup`` into the array form the MIL model consumes."""
    X, docs = instance_matrix(group, decay)
    if not docs:
        return PooledGroup(
            X=np.zeros((0, 0)), bag_index=np.zeros(0, dtype=int),
            n_bags=0, region=group.region, label=group.label,
        )
    dates = sorted({d.date for d in docs})
    day_of = {d: i for i, d in enumerate(dates)}
    bag_index = np.array([day_of[d.date] for d in docs], dtype=int)
    return PooledGroup(
        X=X, bag_index=bag_index, n_bags=len(dates),
        region=group.region, label=group.label,
    )


class HybridEventPredictor:
    """Two-branch stacked forecaster with calibration and conformal abstention."""

    def __init__(self, config: HybridConfig | None = None) -> None:
        self.config = config or HybridConfig()
        self.mil: NestedMIL | None = None
        self.gb: HistGradientBoostingClassifier | None = None
        self.meta: LogisticRegression | None = None
        self.calibrator = Calibrator(self.config.calibration_method)
        self.conformal = SplitConformal(alpha=self.config.conformal_alpha)
        self._pooled_dim: int | None = None
        self.diagnostics: dict[str, object] = {}

    # -- base branches ---------------------------------------------------

    def _fit_mil(self, groups: list[BagGroup]) -> NestedMIL:
        pooled = [to_pooled(g, self.config.decay) for g in groups]
        usable = [p for p in pooled if p.label is not None and p.X.shape[0] > 0]
        if not usable:
            raise ValueError("no non-empty labelled groups available to fit the MIL branch")
        self._pooled_dim = usable[0].X.shape[1]
        model = NestedMIL(self.config.nmil)
        model.fit(usable)
        return model

    def _mil_scores(self, model: NestedMIL, groups: list[BagGroup]) -> np.ndarray:
        pooled = []
        for g in groups:
            p = to_pooled(g, self.config.decay)
            if p.X.shape[0] == 0 and self._pooled_dim:
                p.X = np.zeros((0, self._pooled_dim), dtype=np.float64)
            pooled.append(p)
        return model.predict_proba(pooled)

    def _fit_gb(self, groups: list[BagGroup], y: np.ndarray) -> HistGradientBoostingClassifier:
        X = build_group_matrix(groups, self.config.decay, self.config.lookback_days)
        cfg = self.config
        gb = HistGradientBoostingClassifier(
            max_iter=cfg.gb_max_iter,
            learning_rate=cfg.gb_learning_rate,
            max_leaf_nodes=cfg.gb_max_leaf_nodes,
            min_samples_leaf=cfg.gb_min_samples_leaf,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=cfg.random_state,
        )
        gb.fit(X, y)
        return gb

    def _gb_scores(self, gb: HistGradientBoostingClassifier, groups: list[BagGroup]) -> np.ndarray:
        X = build_group_matrix(groups, self.config.decay, self.config.lookback_days)
        return gb.predict_proba(X)[:, 1]

    # -- meta learner ----------------------------------------------------

    def _forward_chaining_oof(
        self, groups: list[BagGroup], y: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Out-of-fold meta-features from expanding-window temporal folds.

        Fold ``k`` trains on the earliest ``k`` blocks and predicts block
        ``k+1``. The first block is never predicted (nothing precedes it), so it
        is excluded from meta-training via the returned mask.
        """
        order = np.argsort([g.origin for g in groups], kind="stable")
        n_folds = max(2, self.config.n_meta_folds)
        blocks = np.array_split(order, n_folds + 1)

        oof = np.full((len(groups), 2), np.nan, dtype=np.float64)
        for k in range(1, len(blocks)):
            train_idx = np.concatenate(blocks[:k])
            test_idx = blocks[k]
            if test_idx.size == 0 or len(np.unique(y[train_idx])) < 2:
                continue
            tr = [groups[i] for i in train_idx]
            te = [groups[i] for i in test_idx]
            try:
                mil = self._fit_mil(tr)
                oof[test_idx, 0] = self._mil_scores(mil, te)
            except ValueError:
                pass
            gb = self._fit_gb(tr, y[train_idx])
            oof[test_idx, 1] = self._gb_scores(gb, te)

        mask = ~np.isnan(oof).any(axis=1)
        return oof, mask

    def fit(self, groups: list[BagGroup], calibration_fraction: float = 0.25) -> "HybridEventPredictor":
        labelled = [g for g in groups if g.label is not None]
        if len(labelled) < 8:
            raise ValueError(f"need at least 8 labelled groups to fit, got {len(labelled)}")
        labelled = sorted(labelled, key=lambda g: (g.origin, g.region))
        y = np.array([g.label for g in labelled], dtype=np.int64)
        if len(np.unique(y)) < 2:
            raise ValueError("training groups contain only one class")

        # 1. Meta-features via forward chaining, then the meta-learner.
        oof, mask = self._forward_chaining_oof(labelled, y)
        if mask.sum() >= 4 and len(np.unique(y[mask])) >= 2:
            self.meta = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
            self.meta.fit(oof[mask], y[mask])
            self.diagnostics["meta_coef"] = self.meta.coef_.ravel().tolist()
            self.diagnostics["meta_n_train"] = int(mask.sum())
        else:
            # Not enough clean out-of-fold rows: fall back to an equal-weight
            # average rather than a meta-learner fitted on leaky inputs.
            self.meta = None
            self.diagnostics["meta_coef"] = None

        # 2. Refit both branches on everything for deployment.
        self.mil = self._fit_mil(labelled)
        self.gb = self._fit_gb(labelled, y)
        self.diagnostics["region_divergence"] = self.mil.region_divergence()

        # 3. Calibrate + conformalise on the most recent held-out slice, so the
        #    calibration map is fitted on data later than what trained the model.
        n_cal = max(4, int(len(labelled) * calibration_fraction))
        cal_groups = labelled[-n_cal:]
        cal_y = y[-n_cal:]
        cal_raw = self._blend(cal_groups)
        self.calibrator.fit(cal_raw, cal_y)
        cal_p = self.calibrator.transform(cal_raw)
        self.conformal.fit(cal_p, cal_y)
        self.diagnostics["calibration_method"] = self.calibrator.fitted_method
        self.diagnostics["conformal_thresholds"] = self.conformal.thresholds
        return self

    def _blend(self, groups: list[BagGroup]) -> np.ndarray:
        """Combine branch probabilities into a single uncalibrated score."""
        assert self.mil is not None and self.gb is not None
        p_mil = self._mil_scores(self.mil, groups)
        p_gb = self._gb_scores(self.gb, groups)
        stacked = np.column_stack([p_mil, p_gb])
        if self.meta is not None:
            return self.meta.predict_proba(stacked)[:, 1]
        return stacked.mean(axis=1)

    def predict_proba(self, groups: list[BagGroup]) -> np.ndarray:
        return self.calibrator.transform(self._blend(groups))

    def branch_probabilities(self, groups: list[BagGroup]) -> dict[str, np.ndarray]:
        """Per-branch probabilities, for ablation and diagnosis."""
        assert self.mil is not None and self.gb is not None
        return {
            "mil": self._mil_scores(self.mil, groups),
            "gradient_boosting": self._gb_scores(self.gb, groups),
            "stacked": self.predict_proba(groups),
        }

    def predict(self, groups: list[BagGroup], top_k_evidence: int = 5) -> list[Forecast]:
        """Full forecasts: calibrated probability, conformal set, and evidence."""
        from .evidence import extract_precursors  # local import avoids a cycle

        raw = self._blend(groups)
        probs = self.calibrator.transform(raw)
        sets = self.conformal.predict_set(probs)
        out: list[Forecast] = []
        for group, r, p, s in zip(groups, raw, probs, sets):
            out.append(
                Forecast(
                    region=group.region,
                    origin=group.origin,
                    horizon_days=group.horizon_days,
                    probability=float(p),
                    raw_score=float(r),
                    precursors=extract_precursors(self, group, top_k=top_k_evidence),
                    conformal_set=s,
                    label=group.label,
                )
            )
        return out
