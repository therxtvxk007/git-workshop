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
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit, cross_val_predict

from .calibration import Calibrator, SplitConformal
from .features import (
    GROUP_FEATURE_NAMES,
    DecayConfig,
    build_group_matrix,
    instance_matrix,
)
from .nmil import NestedMIL, NestedMILConfig, PooledGroup
from .schema import BagGroup, Forecast


@dataclass(slots=True)
class HybridConfig:
    lookback_days: int = 14
    half_life_days: float = 5.0
    nmil: NestedMILConfig = field(default_factory=NestedMILConfig)
    tabular_model: str = "logistic_l1"
    """Model for the tabular branch: ``logistic_l1`` (default), ``logistic_l2``,
    or ``gradient_boosting``.

    A linear model is the default because the boosted one measurably lost to it.
    Over four walk-forward folds the booster averaged 0.521 ROC-AUC against 0.574
    for L1 logistic and 0.557 for L2 -- and it also lost to a two-feature
    volume-only baseline (0.586), which is the signature of overfitting rather
    than of a hard problem. There are only ~18 correlated features and a few
    hundred labelled windows per fold; that is linear-model territory. L1 also
    zeroes most coefficients, so ``tabular_coefficients()`` reads as an
    explanation rather than an importance ranking."""
    logistic_C: float = 0.1
    gb_max_iter: int = 60
    gb_learning_rate: float = 0.05
    gb_max_leaf_nodes: int = 3
    gb_min_samples_leaf: int = 40
    gb_l2: float = 10.0
    n_meta_folds: int = 4
    blend_rule: str = "mean"
    """How to combine branches: ``mean`` (default), ``mil``, ``gradient_boosting``,
    ``meta``, or ``auto`` to pick per fit on the calibration slice.

    ``mean`` is the default because selection measurably lost to it here. The
    two branches are unstable in opposite directions across folds -- on one test
    window the MIL branch scored 0.706 ROC-AUC against the booster's 0.567, and
    on the next it scored 0.492 against the booster's 0.653. A selector judging
    on ~90 held-out windows (~19 positives) cannot tell those apart in advance:
    at the second cut it saw mil 0.682 / booster 0.374 and chose exactly wrong.
    Averaging gave 0.701 and 0.667 on those same two folds, beating per-fold
    selection's 0.701 and 0.492. Instability between branches is the reason to
    ensemble, not a reason to pick one."""
    calibration_method: str = "platt"
    """``platt`` (default), ``isotonic``, or ``none``.

    Platt is the default because it is strictly increasing and therefore cannot
    change how windows are ranked; isotonic is only weakly monotone and was
    observed collapsing whole folds to a constant probability."""
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
        self.gb = None
        self.meta: LogisticRegression | None = None
        self.calibrator = Calibrator(self.config.calibration_method)
        self.conformal = SplitConformal(alpha=self.config.conformal_alpha)
        self._pooled_dim: int | None = None
        self.blend_rule: str = "mean"
        self._branch_scale: dict[str, tuple[float, float]] = {}
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

    def _make_tabular(self):
        cfg = self.config
        if cfg.tabular_model == "gradient_boosting":
            return HistGradientBoostingClassifier(
                max_iter=cfg.gb_max_iter,
                learning_rate=cfg.gb_learning_rate,
                max_leaf_nodes=cfg.gb_max_leaf_nodes,
                min_samples_leaf=cfg.gb_min_samples_leaf,
                l2_regularization=cfg.gb_l2,
                early_stopping=False,
                random_state=cfg.random_state,
            )
        if cfg.tabular_model in {"logistic_l1", "logistic_l2"}:
            # l1_ratio rather than the deprecated penalty= argument.
            l1_ratio = 1.0 if cfg.tabular_model == "logistic_l1" else 0.0
            return make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    C=cfg.logistic_C,
                    solver="liblinear",
                    l1_ratio=l1_ratio,
                    max_iter=2000,
                    random_state=cfg.random_state,
                ),
            )
        raise ValueError(f"unknown tabular_model: {cfg.tabular_model!r}")

    def _fit_gb(self, groups: list[BagGroup], y: np.ndarray):
        X = build_group_matrix(groups, self.config.decay, self.config.lookback_days)
        model = self._make_tabular()
        model.fit(X, y)
        return model

    def _gb_scores(self, gb, groups: list[BagGroup]) -> np.ndarray:
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
        """Fit the branches, the meta-learner, the calibrator and the conformaliser.

        The calibration slice is the most recent ``calibration_fraction`` of the
        training windows and is held out of base-model training completely. An
        earlier version calibrated on data the branches had already fitted, which
        made the calibration inputs in-sample and overconfident; isotonic then
        learned a map that was wrong for genuinely unseen windows, and the
        deployed model scored *worse* than predicting the base rate. This is the
        prefit pattern -- the branches never see the calibration slice.
        """
        labelled = [g for g in groups if g.label is not None]
        if len(labelled) < 16:
            raise ValueError(f"need at least 16 labelled groups to fit, got {len(labelled)}")
        labelled = sorted(labelled, key=lambda g: (g.origin, g.region))
        y_all = np.array([g.label for g in labelled], dtype=np.int64)
        if len(np.unique(y_all)) < 2:
            raise ValueError("training groups contain only one class")

        n_cal = max(8, int(len(labelled) * calibration_fraction))
        n_cal = min(n_cal, len(labelled) - 8)
        fit_part, cal_part = labelled[:-n_cal], labelled[-n_cal:]
        y_fit = np.array([g.label for g in fit_part], dtype=np.int64)
        y_cal = np.array([g.label for g in cal_part], dtype=np.int64)
        if len(np.unique(y_fit)) < 2:
            raise ValueError("the base-model training slice contains only one class")

        # 1. Meta-features from forward-chaining folds inside the fit slice.
        oof, mask = self._forward_chaining_oof(fit_part, y_fit)
        if mask.sum() >= 8 and len(np.unique(y_fit[mask])) >= 2:
            self.meta = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
            self.meta.fit(oof[mask], y_fit[mask])
            self.diagnostics["meta_coef"] = self.meta.coef_.ravel().tolist()
            self.diagnostics["meta_n_train"] = int(mask.sum())
        else:
            self.meta = None
            self.diagnostics["meta_coef"] = None

        # 2. Branches, fitted on the fit slice only.
        self.mil = self._fit_mil(fit_part)
        self.gb = self._fit_gb(fit_part, y_fit)
        self.diagnostics["region_divergence"] = self.mil.region_divergence()

        # 3. Fix the combination rule (see HybridConfig.blend_rule for why the
        #    default is a plain average rather than a per-fit selection). When
        #    selection *is* requested it judges on the calibration slice, whose
        #    branches are the deployed ones -- judging on out-of-fold predictions
        #    is worse still, because the early folds train the MIL branch on a
        #    few dozen windows where it is pure overfit noise (measured: 0.464
        #    out-of-fold versus 0.706 on the matching test window).
        p_mil = self._mil_scores(self.mil, cal_part)
        p_gb = self._gb_scores(self.gb, cal_part)
        self._fit_branch_scale(p_mil, p_gb)
        if self.config.blend_rule == "auto":
            self.blend_rule = self._select_blend(p_mil, p_gb, y_cal)
        else:
            self.blend_rule = self.config.blend_rule
            self.diagnostics["blend_selection_auc"] = self._branch_auc(p_mil, p_gb, y_cal)
        self.diagnostics["blend_rule"] = self.blend_rule

        # 4. Calibrate and conformalise the winner on that same slice.
        cal_raw = self._combine(p_mil, p_gb)
        self.calibrator.fit(cal_raw, y_cal)
        self.conformal.fit(self.calibrator.transform(cal_raw), y_cal)
        self.diagnostics["calibration_method"] = self.calibrator.fitted_method
        self.diagnostics["conformal_thresholds"] = self.conformal.thresholds
        self.diagnostics["n_fit"] = len(fit_part)
        self.diagnostics["n_calibration"] = len(cal_part)
        return self

    def _branch_auc(self, p_mil: np.ndarray, p_gb: np.ndarray, y: np.ndarray) -> dict[str, float]:
        """Held-out AUC per branch. Recorded as a diagnostic even when the blend
        rule is fixed, so branch drift is visible across folds."""
        if len(np.unique(y)) < 2:
            return {}
        out = {}
        for name, p in (("mil", p_mil), ("gradient_boosting", p_gb),
                        ("mean", self._combine(p_mil, p_gb))):
            try:
                out[name] = float(roc_auc_score(y, p))
            except ValueError:
                out[name] = 0.5
        return out

    def _select_blend(self, p_mil: np.ndarray, p_gb: np.ndarray, y: np.ndarray) -> str:
        """Choose how to combine branches, judged on the held-out slice.

        Stacking is not guaranteed to beat its best branch: with few labelled
        windows the meta-learner is fitted on noisy inputs and can land well
        below either branch alone. So the rule is selected rather than assumed.
        The selection is over four options on one slice, so it carries a little
        optimism of its own; the walk-forward test folds remain untouched by it.
        """
        if len(np.unique(y)) < 2:
            return "mean"
        candidates: dict[str, np.ndarray] = {
            "mil": p_mil,
            "gradient_boosting": p_gb,
            "mean": 0.5 * (p_mil + p_gb),
        }
        if self.meta is not None:
            candidates["meta"] = self.meta.predict_proba(
                np.column_stack([p_mil, p_gb])
            )[:, 1]

        scores: dict[str, float] = {}
        for name, p in candidates.items():
            try:
                scores[name] = float(roc_auc_score(y, p))
            except ValueError:
                scores[name] = 0.5
        self.diagnostics["blend_selection_auc"] = scores

        best = max(scores, key=scores.__getitem__)
        # Prefer averaging over a single branch on a near-tie: two signals are
        # more robust than one, and the slice is too small to trust a 1% gap.
        if best in {"mil", "gradient_boosting"} and scores.get("mean", 0.0) >= scores[best] - 0.01:
            return "mean"
        return best

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(np.asarray(p, dtype=np.float64), 1e-6, 1 - 1e-6)
        return np.log(p / (1.0 - p))

    def _fit_branch_scale(self, p_mil: np.ndarray, p_gb: np.ndarray) -> None:
        """Record each branch's logit mean and spread on the calibration slice.

        Needed because a plain probability average is not scale-free: whichever
        branch has the wider spread dominates the sum regardless of which is
        more accurate. Measured here, averaging a MIL branch at 0.709 ROC-AUC
        with a booster at 0.509 produced 0.538 -- worse than either would
        suggest -- because the booster's probabilities were ~1.6x as spread out
        and swamped the sharper branch. Standardising both to zero mean and unit
        variance first makes the average a genuine consensus.

        The scale is learned once, on held-out data, so a single forecast can be
        combined without reference to the rest of its batch.
        """
        for name, p in (("mil", p_mil), ("gradient_boosting", p_gb)):
            z = self._logit(p)
            self._branch_scale[name] = (float(z.mean()), float(z.std()) or 1.0)

    def _standardise(self, name: str, p: np.ndarray) -> np.ndarray:
        mean, std = self._branch_scale.get(name, (0.0, 1.0))
        return (self._logit(p) - mean) / (std if std > 1e-9 else 1.0)

    def _combine(self, p_mil: np.ndarray, p_gb: np.ndarray) -> np.ndarray:
        """Combine branch probabilities into one uncalibrated score.

        Returns a score, not necessarily a probability -- the calibrator that
        follows is what turns it into one.
        """
        rule = getattr(self, "blend_rule", "mean")
        if rule == "mil":
            return p_mil
        if rule == "gradient_boosting":
            return p_gb
        if rule == "meta" and self.meta is not None:
            return self.meta.predict_proba(np.column_stack([p_mil, p_gb]))[:, 1]
        if rule == "prob_mean":
            return 0.5 * (p_mil + p_gb)
        # "mean": equal-weight average of standardised branch logits.
        return 0.5 * (
            self._standardise("mil", p_mil)
            + self._standardise("gradient_boosting", p_gb)
        )

    def _blend(self, groups: list[BagGroup]) -> np.ndarray:
        """Combine branch probabilities into a single uncalibrated score."""
        assert self.mil is not None and self.gb is not None
        return self._combine(
            self._mil_scores(self.mil, groups), self._gb_scores(self.gb, groups)
        )

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

    def tabular_coefficients(self) -> dict[str, float] | None:
        """Named coefficients of the tabular branch, when it is linear.

        With L1 most of these are exactly zero, so the non-zero ones are a
        compact statement of which stream dynamics the model is actually using.
        Returns ``None`` for the gradient-boosted branch, which has no
        coefficients to report.
        """
        if self.gb is None or not hasattr(self.gb, "named_steps"):
            return None
        lr = self.gb.named_steps.get("logisticregression")
        if lr is None:
            return None
        return dict(zip(GROUP_FEATURE_NAMES, lr.coef_.ravel().tolist()))

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
