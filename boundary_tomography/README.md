# Multi-tracer inverse tomography of a vanished interface

A working prototype for the question: **can several individually uninformative,
passively observed social processes identify a shared hidden interface, because
each encounters that interface differently?**

Nothing here is fitted to real data. It is a controlled synthetic study whose
purpose is to find out whether the idea survives contact with its own kill
criteria before any real data is touched.

## The setup

`M = 5` tracers — market prices, road orientation, land tenure, tax capacity,
settlement density — are observed as scalar fields on a 40x40 grid at 6 epochs.
Each tracer equilibrates under

    div( C_m(x, t) grad u_m ) - lambda u_m + s_m(x) = 0

with its own smooth, independent source field `s_m`. Conductance `C_m` is
uniform except on interfaces, where it is reduced.

Two kinds of interface exist:

* one **shared** interface, present in every tracer but with a tracer-specific
  permeability `tau_m`, and active only over an epoch window `[t_on, t_off]`;
* a **private distractor** per tracer, a sharp discontinuity nobody else sees.

The distractors are the whole point. Real geography is full of sharp things —
rivers, scarps, soil boundaries, forest edges — and each shows up in some
processes and not others. Without them the problem is trivial: any single
tracer's residual map hands you the answer. With them, no single tracer can
tell "the" vanished frontier from its own discontinuity, and the only thing
that distinguishes the shared interface is that it recurs across tracers with
*different* permeabilities.

Three interface types are simulated, differing only in their permeability
profile and chronology:

| type | tau (prices, roads, tenure, tax, settlement) | chronology |
|---|---|---|
| physical (mountain) | 0.35, 0.20, 0.40, 0.45, 0.30 | always present |
| administrative (imperial frontier) | 0.85, 0.55, 0.10, 0.05, 0.60 | epochs 1.2–4.4 |
| economic (market jurisdiction) | 0.15, 0.70, 0.90, 0.95, 0.35 | from epoch 2.8 |
| null (placebo) | none | — |

## What is recovered

Interface geometry (6 spline control points), the chronology `(t_on, t_off)`,
and the permeability `tau_m` for each tracer. The **permeability profile is the
point** — recovering geometry alone is what existing boundary-detection methods
already do. The profile is what says whether the interface was physical,
administrative or economic.

## Method

The unknowns split, which is what makes the search tractable without gradients:

* geometry and chronology are **shared** across tracers — the identifying assumption;
* `tau_m` is **private** to a tracer and, given the geometry, separable across `m`;
* source coefficients `beta_m` enter **linearly** and are profiled out in closed
  form, so they never enter the search space.

That gives a 6-D outer problem, a 2-D chronology problem, and `M` independent
1-D problems, cycled by block-coordinate descent from a screened initialisation.

Initialisation matters more than the optimiser. Candidate curves come from
Viterbi ridge-tracing over rank-fused residual sharpness, computed over the
whole record and over each half separately, plus non-maximum-suppressed
runners-up and each tracer's own best ridge. Candidates are then screened
jointly against four coarse chronology hypotheses on a permeability grid.

## Two things the prototype established the hard way

**Bulk conductivity is not estimable and must not be fitted.** With transport
range `sqrt(K/lambda)` much larger than the domain, `u ~ K^-1 L^+ s`, so `K` and
the source amplitude are degenerate — profiling `beta` absorbs any rescaling of
`K` exactly. Left free, the search drove `K` down by an order of magnitude,
because a shorter transport range lets the smooth source basis mimic
interface-like structure, and that biased `tau`. `K` is held at 1 and absorbed
into the source scale; `tau_m` is a ratio against it.

**Chronology must be screened jointly with geometry, not after it.** Screening
candidate curves as though the interface were always present breaks on a
late-appearing one: the early epochs get modelled as though it existed, the fit
pushes `tau` towards 1 to limit the damage, and the *true* curve scores worse
than somebody's private discontinuity. On the economic scenario this alone was
the difference between 4.5 cells of error and 1.3.

## Reproducing

```
pip install numpy scipy matplotlib
python experiments/run.py --seeds 5 --workers 4     # full matrix, ~1 core-hour
python experiments/naive_womble.py 5                # plain wombling baseline
python experiments/summarise.py results/results.json
python experiments/figures.py
```

## What this does not establish

* It is synthetic, and the inversion assumes the same interface family and the
  same PDE that generated the data. The distractors are unmodelled and the
  source field is generated from a Gaussian random field but fitted with 16
  coarse RBFs, so the misspecification is real but mild. This is not a test
  against a different generative process, and it is not a test on real data.
* The interface is a single-valued curve `x = c(y)`. Closed loops, branching
  frontiers and multiply-connected boundaries are untested.
* Exactly one shared interface exists. Real regions carry several overlapping
  historical frontiers.
* Permeability saturates: below `tau ~ 0.15` the field stops responding, so the
  data can say "nearly closed" but not how nearly. Profile *shape* survives
  this; absolute values do not.
* **No identifiability theorem is proved here.** The paper's actual contribution
  would be sufficient conditions under which independent sources and differing
  tracer permeabilities recover a shared interface. This prototype is an
  existence demonstration in a controlled setting, which is a different and much
  weaker thing.
