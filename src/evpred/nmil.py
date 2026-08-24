"""Nested multiple-instance learning with regularised multi-task heads.

The surveyed nMIL work forecasts societal events from news and recovers
precursors, but the survey itself flags two limitations (G5): it was validated
on one geography, and it does not use regularised multi-task learning. This
module addresses both.

Structure
---------
Instances (documents) pool into bags (region-days), bags pool into a group
(region-window) that carries the only observed label::

    s_i = (w0 + v_r) . x_i + (b0 + c_r)              instance logit
    u_b = t1 * log( mean_i exp(s_i / t1) )           within-day pooling
    S_g = t2 * log( mean_b exp(u_b / t2) )           across-day pooling
    p_g = sigmoid(S_g)

Both pooling steps are smooth maxima (log-sum-exp). The temperature interpolates
between max-pooling (standard MIL, ``t -> 0``) and mean-pooling (``t -> inf``).
Smoothness matters here beyond optimisation convenience: hard max attributes a
forecast to exactly one article, which is useless as evidence, while mean
pooling drowns a single decisive report in routine coverage.

Multi-task regularisation
-------------------------
Each region ``r`` gets its own deviation ``v_r`` from a shared trunk ``w0``,
penalised as ``lambda_task * ||v_r||^2`` (Evgeniou & Pontil style). Large
``lambda_task`` collapses every region onto one global model; small values give
fully independent per-region models. This lets a region with few labelled
windows borrow strength from the rest instead of overfitting -- exactly the
"tested only on Latin America" generalisation problem.

Precursor attribution
---------------------
``dS_g / ds_i = beta_b * alpha_i``, the product of the two pooling softmaxes.
That is an exact sensitivity of the forecast to each document, available in
closed form -- no post-hoc surrogate explainer, so the evidence the system shows
is the evidence the model actually used.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from threadpoolctl import threadpool_limits
from scipy.special import expit


@dataclass(slots=True)
class PooledGroup:
    """One forecasting unit, flattened for vectorised pooling."""

    X: np.ndarray               # (n_instances, d)
    bag_index: np.ndarray       # (n_instances,) which bag each instance is in
    n_bags: int
    region: str
    label: int | None = None
    _members: list[np.ndarray] | None = None

    def members(self) -> list[np.ndarray]:
        """Instance indices per bag, computed once and cached.

        The optimiser evaluates the objective hundreds of times over the same
        groups; recomputing ``flatnonzero`` per bag per evaluation dominated the
        fit before this was cached.
        """
        if self._members is None:
            order = np.argsort(self.bag_index, kind="stable")
            sorted_bags = self.bag_index[order]
            bounds = np.searchsorted(sorted_bags, np.arange(self.n_bags + 1))
            self._members = [
                order[bounds[b] : bounds[b + 1]] for b in range(self.n_bags)
            ]
        return self._members


# --------------------------------------------------------------------------
# Compiled batch form.
#
# The objective is evaluated a few hundred times by L-BFGS over the same groups.
# Looping over groups in Python cost ~0.12s per evaluation at 500 groups, which
# made a single fit take half a minute and a full backtest unusable. Flattening
# every instance into one array and doing the two pooling levels with segmented
# reductions (``np.maximum.reduceat`` / ``np.add.reduceat``) turns the whole
# objective into a handful of BLAS calls.
# --------------------------------------------------------------------------

@dataclass(slots=True)
class _Compiled:
    """All groups flattened into contiguous, segment-sorted arrays."""

    X: np.ndarray            # (N, d) instances, sorted by (group, bag)
    seg_starts: np.ndarray   # (S,) offset of each bag into X
    seg_counts: np.ndarray   # (S,)
    seg_group: np.ndarray    # (S,) group id per bag
    grp_starts: np.ndarray   # (G_ne,) offset of each non-empty group into segments
    grp_counts: np.ndarray   # (G_ne,)
    inst_region: np.ndarray  # (N,) region id per instance
    inst_group: np.ndarray   # (N,) local (non-empty) group id per instance
    y: np.ndarray            # (G_ne,) labels of non-empty groups
    region_slices: list[tuple[int, int]]
    """Contiguous instance range per region. Groups are compiled region-major so
    each region's head applies to a slice (a view), not a fancy index."""
    empty_region: np.ndarray  # region ids of label-carrying groups with no text
    empty_y: np.ndarray
    d: int
    n_regions: int


def _compile(groups: list[PooledGroup], region_index: dict[str, int], d: int) -> _Compiled:
    """Flatten groups into segment-sorted arrays, region-major.

    Groups are emitted in region order so that each region's instances form one
    contiguous block; the objective then applies per-region heads with slices
    (views) instead of boolean masks (copies).
    """
    Xs: list[np.ndarray] = []
    seg_counts: list[int] = []
    seg_group: list[int] = []
    grp_counts: list[int] = []
    ys: list[float] = []
    inst_region: list[np.ndarray] = []
    inst_group: list[np.ndarray] = []
    empty_region: list[int] = []
    empty_y: list[float] = []

    n_regions = len(region_index)
    region_bounds = [[0, 0] for _ in range(n_regions)]
    g_local = 0
    n_inst = 0

    for g in sorted(groups, key=lambda gg: region_index[gg.region]):
        r = region_index[g.region]
        if g.X.shape[0] == 0:
            empty_region.append(r)
            empty_y.append(float(g.label))
            continue

        block_start = n_inst
        n_segs_before = len(seg_counts)
        for idx in g.members():
            if idx.size == 0:
                continue
            Xs.append(g.X[idx])
            seg_counts.append(int(idx.size))
            seg_group.append(g_local)
            inst_region.append(np.full(idx.size, r, dtype=np.int64))
            inst_group.append(np.full(idx.size, g_local, dtype=np.int64))
            n_inst += int(idx.size)

        if len(seg_counts) == n_segs_before:  # every bag empty -> textless group
            empty_region.append(r)
            empty_y.append(float(g.label))
            continue

        if region_bounds[r][1] == region_bounds[r][0]:
            region_bounds[r][0] = block_start
        region_bounds[r][1] = n_inst
        grp_counts.append(len(seg_counts) - n_segs_before)
        ys.append(float(g.label))
        g_local += 1

    if not Xs:
        raise ValueError("no instances to compile")

    seg_counts_a = np.asarray(seg_counts, dtype=np.int64)
    grp_counts_a = np.asarray(grp_counts, dtype=np.int64)
    return _Compiled(
        X=np.vstack(Xs),
        seg_starts=np.concatenate([[0], np.cumsum(seg_counts_a)[:-1]]).astype(np.int64),
        seg_counts=seg_counts_a,
        seg_group=np.asarray(seg_group, dtype=np.int64),
        grp_starts=np.concatenate([[0], np.cumsum(grp_counts_a)[:-1]]).astype(np.int64),
        grp_counts=grp_counts_a,
        inst_region=np.concatenate(inst_region),
        inst_group=np.concatenate(inst_group),
        y=np.asarray(ys, dtype=np.float64),
        region_slices=[(int(a), int(b)) for a, b in region_bounds],
        empty_region=np.asarray(empty_region, dtype=np.int64),
        empty_y=np.asarray(empty_y, dtype=np.float64),
        d=d,
        n_regions=n_regions,
    )


def _segment_lse(
    values: np.ndarray, starts: np.ndarray, counts: np.ndarray, tau: float
) -> tuple[np.ndarray, np.ndarray]:
    """Mean-normalised log-sum-exp over contiguous segments.

    Returns ``(tau * log(mean_j exp(v_j / tau)))`` per segment and the softmax
    weights within each segment. Shifted by the per-segment max for stability.
    """
    z = values / tau
    seg_max = np.maximum.reduceat(z, starts)
    ez = np.exp(z - np.repeat(seg_max, counts))
    seg_sum = np.add.reduceat(ez, starts)
    pooled = tau * (seg_max + np.log(seg_sum) - np.log(counts))
    weights = ez / np.repeat(seg_sum, counts)
    return pooled, weights


@dataclass(slots=True)
class NestedMILConfig:
    tau_instance: float = 0.5
    tau_bag: float = 0.7
    lambda_global: float = 1.0
    lambda_task: float = 5.0
    max_iter: int = 300
    tol: float = 1e-7
    verbose: bool = False


@dataclass(slots=True)
class _Fitted:
    w0: np.ndarray
    b0: float
    V: np.ndarray               # (n_regions, d)
    c: np.ndarray               # (n_regions,)
    regions: list[str]
    region_index: dict[str, int] = field(default_factory=dict)


class NestedMIL:
    """Nested MIL classifier with per-region multi-task heads."""

    def __init__(self, config: NestedMILConfig | None = None) -> None:
        self.config = config or NestedMILConfig()
        self._fit: _Fitted | None = None
        self.n_iter_: int = 0
        self.loss_: float = float("nan")

    # -- pooling ---------------------------------------------------------

    def _pool(
        self,
        scores: np.ndarray,
        members: list[np.ndarray],
    ) -> tuple[float, np.ndarray]:
        """Two-level smooth-max pooling.

        Returns the group score and the per-instance attribution weights
        ``beta_b * alpha_i`` (which sum to 1 across instances).
        """
        cfg = self.config
        if scores.size == 0:
            return 0.0, np.zeros(0, dtype=np.float64)

        t1, t2 = cfg.tau_instance, cfg.tau_bag
        attribution = np.zeros(scores.shape[0], dtype=np.float64)
        u: list[float] = []
        live: list[np.ndarray] = []

        for idx in members:
            if idx.size == 0:
                continue
            z = scores[idx] / t1
            zmax = float(z.max())
            ez = np.exp(z - zmax)
            total = float(ez.sum())
            u.append(t1 * (zmax + np.log(total) - np.log(idx.size)))
            # alpha_i within this bag, parked in the attribution buffer.
            attribution[idx] = ez / total
            live.append(idx)

        if not u:
            return 0.0, attribution

        ua = np.asarray(u, dtype=np.float64) / t2
        umax = float(ua.max())
        eu = np.exp(ua - umax)
        utotal = float(eu.sum())
        group_score = float(t2 * (umax + np.log(utotal) - np.log(len(u))))
        beta = eu / utotal

        for b_weight, idx in zip(beta, live):
            attribution[idx] *= b_weight
        return group_score, attribution

    # -- objective -------------------------------------------------------

    def _unpack(self, theta: np.ndarray, d: int, n_regions: int) -> _Fitted:
        off = 0
        w0 = theta[off : off + d]; off += d
        b0 = float(theta[off]); off += 1
        V = theta[off : off + n_regions * d].reshape(n_regions, d); off += n_regions * d
        c = theta[off : off + n_regions]
        return _Fitted(w0=w0, b0=b0, V=V, c=c, regions=self._regions)

    def _scores(self, f: _Fitted, c: _Compiled) -> np.ndarray:
        """Instance logits, one matvec per contiguous region block."""
        scores = np.empty(c.X.shape[0], dtype=np.float64)
        for r, (a, b) in enumerate(c.region_slices):
            if b > a:
                scores[a:b] = c.X[a:b] @ (f.w0 + f.V[r]) + (f.b0 + f.c[r])
        return scores

    def _objective(
        self, theta: np.ndarray, c: _Compiled, d: int, n_regions: int
    ) -> tuple[float, np.ndarray]:
        cfg = self.config
        f = self._unpack(theta, d, n_regions)

        scores = self._scores(f, c)
        # Level 1: pool instances within each bag (region-day).
        u, alpha = _segment_lse(scores, c.seg_starts, c.seg_counts, cfg.tau_instance)
        # Level 2: pool bags within each group (region-window).
        S, beta = _segment_lse(u, c.grp_starts, c.grp_counts, cfg.tau_bag)

        # dS_g/ds_i = beta_b * alpha_i, broadcast from bags back to instances.
        attribution = alpha * np.repeat(beta, c.seg_counts)

        loss = float(np.sum(np.logaddexp(0.0, S) - c.y * S))
        dscore = expit(S) - c.y                     # (G_ne,)
        coef = dscore[c.inst_group] * attribution   # (N,)

        # grad_V[r] = sum_{i in region r} coef_i x_i over that region's slice;
        # grad_w0 is the same sum over every instance, i.e. the row total.
        grad_V = np.zeros((n_regions, d), dtype=np.float64)
        grad_c = np.zeros(n_regions, dtype=np.float64)
        for r, (a, b) in enumerate(c.region_slices):
            if b > a:
                grad_V[r] = coef[a:b] @ c.X[a:b]
                grad_c[r] = float(coef[a:b].sum())
        grad_w0 = grad_V.sum(axis=0)
        grad_b0 = float(coef.sum())

        # Groups with no text at all: the score is the region bias alone.
        if c.empty_y.size:
            s_empty = f.b0 + f.c[c.empty_region]
            loss += float(np.sum(np.logaddexp(0.0, s_empty) - c.empty_y * s_empty))
            d_empty = expit(s_empty) - c.empty_y
            grad_b0 += float(d_empty.sum())
            np.add.at(grad_c, c.empty_region, d_empty)

        loss += cfg.lambda_global * float(np.dot(f.w0, f.w0))
        loss += cfg.lambda_task * float(np.sum(f.V * f.V))
        grad_w0 = grad_w0 + 2.0 * cfg.lambda_global * f.w0
        grad_V = grad_V + 2.0 * cfg.lambda_task * f.V

        return loss, np.concatenate([grad_w0, [grad_b0], grad_V.ravel(), grad_c])

    # -- public API ------------------------------------------------------

    def fit(self, groups: list[PooledGroup]) -> "NestedMIL":
        labelled = [g for g in groups if g.label is not None]
        if not labelled:
            raise ValueError("NestedMIL.fit requires at least one labelled group")

        dims = {g.X.shape[1] for g in labelled if g.X.shape[0] > 0}
        if not dims:
            raise ValueError("all training groups are empty; nothing to learn from")
        if len(dims) > 1:
            raise ValueError(f"inconsistent instance dimensionality: {sorted(dims)}")
        d = dims.pop()

        self._regions = sorted({g.region for g in labelled})
        self._region_index = {r: i for i, r in enumerate(self._regions)}
        n_regions = len(self._regions)

        compiled = _compile(labelled, self._region_index, d)

        theta0 = np.zeros(d + 1 + n_regions * d + n_regions, dtype=np.float64)
        # Start at the empirical base rate so the model begins calibrated.
        base = float(np.mean([g.label for g in labelled]))
        theta0[d] = float(np.log(max(base, 1e-6) / max(1.0 - base, 1e-6)))

        # Pin BLAS to one thread for the fit. The objective is a few hundred
        # thin matrix products (n x 108 by 108); on a small container the
        # multithreaded path spends far more time in thread sync than in
        # arithmetic -- measured 179ms vs 3.7ms for the gradient GEMM. Scoped to
        # this call so the setting does not leak into the caller's process.
        with threadpool_limits(limits=1):
            result = minimize(
                self._objective,
                theta0,
                args=(compiled, d, n_regions),
                jac=True,
                method="L-BFGS-B",
                options={
                    "maxiter": self.config.max_iter,
                    "ftol": self.config.tol,
                    "disp": self.config.verbose,
                },
            )
        self._fit = self._unpack(result.x, d, n_regions)
        self._fit.region_index = self._region_index
        self.n_iter_ = int(result.nit)
        self.loss_ = float(result.fun)
        self._d = d
        return self

    def _weights_for(self, region: str) -> tuple[np.ndarray, float]:
        """Per-region head, falling back to the shared trunk for unseen regions.

        An unseen region is not an error -- it is the cold-start case the survey's
        single-geography criticism is about, and the shared trunk is exactly the
        transferable part.
        """
        assert self._fit is not None
        r = self._fit.region_index.get(region)
        if r is None:
            return self._fit.w0, self._fit.b0
        return self._fit.w0 + self._fit.V[r], self._fit.b0 + self._fit.c[r]

    def decision_function(self, groups: list[PooledGroup]) -> np.ndarray:
        if self._fit is None:
            raise RuntimeError("call fit() first")
        out = np.empty(len(groups), dtype=np.float64)
        for i, g in enumerate(groups):
            w_r, b_r = self._weights_for(g.region)
            if g.X.shape[0] == 0:
                out[i] = b_r
            else:
                out[i], _ = self._pool(g.X @ w_r + b_r, g.members())
        return out

    def predict_proba(self, groups: list[PooledGroup]) -> np.ndarray:
        return expit(self.decision_function(groups))

    def attributions(self, group: PooledGroup) -> np.ndarray:
        """Per-instance attribution weights for one group (sums to 1)."""
        if self._fit is None:
            raise RuntimeError("call fit() first")
        if group.X.shape[0] == 0:
            return np.zeros(0, dtype=np.float64)
        w_r, b_r = self._weights_for(group.region)
        _, attribution = self._pool(group.X @ w_r + b_r, group.members())
        return attribution

    def instance_scores(self, group: PooledGroup) -> np.ndarray:
        """Raw per-instance logits, before pooling."""
        if self._fit is None:
            raise RuntimeError("call fit() first")
        if group.X.shape[0] == 0:
            return np.zeros(0, dtype=np.float64)
        w_r, b_r = self._weights_for(group.region)
        return group.X @ w_r + b_r

    def region_divergence(self) -> dict[str, float]:
        """``||v_r||`` per region: how far each task pulled from the shared trunk.

        A diagnostic for whether ``lambda_task`` is set sensibly -- all zeros means
        the multi-task structure is inert, huge values mean it is not sharing.
        """
        if self._fit is None:
            raise RuntimeError("call fit() first")
        return {
            r: float(np.linalg.norm(self._fit.V[i]))
            for r, i in self._fit.region_index.items()
        }


def check_gradient(model: NestedMIL, groups: list[PooledGroup], eps: float = 1e-6) -> float:
    """Max abs difference between analytic and numeric gradient.

    Used in the test suite: the pooling gradient is the mathematical heart of
    both the fit and the evidence, so it is verified rather than trusted.
    """
    labelled = [g for g in groups if g.label is not None]
    d = next(g.X.shape[1] for g in labelled if g.X.shape[0] > 0)
    model._regions = sorted({g.region for g in labelled})
    model._region_index = {r: i for i, r in enumerate(model._regions)}
    n_regions = len(model._regions)
    rng = np.random.default_rng(0)
    theta = rng.normal(scale=0.1, size=d + 1 + n_regions * d + n_regions)

    compiled = _compile(labelled, model._region_index, d)
    _, analytic = model._objective(theta, compiled, d, n_regions)
    numeric = np.empty_like(theta)
    for k in range(theta.size):
        up, dn = theta.copy(), theta.copy()
        up[k] += eps
        dn[k] -= eps
        f_up, _ = model._objective(up, compiled, d, n_regions)
        f_dn, _ = model._objective(dn, compiled, d, n_regions)
        numeric[k] = (f_up - f_dn) / (2 * eps)
    return float(np.max(np.abs(analytic - numeric)))
