"""Spatial figures, plus a JSON dump of the numbers the report plots as SVG."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boundary_tomography import core, inverse, scenarios as S   # noqa: E402

SCEN = ["physical", "administrative", "economic"]
INK, MUTED = "#0b0b0b", "#52514e"
BLUE, ORANGE, AQUA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
SURFACE = "#fcfcfb"

# Diverging for signed fields: two hues, neutral grey midpoint -- never a rainbow.
DIVERGE = LinearSegmentedColormap.from_list(
    "bo", ["#12467e", BLUE, "#dcdcd8", ORANGE, "#8c3413"])
# Sequential single hue for magnitude-only maps.
SEQ = LinearSegmentedColormap.from_list("seq", ["#f5f5f2", "#a8c6e8", "#12467e"])


def _show(ax, m, cmap=None):
    """Percentile-clipped so the ridge is visible; a rank-fused map has almost
    no dynamic range at its extremes and washes out under a raw scale."""
    lo, hi = np.percentile(m, [2, 99])
    return ax.imshow(m, cmap=cmap or SEQ, origin="lower", aspect="auto",
                     vmin=lo, vmax=hi, interpolation="nearest")


def _frame(ax, title=None):
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color("#d5d5d0")
    if title:
        ax.set_title(title, fontsize=8.5, color=INK, pad=4)


def _curve(ax, ctrl, ny, **kw):
    ax.plot(core.curve_from_controls(ctrl, ny)[0], np.arange(ny), **kw)


def fitted(scenario, seed, cache):
    key = f"{scenario}:{seed}"
    if key in cache:
        return {k: (np.array(v) if k == "ctrl" or k == "tau" else v)
                for k, v in cache[key].items()}
    data = S.generate(scenario, seed)
    res = inverse.fit(data)
    ini = inverse.initialise(data["cfg"], data["obs"])
    womb = inverse.fit(data, init=ini, fix_geometry=True, fit_timing=False, rounds=1)
    out = dict(ctrl=res["ctrl"].tolist(), tau=res["tau"].tolist(),
               t_on=res["t_on"], t_off=res["t_off"], gain=res["gain"],
               womble_ctrl=ini["ctrl"].tolist(),
               womble_tau=womb["tau"].tolist(),
               fused=ini["fused"].tolist())
    cache[key] = out
    return {k: (np.array(v) if isinstance(v, list) else v) for k, v in out.items()}


# --------------------------------------------------------------------------
def fig_why_fusion(path, scenario="administrative", seed=0):
    """Each tracer sees two ridges; only one of them is shared."""
    data = S.generate(scenario, seed)
    cfg, tr = data["cfg"], data["truth"]
    K = np.ones(cfg.M)
    maps = inverse.edge_anomaly(cfg, data["obs"], K)
    fused = inverse.rank_fuse(maps)

    fig, axes = plt.subplots(1, 6, figsize=(13.2, 2.65), facecolor=SURFACE)
    for m, ax in enumerate(axes[:5]):
        _show(ax, maps[m])
        _curve(ax, tr["ctrl"], cfg.ny, color=INK, lw=1.8)
        d = tr["distractors"][m]
        if d["horizontal"]:
            ax.plot(np.arange(cfg.nx),
                    core.curve_from_controls(d["ctrl"], cfg.nx)[0],
                    color=ORANGE, lw=1.6, ls=(0, (4, 2)))
        else:
            _curve(ax, d["ctrl"], cfg.ny, color=ORANGE, lw=1.6, ls=(0, (4, 2)))
        _frame(ax, f"{S.TRACERS[m]}\n" + r"$\tau$ = " + f"{tr['tau'][m]:.2f}")
        ax.set_xlim(0, cfg.nx - 2); ax.set_ylim(0, cfg.ny - 1)
    _show(axes[5], fused)
    _curve(axes[5], tr["ctrl"], cfg.ny, color=INK, lw=1.8)
    _frame(axes[5], "rank-fused\nacross tracers")
    axes[5].set_xlim(0, cfg.nx - 2); axes[5].set_ylim(0, cfg.ny - 1)

    fig.legend(handles=[
        plt.Line2D([], [], color=INK, lw=1.8, label="shared interface (unknown)"),
        plt.Line2D([], [], color=ORANGE, lw=1.6, ls=(0, (4, 2)),
                   label="that tracer's private distractor"),
    ], loc="lower center", ncol=2, frameon=False, fontsize=8.5,
        bbox_to_anchor=(0.5, -0.03), labelcolor=MUTED)
    fig.suptitle(
        f"Residual sharpness per tracer — {scenario} interface. "
        "Each map holds two ridges; only the black one recurs across tracers.",
        fontsize=9.5, color=INK, y=1.02)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def fig_recovery(path, cache, seed=0):
    """Recovered curve against truth and the composed baseline, per scenario."""
    fig, axes = plt.subplots(1, 3, figsize=(9.6, 3.5), facecolor=SURFACE)
    for ax, sc in zip(axes, SCEN):
        data = S.generate(sc, seed)
        cfg, tr = data["cfg"], data["truth"]
        f = fitted(sc, seed, cache)
        _show(ax, np.array(f["fused"]))
        _curve(ax, tr["ctrl"], cfg.ny, color=INK, lw=2.4, label="true interface")
        _curve(ax, f["ctrl"], cfg.ny, color=BLUE, lw=2.0, ls=(0, (5, 2)),
               label="joint inversion")
        _curve(ax, f["womble_ctrl"], cfg.ny, color=ORANGE, lw=1.7, ls=(0, (2, 2)),
               label="womble + RD")
        err = np.abs(core.curve_from_controls(f["ctrl"], cfg.ny)[0]
                     - core.curve_from_controls(tr["ctrl"], cfg.ny)[0]).mean()
        _frame(ax, f"{sc}\njoint error {err:.2f} cells")
        ax.set_xlim(0, cfg.nx - 2); ax.set_ylim(0, cfg.ny - 1)
    axes[0].legend(loc="lower left", fontsize=7.5, frameon=True,
                   facecolor="white", edgecolor="#d5d5d0", labelcolor=MUTED)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def fig_field(path, scenario="administrative", seed=0):
    """What the observer actually has: smooth fields with a faint seam."""
    data = S.generate(scenario, seed)
    cfg, tr = data["cfg"], data["truth"]
    ep = int(np.argmax(tr["acts"]))
    fig, axes = plt.subplots(1, 5, figsize=(11.6, 2.5), facecolor=SURFACE)
    for m, ax in enumerate(axes):
        u = data["obs"][ep, m]
        v = np.abs(u - u.mean()).max()
        ax.imshow(u, cmap=DIVERGE, origin="lower", aspect="auto",
                  vmin=u.mean() - v, vmax=u.mean() + v)
        _curve(ax, tr["ctrl"], cfg.ny, color=INK, lw=1.4, alpha=0.75)
        _frame(ax, f"{S.TRACERS[m]}\n" + r"$\tau$ = " + f"{tr['tau'][m]:.2f}")
    fig.suptitle(
        f"Observed tracer fields at epoch {ep} — {scenario} interface, "
        "true curve overlaid. The interface is not visible by eye.",
        fontsize=9.5, color=INK, y=1.04)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def main():
    out = Path("results")
    out.mkdir(exist_ok=True)
    cpath = out / "fits.json"
    cache = json.loads(cpath.read_text()) if cpath.exists() else {}
    fig_field(out / "fig_fields.png")
    fig_why_fusion(out / "fig_fusion.png")
    fig_recovery(out / "fig_recovery.png", cache)
    cpath.write_text(json.dumps(cache))
    print("figures written to", out)


if __name__ == "__main__":
    main()
