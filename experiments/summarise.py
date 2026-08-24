"""Turn the raw runs into the tables the kill criteria are judged on."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boundary_tomography.scenarios import PROFILES, TRACERS   # noqa: E402

SCEN = ["physical", "administrative", "economic"]
METHODS = ["joint", "shared-tau", "womble+RD", "best single tracer"]


def load(path):
    return json.loads(Path(path).read_text())


def _ms(v):
    v = np.asarray(v, float)
    return f"{v.mean():5.2f} +- {v.std():4.2f}" if len(v) else "    -     "


def boundary_table(rows):
    """Kill criterion 1: does a composed baseline localise the interface as well?"""
    by = defaultdict(lambda: defaultdict(list))
    singles = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["scenario"] == "null":
            continue
        if r["kind"].startswith("single:"):
            singles[r["scenario"]][r["seed"]].append(r["boundary"]["mae"])
        elif r["kind"] in ("joint", "shared", "womble"):
            name = {"joint": "joint", "shared": "shared-tau",
                    "womble": "womble+RD"}[r["kind"]]
            by[name][r["scenario"]].append(r["boundary"]["mae"])
    for sc, per_seed in singles.items():         # generous: oracle-best tracer
        by["best single tracer"][sc] = [min(v) for v in per_seed.values()]

    print("\nBOUNDARY RECOVERY -- mean absolute distance to the true curve, in cells")
    print(f"{'method':22s} " + " ".join(f"{s:>16s}" for s in SCEN))
    for m in METHODS:
        print(f"{m:22s} " + " ".join(f"{_ms(by[m][s]):>16s}" for s in SCEN))
    return by


def permeability_table(rows):
    """Does modelling *differential* permeability matter, or is one enough?"""
    print("\nPERMEABILITY PROFILE -- error against the true tau vector")
    print(f"{'method':22s} {'MAE':>16s} {'rank corr.':>12s}")
    for kind, name in [("joint", "joint"), ("shared", "shared-tau"),
                       ("womble", "womble+RD")]:
        mae = [r["tau"]["mae"] for r in rows
               if r["kind"] == kind and r["scenario"] != "null"]
        rho = [r["tau"]["spearman"] for r in rows
               if r["kind"] == kind and r["scenario"] != "null"
               and not np.isnan(r["tau"]["spearman"])]
        print(f"{name:22s} {_ms(mae):>16s} {np.mean(rho) if rho else np.nan:12.2f}")


def chronology_table(rows):
    print("\nCHRONOLOGY -- mean error in the per-epoch activity of the interface")
    for sc in SCEN:
        v = [r["timing"]["schedule_mae"] for r in rows
             if r["kind"] == "joint" and r["scenario"] == sc]
        w = PROFILES[sc]["window"]
        print(f"  {sc:16s} {_ms(v)}   (true window: {w})")


def type_table(rows):
    """The headline claim: the permeability profile says what the boundary was."""
    print("\nINTERFACE TYPE -- classification from the recovered profile alone")
    conf = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r["kind"] == "joint" and r["scenario"] != "null":
            conf[r["scenario"]][r["predicted_type"]] += 1
    hdr = " ".join(f"{s[:8]:>10s}" for s in SCEN)
    print(f"  {'true \\ called':16s} {hdr}")
    ok = tot = 0
    for sc in SCEN:
        print(f"  {sc:16s} " + " ".join(f"{conf[sc][p]:10d}" for p in SCEN))
        ok += conf[sc][sc]
        tot += sum(conf[sc].values())
    print(f"  accuracy {ok}/{tot}")
    for kind, name in [("shared", "shared-tau"), ("womble", "womble+RD")]:
        o = sum(1 for r in rows if r["kind"] == kind and r["scenario"] != "null"
                and r["correct_type"])
        t = sum(1 for r in rows if r["kind"] == kind and r["scenario"] != "null")
        print(f"  same test, {name:12s} {o}/{t}")


def placebo_table(rows):
    """Kill criterion 2: does it invent an interface where none exists?"""
    null = [r["gain"] for r in rows if r["scenario"] == "null" and r["kind"] == "joint"]
    print("\nPLACEBO -- worlds containing distractors but no shared interface")
    if not null:
        print("  (no null runs)")
        return
    thr = float(np.percentile(null, 95))
    print(f"  null gain: median {np.median(null):.4f}  max {max(null):.4f}  "
          f"95th pct {thr:.4f}   (n={len(null)})")
    taus = [t for r in rows if r["scenario"] == "null" and r["kind"] == "joint"
            for t in r["tau_est"]]
    print(f"  permeability reported on null data: median {np.median(taus):.2f} "
          f"(1.00 = 'no interface');  fraction below 0.5: "
          f"{np.mean(np.asarray(taus) < 0.5):.2f}")
    print(f"  detection rate at the null 95th-percentile threshold:")
    for sc in SCEN:
        g = [r["gain"] for r in rows if r["kind"] == "joint" and r["scenario"] == sc]
        print(f"    {sc:16s} {np.mean(np.asarray(g) > thr):.2f}   "
              f"(gain median {np.median(g):.4f})")


def heldout_table(rows):
    """Kill criterion 3: does the recovered boundary predict a tracer it never saw?"""
    print("\nHELD-OUT TRACER -- fit on four tracers, predict the fifth")
    print(f"  {'scenario':16s} {'dR2 recovered':>14s} {'dR2 random curve':>18s}")
    for sc in SCEN:
        rs = [r for r in rows if r["kind"] == "heldout" and r["scenario"] == sc]
        a = [r["heldout"]["delta_r2"] for r in rs]
        b = [r["heldout_placebo"]["delta_r2"] for r in rs]
        print(f"  {sc:16s} {_ms(a):>14s} {_ms(b):>18s}")
    print("  per-run detail (held-out tracer, true tau -> estimated):")
    for r in sorted(rows, key=lambda r: (r["scenario"], r["seed"])):
        if r["kind"] != "heldout":
            continue
        h = r["heldout"]
        print(f"    {r['scenario']:15s} seed {r['seed']}  {h['tracer']:19s} "
              f"tau {h['tau_true']:.2f} -> {h['tau_hat']:.2f}   "
              f"dR2 {h['delta_r2']:+.4f}  (random curve {r['heldout_placebo']['delta_r2']:+.4f})")


def main():
    rows = load(sys.argv[1] if len(sys.argv) > 1 else "results/results.json")
    print(f"{len(rows)} runs, {sum(r['seconds'] for r in rows)/60:.0f} core-minutes")
    boundary_table(rows)
    permeability_table(rows)
    chronology_table(rows)
    type_table(rows)
    placebo_table(rows)
    heldout_table(rows)


if __name__ == "__main__":
    main()
