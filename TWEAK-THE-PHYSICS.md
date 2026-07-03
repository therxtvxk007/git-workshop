# Tweak the Physics

## The substrate frontier: hardware co-design for intelligence per joule

Companion to `INTELLIGENCE-PER-JOULE.md` (the algorithm layer). This is the layer below:
what becomes possible when the hardware is a free variable.

### The core insight: digital computing is a tax, not a law

A GPU running a neural network is physics emulating boolean algebra emulating linear
algebra emulating probability. Every abstraction layer costs energy — and the layers
exist for *generality*, which AI workloads mostly don't need. AI is matrix multiplies,
sampling, and relaxation to equilibrium — and each of those is something some physical
system does **natively, for free, by existing**:

| The math AI needs | The physics that does it for free |
|---|---|
| Matrix–vector multiply | Ohm's law + Kirchhoff's law in a resistor crossbar; light diffracting through a mask |
| Sampling from distributions | Thermal noise in an electron |
| Energy minimization / fixed points | Any physical system relaxing to equilibrium |
| Continuous-time dynamics | Any circuit with capacitance; any material with memory |
| Random projections | Disorder in any messy material |

The efficiency headroom to the Landauer limit is ~10^8. The digital tax is most of it.
"Tweaking the hardware" means collapsing abstraction layers until the math you want *is*
the physics you have. Ladder below, ordered by radicalism.

---

## Rung 1 — Compute-in-memory: stop moving the data

~90% of inference energy is data movement, not arithmetic. Memristor/RRAM crossbars do
the matrix multiply *where the weights live*: weights are conductances, inputs are
voltages, the output current **is** the dot product — one physical step, no fetch.

- [Review of memristors for in-memory computing and SNNs (2026)](https://advanced.onlinelibrary.wiley.com/doi/10.1002/aisy.202500806)
- [Michigan 2026: memristor meeting all three requirements (retention, analog tuning, regulator-free) in a fully analog hardware NN](https://news.engin.umich.edu/2026/03/memristor-demonstrates-use-in-fully-analog-hardware-based-neural-network/)
- [Next-gen reservoir computing implemented in-situ in crossbar arrays](https://www.cell.com/iscience/fulltext/S2589-0042(26)00017-9)
- [BitROM: read-only compute-in-memory for 1.58-bit billion-param inference](https://arxiv.org/pdf/2509.08542) —
  note the co-design: **ternary weights (algorithm doc, Vein 2) are what make ROM-based
  weights-etched-in-silicon viable.** The 1.58-bit constraint wasn't a compromise; it was
  hardware foresight.

**Status:** shipping-adjacent. **Blocker:** analog training (see Rung 2) and D/A
conversion overhead at the array boundaries — the converters can eat the savings, which
is why *staying analog end-to-end* (Rungs 3–4) matters.

## Rung 2 — Training in physics: equilibrium propagation on crossbars

The reason every analog chip today is inference-only: backprop needs global,
high-precision gradient transport, and analog hardware can't do it. The fix is not
porting backprop — it's using learning rules whose *mechanism is physical relaxation*:
equilibrium propagation and predictive coding compute gradients via **local** dynamics,
which crossbars do natively.

- [Learning dynamics in memristor-based equilibrium propagation (2025)](https://arxiv.org/pdf/2512.12428)
- [Energy-efficient crossbar training — on-chip training also absorbs device variability](https://www.mdpi.com/2674-0729/4/3/38)
  (the devices' flaws get *learned around*, turning analog's biggest weakness into a non-issue)
- This is the same vein as the algorithm doc's Vein 7: predictive coding's depth-scaling
  anomaly is the math bug gating this entire rung.

**The deep connection to TRM (this one matters):** latent recursion — TRM's whole trick —
is *iterating a network to a fixed point*. HRM's original theory was literally fixed-point
mathematics. But relaxing to a fixed point is what analog circuits do **by existing**:
you don't iterate, you let the circuit settle. TRM's recursion loop is a discrete digital
*simulation* of what an analog network does for free in nanoseconds. A recursive tiny
reasoner implemented as a settling analog circuit would collapse the algorithm doc's
Vein 1 and this rung into one device: **reasoning as relaxation.** Nobody has built it.

## Rung 3 — Thermodynamic & probabilistic computing: noise as the engine

Digital computing spends enormous energy *suppressing* thermal noise. Probabilistic
computing inverts this: p-bits fluctuate randomly by design, with tunable bias — the
noise IS the random number generator, and networks of p-bits physically *are* samplers.

- [Extropic's thermodynamic sampling units: claimed parity with a top GPU at ~10,000× less energy on sampling workloads](https://arxiv.org/html/2510.23972v1); [XTR0 dev kits shipping](https://extropic.ai/)
- [CMOS probabilistic chip with in-situ hardware-aware learning](https://arxiv.org/pdf/2504.14070)
- [Polymer-based p-bits](https://arxiv.org/pdf/2509.21372); [CACM overview](https://cacm.acm.org/news/thermodynamic-computing-becomes-cool/)

**The match:** diffusion models, energy-based models, Bayesian inference — the workloads
that are *pure sampling* — map onto this hardware with no translation. The honest caveat:
the 10,000× claims are for those niches, not general workloads, and Extropic's numbers
await independent replication. But note the shape: probabilistic AI on probabilistic
hardware is the same "stop translating" move as sampling→noise, matmul→light.

## Rung 4 — Photonic computing: matrix multiply at the speed of light

Light passing through a diffractive mask performs a matrix multiplication with **zero
energy in the multiply itself** — the photons were traveling anyway. The showcase is
(fittingly for this thread's playbook) a Tsinghua paper:

- [ACCEL (Tsinghua, Nature 2023): all-analog photoelectronic chip — 99% of ops optical, ~3,000× faster and claimed ~4,000,000× less energy than an A100 on high-res vision classification](https://interestingengineering.com/science/china-light-ai-chips-faster-than-nvidia)
  ([Tom's Hardware analysis](https://www.tomshardware.com/tech-industry/semiconductors/chinas-accel-analog-chip-promises-to-outpace-industry-best-in-ai-acceleration-for-vision-tasks) —
  more conservative read: 3.7× vs A100 on some tasks; the truth is task-shaped)
- [2025-26 wave: Chinese photonic chips claiming 100× on narrow generative tasks](https://www.techradar.com/pro/not-exactly-a-deepseek-moment-for-ai-accelerators-but-this-chinese-optical-chip-may-well-be-100x-faster-than-nvidias-a100-on-some-tasks)
- [IEEE Spectrum: optical NN cutting energy >99%](https://spectrum.ieee.org/optical-neural-network)

**Status:** works brilliantly for *fixed* linear front-ends (vision feature extraction);
weak at nonlinearity, memory, and reprogrammability. Which is exactly why it wants to be
a **front-end layer**, not a whole computer — see the stack below.

## Rung 5 — Reversible computing: cheating Landauer

[Landauer's limit](https://arxiv.org/pdf/2009.05045) taxes only *irreversible* operations —
erasing a bit costs kT·ln2. Logically reversible computation circumvents the floor
entirely. Adiabatic/reversible circuits exist in labs; nobody has connected them to AI
workloads seriously. Longest horizon, deepest ceiling: this rung is not about 100× — it
is about whether there is *any* thermodynamic floor at all. Watch, don't build (yet).

## Rung 6 — In-materia: covered as Vein 8 in the algorithm doc

Reservoirs — spin waves, ferroelectrics, soft matter — as free nonlinear feature maps.
The bridge rung between "hardware" and "the potato is the computer."

---

## The Potato-Dyson Stack (the co-design endgame)

The rungs compose into a single device architecture, each layer doing what its physics
does for free:

```
  sensor light/signal
        │
  [ photonic / in-materia front-end ]   free nonlinear features   (Rungs 4, 6)
        │  analog
  [ memristor crossbar core ]           matmul in Ohm's law        (Rung 1)
        │  settles to equilibrium
  [ analog recursion: reasoning-as-relaxation ]  TRM's loop as physics (Rung 2 × Vein 1)
        │  needs sampling?
  [ p-bit sampler ]                     noise as randomness        (Rung 3)
        │
  [ tiny digital controller ]           1.58-bit, control only     (Vein 2)
        │
  weights learned in-device, per-device: mortal computation (Vein 7)
```

The last line is Hinton's point sharpened by everything above: a device like this cannot
have its weights copied out — the intelligence is fitted to *this* crossbar's defects,
*this* reservoir's disorder. It is mortal, unclonable, and near-thermodynamic-floor
efficient. (Unclonable-by-physics also quietly solves device identity — the same
property PUFs exploit — connecting this stack back to the Silicon Custody thread.)

## Why analog lost every previous round — and why this round is different

Honesty section. Analog computing has died repeatedly since the 1960s, for three
recurring reasons: (1) precision — analog drifts, digital doesn't; (2) the conversion
tax — A/D boundaries eat the gains; (3) Moore's law — digital got 2× better every two
years for free, so why bet on exotic physics.

What changed: **Moore's law ended** (reason 3 gone). **AI workloads are noise-tolerant
by construction** — a network that survives 1.58-bit quantization does not need five
digits of analog precision (reason 1 defused). **End-to-end analog stacks** like ACCEL's
99%-optical design and on-chip training that learns around device flaws attack reason 2.
None of this guarantees analog wins this round — but the three historical killers are
each specifically weakened, which was never true before.

## Where the tweak-shaped openings are

1. **Reasoning-as-relaxation** (Rung 2 × Vein 1): implement latent recursion as an
   analog settling circuit. Simulation-first (SPICE + a 7M-param TRM is a laptop
   project); the result either way is publishable. Highest originality per dollar on
   this page.
2. **Fix equilibrium-prop/predictive-coding depth scaling** — the single math bug
   gating Rung 2, same target as the algorithm doc's Vein 7. Whoever fixes it hands
   every crossbar and neuromorphic vendor their training algorithm.
3. **Ternary-native crossbar cells** — co-design the {-1,0,+1} constraint into the
   device (three conductance states is *vastly* easier than analog-continuous; BitROM
   points the way). Ternary is the algorithm meeting the hardware halfway.
4. **VSA on p-bits** — hyperdimensional computing was explicitly designed for noisy
   nanoscale substrates; thermodynamic hardware is the noisiest substrate on offer.
   The pairing is sitting in plain sight.
