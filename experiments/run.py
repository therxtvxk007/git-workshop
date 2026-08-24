"""Run the full experiment matrix: joint inversion against its kill criteria.

Three questions, from the project's own kill list:

  1. Does change-surface detection plus geographic RD do as well?   -> `womble`
     (trace the fused ridge, then estimate permeability at that fixed curve)
     and `shared`  (one permeability for every tracer -- the multivariate
     difference-boundary / areal-wombling model).
  2. Does it invent boundaries where there are none?                -> `null`
  3. Can the recovered boundary predict an independent outcome?     -> `heldout`
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from boundary_tomography import core, evaluate as ev, inverse, scenarios as S

SCENARIOS = ["physical", "administrative", "economic"]


def run_job(job):
    kind, scenario, seed = job
    t0 = time.time()
    data = S.generate(scenario, seed)
    cfg = data["cfg"]

    if kind == "joint":
        res = inverse.fit(data)
        out = ev.summarise(data, res, "joint")
    elif kind == "shared":
        res = inverse.fit(data, shared_tau=True)
        out = ev.summarise(data, res, "shared-tau")
    elif kind == "womble":
        init = inverse.initialise(cfg, data["obs"])
        res = inverse.fit(data, init=init, fix_geometry=True, fit_timing=False,
                          rounds=1)
        out = ev.summarise(data, res, "womble+RD")
    elif kind.startswith("single:"):
        m = int(kind.split(":")[1])
        res = inverse.fit(data, tracers=[m])
        out = ev.summarise(data, res, f"single:{S.TRACERS[m]}")
        out["tau_est"] = [float(res["tau"][0])]
        out["tau_true"] = [float(data["truth"]["tau"][m])]
        out["tau"] = ev.tau_error(res["tau"], [data["truth"]["tau"][m]])
        out["predicted_type"], out["correct_type"] = None, None
    elif kind == "heldout":
        held = seed % cfg.M
        keep = [m for m in range(cfg.M) if m != held]
        res = inverse.fit(data, tracers=keep)
        out = ev.summarise(data, res, "heldout")
        out["heldout"] = ev.heldout_tracer(data, res, held)
        # control: the identical test against a randomly placed curve, so the
        # reported gain cannot be an artefact of "any curve helps"
        rng = np.random.default_rng(seed + 9000)
        fake = dict(res, ctrl=S.random_curve(rng, cfg.n_ctrl, cfg.nx))
        out["heldout_placebo"] = ev.heldout_tracer(data, fake, held)
    else:
        raise ValueError(kind)

    out["kind"], out["seconds"] = kind, time.time() - t0
    return out


def build_jobs(seeds):
    jobs = []
    for sc in SCENARIOS:
        for sd in seeds:
            jobs += [("joint", sc, sd), ("shared", sc, sd), ("womble", sc, sd),
                     ("heldout", sc, sd)]
            jobs += [(f"single:{m}", sc, sd) for m in range(len(S.TRACERS))]
    for sd in range(2 * len(seeds)):       # placebo: no shared interface exists
        jobs += [("joint", "null", sd), ("womble", "null", sd)]
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="results/results.json")
    a = ap.parse_args()

    jobs = build_jobs(list(range(a.seeds)))
    print(f"{len(jobs)} jobs on {a.workers} workers", flush=True)
    t0 = time.time()
    rows = []
    with Pool(a.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(run_job, jobs), 1):
            rows.append(r)
            print(f"[{i}/{len(jobs)}] {r['scenario']:15s} {r['kind']:12s} "
                  f"seed={r['seed']} mae={r['boundary']['mae']:6.2f} "
                  f"({r['seconds']:.0f}s)", flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rows, indent=1))
    print(f"wrote {a.out} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
