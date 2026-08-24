"""Forward model: multi-tracer transport across a hidden, semi-permeable interface.

Each tracer m is a scalar field u_m observed at a handful of epochs.  Institutions
change more slowly than the processes that reveal them, so every epoch is solved
at equilibrium rather than integrated through time:

    div( C_m(x, t_k) grad u_m ) - lambda u_m + s_m(x) = 0.

C_m is an *edge* conductance, equal to K_m everywhere except on thin interfaces
where it is scaled down.  Two kinds of interface exist:

  * one **shared** interface B, crossed by every tracer but with a
    tracer-specific permeability tau_m in (0, 1], active only on [t_on, t_off];
  * a **private** distractor interface D_m per tracer, with its own permeability,
    always active.

The distractors are the point of the experiment.  Real geography is full of sharp
things -- rivers, scarps, soil boundaries, forest edges -- and each shows up in
some tracers and not others.  A single tracer therefore cannot tell "the" vanished
frontier from its own private discontinuity.  Only the fact that one interface is
shared across tracers, with *different* permeabilities, distinguishes it.

The transport range sqrt(K/lambda) must be comparable to the domain, or the field
is locally determined, nothing flows across the interface, and blocking it changes
nothing observable.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.ndimage import gaussian_filter
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu

# Membrane half-width, in cells.  A real frontier is not infinitely thin, and a
# smooth membrane keeps the objective differentiable in the boundary geometry.
EPS_MEMBRANE = 0.85

# Interface thickness in cells.  An interface behaves like BARRIER_CELLS cells of
# material with conductivity tau * K, so crossing it costs an extra resistance
# BARRIER_CELLS * (1/tau - 1) / K.  Without this the interface is one pixel thick
# and adds so little series resistance that even tau = 0.05 barely perturbs the
# field -- the failure mode that makes a naive membrane model useless.
BARRIER_CELLS = 6.0


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def curve_from_controls(ctrl_x, ny: int):
    """Cubic spline x = c(y) through the control points, sampled at row centres.

    Returns c(y) and c'(y) in cell units.
    """
    ctrl_x = np.asarray(ctrl_x, dtype=np.float64)
    knots = np.linspace(0.0, ny - 1.0, len(ctrl_x))
    spline = CubicSpline(knots, ctrl_x, bc_type="natural")
    rows = np.arange(ny, dtype=np.float64)
    return spline(rows), spline(rows, 1)


def signed_distance(ctrl_x, ny: int, nx: int):
    """First-order signed distance to the curve x = c(y), in cell units."""
    c, cp = curve_from_controls(ctrl_x, ny)
    cols = np.arange(nx, dtype=np.float64)[None, :]
    return (cols - c[:, None]) / np.sqrt(1.0 + cp[:, None] ** 2), cp


def edge_weights(ctrl_x, ny: int, nx: int, eps: float = EPS_MEMBRANE):
    """Per-edge crossing share for the interface x = c(y).

    Two properties matter.  First, an interface impedes flux *across* itself and
    not along itself, so each edge family carries the squared projection of its
    direction onto the interface normal: with n = (1, -c')/sqrt(1+c'^2) we get
    (n.xhat)^2 = 1/(1+c'^2) and (n.yhat)^2 = c'^2/(1+c'^2), which sum to one.

    Second, the weights are *normalised along the crossing direction* so that a
    path cutting the interface accumulates exactly one interface's worth of
    resistance no matter where the curve falls relative to the cell grid.  An
    unnormalised Gaussian membrane blocks a curve sitting on a cell face far more
    than one sitting on a cell centre, which makes the objective a washboard in
    the geometry parameters.
    """
    phi, cp = signed_distance(ctrl_x, ny, nx)
    denom = 1.0 + cp**2
    proj_x = (1.0 / denom)[:, None]
    proj_y = (cp**2 / denom)[:, None]

    gh = np.exp(-((0.5 * (phi[:, 1:] + phi[:, :-1]) / eps) ** 2))
    w_h = gh / np.maximum(gh.sum(axis=1, keepdims=True), 1e-12) * proj_x

    gv = np.exp(-((0.5 * (phi[1:, :] + phi[:-1, :]) / eps) ** 2))
    col = np.maximum(gv.sum(axis=0, keepdims=True), 1e-12)
    pv = 0.5 * (proj_y[1:] + proj_y[:-1])
    w_v = gv / col * ((gv * pv).sum(axis=0, keepdims=True) / col)
    return w_h, w_v


def activity(epochs, t_on, t_off, kappa: float = 0.35) -> np.ndarray:
    """Smooth 0->1->0 activity of the interface across observation epochs.

    Smooth rather than a hard switch, so the two chronology parameters are
    optimisable instead of piecewise-constant.
    """
    t = np.asarray(epochs, dtype=np.float64)
    return (1.0 / (1.0 + np.exp(-(t - t_on) / kappa))) * (
        1.0 / (1.0 + np.exp(-(t_off - t) / kappa))
    )


# --------------------------------------------------------------------------
# source fields
# --------------------------------------------------------------------------
def rbf_basis(ny: int, nx: int, n_side: int = 4) -> np.ndarray:
    """Coarse Gaussian RBF basis for the unknown source field, (n_side^2, ny, nx).

    Deliberately smooth: it can represent gentle spatial forcing but cannot
    manufacture a one-cell-wide discontinuity.  That asymmetry -- smooth
    nuisance, sharp target -- is what makes the interface estimable at all.
    """
    yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float64)
    centres = np.linspace(0, ny - 1, n_side), np.linspace(0, nx - 1, n_side)
    width = max(ny, nx) / (n_side - 1) * 0.62
    return np.stack([
        np.exp(-(((yy - a) ** 2 + (xx - b) ** 2) / (2 * width**2)))
        for a in centres[0] for b in centres[1]
    ])


def smooth_random_field(ny, nx, corr, rng) -> np.ndarray:
    f = gaussian_filter(rng.standard_normal((ny, nx)), corr, mode="nearest")
    f -= f.mean()
    s = f.std()
    return f / s if s > 0 else f


# --------------------------------------------------------------------------
# forward solve
# --------------------------------------------------------------------------
def resistance(perm):
    """Extra dimensionless resistance per unit crossing share, for permeability tau."""
    return BARRIER_CELLS * (1.0 / max(float(perm), 1e-6) - 1.0)


def static_resistance(barriers, M, ny, nx):
    """Accumulate always-on interfaces into additive edge resistance.

    Resistances add in series, so two interfaces crossing the same edge simply
    sum -- no ordering, no interaction term.
    """
    rh = np.zeros((M, ny, nx - 1))
    rv = np.zeros((M, ny - 1, nx))
    for m in range(M):
        for (w_h, w_v, perm) in barriers[m]:
            rh[m] += resistance(perm) * w_h
            rv[m] += resistance(perm) * w_v
    return rh, rv


def _operator(ch, cv, lam, ny, nx):
    """Sparse (Laplacian - lambda I) for one conductance field, Neumann edges.

    Only interior faces carry conductance, so no flux leaves the domain; lambda
    keeps the operator negative definite.
    """
    idx = np.arange(ny * nx).reshape(ny, nx)
    r, c, v = [], [], []
    for a, b, w in (
        (idx[:, :-1].ravel(), idx[:, 1:].ravel(), ch.ravel()),
        (idx[:-1, :].ravel(), idx[1:, :].ravel(), cv.ravel()),
    ):
        r += [a, b, a, b]
        c += [b, a, a, b]
        v += [w, w, -w, -w]
    n = ny * nx
    d = np.arange(n)
    r.append(d); c.append(d); v.append(np.full(n, -lam))
    return coo_matrix(
        (np.concatenate(v), (np.concatenate(r), np.concatenate(c))), shape=(n, n)
    ).tocsc()


def solve_fields(
    K,                 # (M,) bulk conductivity
    sources,           # (M, B, ny, nx) or (1, B, ny, nx)
    acts,              # (n_epoch,) shared-interface activity, or None
    lam=0.003,
    static_h=None,     # (M, ny, nx-1) always-on additive resistance
    static_v=None,
    dyn_wh=None,       # (ny, nx-1) shared-interface weights
    dyn_wv=None,
    dyn_perm=None,     # (M,) tracer-specific permeability
):
    """Quasi-static fields at each observation epoch, (n_epoch, M, B, ny, nx).

    Sources enter linearly, so every basis member is solved as an extra
    right-hand side against a single factorisation, and factorisations are
    cached across epochs whose activity coincides -- which is most of them.
    """
    K = np.asarray(K, dtype=np.float64)
    M = K.shape[0]
    src = np.asarray(sources, dtype=np.float64)
    if src.shape[0] == 1:
        src = np.broadcast_to(src, (M,) + src.shape[1:])
    B, ny, nx = src.shape[1:]
    acts = np.ones(1) if acts is None else np.atleast_1d(np.asarray(acts, float))
    n_ep = len(acts)

    mh = np.zeros((M, ny, nx - 1)) if static_h is None else static_h
    mv = np.zeros((M, ny - 1, nx)) if static_v is None else static_v
    has_dyn = dyn_wh is not None and dyn_perm is not None
    gap = (np.array([resistance(t) for t in np.atleast_1d(dyn_perm)])
           if has_dyn else None)

    out = np.empty((n_ep, M, B, ny, nx))
    cache = {}
    for m in range(M):
        rhs = -src[m].reshape(B, -1).T                       # (n, B)
        for k in range(n_ep):
            a = float(acts[k]) if has_dyn else 0.0
            key = (m, round(a, 3))
            lu = cache.get(key)
            if lu is None:
                rh, rv = mh[m], mv[m]
                if has_dyn and a > 1e-6:
                    rh = rh + gap[m] * a * dyn_wh
                    rv = rv + gap[m] * a * dyn_wv
                ch, cv = K[m] / (1.0 + rh), K[m] / (1.0 + rv)
                lu = cache[key] = splu(_operator(ch, cv, lam, ny, nx))
            out[k, m] = lu.solve(rhs).T.reshape(B, ny, nx)
    return out
