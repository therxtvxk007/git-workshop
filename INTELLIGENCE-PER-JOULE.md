# Intelligence Per Joule

## The research map for "Dyson spheres on potato PCs" — maximum intelligence on minimal hardware

There are two frontiers in AI. On the **scaling frontier**, capital wins: results cost
$100M runs and math advantages get bought before they compound. On the **efficiency
frontier**, math is the only currency — you cannot buy your way out of 256KB of SRAM or
a microwatt power budget. Every landmark result on this frontier is a clever trick, which
is why it is the natural hunting ground for the "small tweak, massive result" playbook.

The existence proof that this frontier is nowhere near closed: the human brain — 20 watts,
~86B neurons, general intelligence. Every datacenter model is ~6 orders of magnitude less
efficient per unit of capability. The gap between current silicon and the Landauer limit
(the thermodynamic floor for computation) is another ~10^8. The headroom is not a rounding
error; it is the majority of what's possible.

Eight veins, each with anchor papers, the state of the art, and the open tweak-shaped
problems. Then the convergence plays — the unclaimed combinations.

---

## Vein 1 — Latent recursion: reasoning per parameter

**Anchor:** HRM (Sapient Intelligence, 27M params, 40.3% ARC-AGI-1) →
[TRM, "Less is More: Recursive Reasoning with Tiny Networks"](https://arxiv.org/abs/2510.04871)
(Samsung SAIL Montréal, **7M params, 44.6% ARC-AGI-1**, 87.4% Sudoku-Extreme vs HRM's 55%).

The trick: trade parameters for *iterations*. A tiny network refines a latent answer
recursively — depth through time instead of depth through weights. TRM is itself the
proof the arbitrage works: one researcher simplified HRM's math (two networks → one,
dropped the fixed-point theory) and beat it with 4× fewer parameters.

**Open problems (tweak-shaped):**
- Does latent recursion scale — 7M → 100M → 1B? Nobody has published the scaling curve.
- Grafting: recursion as a *module inside* an LLM rather than a competitor to one.
- Open-ended tasks: everything so far is grids and puzzles.
- Quantized recursion: does the iterative refinement survive 4-bit weights? Unpublished.

**Follow-on literature:** [Mamba-2 hybrid TRM](https://arxiv.org/pdf/2602.12078),
[inductive-bias ablations](https://arxiv.org/pdf/2512.11847),
[ARC Prize 2025 technical report](https://arxiv.org/pdf/2601.10904).

---

## Vein 2 — Extreme quantization: intelligence per bit

**Anchor:** [BitNet b1.58](https://en.wikipedia.org/wiki/1.58-bit_large_language_model) —
weights restricted to {-1, 0, +1}, trained natively ternary (not post-quantized), which
lets the network *adapt its representations to the constraint*. Result:
[100B-parameter inference at reading speed on a single CPU](https://glenrhodes.com/microsoft-open-sources-bitnet-enabling-100b-parameter-llm-inference-on-a-single-cpu-using-1-58-bit-ternary-weights/),
no GPU, matrix multiplication reduced to integer addition.

The deep point: ternary weights make **multiplication disappear** from inference
([Matmul or No Matmul in the 1-bit era](https://arxiv.org/pdf/2408.11939),
[FairyFuse ternary CPU kernels](https://arxiv.org/pdf/2604.20913)), and multiplication
is where the silicon and the energy go. Follow-on hardware:
[BitROM read-only compute-in-memory for billion-param 1.58-bit inference](https://arxiv.org/pdf/2509.08542).

**Open problems:**
- Native-ternary *training* efficiency (training still runs in float shadow weights).
- Ternary × recursion (Vein 1) — the two tricks multiply, nobody has composed them.
- Sub-bit: weight sharing/hashing below 1 bit per weight remains mostly unexplored at scale.

---

## Vein 3 — On-device training: learning per byte

**Anchor:** [MIT Han Lab, "On-Device Training Under 256KB Memory"](https://arxiv.org/pdf/2206.15472)
— full training inside a microcontroller's SRAM. 1000× training-memory reduction vs
PyTorch, achieved with math (quantization-aware scaling, sparse layer updates), not
hardware. See also the [TinyML: Progress and Futures survey](https://arxiv.org/pdf/2403.19076)
and [Han Lab's project index](https://hanlab.mit.edu/projects/tinyml).

**State of the art in continual learning on-device:**
[12 mJ per class few-shot class-incremental learning](https://arxiv.org/pdf/2403.07851).

**Open problems:**
- Years-long on-device continual learning without forgetting. The
  ["spurious forgetting" result](https://arxiv.org/pdf/2501.13453) (most forgetting is
  shallow-layer alignment disruption, not knowledge loss) has never been carried down to
  the MCU regime — where protecting a few layers is *cheap*. Straight transplant, big win.
- [Streaming RL that finally works](https://arxiv.org/pdf/2410.14606) has not been
  ported to embedded constraints.

---

## Vein 4 — Hyperdimensional computing: the forgotten algebra

**Anchor:** [Vector Symbolic Architectures as a computing framework for emerging hardware](https://www.researchgate.net/publication/365110950_Vector_Symbolic_Architectures_as_a_Computing_Framework_for_Emerging_Hardware);
[HD computing overview](https://en.wikipedia.org/wiki/Hyperdimensional_computing).

Represent everything as ~10,000-dimensional random vectors; compute with three algebraic
operations (bind, bundle, permute). Properties nothing else on this list has: **one-shot
learning** (no gradient descent at all), extreme noise robustness (holographic
representation — any 10% of the bits carries the signal), and trivially parallel integer
math. Already runs classification and even training on MCUs
(HyperCam: 93.6% MNIST on a low-power microcontroller) with
[42× energy gains in hardware implementations](https://arxiv.org/pdf/2506.09282).

**Why it's underexploited:** it peaked as a niche before deep learning ate the field's
attention; the community is small and hardware-oriented. Hybrids with modern nets barely
exist ([BiHDTrans, binary hyperdimensional transformer](https://arxiv.org/pdf/2509.24425)
is nearly alone). [Capacity theory](https://arxiv.org/pdf/2301.10352) and
[modular composite representations](https://arxiv.org/pdf/2511.09708) are recent and
tweakable.

**Open problems:** VSA as the *memory* of a tiny reasoner (symbolic binding is exactly
what neural nets lack); VSA on intermittent power (its noise robustness means partial
computation ≈ approximate answer — free anytime inference).

---

## Vein 5 — Liquid / continuous-time networks: intelligence per neuron

**Anchor:** MIT's liquid neural networks —
[**19 neurons** keeping a car in lane](https://venturebeat.com/ai/how-mits-liquid-neural-networks-can-solve-ai-problems-from-robotics-to-self-driving-cars),
a task that takes a conventional net ~100,000 neurons. Made practical by
[closed-form continuous-time (CfC) networks, Nature MI 2022](https://www.nature.com/articles/s42256-022-00556-7),
which killed the ODE-solver overhead.

The trick: neurons are differential equations with input-dependent time constants —
each neuron is enormously more expressive, and the network adapts its dynamics *after*
training. Commercially validated (Liquid AI; AMD-backed) but the company chases LLMs —
**the extreme-edge application space (19-neuron controllers for every actuator on
earth) is left on the table.**

**Open problems:** CfC on neuromorphic/analog substrates; formal verification of tiny
CfC controllers (19 neurons is small enough to *prove things about* — certifiable
neural control for aviation/medical, a regulatory moat).

---

## Vein 6 — Intermittent & batteryless intelligence: inference per harvested joule

**Anchor:** [Inference on intermittently-powered systems](https://arxiv.org/pdf/1810.07751),
[Intermittent Learning](https://arxiv.org/pdf/1904.09644),
[FreeML energy-adaptive inference](https://arxiv.org/abs/2405.10426).

Devices powered by harvested light/vibration/RF compute in bursts between power deaths.
This is the trillion-sensor endgame: zero battery, zero maintenance, decade lifetimes.
The literature is still small enough that single-author papers move the frontier.

**Open problems:** intermittent *training* (barely touched since 2019); checkpointing
strategies co-designed with model architecture instead of bolted on; and the anytime
convergence play below.

---

## Vein 7 — Local learning rules & mortal computation: training per joule

**Anchors:** [Hinton's Forward-Forward algorithm](https://www.cs.toronto.edu/~hinton/FFA13.pdf)
and his ["mortal computation" argument](https://www.inference.vc/mortal-computation-hintons/):
if you want trillion-parameter intelligence at a few watts, the computation may have to
be *inseparable from its specific analog hardware* — learned in, non-transferable, dying
with the device. Immortality (copyable weights) is what costs the energy.
[Predictive coding provably approximates backprop with purely local updates](https://arxiv.org/pdf/2006.04182);
[equilibrium propagation just reached ImageNet scale](https://arxiv.org/pdf/2606.03584);
[hybrid digital-analog gradient schemes](https://arxiv.org/pdf/2409.03306) are emerging.

**The known anomaly (= the opportunity):** deeper predictive-coding models perform
*worse* — inverted depth scaling, backwards vs. backprop. That is a math bug in an
otherwise-proven framework. Whoever finds the stability fix (normalization? update
scheduling?) hands the entire analog-hardware industry its training algorithm.

**Why sharks care:** the analog chips are already shipping —
[microwatt neuromorphic processors ordering at CES 2026](https://www.electropages.com/2025/10/new-analogue-neuromorphic-processors-offer-microwatt-edge-ai),
[Innatera T1, Loihi 2, Akida](https://quantaracore.in/blog/neuromorphic-chips-guide.html),
[massively parallel analog in-memory architectures](https://arxiv.org/pdf/2211.12877) —
and every one of them is inference-only *because the training algorithm doesn't exist yet*.

---

## Vein 8 — Physical reservoir computing: the potato IS the computer

**Anchor:** [Physical reservoir computing with emerging electronics, Nature Electronics](https://www.nature.com/articles/s41928-024-01133-z).

The endpoint of the whole efficiency frontier: stop simulating dynamics on silicon and
let **matter itself do the computation**. Any sufficiently rich nonlinear physical
system — [spin waves](https://arxiv.org/pdf/2603.29311),
[optomechanics](https://www.pnas.org/doi/10.1073/pnas.2424991122),
[ferroelectric-ionic transistors](https://advanced.onlinelibrary.wiley.com/doi/10.1002/adma.202511337),
[magnetic metamaterials](https://www.nature.com/articles/s42005-023-01352-4), the
elasticity of a soft robot's own body — acts as a fixed random feature map ("reservoir"),
and you train only a linear readout on top. Training a linear layer is trivial; the
physics computes for free, at femtojoules, in parallel, forever.

**Why it's stuck:** every group demos its own material on toy tasks (spoken digits,
time series). There is no standard task suite, no composability story, no "reservoir +
modern readout (VSA? tiny transformer?)" literature to speak of.

**Open problems:** benchmarking harness across substrates; stacking reservoirs;
reservoir front-end + trained tiny model back-end as a standard architecture. This vein
is 5–10 years behind the others in engineering maturity — highest risk, and the most
literal realization of "dyson sphere on a potato."

---

## The convergence plays (the unclaimed combinations)

The veins multiply. Each pairing below is, as far as this sweep found, unclaimed:

1. **The nano-reasoner: Vein 1 × 2 × 3.** TRM at 1.58-bit is ~1.4MB — flash-resident on
   a $5 MCU, multiplication-free. On-device recursion means *reasoning* (not
   classification) at the extreme edge. No published attempt.
2. **Anytime reasoning under harvested power: Vein 1 × 6.** Latent recursion is
   naturally *anytime* — every iteration refines the answer, so power death mid-compute
   yields a coarser answer instead of no answer. Intermittent computing currently
   bolts early-exit branches onto feedforward nets; a recursive reasoner is an
   early-exit machine *by construction*. This is a paper waiting for an author.
3. **The analog training algorithm: Vein 7 × the shipping chips.** Fix predictive
   coding's depth anomaly (or scale Forward-Forward), and every inference-only
   neuromorphic part in the field guide becomes a *learning* device.
4. **Symbolic memory for tiny reasoners: Vein 4 × 1.** VSA binding gives a 7M-param
   recursive net the compositional memory transformers fake with attention — at integer
   cost.
5. **Certified 19-neuron control: Vein 5 × formal methods.** Networks small enough to
   verify exhaustively → provably-safe neural controllers → the aviation/medical/auto
   regulatory moat.
6. **Reservoir front-end, trained back-end: Vein 8 × 4/1.** The physics does the
   nonlinear feature extraction for free; a VSA or tiny recursive readout does the
   cognition. "Sensor that thinks" with near-zero energy budget.

## How to hunt in this space (the distilled playbook)

Pick targets where **(a)** the math is peer-reviewed and reproducible on hobby-scale
compute, **(b)** the authors are academics or corporate researchers who won't
productize, **(c)** there's a public leaderboard or benchmark that makes wins legible
(ARC-AGI-2 is ideal: everything scores <10%), and **(d)** two veins intersect — because
composition is where "minor tweak" turns into "massive result." Every experiment implied
by plays 1–2 and 4 above costs one dev board and single-GPU training runs. That is the
whole point of this frontier: the table stakes are a potato.
