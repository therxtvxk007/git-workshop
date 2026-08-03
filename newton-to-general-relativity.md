# From Newton to General Relativity

### A single chain of reasoning, with as few imported facts as possible

---

## The ledger

Before starting, let me be honest about what is *assumed* versus what is *derived*, because the
whole point of this document is that the list on the left is embarrassingly short.

**Empirical inputs (3):**

| # | Input | Where it enters |
|---|---|---|
| **E1** | All bodies fall with the same acceleration, whatever they are made of. | Step 2 |
| **E2** | Space is homogeneous and isotropic; no inertial observer is privileged. | Step 4 |
| **E3** | Light has a finite propagation speed and a countable phase (crests). | Step 5 |

**Principles (2)** — these are not facts, they are demands we place on any acceptable theory:

| # | Principle | Where it enters |
|---|---|---|
| **P1** | *Locality.* No influence acts across a distance with no intermediary and no delay. (Newton's own objection to his own theory.) | Step 5 |
| **P2** | *Determinism from minimal data.* The state of the field plus its rate of change should determine the future. | Step 12 |

**Everything else below is logic.** Newton's law of gravitation, $F = GMm/r^2$, is never used as a
structural input. It appears only as a *target to be reproduced*: once in Step 9 to suggest what
shape the field equation should have, and once in Step 11 to fix the numerical value of a single
constant. Nothing in the chain depends on the inverse square being an inverse square — that is an
output. That is the discipline: we are not going to "relativize
Newton," we are going to notice that Newton's own theory contains a fact it cannot explain, pull
on that thread, and watch the whole thing unravel into geometry.

Signature convention throughout: $(-,+,+,+)$. Greek indices run $0,1,2,3$; Latin run $1,2,3$.

---

## Step 1. Newton's theory contains a coincidence it cannot explain

Newton's mechanics has two laws in which a quantity called "mass" appears, and they have nothing
to do with each other.

The first is the definition of inertia:

$$\mathbf{F} = m_I \mathbf{a}$$

Here $m_I$ measures *reluctance to be pushed*. It is a property of the body alone, and it appears
in every force law — electric, magnetic, elastic, frictional.

The second is the law of gravitation:

$$\mathbf{F} = -\frac{G M m_G}{r^2}\hat{\mathbf{r}}$$

Here $m_G$ measures *gravitational charge* — how strongly the body couples to the gravitational
field. It is the exact analogue of electric charge $q$ in Coulomb's law.

There is no reason in Newton's framework why these two numbers should be related. Electric charge
is not proportional to inertia; a proton and a positron have wildly different $m_I$ and identical
$q$. Yet for gravity, and only for gravity, experiment says (**E1**)

$$m_G = m_I \qquad \text{for every body, to whatever precision you care to test.}$$

Newton knew this. He tested it with pendulums. He wrote it down and moved on. It is the single
loose thread in classical physics, and it is the only thing we will need.

**The immediate consequence.** Put the two laws together:

$$m_I \mathbf{a} = m_G \mathbf{g} \quad \Longrightarrow \quad \mathbf{a} = \mathbf{g}$$

The mass cancels. *Acceleration in a gravitational field is independent of the body being
accelerated.* Gravity is the only force with this property.

---

## Step 2. Therefore gravity is not a force

Here is the logical move that everything else rests on. Ask: what else has the property of
accelerating all bodies identically, regardless of composition?

**A change of reference frame.**

If I describe the world from a frame that is accelerating with $-\mathbf{A}$, then every object in
the world — lead, feathers, neutrinos, thoughts — appears to accelerate by $+\mathbf{A}$. That is
not a statement about the objects. It is a statement about my coordinates. The "force" is
fictitious: it has no source, it acts on everything equally, and it vanishes if I stop
accelerating.

Compare the two lists:

| Property | Fictitious force (accelerated frame) | Gravity | Any real force (e.g. EM) |
|---|---|---|---|
| Acts on all bodies equally? | Yes | **Yes** (E1) | No |
| Independent of composition? | Yes | **Yes** (E1) | No |
| Removable by choosing a frame? | Yes, by definition | **?** | Never |

The first two rows match exactly. The logic is then forced: either this is a coincidence of
staggering precision, or the third row matches too.

**Take the second option.** This is the *equivalence principle*, and note that it is not a new
physical postulate — it is the refusal to accept E1 as a coincidence.

$$\boxed{\text{A freely falling frame is indistinguishable from an inertial frame.}}$$

Concretely: step into a falling elevator. Release a ball. It floats. Release a lead brick. It
floats too — *because it falls at the same rate you do*, which is E1 and nothing else. Inside that
elevator, gravity is gone. Not weakened: **gone**. Every experiment you can do gives the answer it
would give in deep space.

And conversely: sit in a windowless box in deep space being towed at $9.8\,\text{m/s}^2$. Release a
ball. It falls. You cannot tell whether you are accelerating or standing on Earth.

**What follows immediately.** A real force cannot be made to vanish by a coordinate change — the
electromagnetic field tensor $F_{\mu\nu}$ is a tensor, and a tensor that is nonzero in one frame is
nonzero in all of them. So if gravity *can* be transformed away, gravity is **not a tensor field
of forces**. It is not a force at all.

Then what is it? It is a statement about **which frames are inertial** — about what "unaccelerated"
means. And the answer, we are about to see, varies from place to place.

---

## Step 3. But gravity cannot be transformed away *everywhere at once*

If gravity were *globally* removable, it would be pure bookkeeping and there would be nothing to
explain. It isn't. Take the elevator, but make it very large — say, the size of the Earth's
diameter — and drop it toward the Earth. Release two balls, side by side, separated horizontally
by $\xi$.

Both fall toward the Earth's *center*. Their paths converge. In the elevator's frame, the two
balls drift toward each other. Release two balls separated *vertically*: the lower one is deeper in
the field, falls faster, and they drift apart.

This is a **tidal effect**, and it is not removable. No choice of frame can make both balls float
motionless, because "the frame that kills gravity here" and "the frame that kills gravity one metre
over" are *different frames*.

So we arrive at the precise structure:

> Gravity can be eliminated at any **single event**, but not in any **extended region**. The field
> of "locally inertial frames" exists everywhere, but it *twists* as you move from point to point,
> and that twisting is not removable.

Hold on to that sentence. It is the definition of a curved space, though we have not said the word
yet, and we have used nothing but E1 and a large elevator.

Notice also what has just been identified as the *physically real* part of gravity. Not
$\mathbf{g}$ — that is frame-dependent, an artefact of your coordinates. The real, irreducible,
frame-independent content of gravity is the **relative acceleration of neighbouring free-fallers**.
That is the quantity a theory must compute. Everything else is choice of chart.

---

## Step 4. What is the arena? The relativity principle admits exactly two worlds

We now need to know what kind of object the "field of local inertial frames" lives on. That
requires knowing the structure of the local, gravity-free physics — i.e., what the inertial frames
of a *small* region look like relative to each other.

Take **E2** alone: space is homogeneous and isotropic, time is homogeneous, and all inertial
observers are equivalent. Do *not* assume anything about light. Ask: what are the possible
transformations between two inertial frames in relative motion $v$ along $x$?

1. **Homogeneity** ⟹ the transformation maps straight lines to straight lines and equal intervals
   to equal intervals ⟹ it is **linear**:

$$x' = a(v)\,x + b(v)\,t, \qquad t' = d(v)\,x + e(v)\,t.$$

2. The origin of the primed frame moves at $v$: setting $x'=0$ gives $b = -av$, so

$$x' = a(v)\,(x - vt).$$

3. **Reciprocity** (from isotropy: if I see you move at $+v$, you see me move at $-v$, and space
   has no preferred handedness) ⟹ the inverse transformation is the same function with $v \to -v$,
   which forces $a(v) = a(-v) \equiv \gamma(v)$, an even function.

4. **Closure** (the composition of two boosts must be a boost — the transformations form a group,
   because "inertial frame" is a transitive relation). Compose a boost $v$ and a boost $u$ and
   demand the result have the same form. Grind through the algebra and it collapses to a single
   constraint: there exists a **universal constant** $K$, with dimensions of $1/\text{velocity}^2$,
   such that

$$\gamma(v) = \frac{1}{\sqrt{1 - K v^2}}, \qquad t' = \gamma\,(t - K v x).$$

That is the whole answer. The relativity principle plus symmetry does not give one theory; it
gives a **one-parameter family** of theories, indexed by $K$. And there are only three cases:

- $K < 0$: boosts become *rotations* in the $(x,t)$ plane. Compose enough of them and you return
  to where you started with time reversed — the temporal order of causally connected events is not
  invariant. Self-inconsistent. **Excluded by logic.**
- $K = 0$: $\gamma = 1$ and $t' = t$. **Absolute time.** This is Galileo and Newton.
- $K > 0$: define $c \equiv 1/\sqrt{K}$. Then $\gamma = (1-v^2/c^2)^{-1/2}$ and $c$ is an invariant
  speed. **This is Minkowski.**

So the choice is binary: **either there is an invariant speed, or there is an absolute time.** No
third option. And note that nothing about light has been mentioned; $c$ here is not "the speed of
light," it is the invariant speed that the group structure demands, which light merely happens to
travel at.

---

## Step 5. Newton's own theory forces $K \neq 0$

Now we close the branch. Suppose $K = 0$: absolute time, Galilean world.

Return to the accelerating box in deep space (Step 2). Acceleration $A$, height $h$. Emit a light
signal — or any wave with countable crests (**E3**) — from the floor toward the ceiling. The
signal takes time $\Delta t \approx h/c$ to cross. In that time the ceiling has picked up speed

$$\Delta v = A\,\Delta t = \frac{Ah}{c}.$$

The ceiling is running *away* from the crests as they arrive, so it counts them at a lower rate:

$$\frac{f_{\text{received}}}{f_{\text{emitted}}} = 1 - \frac{\Delta v}{c} = 1 - \frac{Ah}{c^2}.$$

This is elementary Doppler shift in flat, gravity-free space. There is nothing to dispute.

Now apply Step 2's equivalence: this box is *indistinguishable* from a box at rest in a
gravitational field of strength $A$. Therefore the same must happen in the field. Writing
$\Delta\Phi = Ah$ for the potential difference between floor and ceiling:

$$\frac{f_{\text{top}}}{f_{\text{bottom}}} = 1 - \frac{\Delta\Phi}{c^2}.$$

**Read what this says.** The emitter at the bottom sends $N$ crests per second *of its own time*.
The receiver at the top counts fewer than $N$ per second *of its time*. No crests were destroyed in
between — the field is static, so whatever goes in must come out. The only possible resolution:

$$\boxed{\ \text{The two clocks are running at different rates.}\ }$$

$$\frac{d\tau_{\text{top}}}{d\tau_{\text{bottom}}} = 1 + \frac{\Delta\Phi}{c^2}.$$

And now the branch closes. In the $K=0$ Galilean world there is an *absolute time* — by
construction, every clock everywhere ticks at the same rate, and this effect is impossible. But the
effect follows from E1 (Step 2) plus E3 plus arithmetic. So:

$$K \ne 0 \quad \Longrightarrow \quad K > 0 \quad \Longrightarrow \quad \text{there is an invariant speed } c.$$

Newtonian gravity, taken seriously together with the equivalence principle, destroys Newtonian
time. The theory refutes itself.

> **Independent confirmation, from energy alone.** Drop a mass $m$ through height $h$; it gains
> energy $mgh$. Convert the whole thing to radiation, send it up, reconstitute the mass at the top.
> If radiation did *not* lose energy climbing, you would return to the start with $mgh$ in hand and
> could repeat forever. Perpetual motion. So energy climbing a potential must be red-shifted by
> exactly the factor above — same conclusion, from conservation of energy instead of Doppler.

> **Independent confirmation, from locality (P1).** In the $K=0$ world there is no invariant speed,
> so nothing limits propagation — and indeed Newton's $\nabla^2\Phi = 4\pi G\rho$ has *no time
> derivative*. It is a constraint, not an evolution equation: move a mass here and the potential on
> Andromeda changes now. Newton called this "so great an absurdity that no man who has in
> philosophical matters a competent faculty of thinking can ever fall into it." To make the field
> equation hyperbolic — to give it characteristics, a wave speed, a genuine field — you need an
> invariant speed. Only $K>0$ supplies one.

---

## Step 6. The arena is a metric, and its $00$ component is Newton's potential

We now have everything needed to name the arena.

- **Locally** (Step 2), a freely falling frame is inertial. Inertial physics is governed by the
  $K>0$ group (Steps 4–5), whose invariant is the Minkowski interval
  $ds^2 = -c^2dt^2 + dx^2+dy^2+dz^2$.
- **Globally** (Steps 3, 5), these local frames disagree with each other — in particular their
  clocks run at rates that depend on position.

An object that is a Minkowski metric at each point but varies smoothly from point to point *is* a
Lorentzian metric field:

$$ds^2 = g_{\mu\nu}(x)\,dx^\mu dx^\nu, \qquad \text{with } g_{\mu\nu}(p) = \eta_{\mu\nu} \text{ in a suitable frame at each } p.$$

The quadratic form is not a choice. It is inherited: the local invariant is quadratic (Step 4), so
the global object interpolating between local invariants is a rank-2 symmetric tensor field. Ten
functions $g_{\mu\nu}(x)$, of which four are pure coordinate freedom.

**And we already know one component.** Proper time is what clocks measure: $d\tau^2 = -ds^2/c^2$.
For a clock sitting still at position $x$, $d\tau^2 = -g_{00}\,dt^2$. Step 5 gave us
$d\tau = (1+\Phi/c^2)\,dt$. Therefore

$$-g_{00} = \left(1 + \frac{\Phi}{c^2}\right)^{2} \approx 1 + \frac{2\Phi}{c^2}
\qquad \Longrightarrow \qquad \boxed{\,g_{00} = -\left(1 + \frac{2\Phi}{c^2}\right)}$$

This is the hinge of the entire derivation. **Newton's gravitational potential is not a force
field. It is one component of the metric of spacetime** — specifically, the amount by which time
runs slow. Everything Newton called gravity is, to leading order, the statement that clocks tick
slower where the potential is deeper.

---

## Step 7. Free fall is the straightest possible path

Gravity is now geometry, but we need the law of motion. Logic supplies it with no freedom.

In a local inertial frame, a free particle moves in a straight line — that is what "inertial"
means. In flat spacetime, a straight worldline is the one of **maximal proper time** between two
events (this is the twin "paradox": the inertial twin ages most). That statement — *extremal proper
time* — makes no reference to coordinates. So it is true in *every* frame, including the ones where
gravity appears.

$$\delta \int d\tau = 0, \qquad d\tau = \frac{1}{c}\sqrt{-g_{\mu\nu}\,dx^\mu dx^\nu}.$$

Vary it. With $L = \sqrt{-g_{\mu\nu}\dot x^\mu \dot x^\nu}$ and $\lambda = \tau$, the
Euler–Lagrange equations give

$$\boxed{\ \frac{d^2 x^\mu}{d\tau^2} + \Gamma^\mu_{\ \alpha\beta}\,\frac{dx^\alpha}{d\tau}\frac{dx^\beta}{d\tau} = 0\ }
\qquad
\Gamma^\mu_{\ \alpha\beta} = \tfrac12 g^{\mu\nu}\left(\partial_\alpha g_{\nu\beta} + \partial_\beta g_{\nu\alpha} - \partial_\nu g_{\alpha\beta}\right).$$

Three things to notice, all of them forced rather than assumed:

- **No mass appears.** Not $m_I$, not $m_G$. The equation of motion is a property of the
  *spacetime*, not of the particle. E1 is not merely accommodated — it is *unavoidable*. A theory
  in which bodies fell differently could not be written in this form at all. The coincidence that
  started us off has become a theorem.
- **$\Gamma$ is not a tensor.** It transforms inhomogeneously, which is exactly why it can be set
  to zero at any point by a change of coordinates (Step 2) but not everywhere (Step 3). The
  "gravitational force" $\Gamma^\mu_{\ \alpha\beta}$ has precisely the character we demanded of it
  in Step 2: real in one frame, absent in another. It is the field of local inertial frames, made
  explicit.
- **The connection is metric and torsion-free, and it had to be.** Metric-compatible
  ($\nabla_\lambda g_{\mu\nu} = 0$) because clock rates and rod lengths are physical: transporting
  a clock must not change what it measures relative to the local standard. Torsion-free
  ($\Gamma^\mu_{\ \alpha\beta} = \Gamma^\mu_{\ \beta\alpha}$) because the equivalence principle
  demands coordinates in which $\Gamma$ *vanishes* at a point — and the antisymmetric part is a
  tensor, so if it were nonzero it could never be removed. Those two conditions determine
  $\Gamma$ uniquely. There is exactly one connection available, and it is the one above.

**Check against Newton.** Slow motion ($dx^i/d\tau \ll c\,dt/d\tau$, so only the $\alpha=\beta=0$
term survives) and a static field ($\partial_0 g_{\mu\nu}=0$, and $g_{ij}\approx\delta_{ij}$):

$$\Gamma^i_{\ 00} = -\tfrac12 g^{ij}\partial_j g_{00} = -\tfrac12 \delta^{ij}\,\partial_j\!\left[-\left(1+\tfrac{2\Phi}{c^2}\right)\right] = \frac{\partial_i \Phi}{c^2}$$

$$\Longrightarrow \qquad \frac{d^2x^i}{dt^2} = -c^2\,\Gamma^i_{\ 00} = -\partial_i\Phi = \mathbf{g}$$

Newton's law of motion in a gravitational field, recovered exactly — as the statement that a
falling apple is *coasting in a straight line* through a spacetime whose time axis is slightly
tilted by the Earth's mass. Nothing pulls the apple. The apple is going straight; it is the ground,
held up by the electromagnetic rigidity of rock, that is accelerating.

---

## Step 8. The irreducible field is curvature

Step 3 identified the physically real content of gravity: the **relative acceleration of
neighbouring free-fallers**. Compute it.

Take a one-parameter family of geodesics $x^\mu(\tau, s)$, with tangent $u^\mu = \partial x^\mu/\partial\tau$
and separation $\xi^\mu = \partial x^\mu/\partial s$. Since these are coordinate derivatives on the
same surface, they commute: $\nabla_u \xi = \nabla_\xi u$. Then

$$\frac{D^2\xi^\mu}{d\tau^2} = \nabla_u\nabla_u \xi^\mu = \nabla_u \nabla_\xi u^\mu
= \nabla_\xi \underbrace{\nabla_u u^\mu}_{=\,0\ \text{(geodesic)}} + \left[\nabla_u, \nabla_\xi\right]u^\mu$$

so the entire answer is a **commutator of covariant derivatives**, which by definition is the
Riemann tensor:

$$\boxed{\ \frac{D^2 \xi^\mu}{d\tau^2} = -R^\mu_{\ \alpha\nu\beta}\,u^\alpha \xi^\nu u^\beta\ }
\qquad
R^\rho_{\ \sigma\mu\nu} = \partial_\mu\Gamma^\rho_{\ \nu\sigma} - \partial_\nu\Gamma^\rho_{\ \mu\sigma} + \Gamma^\rho_{\ \mu\lambda}\Gamma^\lambda_{\ \nu\sigma} - \Gamma^\rho_{\ \nu\lambda}\Gamma^\lambda_{\ \mu\sigma}.$$

This is the punchline of the first half. The Riemann tensor is *by construction* the failure of
$\Gamma$ to be removable in a neighbourhood — it is built from derivatives of $\Gamma$ in an
antisymmetrised combination that survives when $\Gamma$ itself is set to zero at a point. It is
exactly the object Step 3 said we needed: zero if and only if gravity is globally fake, nonzero
otherwise, and a **tensor**, so no coordinate change can hide it.

$$\text{Gravity} = \text{Curvature.}$$

Not by analogy, not by aesthetic preference. By the requirement that the theory's physical content
be the part of the field that cannot be transformed away.

**Check against Newton.** Two particles at rest, separated by $\xi^i$, in the weak static field of
Step 6. Newton says the tidal drift is $\ddot\xi^i = -(\partial_i\partial_j\Phi)\,\xi^j$. The
geodesic-deviation equation with $u^\mu \approx (c,0,0,0)$ says $\ddot\xi^i = -c^2 R^i_{\ 0j0}\xi^j$.
And to first order in $\Phi$, using $\Gamma^i_{\ 00}=\partial_i\Phi/c^2$ from Step 7:

$$R^i_{\ 0j0} = \partial_j \Gamma^i_{\ 00} - \partial_0\Gamma^i_{\ j0} = \frac{\partial_i\partial_j\Phi}{c^2}. \qquad \checkmark$$

The Newtonian **tidal tensor** $\partial_i\partial_j\Phi$ — Newton's only frame-independent
gravitational quantity — is a piece of the Riemann tensor. We have found where Newton's gravity was
hiding all along.

---

## Step 9. What sources the curvature? (First, the obvious guess.)

We have kinematics. We need a field equation: *matter here* ⟹ *curvature there*.

Contract the check above. Newton's field equation is the trace of his tidal tensor:

$$\partial_i\partial_i \Phi = \nabla^2\Phi = 4\pi G\rho.$$

And the trace of the Riemann tensor over the corresponding indices is the Ricci tensor:

$$R_{00} = R^\mu_{\ 0\mu 0} = R^i_{\ 0i0} = \frac{\nabla^2 \Phi}{c^2} = \frac{4\pi G \rho}{c^2}.$$

Newton's field equation, written geometrically. Now, the left side $R_{00}$ is the $00$ component
of a tensor. What is $\rho$ the $00$ component of?

Not of a scalar — mass density is manifestly frame-dependent (a moving box of gas has more energy
*and* its volume contracts). And relativity has already taught us that mass is a form of energy, so
the source cannot be mass alone: energy, momentum, pressure and stress must all appear, since a
boost mixes them. The object with those components, symmetric and rank two, is the
**stress–energy tensor** $T_{\mu\nu}$, with $T_{00} = \rho c^2$.

So the natural guess is:

$$R_{\mu\nu} \overset{?}{=} \kappa\, T_{\mu\nu}.$$

Both sides symmetric, rank two, built from the right ingredients, and reducing to Newton in the
appropriate limit. Einstein believed this for two years.

---

## Step 10. The guess is wrong, and the failure dictates the answer

Here logic does the work that no amount of physical intuition would.

**Left side: a geometric identity.** Work at a point $p$ in normal coordinates — the ones the
equivalence principle guarantees exist, where $\Gamma(p)=0$ (though $\partial\Gamma \ne 0$). Then at
$p$ the Riemann tensor is just $R^\rho_{\ \sigma\mu\nu} = \partial_\mu\Gamma^\rho_{\ \nu\sigma} - \partial_\nu\Gamma^\rho_{\ \mu\sigma}$, and

$$\nabla_\lambda R^\rho_{\ \sigma\mu\nu} = \partial_\lambda\partial_\mu\Gamma^\rho_{\ \nu\sigma} - \partial_\lambda\partial_\nu\Gamma^\rho_{\ \mu\sigma}.$$

Now cyclically permute $\lambda \to \mu \to \nu \to \lambda$ and add the three terms. Every second
derivative appears twice with opposite signs. Everything cancels:

$$\nabla_{[\lambda} R^\rho_{\ |\sigma|\mu\nu]} = 0 \qquad \textbf{(Bianchi identity)}$$

Both sides are tensors, so this holds in all frames; the point $p$ was arbitrary, so it holds
everywhere. **This is not a physical fact.** It is a theorem about any object built as the
curvature of a connection — as inevitable as $\partial_\mu\partial_\nu = \partial_\nu\partial_\mu$.
Contract it twice ($\rho$ with $\mu$, then $\sigma$ with $\nu$):

$$\nabla^\mu\left(R_{\mu\nu} - \tfrac12 R\,g_{\mu\nu}\right) = 0.$$

The Ricci tensor alone is *not* divergence-free; only that particular combination is.

**Right side: a physical requirement.** In a local inertial frame, gravity is absent and
special-relativistic physics holds, in which energy and momentum are locally conserved:
$\partial^\mu T_{\mu\nu}=0$. Promote to arbitrary coordinates (there is only one way — replace
$\partial$ with $\nabla$, and Step 7 already fixed $\nabla$ uniquely):

$$\nabla^\mu T_{\mu\nu} = 0.$$

**Collide the two.** If $R_{\mu\nu} = \kappa T_{\mu\nu}$, then taking the divergence gives
$\nabla^\mu R_{\mu\nu} = 0$. But Bianchi says $\nabla^\mu R_{\mu\nu} = \tfrac12\nabla_\nu R$.
Therefore $\nabla_\nu R = 0$, so $R$ is constant everywhere. Taking the trace of the guess,
$R = \kappa T$, so $T$ is constant everywhere too — the total energy density of the universe would
be forbidden to vary from place to place. **The guess is not merely inaccurate; it is inconsistent
with matter existing in lumps.**

**And the repair is unique.** The left side must be a symmetric, rank-2 tensor built from the
metric, with vanishing divergence *identically* (not as an extra condition). Bianchi has just
handed us exactly one such object out of curvature. Define

$$G_{\mu\nu} \equiv R_{\mu\nu} - \tfrac12 R\, g_{\mu\nu}.$$

$$\boxed{\ G_{\mu\nu} = \kappa\,T_{\mu\nu}\ }$$

There is no room left. **Lovelock's theorem** makes the uniqueness precise: in four dimensions, the
*only* symmetric, identically divergence-free 2-tensors constructible from $g_{\mu\nu}$ and its
first two derivatives, linear in the second derivatives, are

$$a\,G_{\mu\nu} + b\,g_{\mu\nu}.$$

So the most general possible field equation is $G_{\mu\nu} + \Lambda g_{\mu\nu} = \kappa T_{\mu\nu}$
— Einstein's equation, plus one free constant $\Lambda$ that logic permits and does not require.
(Its smallness is not something this chain of reasoning can explain, and nobody else has explained
it either.)

---

## Step 11. Fix the last constant by calibrating against Newton

One number remains. This is the *only* place the inverse-square law is used, and it is used purely
as a units conversion.

Trace the field equation: $g^{\mu\nu}G_{\mu\nu} = R - 2R = -R = \kappa T$. Substitute back to get
the **trace-reversed** form, which is more convenient:

$$R_{\mu\nu} = \kappa\left(T_{\mu\nu} - \tfrac12 T\, g_{\mu\nu}\right).$$

For slow, cold, non-relativistic matter (dust at rest): $T_{00} = \rho c^2$, all else negligible,
and $T = g^{\mu\nu}T_{\mu\nu} = g^{00}T_{00} = (-1)(\rho c^2) = -\rho c^2$. So

$$T_{00} - \tfrac12 T g_{00} = \rho c^2 - \tfrac12(-\rho c^2)(-1) = \tfrac12 \rho c^2.$$

Step 9 gave $R_{00} = \nabla^2\Phi/c^2$. Equate:

$$\frac{\nabla^2\Phi}{c^2} = \frac{\kappa \rho c^2}{2} \qquad \Longrightarrow \qquad \nabla^2 \Phi = \frac{\kappa c^4}{2}\rho.$$

Demand this be Newton's $\nabla^2\Phi = 4\pi G\rho$:

$$\kappa = \frac{8\pi G}{c^4}.$$

And the chain terminates:

$$\boxed{\ R_{\mu\nu} - \tfrac12 R\,g_{\mu\nu} + \Lambda g_{\mu\nu} = \frac{8\pi G}{c^4}\,T_{\mu\nu}\ }$$

---

## Step 12. A second, independent route to the same place

If the above feels like it leaned on the guess-and-repair of Steps 9–10, here is a completely
different argument that lands on the identical equation — which is the strongest evidence that no
choices were made.

Ask for the field equation to come from a variational principle (as every other field theory does),
and impose **P2**: the equations must be second order in $g$, so that $g$ and $\dot g$ on an initial
slice determine the future. (Higher derivatives would require extra initial data that the
equivalence principle gives no way to specify — and, by Ostrogradsky's theorem, would make the
energy unbounded below.) Then:

- The action must be $S = \int \mathcal{L}\,\sqrt{-g}\,d^4x$ with $\mathcal{L}$ a **scalar** — else
  the theory would prefer a coordinate system, contradicting Steps 2 and 4.
- $\mathcal{L}$ must be built from $g_{\mu\nu}$ and its derivatives. But a scalar cannot be built
  from $g$ and $\partial g$ alone: normal coordinates set $\partial g = 0$ at any point, so any such
  scalar is constant.
- So $\mathcal{L}$ needs second derivatives. Every curvature scalar built from second derivatives
  is a combination of $R$ and a constant. And $R$ is *linear* in second derivatives, so the
  resulting equations stay second order despite the Lagrangian being second order.

Hence the unique candidate is

$$S_{\text{EH}} = \frac{c^4}{16\pi G}\int (R - 2\Lambda)\,\sqrt{-g}\;d^4x + S_{\text{matter}}.$$

Vary with respect to $g^{\mu\nu}$, using $\delta\sqrt{-g} = -\tfrac12\sqrt{-g}\,g_{\mu\nu}\delta g^{\mu\nu}$
and $\delta R_{\mu\nu} = \nabla_\lambda \delta\Gamma^\lambda_{\ \mu\nu} - \nabla_\nu\delta\Gamma^\lambda_{\ \mu\lambda}$
(a total derivative, discarded at the boundary):

$$\frac{\delta S}{\delta g^{\mu\nu}} = 0 \qquad \Longrightarrow \qquad R_{\mu\nu} - \tfrac12 R g_{\mu\nu} + \Lambda g_{\mu\nu} = \frac{8\pi G}{c^4}T_{\mu\nu},$$

where $T_{\mu\nu} \equiv -\frac{2}{\sqrt{-g}}\frac{\delta S_{\text{matter}}}{\delta g^{\mu\nu}}$ —
so the stress–energy tensor is not even an input, it is *defined* by how matter responds to the
metric. And $\nabla^\mu T_{\mu\nu}=0$ is then not an assumption either: it follows from the
invariance of $S_{\text{matter}}$ under coordinate changes, via Noether's theorem.

Two independent routes, one destination. There was never a choice.

---

## Step 13. The chain, compressed

1. **Inertial mass equals gravitational mass** — an unexplained coincidence in Newton (E1).
2. Refuse the coincidence ⟹ gravity accelerates everything alike ⟹ it behaves exactly like a
   **fictitious force** ⟹ it can be transformed away locally ⟹ **it is not a force**.
3. Tidal effects show it *cannot* be transformed away globally ⟹ the field of local inertial
   frames **varies from point to point**, and the real content of gravity is the **relative
   acceleration of neighbouring free-fallers**.
4. The relativity principle alone permits exactly two worlds: absolute time, or an invariant speed.
5. Step 2 + Doppler in an accelerating box ⟹ clocks run at different rates at different potentials
   ⟹ **absolute time is dead** ⟹ invariant speed $c$ exists.
6. Locally Minkowski + globally varying ⟹ the arena is a **metric field** $g_{\mu\nu}$, and its
   $00$ component *is* Newton's potential: $g_{00} = -(1+2\Phi/c^2)$.
7. Free = inertial = straight = extremal proper time ⟹ **geodesic equation**, in which the
   particle's mass does not appear (E1 becomes a theorem), and which reproduces $\ddot{\mathbf{x}} = -\nabla\Phi$.
8. Relative acceleration of neighbouring geodesics = commutator of covariant derivatives =
   **Riemann tensor** ⟹ *gravity is curvature*, and the Newtonian tidal tensor is part of it.
9. Newton's $\nabla^2\Phi = 4\pi G\rho$ is the trace of that ⟹ $R_{00} = 4\pi G\rho/c^2$ ⟹ guess
   $R_{\mu\nu} = \kappa T_{\mu\nu}$.
10. The **Bianchi identity** (pure geometry) plus **local energy conservation** (pure equivalence
    principle) kill the guess and leave exactly one repair: $G_{\mu\nu} + \Lambda g_{\mu\nu} = \kappa T_{\mu\nu}$.
11. Calibrate $\kappa$ against Newton once: $\kappa = 8\pi G/c^4$. Done.
12. Independently: the only second-order-consistent scalar action is $\int R\sqrt{-g}$, giving the
    same equation.

Total empirical content consumed: *things fall the same way*, *no observer is special*, *light is
finite and has crests*. Everything else was forced.

---

## Step 14. Did we get anything for free?

A derivation that only reproduced its inputs would be a tautology. This one is not — the same
equation, with no further tuning, says things Newton cannot:

- **Gravitational redshift.** Already derived in Step 5, before the field equation existed. Newton
  has no mechanism for it at all. Verified by Pound–Rebka; corrected for daily by every GPS
  satellite, which would drift ~10 km/day without it.

- **Light bends by exactly twice the "Newtonian" amount.** Treat light as a corpuscle in Newton's
  theory and you get a deflection $2GM/c^2 b$. The metric derivation gives $4GM/c^2b$ — because
  $g_{00}$ contributes one half (the time curvature Step 6 gave us) and the *spatial* components
  $g_{ij}$, which have no Newtonian analogue whatsoever, contribute the other half. The factor of
  two is a clean, unambiguous test of whether gravity is a force in space or the geometry of
  spacetime. It is two.

- **Perihelion precession.** The $1/r^3$ correction to the effective potential, appearing
  automatically from the geodesic equation in the Schwarzschild metric, gives Mercury
  $43''$/century — a number that had been an unexplained anomaly for 60 years and that nobody
  adjusted anything to reproduce.

- **Gravitational waves.** Step 5's locality argument demanded a hyperbolic field equation, and
  linearising $G_{\mu\nu}=\kappa T_{\mu\nu}$ delivers one: $\Box \bar h_{\mu\nu} = -2\kappa T_{\mu\nu}$.
  Ripples in the metric, propagating at $c$, transverse, quadrupolar, two polarisations. Detected
  100 years later, at the predicted strain and waveform.

- **Black holes and cosmology.** Not added; unavoidable. The equation has singular solutions and no
  static cosmological ones. Both were regarded as defects for decades. Both are what we see.

## What it cost

Absolute time. Absolute space. Gravity as a force. Energy conservation as a global statement
(there is no generally covariant way to say how much gravitational energy is in a region — the
field can be transformed away at any point, so its "density" is not a tensor). And the guarantee
that the equations remain valid all the way down: they predict singularities, i.e. their own
breakdown.

That last one is not a flaw in the derivation. It is the derivation, still running.
