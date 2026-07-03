# Quantum Pieces

## Where quantum hardware actually helps — the warm, small, cheap parts

Companion to `TWEAK-THE-PHYSICS.md`. The question this answers: where does
quantum-*related* hardware help most, deliberately excluding the cathedral — the
fault-tolerant gate-model quantum computer at -273°C, which is real but decades from
mattering to this thesis.

### The sorting principle

Split "quantum hardware" into two categories that the hype conflates:

1. **Coherence-dependent** devices — need qubits to stay entangled: gate-model QC,
   quantum advantage for ML. Fragile, cryogenic, error-correction-bound. Furthest out.
2. **Coherence-free quantum effects** — tunneling, spin, discrete photons, quantum
   randomness — harnessed as a *resource* in devices that run **at room temperature,
   on existing fab lines, today**. This category is not future tech; parts of it are
   in your phone.

Everything valuable near-term is in category 2. Ranked by impact on the
intelligence-per-joule thesis:

---

## 1. Stochastic magnetic tunnel junctions — the quantum p-bit (the winner)

The headline result of this entire research thread. An sMTJ is an MRAM cell engineered
with a *low* energy barrier so quantum tunneling + thermal agitation make it flicker
randomly between states — a natural, tunable random bit at room temperature, built on
**market-ready MRAM production lines**.

- [A 250-MTJ probabilistic Ising machine](https://arxiv.org/pdf/2506.14590) achieved
  2.5×10⁴ solutions/sec/watt — **six orders of magnitude better than quantum
  processors and seven orders better than GPUs on identical benchmarks.** Read that
  again: the room-temperature quantum *component* beats the cryogenic quantum
  *computer* at the quantum computer's own signature workload (Ising optimization),
  by a million-fold, on energy.
- [On-chip p-bit cores: sMTJs + 2D MoS₂ transistors](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11096331/)
- [sMTJs as hardware p-bits with sigmoidal transfer curves](https://www.emergentmind.com/topics/stochastic-magnetic-tunnel-junction-smtj) —
  the sigmoid is the device physics; the neuron's activation function comes for free.
- [Hybrid memristor–MTJ Ising machines with intrinsic annealing](https://www.researchgate.net/publication/392766212_Intrinsic_Annealing_in_a_Hybrid_Memristor-Magnetic_Tunnel_Junction_Ising_Machine) —
  crossbar (Rung 1) + quantum p-bit (this) in one device, already demonstrated.
- [p-bits machine-learning quantum systems](https://arxiv.org/pdf/2310.06679) — the
  probabilistic hardware even encroaching on quantum simulation itself.

**Why this ranks first:** it *is* the missing hardware for Rung 3 (thermodynamic
computing). Extropic builds custom CMOS; sMTJs offer the same p-bit primitive from a
device the memory industry already mass-produces. Sampling workloads — diffusion,
energy-based models, Bayesian inference, combinatorial optimization — get their native
substrate from a quantum tunneling effect that needs no coherence, no cooling, no new fab.

## 2. NV-center diamond sensing — the quantum front-end for data

A nitrogen-vacancy center is a single-atom-scale defect in diamond whose spin state
reads out optically **at room temperature** — a quantum sensor with
[femtotesla-class sensitivity and nanoscale resolution](https://entangledfuture.com/guides/nv-center-quantum-computing/):
map the magnetic field of a *single neuron*, image the structure of a single protein,
detect current in a nanometer wire. No classical sensor can do any of that.

- [Commercially mature now — sensing, not computing, is the revenue line](https://entangledfuture.com/guides/nv-center-quantum-computing/)
  (Qnami, Quantum Diamonds, NVision, Chipiron: niche-by-niche real products)
- [On-chip diamond micro-resonator quantum sensors](https://www.nature.com/articles/s43246-025-00770-x)
- [Magnetoneurography/magnetomyography](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9885266/) —
  reading nerve and muscle signals *without electrodes or surgery*: the non-invasive
  BCI path runs through this device.

**Thesis fit:** intelligence is downstream of data, and quantum sensing moves the data
floor itself — signals that classically don't exist to be sensed. In the Potato-Dyson
stack this is the layer *above* the photonic front-end: quantum-grade input.

## 3. Single-photon detectors & quantum RNG — already in your pocket

The unglamorous proof that category 2 ships: SPAD arrays (single-photon avalanche
diodes) are in phone LiDAR today — imaging at light's quantum floor, photon by photon.
QRNG chips (quantum random number generators) shipped in consumer phones years ago.
Individually small; strategically important as the existence proof + as feedstock —
true quantum randomness is exactly what sampling hardware (item 1, Rung 3) consumes.

## 4. Quantum reservoir computing — the warm quantum reservoir

The one place a *computing* quantum system helps without fault tolerance: use a small,
noisy quantum system as a **reservoir** (Vein 8 logic — fixed random dynamics + trained
linear readout). Decoherence and noise, fatal for gate-model QC, are *features* here —
the reservoir is supposed to be messy.

- [QRC on near-term devices](https://arxiv.org/pdf/2011.04890) ·
  [configured QRC for multi-task learning](https://arxiv.org/abs/2303.17629) ·
  [coupled quantum oscillators as reservoir](https://arxiv.org/pdf/2209.03221) ·
  [where quantum advantage in RC actually comes from](https://arxiv.org/pdf/2302.03595)
- Exponential state space per physical component: an n-spin reservoir explores 2ⁿ
  dimensions of dynamics — feature richness per atom no classical reservoir matches.

**Honest status:** research-grade; the demonstrated advantages are on small tasks. But
it's the correct *shape* of quantum computing for this thesis: no error correction, no
cryostat requirement in several proposals, noise-tolerant by construction.

## 5. Tensor networks — quantum math, zero quantum hardware

The stealth entry. Tensor networks were invented to simulate quantum many-body systems;
they turn out to be a general compression algebra for high-dimensional functions —
including classical neural networks.

- [Tensor networks for quantum ML (Royal Society)](https://royalsocietypublishing.org/doi/10.1098/rspa.2023.0218)
- [Quantum-inspired tensor-network reservoir computing, simulating 100 qubits with low classical overhead](https://arxiv.org/html/2503.05535v1)
- [Randomized tensor-network reservoirs with learnability phase transitions](https://iopscience.iop.org/article/10.1088/2632-2153/aded56)

**The punchline:** "quantum-inspired" currently beats actual quantum hardware at ML —
100 simulated qubits on a laptop outperform 100 physical qubits in a fridge. For the
efficiency frontier, tensor-network compression of tiny models is another unexploited
math vein (compressing a 7M-param TRM with MPS layers: unpublished, laptop-scale).

## 6. Tunnel FETs — quantum tunneling vs. the transistor's thermal floor

Deepest and slowest: every conventional transistor pays the Boltzmann limit
(≥60 mV/decade switching at room temperature) — a thermodynamic floor on *all* digital
rungs of the physics ladder. Tunnel FETs switch by quantum tunneling instead of thermal
injection, breaking that floor. Still a materials struggle, but it's the only known
path to orders-of-magnitude cheaper *digital* switching — the rung that would lift even
the boring parts of every stack.

---

## The revised bottom line

"Quantum helps most" ≠ quantum computers. Ranked by leverage on intelligence-per-joule:

1. **sMTJ p-bits** — the thermodynamic-computing substrate, on today's MRAM lines,
   beating QPUs by 10⁶ on their own benchmark. Slot it into the Potato-Dyson stack as
   the sampler layer.
2. **NV sensing** — quantum-grade data acquisition, room temperature, shipping.
3. **SPADs/QRNG** — already commodity; randomness feedstock.
4. **Quantum reservoirs** — the research bet: exponential dynamics per atom, noise as
   a feature.
5. **Tensor networks** — quantum mathematics needing no quantum hardware at all.
6. **TFETs** — the long game against the Boltzmann floor.

The pattern across all six: the value is in quantum *effects as resources* —
tunneling as randomness, spin as sensitivity, photon discreteness as precision —
not coherence as computation. Coherence is the expensive part; every win above
is coherence-free.
