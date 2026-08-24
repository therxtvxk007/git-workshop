"""Joint inversion for a shared interface from several passively observed tracers.

The unknowns split cleanly:

  * **geometry and chronology** (6 spline control points, t_on, t_off) are
    *shared* by every tracer -- this is the whole identifying assumption;
  * **permeability and bulk conductivity** (tau_m, K_m) are private to a tracer
    and, given the geometry, separate across m;
  * **source coefficients** beta_m enter linearly and are profiled out in closed
    form, so they never appear in the search space.

That structure gives an 8-dimensional outer problem and M independent
2-dimensional inner problems, which is what makes the thing tractable without
gradients.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares, minimize

from . import core

RIDGE = 1e-6


# --------------------------------------------------------------------------
# parameter transforms (Nelder-Mead is unconstrained; keep everything finite)
# --------------------------------------------------------------------------
def _sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _to_tau(z):
    return 0.02 + 0.98 * _sig(z)


def _from_tau(t):
    p = np.clip((np.asarray(t, float) - 0.02) / 0.98, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _to_K(z):
    return np.exp(np.clip(z, -2.5, 2.5))


def _inv_timing(t_on, t_off, n_epochs):
    """Inverse of `_timing`, so a screened chronology can seed the search."""
    span = n_epochs + 3.0
    p = np.clip((t_on + 2.0) / span, 1e-4, 1 - 1e-4)
    q = np.clip((t_off - t_on - 0.3) / (n_epochs + 4.0), 1e-4, 1 - 1e-4)
    return float(np.log(p / (1 - p))), float(np.log(q / (1 - q)))


def _timing(z_on, z_dur, n_epochs):
    """Chronology in epoch units, bounded so the search cannot run away."""
    t_on = -2.0 + (n_epochs + 3.0) * _sig(z_on)
    dur = 0.3 + (n_epochs + 4.0) * _sig(z_dur)
    return t_on, t_on + dur


# --------------------------------------------------------------------------
# profiled least squares
# --------------------------------------------------------------------------
def _solve_beta(R_m, y_m):
    """Profile out the source coefficients for one tracer. Returns sse, tss."""
    B = R_m.shape[1]
    A = R_m.transpose(1, 0, 2, 3).reshape(B, -1).T.astype(np.float64)
    y = y_m.ravel().astype(np.float64)
    G = A.T @ A
    G.flat[:: B + 1] += RIDGE * (np.trace(G) / B) + 1e-12
    beta = np.linalg.solve(G, A.T @ y)
    r = y - A @ beta
    return float(r @ r), float(((y - y.mean()) ** 2).sum()), beta, r


def evaluate(cfg, obs, ctrl, tau, K, t_on=None, t_off=None, want_resid=False):
    """Simulate under these parameters and return per-tracer (sse, tss)."""
    if ctrl is None:
        wh = wv = None
        acts = np.ones(cfg.n_epochs)
    else:
        wh, wv = core.edge_weights(ctrl, cfg.ny, cfg.nx)
        acts = (np.ones(cfg.n_epochs) if t_on is None
                else core.activity(cfg.epochs, t_on, t_off))
    R = core.solve_fields(
        np.asarray(K, float), cfg.basis[None], acts, lam=cfg.lam,
        dyn_wh=wh, dyn_wv=wv,
        dyn_perm=None if wh is None else np.asarray(tau, float),
    )
    sse, tss, resid = [], [], []
    for i in range(R.shape[1]):
        s, t, _, r = _solve_beta(R[:, i], obs[:, i])
        sse.append(s); tss.append(t)
        if want_resid:
            resid.append(r.reshape(obs.shape[0], cfg.ny, cfg.nx))
    sse, tss = np.array(sse), np.array(tss)
    return (sse, tss, resid) if want_resid else (sse, tss)


def _obj(sse, tss):
    """Scale-free objective: sum of unexplained variance fractions."""
    return float(np.sum(sse / np.maximum(tss, 1e-12)))


# --------------------------------------------------------------------------
# initialisation: rank-fused edge anomaly + Viterbi ridge tracking
# --------------------------------------------------------------------------
def bulk_K(cfg, obs):
    """Bulk conductivity, held at one.

    It is not separately estimable here and must not be fitted.  With transport
    range sqrt(K/lambda) far larger than the domain, u ~ K^-1 L^+ s, so K and the
    source amplitude beta are degenerate: profiling beta absorbs any rescaling of
    K exactly.  Left free, the search drives K down by an order of magnitude --
    a shorter transport range lets the smooth source basis mimic interface-like
    structure -- and that biases tau.  Bulk conductivity is therefore absorbed
    into the source scale, and tau_m is estimated as a ratio against it, which is
    the only thing the data actually constrain.
    """
    return np.ones(obs.shape[1])


def edge_anomaly(cfg, obs, K, epochs=None):
    """Residual sharpness across vertical cell faces, after the best smooth
    no-interface model.  A smooth source basis cannot make a one-cell jump, so
    whatever jump survives is interface-like -- shared frontier or distractor.

    `epochs` restricts the average to a slice of history, which matters for an
    interface that only exists for part of the record: pooling over all epochs
    dilutes it with the epochs in which it did not yet exist.
    """
    _, _, resid = evaluate(cfg, obs, None, None, K, want_resid=True)
    sl = slice(None) if epochs is None else epochs
    return np.stack([np.abs(np.diff(r[sl], axis=2)).mean(axis=0) for r in resid])


def rank_fuse(maps):
    """Mean of per-tracer rank-normalised anomaly.

    Mean, not median: an interface may be near-transparent to some tracers (a
    fiscal frontier is invisible in prices), so a majority vote would erase it.
    Ranking first stops one loud tracer from dominating the sum.
    """
    out = np.zeros_like(maps[0], dtype=np.float64)
    for a in maps:
        flat = a.ravel()
        r = np.empty_like(flat, dtype=np.float64)
        r[np.argsort(flat)] = np.arange(flat.size)
        out += (r / max(flat.size - 1, 1)).reshape(a.shape)
    return out / len(maps)


def viterbi_curve(score, max_slope=2):
    """Highest-scoring left-to-right-constrained path x(y) through the map."""
    ny, nw = score.shape
    best = score[0].copy()
    back = np.zeros((ny, nw), dtype=np.int32)
    offs = np.arange(-max_slope, max_slope + 1)
    for i in range(1, ny):
        cand = np.full((len(offs), nw), -np.inf)
        for k, o in enumerate(offs):
            src = np.roll(best, o)
            if o > 0:
                src[:o] = -np.inf
            elif o < 0:
                src[o:] = -np.inf
            cand[k] = src
        k_best = np.argmax(cand, axis=0)
        best = cand[k_best, np.arange(nw)] + score[i]
        back[i] = np.arange(nw) - offs[k_best]
    path = np.zeros(ny, dtype=np.int32)
    path[-1] = int(np.argmax(best))
    for i in range(ny - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path.astype(float) + 0.5      # face centre -> cell coordinate


def controls_from_path(path, n_ctrl, nx):
    """Least-squares fit of the spline control points to a traced path."""
    ny = len(path)
    x0 = np.interp(np.linspace(0, ny - 1, n_ctrl), np.arange(ny), path)

    def res(c):
        return core.curve_from_controls(np.clip(c, 1, nx - 2), ny)[0] - path

    return np.clip(least_squares(res, x0, max_nfev=60).x, 3, nx - 4)


def candidate_curves(cfg, obs, K, n_suppress=2, band=3):
    """Plausible interface curves to start the search from.

    One traced ridge is not enough.  When an interface is near-transparent to
    most tracers -- a market jurisdiction the fiscal record cannot see -- the
    rank-fused map is dominated by whichever tracer's private discontinuity
    happens to be strongest, and the single best ridge is the wrong one.  So
    also offer: ridges traced from the first and second half of the record
    separately (for interfaces that appear or vanish mid-record), the runner-up
    ridges after suppressing the winner, and each tracer's own best ridge.
    """
    half = cfg.n_epochs // 2
    maps = {
        "all": edge_anomaly(cfg, obs, K),
        "early": edge_anomaly(cfg, obs, K, slice(0, half)),
        "late": edge_anomaly(cfg, obs, K, slice(half, None)),
    }
    fused_all = rank_fuse(maps["all"])
    cands, seen = [], []

    def add(path):
        c = controls_from_path(path, cfg.n_ctrl, cfg.nx)
        if all(np.abs(c - o).mean() > 1.5 for o in seen):
            seen.append(c)
            cands.append(c)

    for name, mp in maps.items():
        fused = rank_fuse(mp)
        add(viterbi_curve(fused))
        if name == "all":
            work = fused.copy()
            for _ in range(n_suppress):     # non-maximum suppression
                p = viterbi_curve(work)
                cols = np.arange(work.shape[1])[None, :]
                work[np.abs(cols - p[:, None]) <= band] = work.min()
                add(viterbi_curve(work))
    for m in range(len(maps["all"])):       # each tracer's own best ridge
        add(viterbi_curve(maps["all"][m]))
    return cands, fused_all


TAU_GRID = np.array([0.08, 0.16, 0.30, 0.50, 0.75, 1.00])


def chronologies(n_epochs):
    """Coarse chronology hypotheses to screen a candidate curve under.

    Screening every candidate as though the interface were always present is
    what breaks on a late-appearing one: the early epochs, in which it did not
    exist, are modelled as though it did, so the fit pushes tau towards 1 to
    limit the damage and the true curve scores *worse* than somebody's private
    discontinuity.  Chronology has to be screened jointly with geometry.
    """
    n = float(n_epochs)
    return [(-2.0, n + 2.0),            # always present
            (n / 2 - 0.5, n + 2.0),     # appears midway
            (-2.0, n / 2 + 0.5),        # vanishes midway
            (n / 4, 3 * n / 4)]         # appears and vanishes


def screen(cfg, obs, cands):
    """Score candidate curves against chronology hypotheses on a permeability grid.

    Given geometry and chronology the tracers are separable, so one solve at a
    shared trial permeability yields every tracer's residual at that value at
    once, and the per-tracer minimum over the grid is the profiled score.  That
    makes the whole screen a handful of solves per combination instead of M
    nested one-dimensional searches.
    """
    M = obs.shape[1]
    K = np.ones(M)
    best = None
    for c in cands:
        for (on, off) in chronologies(cfg.n_epochs):
            frac = np.array([
                (lambda st: st[0] / np.maximum(st[1], 1e-12))(
                    evaluate(cfg, obs, c, np.full(M, t), K, on, off))
                for t in TAU_GRID
            ])                                          # (n_grid, M)
            o = float(frac.min(axis=0).sum())
            if best is None or o < best[0]:
                best = (o, c, TAU_GRID[frac.argmin(axis=0)], on, off)
    return best


def initialise(cfg, obs):
    K = bulk_K(cfg, obs)
    cands, fused = candidate_curves(cfg, obs, K)
    _, ctrl, tau, t_on, t_off = screen(cfg, obs, cands)
    return dict(ctrl=ctrl, K=K, fused=fused, tau=tau, t_on=t_on, t_off=t_off,
                n_candidates=len(cands))


# --------------------------------------------------------------------------
# block-coordinate fit
# --------------------------------------------------------------------------
def fit(data, tracers=None, shared_tau=False, fit_timing=True, rounds=4,
        maxfev_geo=170, init=None, fix_geometry=False, verbose=False):
    """Block-coordinate fit, cycling permeability -> chronology -> geometry.

    Order matters.  Geometry is initialised well (by the fused ridge trace) and
    permeability is not, so running the geometry block first drags a good curve
    away using a placeholder tau = 0.5.  Chronology is separated from geometry
    for the same reason: bundling them makes the geometry search fight a
    two-parameter nuisance it has no gradient information about.

    The chronology also starts *wide open* -- the interface present at every
    epoch -- so that "always-on" is the null the data must argue against.
    Starting mid-range instead silently asserts the interface did not exist
    during the early epochs, which biases tau upward to compensate.
    """
    cfg = data["cfg"]
    obs = data["obs"] if tracers is None else data["obs"][:, list(tracers)]
    M = obs.shape[1]

    init = initialise(cfg, obs) if init is None else init
    ctrl = np.asarray(init["ctrl"], float).copy()
    K = np.ones(M)
    fused = init.get("fused")
    tau = np.asarray(init.get("tau", np.full(M, 0.5)), float).copy()
    if fit_timing:
        t_on = init.get("t_on", -2.0)
        t_off = init.get("t_off", cfg.n_epochs + 2.0)
        z_on, z_dur = _inv_timing(t_on, t_off, cfg.n_epochs)
    else:
        t_on = t_off = None
        z_on, z_dur = -3.0, 3.0

    simplex1 = np.array([[-1.2], [1.2]])
    hist = []
    best = None

    def score(c, tt, on, off):
        sse, tss = evaluate(cfg, obs, c, tt, K, on, off)
        return _obj(sse, tss)

    def keep(c, tt, on, off):
        nonlocal best
        o = score(c, tt, on, off)
        if best is None or o < best[0]:
            best = (o, np.array(c, float), np.array(tt, float), on, off)
        return o

    def penalty(c):
        lo, hi = 3.0, cfg.nx - 4.0
        return 1e3 * float(np.sum(np.clip(lo - c, 0, None) ** 2
                                  + np.clip(c - hi, 0, None) ** 2))

    keep(ctrl, tau, t_on, t_off)
    for r in range(rounds):
        # ---- block B: permeability, separable across tracers given geometry --
        if shared_tau:
            def f_pv(z):
                return score(ctrl, np.full(M, _to_tau(z[0])), t_on, t_off)

            rp = minimize(f_pv, [_from_tau(tau[0])], method="Nelder-Mead",
                          options=dict(maxfev=35, xatol=1e-2, fatol=1e-7,
                                       initial_simplex=simplex1))
            tau = np.full(M, _to_tau(rp.x[0]))
        else:
            for m in range(M):
                def f_m(z, m=m):
                    sse, tss = evaluate(cfg, obs[:, m: m + 1], ctrl,
                                        [_to_tau(z[0])], K[m: m + 1], t_on, t_off)
                    return _obj(sse, tss)

                rp = minimize(f_m, [_from_tau(tau[m])], method="Nelder-Mead",
                              options=dict(maxfev=35, xatol=1e-2, fatol=1e-9,
                                           initial_simplex=simplex1))
                tau[m] = _to_tau(rp.x[0])
        keep(ctrl, tau, t_on, t_off)

        # ---- block C: chronology, shared by every tracer --------------------
        if fit_timing:
            def f_t(z):
                on, off = _timing(z[0], z[1], cfg.n_epochs)
                return score(ctrl, tau, on, off)

            rt = minimize(f_t, [z_on, z_dur], method="Nelder-Mead",
                          options=dict(maxfev=60, xatol=2e-2, fatol=1e-7,
                                       adaptive=True))
            if f_t(rt.x) <= f_t([z_on, z_dur]):
                z_on, z_dur = rt.x
                t_on, t_off = _timing(z_on, z_dur, cfg.n_epochs)
            keep(ctrl, tau, t_on, t_off)

        # ---- block A: shared geometry ---------------------------------------
        if fix_geometry:            # detect-then-estimate baseline: curve frozen
            hist.append(best[0])
            continue

        def f_geo(z):
            return score(np.clip(z, 1, cfg.nx - 2), tau, t_on, t_off) + penalty(z)

        rg = minimize(f_geo, ctrl, method="Nelder-Mead",
                      options=dict(maxfev=maxfev_geo, xatol=2e-2, fatol=1e-7,
                                   adaptive=True))
        cand = np.clip(rg.x, 3, cfg.nx - 4)
        if score(cand, tau, t_on, t_off) <= score(ctrl, tau, t_on, t_off):
            ctrl = cand
        keep(ctrl, tau, t_on, t_off)

        hist.append(best[0])
        if verbose:
            print(f"  round {r}: obj={best[0]:.5f} tau={np.round(best[2],2)} "
                  f"window=({best[3]:.2f}, {best[4]:.2f})" if fit_timing
                  else f"  round {r}: obj={best[0]:.5f} tau={np.round(best[2],2)}")

    obj, ctrl, tau, t_on, t_off = best
    sse, tss = evaluate(cfg, obs, ctrl, tau, K, t_on, t_off)
    sse0, tss0 = evaluate(cfg, obs, None, None, K)          # no-interface null
    return dict(
        ctrl=ctrl, tau=np.asarray(tau, float), K=np.asarray(K, float),
        t_on=t_on, t_off=t_off, fit_timing=fit_timing, shared_tau=shared_tau,
        tracers=list(range(data["obs"].shape[1])) if tracers is None else list(tracers),
        objective=obj, r2=1.0 - sse / tss, r2_null=1.0 - sse0 / tss0,
        gain=_obj(sse0, tss0) - obj, history=hist, fused=fused,
    )
