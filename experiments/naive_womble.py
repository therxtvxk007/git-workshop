"""The plain areal-wombling baseline, with none of this method's machinery.

The `womble+RD` arm in the main matrix is deliberately generous: it is handed
this method's own fused detector *and* its chronology screen, and only the
PDE-based geometry refinement is withheld.  That isolates one component but
overstates what the existing approach would actually do on its own.

This arm is the honest comparison: rank-fuse the residual sharpness over the
whole record, trace the single strongest ridge, stop.  No chronology, no
candidate screening, no differential permeability.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boundary_tomography import core, inverse, scenarios as S   # noqa: E402


def naive(data):
    cfg = data["cfg"]
    K = np.ones(cfg.M)
    fused = inverse.rank_fuse(inverse.edge_anomaly(cfg, data["obs"], K))
    ctrl = inverse.controls_from_path(inverse.viterbi_curve(fused),
                                      cfg.n_ctrl, cfg.nx)
    a = core.curve_from_controls(ctrl, cfg.ny)[0]
    b = core.curve_from_controls(data["truth"]["ctrl"], cfg.ny)[0]
    return float(np.abs(a - b).mean())


def main():
    seeds = range(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
    rows = []
    for sc in ["physical", "administrative", "economic", "null"]:
        for sd in seeds:
            rows.append(dict(scenario=sc, seed=sd, mae=naive(S.generate(sc, sd))))
            print(f"{sc:15s} seed {sd}  mae {rows[-1]['mae']:6.2f}", flush=True)
    Path("results").mkdir(exist_ok=True)
    Path("results/naive_womble.json").write_text(json.dumps(rows, indent=1))
    print("\nmean by scenario:")
    for sc in ["physical", "administrative", "economic"]:
        v = [r["mae"] for r in rows if r["scenario"] == sc]
        print(f"  {sc:15s} {np.mean(v):5.2f} +- {np.std(v):4.2f}")


if __name__ == "__main__":
    main()
