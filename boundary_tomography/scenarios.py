"""Synthetic worlds with a hidden shared interface and private distractors."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import core

TRACERS = [
    "market prices",
    "road orientation",
    "land tenure",
    "tax capacity",
    "settlement density",
]

# Permeability of the shared interface to each tracer, by interface type, and
# the epochs over which the interface exists.  This profile -- not the geometry
# -- is what identifies what the boundary *was*.
PROFILES = {
    # A mountain interface impedes everything, and never switches on or off.
    "physical": dict(
        tau=[0.35, 0.20, 0.40, 0.45, 0.30],
        window=None,
        gloss="mountain interface: impedes every process, no birth or death date",
    ),
    # An imperial frontier blocks fiscal and tenurial processes almost totally
    # while letting trade across, and it has a birth and a death.
    "administrative": dict(
        tau=[0.85, 0.55, 0.10, 0.05, 0.60],
        window=(1.2, 4.4),
        gloss="imperial frontier: blocks tax and tenure, porous to trade, dated",
    ),
    # A market jurisdiction segments prices and settlement but is invisible to
    # the fiscal apparatus, and appears late.
    "economic": dict(
        tau=[0.15, 0.70, 0.90, 0.95, 0.35],
        window=(2.8, 99.0),
        gloss="market jurisdiction: segments prices and settlement, fiscally invisible",
    ),
    # Control: distractors only, no shared interface at all.
    "null": dict(tau=[1.0] * 5, window=None,
                 gloss="no shared interface (placebo)"),
}


@dataclass
class Config:
    ny: int = 40
    nx: int = 40
    n_epochs: int = 6
    lam: float = 1e-4          # transport range sqrt(K/lam) >> domain: well mixed
    n_ctrl: int = 6
    n_basis_side: int = 4
    noise_frac: float = 0.06
    source_corr: float = 5.0
    n_distractors: int = 1
    distractor_perm: tuple = (0.10, 0.40)
    basis: np.ndarray = field(default=None, repr=False)

    def __post_init__(self):
        if self.basis is None:
            self.basis = core.rbf_basis(self.ny, self.nx, self.n_basis_side)

    @property
    def M(self):
        return len(TRACERS)

    @property
    def epochs(self):
        return np.arange(self.n_epochs, dtype=float)


def random_curve(rng, n_ctrl, span, margin=7.0, step=4.0):
    """A smooth curve crossing the domain: a bounded random walk in x over y."""
    x = rng.uniform(margin + 3, span - margin - 3)
    pts = [x]
    for _ in range(n_ctrl - 1):
        x = float(np.clip(x + rng.normal(0, step), margin, span - margin))
        pts.append(x)
    return np.array(pts)


def oriented_weights(ctrl, ny, nx, horizontal=False):
    """Edge weights for a curve in either orientation.

    A horizontal interface y = d(x) is the transposed problem, so build it on the
    transposed grid and swap the two edge families back.
    """
    if not horizontal:
        return core.edge_weights(ctrl, ny, nx)
    wh_t, wv_t = core.edge_weights(ctrl, nx, ny)
    return wv_t.T.copy(), wh_t.T.copy()          # -> (ny, nx-1), (ny-1, nx)


def generate(scenario: str, seed: int, cfg: Config | None = None):
    """Build one synthetic world and its noisy observations."""
    cfg = cfg or Config()
    rng = np.random.default_rng(seed)
    spec = PROFILES[scenario]
    M, ny, nx = cfg.M, cfg.ny, cfg.nx

    # --- shared interface -------------------------------------------------
    ctrl = random_curve(rng, cfg.n_ctrl, nx)
    wh, wv = core.edge_weights(ctrl, ny, nx)
    tau = np.array(spec["tau"], dtype=float)
    if spec["window"] is None:
        t_on, t_off = -np.inf, np.inf
        acts = np.ones(cfg.n_epochs)
    else:
        t_on, t_off = spec["window"]
        acts = core.activity(cfg.epochs, t_on, t_off)

    # --- private distractor interfaces, one per tracer --------------------
    # Each tracer carries a sharp discontinuity nobody else sees.  This is why a
    # single tracer cannot identify the shared frontier.
    distractors, barriers = [], []
    for m in range(M):
        rows = []
        for _ in range(cfg.n_distractors):
            horiz = bool(rng.integers(0, 2))
            d_ctrl = random_curve(rng, cfg.n_ctrl, ny if horiz else nx)
            d_perm = float(rng.uniform(*cfg.distractor_perm))
            dwh, dwv = oriented_weights(d_ctrl, ny, nx, horizontal=horiz)
            rows.append((dwh, dwv, d_perm))
            distractors.append(dict(tracer=m, ctrl=d_ctrl, perm=d_perm,
                                    horizontal=horiz))
        barriers.append(rows)
    static_h, static_v = core.static_resistance(barriers, M, ny, nx)

    # --- forcing ----------------------------------------------------------
    K = rng.uniform(0.80, 1.15, size=M)
    sources = np.stack(
        [core.smooth_random_field(ny, nx, cfg.source_corr, rng) for _ in range(M)]
    )[:, None]                                              # (M, 1, ny, nx)

    clean = core.solve_fields(
        K, sources, acts, lam=cfg.lam,
        static_h=static_h, static_v=static_v,
        dyn_wh=wh, dyn_wv=wv, dyn_perm=tau,
    )[:, :, 0]                                              # (n_epoch, M, ny, nx)

    scale = clean.reshape(cfg.n_epochs, M, -1).std(axis=2)[..., None, None]
    obs = clean + rng.standard_normal(clean.shape) * cfg.noise_frac * scale

    return dict(
        scenario=scenario, seed=seed, cfg=cfg, obs=obs, clean=clean,
        truth=dict(ctrl=ctrl, tau=tau, K=K, t_on=t_on, t_off=t_off,
                   window=spec["window"], acts=acts, sources=sources[:, 0],
                   distractors=distractors, gloss=spec["gloss"]),
    )
