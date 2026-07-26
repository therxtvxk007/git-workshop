# 04 — Portfolio Construction

Given forecasts, what do you hold? Every answer in this chapter has the same shape:
**inverse covariance times expected return, scaled by risk appetite, shrunk toward
something robust.**

---

## 4.1 Mean–variance optimization

**Problem.** Minimize risk for target return:

$$\min_w \tfrac12 w'\Sigma w \quad\text{s.t.}\quad w'\mu = \mu_p,\ \ w'\mathbf 1 = 1$$

**Derivation.** Lagrangian $L = \tfrac12w'\Sigma w - \lambda(w'\mu-\mu_p) - \gamma(w'\mathbf1-1)$.
First-order condition $\Sigma w = \lambda\mu + \gamma\mathbf1$, so

$$w^\star = \Sigma^{-1}(\lambda\mu + \gamma\mathbf 1)$$

Define the scalars $A = \mathbf1'\Sigma^{-1}\mu$, $B = \mu'\Sigma^{-1}\mu$, $C=\mathbf1'\Sigma^{-1}\mathbf1$,
$D = BC - A^2$. Imposing the constraints:

$$\lambda = \frac{C\mu_p - A}{D},\qquad \gamma = \frac{B - A\mu_p}{D}$$

**The efficient frontier** is a parabola in mean–variance space:

$$\boxed{\;\sigma_p^2 = \frac{C\mu_p^2 - 2A\mu_p + B}{D}\;}$$

vertex at the **global minimum variance portfolio**:

$$w_{\mathrm{GMV}} = \frac{\Sigma^{-1}\mathbf 1}{\mathbf 1'\Sigma^{-1}\mathbf 1},\qquad \sigma^2_{\mathrm{GMV}} = \frac1C$$

Note $w_{\mathrm{GMV}}$ needs **no return forecast at all** — which is why it survives
estimation error better than anything else on the frontier.

### The tangency portfolio

With a risk-free asset, maximize the Sharpe ratio $\dfrac{w'(\mu-r\mathbf1)}{\sqrt{w'\Sigma w}}$.
Since the objective is scale-invariant, the FOC gives

$$\boxed{\;w_{\text{tan}} = \frac{\Sigma^{-1}(\mu - r\mathbf1)}{\mathbf 1'\Sigma^{-1}(\mu-r\mathbf1)}\;}$$

and the **maximum attainable Sharpe ratio** satisfies

$$\boxed{\;\mathrm{SR}^2_{\max} = (\mu-r\mathbf1)'\Sigma^{-1}(\mu-r\mathbf1)\;}$$

This is a Mahalanobis distance. It says: **Sharpe ratios add in quadrature after
orthogonalization.** Two uncorrelated 1.0-Sharpe strategies combine to $\sqrt2\approx1.41$,
not 2.0.

**Two-fund separation.** Every mean–variance investor holds only the risk-free asset
and $w_{\text{tan}}$; risk aversion determines only the mix. In practice this fails
because different investors face different constraints — which is precisely where
the leverage-constrained-investor explanation of the low-beta anomaly comes from.

### Unconstrained solution with risk aversion

$$\max_w\ w'(\mu - r\mathbf 1) - \frac{\gamma}{2}w'\Sigma w \quad\Longrightarrow\quad \boxed{\;w^\star = \frac{1}{\gamma}\Sigma^{-1}(\mu-r\mathbf1)\;}$$

The cleanest statement in portfolio theory. **Everything else in this chapter is a
regularization of this formula.**

---

## 4.2 Why naive MVO fails — and what to do

MVO is an **error-maximizer**. It systematically allocates most to the assets whose
returns are most overestimated and whose correlations are most underestimated.

**The core problem.** With $N$ assets and $T$ observations, $\hat\Sigma$ has $N(N+1)/2$
parameters estimated from $NT$ numbers. When $N/T$ is not small, $\hat\Sigma^{-1}$ is
wildly unstable. The smallest eigenvalues of $\hat\Sigma$ are biased **downward**, and
$\Sigma^{-1}$ amplifies exactly those directions.

**Michaud's bound.** The expected out-of-sample Sharpe of the plug-in optimal
portfolio degrades roughly as

$$\mathbb E[\mathrm{SR}_{\text{oos}}] \approx \mathrm{SR}_{\max}\sqrt{\frac{T}{T+N}}$$

At $N=100$, $T=250$: you keep about 84% of the theoretical Sharpe *at best*, and
that assumes stationarity.

**The fixes, in order of value per unit of effort:**

| Fix | Equation | Effect |
|---|---|---|
| Shrink returns | $\tilde\mu = \delta\hat\mu + (1-\delta)\bar\mu\mathbf1$ | Biggest single win. Return errors hurt ~10× more than covariance errors |
| Shrink covariance | Ledoit–Wolf (§12.2) | $\hat\Sigma_{LW} = \alpha F + (1-\alpha)\hat\Sigma$ |
| Constrain | $w\ge0$, $\|w\|_1\le L$ | Long-only constraint is mathematically equivalent to a form of shrinkage |
| Factor-model $\Sigma$ | $\Sigma = B\Omega B' + D$ | Reduces parameters from $N^2/2$ to $NK$ |
| Resample | Average $w^\star$ over bootstrapped inputs | Michaud resampling; smooths the frontier |
| Robust optimization | $\max_w\min_{\mu\in\mathcal U} \ldots$ | Explicit uncertainty set |

**Rule of thumb:** if you cannot state your $t$-stat on $\mu$, use $w_{\mathrm{GMV}}$ or
risk parity instead. An unconditional risk-based portfolio beats a badly estimated
mean–variance one almost always.

---

## 4.3 Black–Litterman

Solves the "MVO gives insane weights" problem by starting from equilibrium and
tilting only where you have a view.

**Step 1 — reverse-optimize the market portfolio** to get implied equilibrium returns:

$$\boxed{\;\Pi = \gamma\,\Sigma\,w_{\text{mkt}}\;}$$

(Invert $w^\star = \frac1\gamma\Sigma^{-1}\Pi$. The market is treated as *someone's*
optimal portfolio.) Calibrate $\gamma = \mathrm{SR}_{\text{mkt}}/\sigma_{\text{mkt}}$, typically 2.5–3.

**Step 2 — express views** as $P\mu = Q + \varepsilon$, $\varepsilon\sim\mathcal N(0,\Omega)$.
$P$ is $K\times N$ (picking matrix), $Q$ is $K\times1$ (view magnitudes), $\Omega$
is your confidence (diagonal, larger = less confident).

A row of $P$ like $(0,\ldots,1,\ldots,-1,\ldots,0)$ with $Q_k = 0.02$ says
"asset $i$ outperforms asset $j$ by 2%."

**Step 3 — Bayesian update** (prior $\mu\sim\mathcal N(\Pi,\tau\Sigma)$, likelihood from views):

$$\boxed{\;\mathbb E[\mu] = \Big[(\tau\Sigma)^{-1} + P'\Omega^{-1}P\Big]^{-1}\Big[(\tau\Sigma)^{-1}\Pi + P'\Omega^{-1}Q\Big]\;}$$

$$\mathrm{Cov}[\mu] = \Big[(\tau\Sigma)^{-1}+P'\Omega^{-1}P\Big]^{-1}$$

Equivalent (numerically better, avoids inverting $N\times N$ twice):

$$\mathbb E[\mu] = \Pi + \tau\Sigma P'\big(P\tau\Sigma P' + \Omega\big)^{-1}\big(Q - P\Pi\big)$$

**Step 4** — feed $\mathbb E[\mu]$ into MVO. Weights now deviate from market cap only
along the directions you expressed views on, in proportion to your confidence.

**Setting $\Omega$.** The standard practical choice ties view uncertainty to the
prior: $\Omega = \mathrm{diag}(P(\tau\Sigma)P')$. This makes each view "as confident as
the prior," a neutral default. $\tau\in[0.01,0.05]$.

**Why it works:** it makes "no view" produce "market weights" instead of garbage.
The failure mode of MVO — extreme positions in assets you have no opinion about —
is eliminated by construction.

---

## 4.4 The Kelly criterion

**Discrete case.** Bet fraction $f$ of wealth, win $b$ with prob $p$, lose stake with
prob $q=1-p$. Maximize $\mathbb E[\ln W]$:

$$g(f) = p\ln(1+bf) + q\ln(1-f)$$
$$g'(f) = \frac{pb}{1+bf} - \frac{q}{1-f} = 0 \ \Longrightarrow\ \boxed{\;f^\star = \frac{pb-q}{b} = \frac{\text{edge}}{\text{odds}}\;}$$

**Continuous case.** Wealth follows $dW/W = f\,dS/S + (1-f)r\,dt$ with $dS/S = \mu dt+\sigma dW$.
By Itô (§01.3), the log-growth rate is

$$g(f) = r + f(\mu - r) - \frac{f^2\sigma^2}{2}$$

$$g'(f) = (\mu-r) - f\sigma^2 = 0\ \Longrightarrow\ \boxed{\;f^\star = \frac{\mu-r}{\sigma^2} = \frac{\mathrm{SR}}{\sigma}\;}$$

with maximized growth rate

$$\boxed{\;g^\star = r + \frac{(\mu-r)^2}{2\sigma^2} = r + \frac{\mathrm{SR}^2}{2}\;}$$

**This is the deepest identity in position sizing:** at full Kelly, your excess
compound growth rate is *exactly half your squared Sharpe ratio.* A Sharpe-1.0
strategy compounds at 50%/yr — if you can survive the leverage it demands.

**Multivariate Kelly:** $f^\star = \Sigma^{-1}(\mu - r\mathbf1)$ — identical to MVO at
$\gamma=1$. Log utility *is* unit relative risk aversion.

### Why nobody runs full Kelly

At $f^\star$, the volatility of your equity curve is $\sigma_W = \mathrm{SR}$ — a Sharpe-2
strategy at full Kelly runs 200% annualized vol. Worse:

$$\mathbb P\big(\text{drawdown} \ge 1-x \text{ ever}\big) = x^{\,2/\!\left(\text{Kelly fraction}\right)-1}\ \Big|_{\text{full Kelly}} = x$$

**At full Kelly the probability of ever halving your capital is 50%.** At fractional
Kelly $f = c\,f^\star$:

$$\mathbb P(\text{drawdown to fraction } x) = x^{2/c - 1}$$

At half-Kelly ($c=0.5$): $\mathbb P(\text{50\% DD}) = 0.5^3 = 12.5\%$, while you retain
$g/g^\star = c(2-c) = 75\%$ of the growth rate.

$$\boxed{\;\frac{g(cf^\star)}{g(f^\star)} = c(2-c)\;}$$

**The asymmetry that decides it:** growth loss is *quadratic* in the shortfall from
$f^\star$, but overbetting is catastrophic — $g<0$ for $f>2f^\star$. And since $f^\star$
is estimated with error, half-Kelly is not conservatism, it's the correct response
to parameter uncertainty. **Most professionals run $c\in[0.25,0.5]$.**

---

## 4.5 Risk parity

Equalize **risk contributions** rather than capital.

Marginal contribution to risk: $\mathrm{MCR}_i = \dfrac{\partial\sigma_p}{\partial w_i} = \dfrac{(\Sigma w)_i}{\sigma_p}$.

Total contribution: $\mathrm{RC}_i = w_i\mathrm{MCR}_i$, and by Euler's theorem
(σ is homogeneous of degree 1) these sum exactly:

$$\sum_i \mathrm{RC}_i = \frac{w'\Sigma w}{\sigma_p} = \sigma_p$$

**Equal risk contribution portfolio:**

$$\boxed{\;w_i\,(\Sigma w)_i = w_j\,(\Sigma w)_j\quad\forall i,j\;}$$

**Special cases:**
- Uncorrelated assets: $w_i \propto 1/\sigma_i$ — **inverse-volatility weighting**.
- Equal correlation $\rho$ and equal vols: equal weights.

**Solve** via the convex reformulation (Spinu):

$$\min_w \ \tfrac12 w'\Sigma w - \frac1N\sum_i\ln w_i,\qquad w>0$$

then normalize. The log barrier's FOC is $(\Sigma w)_i = \frac{1}{Nw_i}$, i.e.
$w_i(\Sigma w)_i = 1/N$ — exactly ERC. Convex, so a single Newton solve.

**Why it's popular:** requires no return forecasts, and is far more stable than MVO.
**Why it's criticized:** it implicitly assumes all assets have equal Sharpe ratios,
and it structurally overweights bonds — requiring leverage to hit return targets,
which reintroduces exactly the tail risk it was meant to avoid.

---

## 4.6 Trading toward a target with transaction costs

The optimal portfolio isn't where you go — it's how fast you go there.

**Gârleanu–Pedersen.** Maximize

$$\mathbb E\sum_t\Big[(1-\rho)^t\Big(x_t'\mu_t - \frac{\gamma}{2}x_t'\Sigma x_t - \frac{\lambda}{2}\Delta x_t'\Lambda\,\Delta x_t\Big)\Big]$$

with quadratic trading cost matrix $\Lambda$ (usually $\Lambda\propto\Sigma$).

**Result:** trade a *constant fraction* of the way toward an **aim portfolio**:

$$\boxed{\;x_t = \Big(1 - \frac{a}{\lambda}\Big)x_{t-1} + \frac{a}{\lambda}\,\mathrm{aim}_t\;}$$

and the aim is not the Markowitz portfolio but a **forecast-horizon-weighted average
of current and future Markowitz portfolios**:

$$\mathrm{aim}_t = \sum_{\tau\ge0}z_\tau\,\mathbb E_t\big[\text{Markowitz}_{t+\tau}\big],\qquad \sum z_\tau=1$$

**Two conclusions that change how you build a book:**

1. **Never fully rebalance.** Partial adjustment is optimal; the rate depends on
   costs relative to risk, not on how confident you are today.
2. **Weight fast signals less.** A signal that decays in a day contributes little to
   the aim portfolio because you can't get there before it's gone. Slow signals
   deserve *more* weight per unit of IC than their raw IC suggests.

**Closed-form trading rate (continuous, single asset):**

$$\frac{a}{\lambda} = \frac{\sqrt{\gamma\lambda\sigma^2 + \tfrac14\lambda^2\rho^2}\; -\; \tfrac12\lambda\rho}{\lambda}\ \approx\ \sqrt{\frac{\gamma\sigma^2}{\lambda}}\ \text{ for small }\rho$$

More risk aversion or more vol ⟹ trade faster. More cost ⟹ trade slower. Square root,
so it's forgiving: getting $\lambda$ wrong by 4× changes the rate by 2×.

**No-trade band (proportional costs).** With costs $\propto|\Delta x|$ rather than
quadratic, the solution is a **band**: do nothing inside, trade to the edge outside.
Width $\approx \left(\frac{3\,c\,\sigma^2}{2\gamma}\right)^{1/3}$ — the classic
**cube-root rule** (Constantinides). Cubic scaling means costs must rise 8× to
double the band.

---

## 4.7 Factor models

$$r_i = \alpha_i + \sum_{k=1}^K \beta_{ik}f_k + \epsilon_i \quad\Longrightarrow\quad \boxed{\;\Sigma = B\Omega_f B' + D\;}$$

with $B$ the $N\times K$ loading matrix, $\Omega_f$ the $K\times K$ factor covariance,
$D=\mathrm{diag}(\sigma^2_{\epsilon_i})$ idiosyncratic.

**Parameter count:** $NK + K^2/2 + N$ instead of $N^2/2$. At $N=3000$, $K=50$:
~155k vs 4.5M. This alone makes large-scale optimization feasible.

**Efficient inversion via Woodbury** — never form the $N\times N$ inverse:

$$\Sigma^{-1} = D^{-1} - D^{-1}B\big(\Omega_f^{-1} + B'D^{-1}B\big)^{-1}B'D^{-1}$$

Cost drops from $O(N^3)$ to $O(NK^2)$.

**Canonical factor sets:**

| Model | Factors |
|---|---|
| CAPM | market |
| Fama–French 3 | market, SMB (size), HML (value) |
| Carhart 4 | + WML (momentum) |
| Fama–French 5 | market, size, value, RMW (profitability), CMA (investment) |
| Barra/Axioma | ~10 style + ~60 industry + country/currency |
| Statistical (PCA) | leading eigenvectors of $\hat\Sigma$ |

**CAPM** as the $K=1$ case: $\mathbb E[r_i]-r = \beta_i(\mathbb E[r_m]-r)$,
$\beta_i = \mathrm{Cov}(r_i,r_m)/\mathrm{Var}(r_m)$.

**Fama–MacBeth two-pass estimation** (the standard test):
1. Time-series regression per asset → $\hat\beta_i$.
2. **Cross-sectional** regression each period: $r_{i,t} = \gamma_{0,t} + \gamma_t'\hat\beta_i + \eta_{i,t}$.
3. Risk premium $\hat\gamma = \frac1T\sum_t\hat\gamma_t$, with
   $\mathrm{SE}(\hat\gamma) = \mathrm{Std}(\hat\gamma_t)/\sqrt T$.

The time-series of $\hat\gamma_t$ handles cross-sectional correlation automatically —
that's the trick. Shanken correction adjusts for the errors-in-variables from using
$\hat\beta$ rather than $\beta$.

**Alpha and hedged risk.** After neutralizing factor exposure ($B'w=0$), portfolio
risk collapses to idiosyncratic:

$$\sigma_p^2 = w'Dw \quad\Longrightarrow\quad \sigma_p \approx \frac{\bar\sigma_\epsilon}{\sqrt{N_{\text{eff}}}}$$

**This is the entire economic case for market-neutral stat arb:** factor-hedging
converts a 20-vol universe into a 4-vol book, multiplying Sharpe by 5 for the same
alpha — provided the factor model is right. When it's wrong (Aug 2007, Jan 2021),
the "hedged" book is levered 6× into an unhedged factor.

---

## 4.8 Constrained optimization in practice

The real problem you solve:

$$\max_w\ w'\mu - \frac{\gamma}{2}w'\Sigma w - c'|w - w_0| \quad\text{s.t.}$$

| Constraint | Form |
|---|---|
| Budget | $\mathbf1'w = 1$ (or $=0$ for dollar-neutral) |
| Leverage | $\|w\|_1 \le L$ |
| Position limits | $|w_i| \le u_i$ |
| Factor neutrality | $|B'w| \le \epsilon$ |
| Sector limits | $|\mathbf1_s'w| \le u_s$ |
| Liquidity / participation | $|w_i - w_{0,i}|\cdot \mathrm{AUM} \le \theta\cdot\mathrm{ADV}_i$ |
| Turnover budget | $\|w-w_0\|_1 \le \Theta$ |
| Cardinality | $\|w\|_0 \le M$ (non-convex — needs MIP or greedy) |

Everything except cardinality is convex — solve with an interior-point QP or, at
scale, ADMM/OSQP. Cardinality constraints turn it into a MIQP; in practice, solve
the relaxation, then apply an $\ell_1$ penalty and threshold.

**Diagnostic that catches most bugs:** decompose realized risk by source
($\mathrm{RC}_i$ from §4.5) and check that the top 10 names aren't 60% of your risk.
If they are, your $\Sigma$ is under-estimating something.

---

## 4.9 Cheat sheet

| Portfolio | Weights | Needs $\mu$? |
|---|---|---|
| Equal weight | $w_i = 1/N$ | no |
| Inverse vol | $w_i \propto 1/\sigma_i$ | no |
| Min variance | $\Sigma^{-1}\mathbf1 / \mathbf1'\Sigma^{-1}\mathbf1$ | no |
| Risk parity | $w_i(\Sigma w)_i$ equal | no |
| Max diversification | $\propto \Sigma^{-1}\sigma$ | no |
| Tangency / max Sharpe | $\propto\Sigma^{-1}(\mu-r\mathbf1)$ | yes |
| Kelly / Merton | $\frac1\gamma\Sigma^{-1}(\mu-r\mathbf1)$ | yes |
| Black–Litterman | MVO on posterior $\mathbb E[\mu]$ | views only |
| Gârleanu–Pedersen | partial step toward aim | yes, + horizon |

**Ordering by robustness** (most to least): equal weight → inverse vol → risk parity
→ min variance → Black–Litterman → tangency. Move down the list only as far as your
forecast quality justifies.

---

**Next:** [05 — Risk Measures](05-risk-measures.md)
