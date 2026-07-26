# 08 — Market Making & Inventory Control

The market maker's problem: quote both sides, earn the spread, and don't get run
over by inventory. The mathematics is stochastic optimal control with a running
inventory penalty.

---

## 8.1 The P&L decomposition

Over a period in which you make $N_{\text{fills}}$ round trips and end with inventory $q$:

$$\boxed{\;\mathrm{P\&L} = \underbrace{\sum_i \delta_i}_{\text{spread capture}} + \underbrace{\sum_i r_i}_{\text{rebates}} - \underbrace{\sum_i A_i}_{\text{adverse selection}} - \underbrace{\int q_t\,dS_t}_{\text{inventory risk}} - \underbrace{\text{fees}}_{}$$

**The first two are yours to control through quoting. The third is the price of
doing business. The fourth is what kills firms.**

Notice: $\int q_t\,dS_t$ has zero mean under a martingale price — it contributes
**pure variance**. A market maker's job is to maximize the ratio of the deterministic
terms to the standard deviation of the fourth. That framing gives the objective for
everything below.

**Sharpe of a market-making book.** With $n$ fills/day, edge $e$ per fill, and
end-of-day inventory std $\sigma_q$:

$$\mathrm{SR}_{\text{daily}} \approx \frac{n\,e}{\sqrt{n\,\mathrm{Var}(e) + \sigma_q^2\sigma^2}}$$

For large $n$ with controlled inventory, $\mathrm{SR}\propto\sqrt n$ — **the entire
economics of HFT market making is fill count**. Doubling fills at the same edge
raises Sharpe by 41%. That is why latency and queue position matter more than
alpha.

---

## 8.2 Ho–Stoll: inventory as the driver of quotes

The original insight (1981): a market maker's quotes shift with inventory,
independent of any information.

**Reservation price.** For a CARA agent with risk aversion $\gamma$ holding
inventory $q$ over remaining horizon $\tau$, the price at which they are
indifferent to holding is

$$\boxed{\;r(s,q,t) = s - q\,\gamma\,\sigma^2\,\tau\;}$$

**Derivation.** With exponential utility $-e^{-\gamma W}$ and Gaussian terminal
wealth, the certainty equivalent is $\mathbb E[W] - \frac\gamma2\mathrm{Var}(W)$. Holding
$q$ units over $\tau$: $\mathrm{Var} = q^2\sigma^2\tau$. The indifference price per
unit solves $CE(q) - CE(q-1) $, giving to first order the linear shift above. $\square$

**Read it as:** if you are long ($q>0$), your fair value is **below** the mid — you
should quote lower on both sides, to be more likely to sell and less likely to buy.
The skew is proportional to inventory, risk aversion, variance, and remaining time.

This is the fundamental market-making reflex, and it is not a bet on direction.
It is inventory management.

---

## 8.3 Avellaneda–Stoikov

The canonical modern model, and the one implemented (in some form) by essentially
every electronic market maker.

**Setup.**
- Mid price: $dS_t = \sigma\,dW_t$ (driftless).
- Quote bid at $S-\delta^b$, ask at $S+\delta^a$.
- Fills arrive as Poisson processes with intensity decreasing in distance:
  $$\lambda(\delta) = A\,e^{-k\delta}$$
- Inventory $q_t$ = (buys − sells). Cash $X_t$.
- Objective: maximize CARA utility of terminal wealth,
  $\ \mathbb E\big[-\exp\big(-\gamma(X_T + q_TS_T)\big)\big]$.

**HJB equation.** With value function $u(x,q,s,t)$:

$$\partial_t u + \frac{\sigma^2}{2}\partial_{ss}u
+ \max_{\delta^b}\lambda(\delta^b)\big[u(x - s + \delta^b,\ q+1,\ s,\ t) - u\big]
+ \max_{\delta^a}\lambda(\delta^a)\big[u(x + s + \delta^a,\ q-1,\ s,\ t) - u\big] = 0$$

**The ansatz that makes it solvable:**

$$u(x,q,s,t) = -\exp\big(-\gamma x\big)\exp\big(-\gamma q s\big)\exp\big(-\gamma\theta(q,t)\big)$$

Substituting reduces the PDE to a system of ODEs in $q$; the exponential utility
factorizes cash out entirely, and the exponential fill intensity makes the inner
maximizations explicit.

**Step 1 — the indifference (reservation) price.** Define $r$ as the price at which
the maker is indifferent between current inventory and one unit more/less. The
ansatz yields

$$\boxed{\;r(s,q,t) = s - q\,\gamma\,\sigma^2\,(T-t)\;}$$

**Step 2 — the optimal total spread.** The inner maximization
$\max_\delta \lambda(\delta)\big[1 - e^{-\gamma(\delta - \Delta\theta)}\big]$
with $\lambda = Ae^{-k\delta}$ gives an explicit optimum, and summing bid and ask:

$$\boxed{\;\delta^a + \delta^b = \gamma\sigma^2(T-t) + \frac{2}{\gamma}\ln\Big(1 + \frac{\gamma}{k}\Big)\;}$$

**Step 3 — the quotes.** Center the spread on the *reservation price*, not the mid:

$$P^a = r + \frac{\delta^a+\delta^b}{2},\qquad P^b = r - \frac{\delta^a+\delta^b}{2}$$

Expanding:

$$\boxed{\;P^{a,b} = s - q\gamma\sigma^2(T-t) \pm \frac12\Big[\gamma\sigma^2(T-t) + \frac2\gamma\ln\Big(1+\frac\gamma k\Big)\Big]\;}$$

### Reading the result

The spread has **two additive pieces with completely different origins:**

| Term | Origin | Behavior |
|---|---|---|
| $\gamma\sigma^2(T-t)$ | **inventory risk** | grows with vol and remaining time |
| $\frac2\gamma\ln(1+\gamma/k)$ | **market power / fill intensity** | constant; $\to 2/k$ as $\gamma\to0$ |

**Limiting cases that check the intuition:**

- $\gamma\to0$ (risk neutral): spread $\to 2/k$, and $r\to s$. A risk-neutral maker
  quotes symmetrically around mid at the monopolist's markup over the demand curve —
  a pure profit-maximization problem, no inventory management.
- $q>0$ (long): both quotes shift **down** by $q\gamma\sigma^2(T-t)$. The ask becomes
  more attractive (more likely to sell), the bid less attractive. **Inventory is
  mean-reverted by skewing, not by widening.**
- $t\to T$: the inventory term vanishes; quotes converge to the symmetric
  risk-neutral case. (In practice you replace $(T-t)$ with a constant horizon — see
  below.)
- $k$ large (fills very sensitive to depth ⟹ competitive): spread narrows toward
  $2/k \to 0$.

### The inventory process

Under the optimal policy, inventory is mean-reverting to zero. To leading order the
fill-rate asymmetry creates a restoring force, and

$$dq \approx -\underbrace{2Ak\gamma\sigma^2(T-t)}_{\text{mean reversion rate}}\,q\,dt + \text{jumps}$$

giving an approximately stationary inventory with

$$\sigma_q^2 \approx \frac{A}{k\gamma\sigma^2(T-t)}$$

**More risk aversion ⟹ tighter inventory control but fewer fills.** That trade-off
is the fundamental dial of a market-making business.

### The infinite-horizon fix

The $(T-t)$ term is an artifact of the finite-horizon formulation; a real market
maker runs indefinitely. Replace it with a **running inventory penalty** $\phi q^2$
in the objective:

$$\max\ \mathbb E\Big[X_T + q_TS_T - \phi\int_0^T q_t^2\,dt\Big]$$

The stationary solution replaces $\gamma\sigma^2(T-t)$ with a constant
$\sqrt{\phi\sigma^2/\ldots}$-type coefficient. Practically: **replace $(T-t)$ with a
fixed "risk horizon" parameter** $\tau_{\text{risk}}$ (typically seconds to minutes
for HFT) and tune it. This is what production systems do.

---

## 8.4 Guéant–Lehalle–Fernandez-Tapia closed form

AS is exact only asymptotically. GLFT solve the same problem with inventory limits
$|q|\le Q$ and give a **closed-form approximation** that is accurate and directly
implementable:

$$\boxed{\;\delta^{b\star}(q) = \frac{1}{\gamma}\ln\Big(1+\frac{\gamma}{k}\Big) + \Big(\frac{2q+1}{2}\Big)\sqrt{\frac{\sigma^2\gamma}{2kA}\Big(1+\frac{\gamma}{k}\Big)^{1+k/\gamma}}\;}$$

$$\boxed{\;\delta^{a\star}(q) = \frac{1}{\gamma}\ln\Big(1+\frac{\gamma}{k}\Big) - \Big(\frac{2q-1}{2}\Big)\sqrt{\frac{\sigma^2\gamma}{2kA}\Big(1+\frac{\gamma}{k}\Big)^{1+k/\gamma}}\;}$$

**Structure:** a constant base half-spread plus a term **linear in inventory**. The
inventory coefficient

$$\Xi = \sqrt{\frac{\sigma^2\gamma}{2kA}\Big(1+\frac\gamma k\Big)^{1+k/\gamma}}$$

is the **skew per unit of inventory** — the single most important tuning parameter
in a live market maker.

**Calibrating the four parameters from data:**

| Param | Meaning | How to estimate |
|---|---|---|
| $\sigma$ | mid volatility | realized vol on 1-s mid returns, deseasonalized (§03.8) |
| $A$ | fill intensity at zero depth | fills/sec when quoting at touch |
| $k$ | depth sensitivity | regress $\ln(\text{fill rate})$ on depth; slope $=-k$ |
| $\gamma$ | risk aversion | **tune** to hit a target inventory std |

**Estimating $k$ properly.** Bucket your quotes by distance from mid, count fills
per unit time in each bucket, and fit $\ln\lambda = \ln A - k\delta$. In liquid US
equities, $k$ is such that moving one tick further out roughly halves the fill rate.
This is the single measurement that most improves a naive market maker.

---

## 8.5 Adverse selection: the term AS leaves out

Avellaneda–Stoikov assumes fills are **uninformative** — a driftless mid and
inventory-independent price dynamics. Reality: you get filled precisely when you
shouldn't.

**The augmented P&L per fill:**

$$\mathbb E[\text{edge}] = \delta + \text{rebate} - \underbrace{\mathbb E[\,\Delta m \mid \text{filled}\,]}_{\text{adverse selection}} $$

Empirically, conditional on being lifted on your offer, the mid drifts **up**. Let
$\alpha_{\text{AS}}(\Delta) = \mathbb E[q(m_{t+\Delta}-m_t)\mid\text{fill}]$ be the markout
(§11.5). Then

$$\boxed{\;\text{Net edge} = \delta + r_m - \alpha_{\text{AS}}(\Delta)\;}$$

**Modelling it.** Let the fill arrival carry information $\lambda_{\text{info}}$:
after a buy fill, $dS$ gains drift $+\mu_{\text{AS}}$. Adding this to the HJB gives a
modified reservation price:

$$r = s - q\gamma\sigma^2\tau + \underbrace{\frac{\mu_{\text{AS}}}{\ldots}}_{\text{drift adjustment}}$$

and a **wider** base spread — the maker must be compensated for the information
content of the fill, exactly as in Glosten–Milgrom (§06.3). In the limit where all
counterparties are informed, the spread diverges and the maker withdraws.

**The practical implementation** — and this is the thing that separates working
market makers from textbook ones:

$$\text{Quote} = \underbrace{\text{fair value}}_{\text{microprice, not mid}} - \underbrace{q\cdot\Xi}_{\text{inventory skew}} \pm \underbrace{\frac{\delta_{\text{base}}}{}}_{\text{width}} + \underbrace{\beta'\,\mathbf{x}_t}_{\text{alpha signals}}$$

1. **Use the microprice (§06.8), not the mid, as fair value.** This alone removes
   a large fraction of adverse selection, because it already conditions on queue
   imbalance — the strongest predictor of the next tick.
2. **Add short-horizon signals** $\mathbf x_t$ (OFI, trade imbalance, futures lead,
   correlated-asset moves) to the fair value. Each one shifts both quotes together;
   it does not widen them.
3. **Widen or pull on toxicity.** When realized markouts deteriorate or VPIN spikes,
   increase $\delta_{\text{base}}$ or stop quoting. The optimal response to unmodelled
   adverse selection is not to skew — it's to leave.

**VPIN (volume-synchronized PIN)** — the standard toxicity monitor. Bucket by
equal *volume* (not time); within each bucket $\tau$ of size $V$:

$$\mathrm{VPIN} = \frac{1}{n}\sum_{\tau=1}^{n}\frac{\big|V_\tau^{\text{buy}} - V_\tau^{\text{sell}}\big|}{V}$$

High VPIN ⟹ one-sided flow ⟹ pull quotes. It spiked sharply before the 2010 Flash
Crash, which is what made it famous; treat it as a regime detector, not a forecast.

---

## 8.6 Multi-asset market making

Quoting $n$ correlated assets with inventory vector $q\in\mathbb R^n$ and covariance
$\Sigma$, the reservation price generalizes naturally:

$$\boxed{\;r_i = s_i - \gamma\,(\Sigma q)_i\,\tau\;}$$

**The skew on asset $i$ depends on your inventory in every correlated asset.** If
you are long the whole sector, you skew *all* quotes down — even in a name where
you are flat — because the marginal unit adds to an already-concentrated exposure.

This is enormously important in practice:
- An ETF market maker long the ETF should skew constituent quotes.
- A futures market maker long the front month should skew the back month.
- Hedging via a liquid proxy ($\beta$-hedge into ES or SPY) reduces $(\Sigma q)_i$
  and lets you quote tighter everywhere — **the hedge pays for itself in spread
  competitiveness, not just in risk**.

**Optimal hedge ratio** for hedging inventory $q$ in asset $i$ with instrument $h$:

$$\theta^\star = \frac{\mathrm{Cov}(r_i,r_h)}{\mathrm{Var}(r_h)}\cdot q_i = \beta_{ih}\,q_i$$

Hedge when $\gamma\,\Delta(\text{risk}) > \text{cost of the hedge}$, i.e. when

$$\gamma\sigma_i^2\rho^2 q_i^2\ \tau\ >\ \frac{S_h}{2}\,|\theta^\star| + \text{impact}$$

giving an inventory threshold $|q_i| > \frac{S_h}{2\gamma\sigma_i^2\rho^2\tau}\cdot\ldots$ —
a **no-hedge band** structurally identical to the no-trade band of §04.6.

---

## 8.7 Optimal quoting on a tick grid

The continuous $\delta^\star$ must be mapped to a discrete price grid, and the
mapping is not rounding.

**Setup.** Prices on a grid of tick size $\Delta$. Quoting one tick tighter gains
priority but loses $\Delta$ of edge and jumps you ahead of the queue.

**The decision.** Let $F(Q)$ = probability of fill given $Q$ shares ahead in the
queue, and let $Q_\ell$ = queue length at level $\ell$.

$$V_\ell = F(Q_\ell)\Big[\underbrace{\delta_\ell + r_m - \alpha_{\text{AS}}}_{\text{edge if filled}}\Big] - \big(1-F(Q_\ell)\big)\,C_{\text{miss}}$$

Choose $\ell$ maximizing $V_\ell$. Joining a level with a **long queue** is cheap in
edge but the fill probability is low *and* conditional on filling, the market has
usually moved against you (you only reach the front when the level is being
swept) — so long queues carry worse adverse selection, not better.

$$\frac{\partial}{\partial Q}\,\mathbb E[\text{markout}\mid\text{fill}] < 0$$

**Tick-constrained vs tick-unconstrained.**

- **Tick-constrained** (spread pinned at one tick — e.g. many large-cap US equities,
  ES futures): you cannot compete on price. All competition is on **queue position**,
  and therefore on latency. The AS/GLFT spread formulas are irrelevant; §11.2 is the
  relevant chapter.
- **Tick-unconstrained** (spread many ticks wide — small caps, crypto, options):
  quote at the AS/GLFT optimum. Latency matters much less; pricing accuracy matters
  much more.

**Diagnosing which regime you're in:** measure the fraction of time the spread is
exactly one tick. Above ~80% ⟹ tick-constrained.

---

## 8.8 Practical parameter table

Order-of-magnitude values for a liquid US equity (\$50 stock, 1-cent tick, 20% annual vol):

| Quantity | Symbol | Typical value |
|---|---|---|
| Mid vol (1-second) | $\sigma_{1s}$ | ~0.6 bp |
| Fill intensity at touch | $A$ | 0.1–2 /sec per side |
| Depth sensitivity | $k$ | ~1 per tick (fills halve per tick out) |
| Base half-spread (GLFT) | $\frac1\gamma\ln(1+\gamma/k)$ | ~0.5–1 tick |
| Inventory skew | $\Xi$ | 0.05–0.3 ticks per 100 shares |
| Target inventory std | $\sigma_q$ | 5–20% of typical fill size × $\sqrt{n}$ |
| Adverse selection (1-min markout) | $\alpha_{\text{AS}}$ | 0.3–0.6 of half-spread |
| Realized spread (§06.5) | | 0.2–0.5 of quoted |

**Sanity checks before going live:**

1. **Markout curve** (§11.5) at 100ms/1s/10s/1min/5min. If it's monotonically
   negative and still falling at 5 minutes, you're providing free options to
   informed flow.
2. **Inventory autocorrelation.** Should mean-revert with a half-life of minutes.
   A random walk in inventory means your skew is too weak.
3. **Fill rate vs. depth** should be exponential. If it isn't, your $k$ is
   mis-estimated and every quote is wrong.
4. **P&L attribution** against §8.1: spread capture, rebates, adverse selection,
   inventory. If inventory P&L has a large mean (positive or negative), you are
   running a directional book, not a market-making one.

---

**Next:** [09 — Statistical Arbitrage](09-statistical-arbitrage.md)
