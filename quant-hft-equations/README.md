# The Quant & HFT Equation Compendium

A derivation-first reference for the equations that actually earn money or stop you
from losing it. Every result is stated with its **assumptions**, a **derivation**
(or a proof sketch tight enough to reconstruct it), and a note on **where it breaks**.

The organizing principle: an equation is only "powerful" if it either (a) tells you
what to hold, (b) tells you what to pay, or (c) tells you how wrong you might be.
Everything here does one of those three.

---

## Contents

| # | Chapter | Core question answered |
|---|---------|------------------------|
| 01 | [Stochastic Calculus Foundations](01-stochastic-calculus.md) | How do prices move, and how do functions of prices move? |
| 02 | [Derivatives Pricing](02-derivatives-pricing.md) | What is a contingent claim worth, and how do I hedge it? |
| 03 | [Volatility Modelling & Estimation](03-volatility-models.md) | What is σ, right now and tomorrow? |
| 04 | [Portfolio Construction](04-portfolio-optimization.md) | Given forecasts, what do I hold? |
| 05 | [Risk Measures](05-risk-measures.md) | How much can I lose, and how sure am I? |
| 06 | [Market Microstructure](06-market-microstructure.md) | Where does the spread come from? |
| 07 | [Optimal Execution](07-optimal-execution.md) | How do I unload size without paying for it twice? |
| 08 | [Market Making & Inventory Control](08-market-making.md) | Where do I quote, and how much inventory do I tolerate? |
| 09 | [Statistical Arbitrage](09-statistical-arbitrage.md) | How do I trade mean reversion optimally? |
| 10 | [Alpha, Signals & Capacity](10-signals-alpha.md) | How good is a signal, and how much can it carry? |
| 11 | [HFT Mechanics](11-hft-mechanics.md) | Queues, latency, adverse selection, markouts. |
| 12 | [Estimation & Numerics](12-estimation-numerics.md) | Covariance cleaning, filtering, backtest honesty. |

---

## Notation

| Symbol | Meaning |
|---|---|
| $S_t$ | asset price at time $t$ |
| $W_t, W^{\mathbb Q}_t$ | Brownian motion under $\mathbb P$ (physical) / $\mathbb Q$ (risk-neutral) |
| $\mu, \sigma$ | drift, volatility (annualized unless stated) |
| $r$ | continuously-compounded risk-free rate |
| $q$ | inventory (signed, in shares/contracts) |
| $\gamma$ | risk aversion (CARA coefficient) |
| $\Sigma$ | covariance matrix; $\Omega$ = correlation matrix |
| $w$ | portfolio weight vector |
| $\lambda$ | Kyle's lambda (price impact per unit order flow) — context-dependent elsewhere |
| $\delta^a, \delta^b$ | ask/bid quote offsets from mid or reference price |
| $\phi(\cdot), \Phi(\cdot)$ | standard normal pdf / cdf |
| $m_t$ | efficient (mid) price |
| $\mathcal L$ | infinitesimal generator of a diffusion |

Time is in years unless a chapter says otherwise. $\mathbb E_t[\cdot] \equiv \mathbb E[\cdot \mid \mathcal F_t]$.

---

## The ten that matter most

If you only internalize ten, make it these.

1. **Itô's lemma** — every other continuous-time result is a corollary.
   $$df = \Big(f_t + \mu f_x + \tfrac12\sigma^2 f_{xx}\Big)dt + \sigma f_x\,dW$$
2. **Black–Scholes PDE** — the statement that hedging replaces forecasting.
   $$V_t + \tfrac12\sigma^2S^2V_{SS} + rSV_S - rV = 0$$
3. **Delta-hedged P&L** — why options are a bet on realized vs implied variance.
   $$d\Pi = \tfrac12 \Gamma S^2\big(\sigma_{\text{real}}^2 - \sigma_{\text{imp}}^2\big)dt$$
4. **Mean–variance / tangency portfolio** — the shape of every optimal book.
   $$w^\star \propto \Sigma^{-1}(\mu - r\mathbf 1)$$
5. **Kelly / Merton fraction** — the bridge from edge to size.
   $$f^\star = \frac{\mu - r}{\gamma\sigma^2}$$
6. **Kyle's lambda** — the price of information.
   $$\lambda = \frac{\sigma_v}{2\sigma_u}$$
7. **Almgren–Chriss trajectory** — the optimal way to be impatient.
   $$x(t) = X\,\frac{\sinh\kappa(T-t)}{\sinh\kappa T},\qquad \kappa=\sqrt{\lambda\sigma^2/\eta}$$
8. **Avellaneda–Stoikov quotes** — inventory-aware market making.
   $$r = s - q\gamma\sigma^2(T-t),\qquad \delta^a+\delta^b = \gamma\sigma^2(T-t) + \frac2\gamma\ln\!\Big(1+\frac\gamma k\Big)$$
9. **Square-root impact law** — the capacity constraint on every strategy.
   $$\frac{\Delta P}{\sigma} \approx Y\sqrt{\frac{Q}{V}}$$
10. **Fundamental law of active management** — why breadth beats brilliance.
    $$\mathrm{IR} \approx \mathrm{TC}\cdot\mathrm{IC}\cdot\sqrt{\mathrm{BR}}$$

---

## How to read a chapter

Each result is laid out as:

> **Name** — one-line statement of what it gives you.
> **Assumptions.** The list that, when violated, is why your live P&L differs from the backtest.
> **Derivation.** Enough steps to re-derive on a whiteboard.
> **In practice.** Calibration, typical magnitudes, failure modes.

Nothing here is a trading recommendation; these are the mathematical objects, not
an edge. The edge is in the data, the latency, and the discipline.
