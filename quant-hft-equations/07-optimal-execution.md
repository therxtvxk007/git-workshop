# 07 — Optimal Execution

You have $X$ shares to trade by time $T$. Trade fast and pay impact; trade slow and
bear price risk. This chapter is the mathematics of that trade-off.

---

## 7.1 Implementation shortfall — the objective

Perold's decomposition. Everything is measured against the **decision price** $P_0$
(the price when you decided to trade, not when you started):

$$\mathrm{IS} = \underbrace{\sum_j n_j p_j - X P_0}_{\text{execution cost}} + \underbrace{(X - \textstyle\sum_j n_j)(P_T - P_0)}_{\text{opportunity cost}}$$

$$= \underbrace{\text{spread cost}}_{\text{half-spread}\times X} + \underbrace{\text{impact}}_{\text{your own footprint}} + \underbrace{\text{timing risk}}_{\text{mean-zero, variance}} + \underbrace{\text{delay cost}}_{\text{drift while waiting}} + \underbrace{\text{fees}}_{}$$

**The key asymmetry:** impact is a *deterministic cost* that increases with speed;
timing risk is a *variance* that increases with duration. You are minimizing

$$\boxed{\;\min_{\text{schedule}}\ \ \mathbb E[\mathrm{IS}] + \lambda\,\mathrm{Var}[\mathrm{IS}]\;}$$

$\lambda$ is urgency/risk aversion, and every result below is parameterized by it.

---

## 7.2 The Almgren–Chriss framework

**Setup.** Liquidate $X$ shares over $[0,T]$, discretized into $N$ intervals of length
$\tau = T/N$. Let $x_k$ = shares **remaining** after interval $k$ ($x_0=X$, $x_N=0$),
$n_k = x_{k-1}-x_k$ = shares traded in interval $k$, $v_k = n_k/\tau$ = trade rate.

**Price dynamics with permanent impact $g(v)$:**

$$S_k = S_{k-1} + \sigma\sqrt\tau\,\xi_k - \tau\,g(v_k),\qquad \xi_k\sim\mathcal N(0,1)$$

**Execution price with temporary impact $h(v)$:**

$$\tilde S_k = S_{k-1} - h(v_k)$$

Temporary impact affects only *your* fill; permanent impact moves the market for
everyone (including your remaining shares).

**Linear impact functions:**

$$g(v) = \gamma v,\qquad h(v) = \epsilon\,\mathrm{sgn}(v) + \eta v$$

$\epsilon$ = half-spread (fixed per-share cost), $\eta$ = temporary impact slope,
$\gamma$ = permanent impact slope. Note $\gamma$ is Kyle's $\lambda$.

**Expected cost.**

$$\mathbb E[\mathrm{IS}] = \sum_k \tau\,x_k\,g(v_k) + \sum_k n_k\,h(v_k)
= \underbrace{\frac{\gamma X^2}{2}}_{\text{permanent, schedule-independent}} + \epsilon\sum_k|n_k| + \Big(\eta - \frac{\gamma\tau}{2}\Big)\frac1\tau\sum_k n_k^2$$

**Critical observation:** the permanent-impact term is $\tfrac12\gamma X^2$ **regardless
of the schedule** (telescoping sum). *You cannot avoid permanent impact by trading
cleverly — only by trading less.* Only the temporary term $\eta$ is controllable.
This is the single most important structural fact in execution.

**Variance.**

$$\mathrm{Var}[\mathrm{IS}] = \sigma^2\sum_{k=1}^N \tau\,x_k^2$$

Risk is the *time-integral of remaining inventory*. Every share still held is
exposed to $\sigma$.

---

## 7.3 Deriving the optimal trajectory

Minimize $U = \mathbb E[\mathrm{IS}] + \lambda\mathrm{Var}[\mathrm{IS}]$. Dropping constants and
ignoring the fixed spread term:

$$U(x) = \tilde\eta\sum_k \frac{(x_{k-1}-x_k)^2}{\tau} + \lambda\sigma^2\sum_k \tau x_k^2,\qquad \tilde\eta = \eta - \frac{\gamma\tau}{2}$$

**Discrete derivation.** $\partial U/\partial x_k = 0$ gives, for $k=1,\ldots,N-1$:

$$\frac{2\tilde\eta}{\tau}\big(-(x_{k-1}-x_k) + (x_k-x_{k+1})\big) + 2\lambda\sigma^2\tau x_k = 0$$

$$\Longrightarrow\quad \frac{x_{k+1} - 2x_k + x_{k-1}}{\tau^2} = \frac{\lambda\sigma^2}{\tilde\eta}\,x_k = \kappa^2 x_k$$

A discrete second-order linear difference equation — the **discrete diffusion
equation with a linear source**.

**Continuous limit.** As $\tau\to0$ this is the Euler–Lagrange equation

$$\boxed{\;\ddot x(t) = \kappa^2 x(t),\qquad \kappa = \sqrt{\frac{\lambda\sigma^2}{\eta}}\;}$$

with boundary conditions $x(0)=X$, $x(T)=0$. The solution is a hyperbolic sine:

$$\boxed{\;x(t) = X\,\frac{\sinh\big(\kappa(T-t)\big)}{\sinh(\kappa T)}\;}$$

and the trade rate is

$$v(t) = -\dot x(t) = X\kappa\,\frac{\cosh\big(\kappa(T-t)\big)}{\sinh(\kappa T)}$$

**Interpretation of $\kappa$ — the urgency parameter.** $1/\kappa$ is the
characteristic time over which the position is worked:

$$\frac1\kappa = \sqrt{\frac{\eta}{\lambda\sigma^2}}$$

- **High $\sigma$ or high $\lambda$** (risk-averse, volatile) ⟹ large $\kappa$ ⟹ front-load.
- **High $\eta$** (illiquid, expensive impact) ⟹ small $\kappa$ ⟹ spread it out.
- $\kappa\to0$: $x(t)\to X(1-t/T)$ — **TWAP** is the risk-neutral solution.
- $\kappa T\gg1$: $x(t)\approx Xe^{-\kappa t}$ — **exponential decay**, and the effective
  horizon $1/\kappa$ is shorter than $T$; the deadline stops binding.

**The efficient frontier of execution.** Evaluating $U$ at the optimum:

$$\mathbb E[\mathrm{IS}]^\star = \frac12\gamma X^2 + \epsilon X + \eta X^2\kappa\,\frac{\coth(\kappa T) \cdot \ldots}{\ldots}$$

Rather than the full expression, the useful scaling in the $\kappa T \gg 1$ regime:

$$\mathbb E[\text{cost}] \approx \eta X^2\kappa = X^2\sqrt{\lambda\eta\sigma^2},\qquad
\mathrm{Var} \approx \frac{\sigma^2X^2}{2\kappa}$$

so along the frontier $\mathbb E[\text{cost}]\cdot\sqrt{\mathrm{Var}} \approx$ const:
**halving execution risk costs $\sqrt2$× more in impact.** That trade-off, not the
formula, is what you present to a portfolio manager.

---

## 7.4 Nonlinear impact and the square-root cost model

Almgren–Chriss assumes linear impact; reality is concave (§06.7). With
$h(v) = \eta\,v^{\,\alpha}$ ($\alpha\approx1/2$ empirically), the Euler–Lagrange
equation becomes

$$\eta\alpha\frac{d}{dt}\big(v^{\alpha-1}\dot x\big)\ \ldots \quad\Longrightarrow\quad
\alpha(2\alpha-1)\ldots$$

The practical result: **optimal trajectories under concave impact are flatter than
under linear impact** — concavity rewards patience less than linear impact rewards
it, but the risk term still drives front-loading. In the risk-neutral limit
($\lambda=0$) with $\alpha<1$, cost is minimized by trading at a **constant rate**
regardless of $\alpha$, so TWAP remains the base case.

**The cost model actually used on desks** (Almgren et al. 2005, calibrated on
Citigroup data):

$$\boxed{\;\text{Cost (bp)} = \underbrace{\frac{\text{spread}}{2}}_{} + \underbrace{a\,\sigma\Big(\frac{Q}{V}\Big)^{0.6}}_{\text{temporary}} + \underbrace{b\,\sigma\Big(\frac{Q}{V}\Big)^{}\frac{\ldots}{}}_{\text{permanent}}$$

Their fitted specification, in the form usually implemented:

$$\mathbb E[\text{IS}] = \frac12\gamma\,\sigma\,\frac{X}{V}\ + \ \eta\,\sigma\,\Big(\frac{X}{V\,T}\Big)^{3/5}$$

with $\gamma\approx0.31$, $\eta\approx0.142$ when $T$ is in days and $V$ in daily
volume. **Sanity check:** 10% of ADV over one day, $\sigma=2\%$ daily
⟹ permanent $\approx 0.5\times0.31\times2\%\times0.1 = 3.1$ bp; temporary
$\approx 0.142\times2\%\times0.1^{0.6} = 7.1$ bp; plus half-spread. Total ~15 bp.

**The universal capacity check.** Before anything else, compute

$$\text{Cost}_{\text{bp}} \approx Y\,\sigma_{\text{daily,bp}}\sqrt{\frac{Q}{\mathrm{ADV}}}$$

and compare to your signal's expected return. If cost > 30% of alpha, the strategy
does not exist at that size.

---

## 7.5 Benchmark algorithms

**TWAP** — trade $X/N$ per interval. Optimal when $\lambda=0$ (risk-neutral) and
volume is uniform. Minimizes tracking error to the time-weighted average price;
highly predictable, therefore gameable.

**VWAP** — track the volume curve $u(t)$ (fraction of daily volume by time $t$):

$$x(t) = X\big(1 - u(t)\big),\qquad v(t) = X\,u'(t)$$

Minimizes variance *against the VWAP benchmark*, not against arrival price. Note
this is a different objective from implementation shortfall and produces materially
different schedules. The intraday volume U-shape means VWAP front- and back-loads.

**Volume prediction** — the input that actually determines VWAP quality:

$$\ln V_{t,i} = \underbrace{s_i}_{\text{intraday seasonal}} + \underbrace{d_t}_{\text{daily level}} + \varepsilon_{t,i}$$

Estimate $s_i$ by cross-day averaging, $d_t$ by an AR model on daily log-volume
(highly persistent, $\rho_1\approx0.7$). Typical out-of-sample $R^2$ on bucket
volume: 0.4–0.6.

**POV (percentage of volume)** — trade at rate $v(t) = \theta\cdot V(t)$. Adaptive to
realized liquidity, but the **completion time is stochastic**, which means the risk
term is unbounded. Use with a hard deadline override.

**Implementation shortfall algos** — the Almgren–Chriss trajectory with $\lambda$
mapped to a user "urgency" setting.

| Benchmark | Minimizes | Use when |
|---|---|---|
| Arrival price / IS | $\mathbb E[\mathrm{IS}]+\lambda\mathrm{Var}$ | You have alpha; time matters |
| VWAP | Variance vs VWAP | Benchmark-driven, no alpha |
| TWAP | Variance vs TWAP | Small orders, no volume forecast |
| POV | Footprint | Very large orders, flexible deadline |
| Close | Variance vs closing auction | Index/benchmark tracking |

---

## 7.6 Execution with alpha

If you expect drift $\mu$ over the horizon, the objective gains a term:

$$\min\ \mathbb E[\mathrm{IS}] + \lambda\mathrm{Var} - \int_0^T \mu(t)\,x(t)\,dt$$

The Euler–Lagrange equation picks up a forcing term:

$$\eta\,\ddot x = \lambda\sigma^2 x - \frac{\mu}{2}$$

**Constant alpha $\mu$.** The solution is the homogeneous AC trajectory plus a
particular solution $x_p = \mu/(2\lambda\sigma^2)$:

$$x(t) = \frac{\mu}{2\lambda\sigma^2} + A\,e^{\kappa t} + B\,e^{-\kappa t}$$

with $A,B$ fixed by $x(0)=X$, $x(T)=0$. **Buying into positive alpha slows you
down** (you'd rather hold), **selling into positive alpha speeds you up**. The
shift $\mu/(2\lambda\sigma^2)$ is exactly the Merton/Kelly position (§04.4) —
execution converges to portfolio choice.

**Decaying alpha** $\mu(t)=\mu_0e^{-\rho t}$ — the realistic case. The particular
solution is

$$x_p(t) = \frac{\mu_0 e^{-\rho t}}{2(\lambda\sigma^2 - \eta\rho^2)}$$

**Fast-decaying alpha ($\rho\gg\kappa$) forces aggressive front-loading**: you must
capture the signal before it evaporates, and the impact cost is worth paying. This
is the formal statement of "fast signals need aggressive execution," and it is why
HFT strategies cross the spread while a value fund never does.

**The break-even.** Trading aggressively is worth it iff

$$\frac{\text{alpha captured by speed}}{\text{extra impact paid}} > 1
\quad\Longleftrightarrow\quad \mu_0\Big(1-\frac{\rho}{\kappa}\Big)^{-1}\ \gtrsim\ \eta\,\kappa\,X$$

---

## 7.7 The Obizhaeva–Wang limit order book model

Almgren–Chriss treats impact as instantaneous and memoryless. Obizhaeva–Wang models
the **book's resilience** explicitly.

**Setup.** The book has density $q$ (shares per price unit). Trading $n$ shares moves
the price by $n/q$. The book **replenishes** exponentially at rate $\rho$:

$$dD_t = -\rho D_t\,dt + \frac{1}{q}\,dX_t$$

where $D_t$ is the current deviation from the "fundamental" price.

**Optimal strategy — a distinctive three-part shape:**

$$\boxed{\;\text{discrete block at } t=0 \;+\; \text{constant rate on } (0,T) \;+\; \text{discrete block at } t=T\;}$$

with

$$X_0 = X_T = \frac{X}{2+\rho T},\qquad \dot x = \frac{\rho X}{2+\rho T}\ \text{ on } (0,T)$$

**Derivation intuition.** The initial block consumes the standing book (paying
$n^2/2q$ once); the constant-rate middle exactly matches the replenishment rate
$\rho$ — trading faster would deplete the book, slower would waste available
liquidity; the final block clears the remainder with no time left to suffer from
the resulting impact.

**Why it matters.** Real algorithms *do* place opening and closing blocks. The
continuous AC trajectory is an artifact of assuming instantaneous resilience
($\rho\to\infty$). The two models agree in the limit and differ exactly where
the book's finite depth and refill speed matter — i.e., in every real large order.

**Calibrating $\rho$:** measure the half-life of book replenishment after a large
trade. Liquid US equities: 1–10 seconds. This is directly observable and is one of
the most useful stats a venue can give you.

---

## 7.8 Optimal liquidation with limit orders

Almgren–Chriss assumes market orders. Real algorithms mix passive and aggressive.

**Setup (Cartea–Jaimungal).** Post limit orders at depth $\delta$; fills arrive as a
Poisson process with intensity decreasing in depth:

$$\Lambda(\delta) = \Lambda_0 e^{-\kappa_f\delta}$$

Also allow market orders at rate $\nu$ with temporary impact.

**HJB.** With value function $H(t,x,q,S)$ for inventory $q$ and cash $x$:

$$\partial_tH + \tfrac12\sigma^2\partial_{SS}H + \max_\delta\ \Lambda(\delta)\big[H(t,x+(S+\delta),q-1,S) - H\big] + \max_\nu\{\ldots\} - \phi q^2 = 0$$

with $\phi$ the running inventory penalty. The ansatz $H = x + qS + h(t,q)$ reduces
this to a system of ODEs in $q$, solvable in closed form for the linear-inventory-penalty
case:

$$\boxed{\;\delta^\star(t,q) = \frac{1}{\kappa_f} + h(t,q) - h(t,q-1)\;}$$

**The structure to remember:** optimal passive depth = a constant term $1/\kappa_f$
(the monopolist's markup over the fill-intensity curve) **plus** the marginal value
of reducing inventory by one. The second term is what makes the strategy
inventory-aware — post tighter when you're long and want out.

**Market order trigger.** Cross the spread when the inventory penalty exceeds the
spread cost:

$$h(t,q) - h(t,q-1) > \frac{S}{2} + \text{impact}$$

i.e. **only when you're running out of time or carrying too much risk.** In steady
state a well-tuned liquidation algorithm executes 70–90% passively.

---

## 7.9 Multi-asset execution

Liquidating a portfolio $X\in\mathbb R^n$ with covariance $\Sigma$ and impact matrix $H$:

$$\min_{x(\cdot)}\ \int_0^T\Big[\dot x' H\dot x + \lambda\,x'\Sigma x\Big]dt$$

**Euler–Lagrange:** $H\ddot x = \lambda\Sigma x$, giving the matrix analogue

$$\ddot x = H^{-1}\Sigma\,\lambda\,x$$

**Diagonalize.** Let $H^{-1/2}\Sigma H^{-1/2} = U\Lambda U'$. In the transformed
coordinates $y = U'H^{1/2}x$, the system **decouples** into $n$ independent
Almgren–Chriss problems with

$$\kappa_i = \sqrt{\lambda\Lambda_{ii}}$$

$$\boxed{\;y_i(t) = y_i(0)\frac{\sinh(\kappa_i(T-t))}{\sinh(\kappa_iT)}\;}$$

**The trading insight this delivers:** high-variance directions (large $\Lambda_{ii}$ —
i.e. **factor exposures**) are liquidated fast; low-variance directions
(**hedged/idiosyncratic** combinations) are liquidated slowly.

Concretely: liquidating a market-neutral book, you should **maintain the hedge
throughout** and unwind the residual patiently — never sell the longs first and the
shorts second. That naive sequencing creates a temporary factor exposure whose risk
often exceeds the entire impact cost you were trying to save.

**Cross-impact.** $H$ is not diagonal: trading A moves B. Empirically the
cross-impact matrix is approximately $H \approx c\,\Sigma^{1/2}$ or, in factor form,
$H \propto B\Omega_fB' + D$ — impact propagates along factor structure. Ignoring
cross-impact systematically understates the cost of liquidating a concentrated
sector book.

---

## 7.10 Practical checklist

| Question | Equation |
|---|---|
| Can I trade this at all? | $\text{cost} \approx Y\sigma\sqrt{Q/V}$ vs alpha |
| How fast? | $1/\kappa = \sqrt{\eta/(\lambda\sigma^2)}$ |
| What shape? | $x(t)=X\sinh(\kappa(T-t))/\sinh(\kappa T)$ |
| Passive or aggressive? | alpha decay $\rho$ vs $\kappa$ |
| Which benchmark? | IS if you have alpha, VWAP if you don't |
| Portfolio order? | decouple via $H^{-1/2}\Sigma H^{-1/2}$; hedge stays on |
| Did it work? | markout-adjusted IS vs a pre-trade cost model |

**Post-trade evaluation.** Always decompose realized IS against the *pre-trade
estimate*, not against zero:

$$\text{Slippage} = \mathrm{IS}_{\text{realized}} - \mathrm{IS}_{\text{predicted}}$$

Regress that residual on order characteristics (size/ADV, vol, spread, urgency,
time of day). Persistent positive residuals mean your algo is being detected —
check for schedule predictability and venue leakage before blaming the market.

---

**Next:** [08 — Market Making & Inventory Control](08-market-making.md)
