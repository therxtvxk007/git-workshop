# 09 — Statistical Arbitrage

Find a portfolio whose price is stationary, then trade its deviations. The math is
mean reversion; the difficulty is that stationarity is a hypothesis, not a fact.

---

## 9.1 Cointegration

Two $I(1)$ series $y_t, x_t$ (each a random walk) are **cointegrated** if there
exists $\beta$ such that

$$z_t = y_t - \beta x_t \sim I(0)$$

is stationary. **Correlation is about returns; cointegration is about levels.**
Two assets can be highly correlated and never converge (correlated random walks
drift apart forever), or weakly correlated and tightly cointegrated.

For trading, cointegration is the property you need: it guarantees the spread
returns, which is what makes a stop-loss finite and a horizon estimable.

### Engle–Granger two-step

1. **Estimate the relationship** by OLS: $y_t = \alpha + \beta x_t + z_t$.
   Under cointegration $\hat\beta$ is *superconsistent* — it converges at rate $T$
   rather than $\sqrt T$, so the estimation error in $\beta$ is second-order.
2. **Test the residual for stationarity** with an ADF regression:
   $$\Delta z_t = \rho\,z_{t-1} + \sum_{i=1}^{p}\phi_i\Delta z_{t-i} + \varepsilon_t$$
   $H_0: \rho=0$ (unit root, no cointegration). **Critical values are not the
   standard ADF ones** — because $z$ is a fitted residual, use the Engle–Granger /
   MacKinnon tables (roughly $-3.9$ at 5% for two variables, more negative as the
   number of variables grows).

**Direction matters.** Regressing $y$ on $x$ and $x$ on $y$ gives different $\hat\beta$
in finite samples. Use total least squares (orthogonal regression) or the Johansen
procedure if the asymmetry bothers you — and it should, since $1/\hat\beta_{y|x} \ne \hat\beta_{x|y}$.

### Johansen procedure

For $n>2$ assets, cointegration relationships can number up to $n-1$; Engle–Granger
can only find one. Johansen tests them jointly via the VECM:

$$\Delta Y_t = \Pi Y_{t-1} + \sum_{i=1}^{p-1}\Gamma_i\Delta Y_{t-i} + \varepsilon_t$$

$$\Pi = \alpha\beta'$$

- $\mathrm{rank}(\Pi) = r$ = number of cointegrating relations.
- $\beta$ ($n\times r$) = the cointegrating vectors — **your portfolio weights**.
- $\alpha$ ($n\times r$) = adjustment speeds — **how fast each asset corrects**.

**Test statistics** from the eigenvalues $\hat\lambda_1>\cdots>\hat\lambda_n$ of the
reduced-rank problem:

$$\text{trace: } -T\sum_{i=r+1}^{n}\ln(1-\hat\lambda_i),\qquad
\text{max-eig: } -T\ln(1-\hat\lambda_{r+1})$$

**Practical guidance:** Johansen is powerful but overfits badly with many assets and
short samples. With $n>5$, the eigenvectors are numerically unstable — small data
changes flip the portfolio. Prefer PCA-based residuals (§9.5) at scale, and reserve
Johansen for small, economically motivated baskets (futures curves, cross-listings,
ETF vs. constituents).

---

## 9.2 The OU spread and its statistics

Model the cointegration residual as Ornstein–Uhlenbeck (§01.4):

$$dz_t = \theta(\bar\mu - z_t)\,dt + \sigma_z\,dW_t$$

**The three numbers that define the trade:**

$$\boxed{\;t_{1/2} = \frac{\ln 2}{\theta},\qquad
\sigma_{\text{eq}} = \frac{\sigma_z}{\sqrt{2\theta}},\qquad
\text{score } Z_t = \frac{z_t - \bar\mu}{\sigma_{\text{eq}}}\;}$$

**Calibration is just an AR(1) fit** on the sampled spread ($\Delta$ = sampling interval):

$$z_{t+\Delta} = c + \rho z_t + \varepsilon_t \quad\Longrightarrow\quad
\theta = -\frac{\ln\rho}{\Delta},\quad \bar\mu = \frac{c}{1-\rho},\quad \sigma_z^2 = \frac{2\theta\,\hat\sigma^2_\varepsilon}{1-\rho^2}$$

**Expected return of a mean-reversion trade.** Enter at $z$, exit at $\bar\mu$:

$$\mathbb E[\text{holding time}] \approx \frac{1}{\theta}\ln\Big|\frac{z-\bar\mu}{\text{exit band}}\Big|,\qquad
\mathbb E[\text{P\&L}] = |z-\bar\mu| - \text{costs}$$

**Annualized Sharpe of a single OU pair** (round trips at $\pm a$ standard
deviations, ignoring costs), the useful approximation:

$$\mathrm{SR} \approx \sqrt{\frac{2\theta}{\ldots}}\ \cdot\ \ldots \quad\Longrightarrow\quad
\boxed{\;\mathrm{SR}\ \propto\ \sqrt{\theta}\;}$$

**Sharpe scales with the square root of the mean-reversion speed.** A spread with a
1-day half-life is $\sqrt{20}\approx4.5\times$ better than one with a 20-day half-life,
all else equal. **This is why stat arb migrated to higher frequencies** — and why
half-life is the first thing to compute about any candidate spread.

**Cost hurdle.** A round trip costs $2c$ (both legs, both ways). You need

$$\text{entry threshold } a\,\sigma_{\text{eq}} > 2c \quad\Longrightarrow\quad a > \frac{2c}{\sigma_{\text{eq}}}$$

If $\sigma_{\text{eq}}$ is 30 bp and round-trip cost is 10 bp, you need $a>0.67$ — fine.
If $\sigma_{\text{eq}}$ is 12 bp, the strategy doesn't exist. **Compute this before
backtesting anything.**

---

## 9.3 Optimal entry and exit thresholds

**The naive rule** — enter at $|Z|>2$, exit at $Z=0$ — is a reasonable default but
provably suboptimal. Two better formulations.

### Bertram's solution: maximize return per unit time

For a symmetric OU spread with entry at $-a$ and exit at $+m$ (in units of
$\sigma_{\text{eq}}$), the expected trade cycle time is

$$\mathbb E[T_{\text{cycle}}] = \frac{\pi}{\theta}\Big[\mathrm{Erfi}\Big(\frac{m}{\sqrt2}\Big) - \mathrm{Erfi}\Big(\frac{a}{\sqrt2}\Big)\Big]$$

with $\mathrm{Erfi}(x) = \frac{2}{\sqrt\pi}\int_0^x e^{u^2}du$. The objective is

$$\max_{a,m}\ \ \mu(a,m) = \frac{(m-a)\sigma_{\text{eq}} - c}{\mathbb E[T_{\text{cycle}}]}$$

**Result:** the optimal symmetric strategy ($m=-a$) has entry near
$a^\star\approx 1.0$–$1.5$ standard deviations for zero costs, widening as costs rise.
**Not 2.0.** Wider thresholds capture more per trade but wait exponentially longer;
the $\mathrm{Erfi}$ growth is brutal, so there is a sharp optimum.

Maximizing the **Sharpe ratio** instead of return-per-time gives slightly wider
bands, since variance of cycle time also matters.

### Stochastic control formulation

Rather than fixed thresholds, solve for the optimal *position* as a function of
the spread (Cartea–Jaimungal, or the Gârleanu–Pedersen framework of §04.6):

$$\max_{\pi}\ \mathbb E\Big[\int_0^T \big(\pi_t\,\theta(\bar\mu - z_t) - \tfrac\gamma2\pi_t^2\sigma_z^2 - \tfrac{\lambda}{2}\dot\pi_t^2\big)dt\Big]$$

**Without trading costs** ($\lambda=0$), the FOC gives

$$\boxed{\;\pi^\star_t = \frac{\theta(\bar\mu - z_t)}{\gamma\sigma_z^2}\;}$$

**Position is linear in the deviation** — not a step function. This is the Merton
solution (§04.4) with $\mu = \theta(\bar\mu-z)$, and it dominates threshold rules
when costs are low: you scale in as the spread widens rather than committing
everything at one level.

**With quadratic costs**, the solution becomes a partial adjustment toward $\pi^\star$
(§04.6), and with **proportional** costs it becomes a **no-trade band** around the
linear rule — the practical hybrid: hold a linear position, but only rebalance when
you drift outside a band of width $\propto (c\sigma^2/\gamma)^{1/3}$.

**Recommendation:** linear-in-$Z$ position sizing with a no-trade band, capped at
some $|Z|_{\max}$ (beyond which you should suspect a structural break, not an
opportunity).

---

## 9.4 Pairs selection

The multiple-testing problem is severe. Screening 500 stocks gives 124,750 pairs;
at 5% significance, ~6,200 will "cointegrate" by chance.

**A disciplined pipeline:**

1. **Economic prior first.** Same industry, same supply chain, dual listings, ETF
   vs basket, futures calendar spreads. Never start from a blind $n^2$ scan.
2. **Cointegration test** on a training window, with a *corrected* significance
   threshold (Bonferroni or, better, Benjamini–Hochberg FDR at 10%).
3. **Half-life filter.** Require $t_{1/2}$ within a tradeable range — typically
   1 day to 3 weeks. Too fast: costs eat you. Too slow: capital is dead and the
   relationship probably breaks first.
4. **Cost hurdle** (§9.2): $\sigma_{\text{eq}} \gg$ round-trip cost.
5. **Out-of-sample stability**: refit $\beta$ on rolling windows and require it to
   be stable. A $\beta$ that wanders is a relationship that doesn't exist.
6. **Hurst exponent** as a model-free confirmation.

**Hurst exponent.** From the scaling of the rescaled range or the variance of
$k$-lag differences:

$$\mathbb E\big[|z_{t+k}-z_t|^2\big] \propto k^{2H}$$

$$\boxed{\;H<0.5\ \Rightarrow\ \text{mean reverting},\quad H=0.5\ \Rightarrow\ \text{random walk},\quad H>0.5\ \Rightarrow\ \text{trending}\;}$$

Estimate by regressing $\ln\mathrm{Var}(z_{t+k}-z_t)$ on $\ln k$; slope $=2H$. It's
model-free and robust — a good cross-check on the ADF test, which has notoriously
low power.

**The relationship to the variance ratio** (§03.7): $\mathrm{VR}(k) = k^{2H-1}$.
They are the same statistic in different clothing.

---

## 9.5 Statistical arbitrage at scale: PCA residuals

For hundreds of names, don't do pairs. Do this.

**Step 1 — extract factors** by PCA on the correlation matrix of returns:

$$R = F\Lambda' + \epsilon,\qquad F = \text{first } K \text{ principal components}$$

Choose $K$ by the Marchenko–Pastur edge (§12.1) — eigenvalues above
$\lambda_+ = \sigma^2(1+\sqrt{N/T})^2$ are signal; below, noise. Typically $K\approx15$
for a 500-name US equity universe.

**Step 2 — regress each stock on the factors:**

$$r_{i,t} = \alpha_i + \sum_{k=1}^{K}\beta_{ik}f_{k,t} + \epsilon_{i,t}$$

**Step 3 — cumulate the residual** to build a mean-reverting score:

$$X_{i,t} = \sum_{s\le t}\epsilon_{i,s}$$

**Step 4 — fit OU to $X_i$** and compute the s-score:

$$\boxed{\;s_i = \frac{X_{i} - \bar\mu_i}{\sigma_{\text{eq},i}}\;}$$

**Step 5 — trade** with position $\propto -s_i$ (or thresholded), then
**re-neutralize**: the resulting portfolio must satisfy $\Lambda'w \approx 0$ so you
hold pure idiosyncratic risk.

**Avellaneda–Lee's rules of thumb:** open long at $s<-1.25$, close at $s>-0.5$;
open short at $s>1.25$, close at $s<0.75$. Require $t_{1/2}$ between roughly 1 day
and 1 month; drop names outside that.

**Why this beats pairs:**
- $N$ signals instead of $N^2$ hypotheses — the multiple-testing problem shrinks by
  orders of magnitude.
- Automatic factor neutrality.
- Diversification across $N$ residuals: $\sigma_p \approx \bar\sigma_\epsilon/\sqrt{N_{\text{eff}}}$,
  so the Sharpe benefit of breadth (§10.1) is captured directly.

**The known failure mode.** All PCA-residual books hold nearly identical positions.
When they delever simultaneously, the residuals become correlated and the "market
neutral" book takes a large, sudden loss — the August 2007 quant quake. The
mathematical signature: the residual correlation matrix, normally near-identity,
develops a dominant eigenvalue in exactly the direction everyone is positioned.
**Monitor the top eigenvalue of your residual covariance as a crowding gauge.**

---

## 9.6 Index arbitrage and structural relationships

The cleanest stat arb has a **hard convergence mechanism** rather than a statistical
one.

**ETF vs. NAV.**

$$\text{Premium}_t = \frac{P^{\mathrm{ETF}}_t}{\mathrm{NAV}_t} - 1$$

Bounded by the creation/redemption cost band $\pm c$. Inside the band the premium
is an OU process; at the band, authorized participants arbitrage it. **A convergence
mechanism with a known cost gives a known, finite band** — the ideal stat-arb setup
(and correspondingly thin margins).

**Cash-and-carry / futures basis.**

$$F_{t,T} = S_te^{(r-q)(T-t)} \quad\Longrightarrow\quad \text{basis} = F - Se^{(r-q)\tau}$$

Deviations are arbitrageable subject to financing, borrow, and margin. The **implied
repo rate**

$$r_{\text{implied}} = \frac{1}{\tau}\ln\frac{F}{S} + q$$

is the tradeable object; compare it to your actual funding cost. During stress,
implied repo dislocates from actual repo — that dislocation *is* the trade, and it
is also a leading indicator of funding stress.

**Triangular FX arbitrage.**

$$\text{Edge} = \frac{1}{(S_{A/B})(S_{B/C})(S_{C/A})} - 1$$

Zero in equilibrium; nonzero for microseconds. Pure latency.

**Covered interest parity:**

$$F_{A/B} = S_{A/B}\,\frac{1+r_A\tau}{1+r_B\tau}$$

CIP held nearly exactly until 2008 and has been persistently violated since — the
**cross-currency basis**, driven by balance-sheet costs and regulatory constraints.
A textbook example of an "arbitrage" that persists because the arbitrage capital is
itself constrained.

---

## 9.7 Momentum and reversal — the two systematic effects

**Time-series momentum:** $\mathbb E[r_{t,t+h}\mid r_{t-k,t}] > 0$ for $k,h$ in the
3–12 month range. Position sizing:

$$w_t = \frac{\mathrm{sgn}(r_{t-12m,t})}{\sigma_t}\cdot\text{target vol}$$

Vol-scaling is not optional — it roughly doubles the Sharpe of a raw momentum
strategy and it is what makes managed-futures programs work.

**Cross-sectional momentum:** rank on past 12-month return skipping the most recent
month (the skip avoids the 1-month reversal effect), long the top decile, short the
bottom.

**Short-horizon reversal:** at daily-to-weekly horizons the sign flips — losers
outperform. This is *liquidity provision*, not a behavioral anomaly: you are paid
for absorbing the inventory imbalance that pushed the price. It is the
lowest-capacity, highest-turnover, highest-cost-sensitivity family in the space,
and it is essentially the portfolio-level version of market making (§08).

**Momentum's structural flaw — the crash.** Momentum has large negative skew
(momentum crashes: 1932, 2009, 2020). The mechanism: after a market decline, the
short leg is composed of high-beta distressed names, so the strategy accumulates a
**large negative market beta** exactly before the rebound.

$$\beta_{\text{mom},t} \approx \beta_{\text{winners}} - \beta_{\text{losers}} \ll 0 \quad\text{after crashes}$$

**Fixes that demonstrably work:** dynamically hedge the momentum portfolio's beta,
and scale exposure by forecast momentum volatility ($w_t\propto1/\hat\sigma^2_{\text{mom},t}$).
Both roughly halve the drawdown.

---

## 9.8 Risk management specific to stat arb

**The break detector.** Stat arb's characteristic death is a spread that stops mean
reverting. Monitor:

$$\text{CUSUM}_t = \max\big(0,\ \mathrm{CUSUM}_{t-1} + (z_t - \bar\mu) - k\big)$$

and exit when it exceeds a threshold. **A widening spread is indistinguishable in
real time from a broken one** — this is the core epistemological problem of the
strategy, and no statistic solves it. Only a hard risk limit does.

**Stop-loss placement.** Under OU, the probability of hitting $-b$ before reverting
to $\bar\mu$ starting from $z$ has a closed form via the scale function
$s(x) = \int_0^x e^{\theta u^2/\sigma_z^2}du$:

$$\mathbb P(\text{hit } -b \text{ before } \bar\mu) = \frac{s(\bar\mu) - s(z)}{s(\bar\mu)-s(-b)}$$

Use it to size the stop so that the stop probability times the loss is a set
fraction of the expected gain. Note the *tension*: a stop-loss on a genuinely
mean-reverting spread is negative-expectancy by construction (you exit at the worst
point). Its justification is entirely about the possibility that the model is wrong
— so set it based on your confidence in cointegration, not on the OU parameters.

**Leverage and the drawdown constraint.** Stat arb books run 4–8× gross leverage
because the residual vol is small. That leverage means:

$$\text{book vol} = L\cdot\sigma_{\text{residual}},\qquad \text{but the tail is } L\cdot\sigma_{\text{residual}}\Big|_{\text{crowded}}$$

and $\sigma_{\text{residual}}$ under crowding is not the estimate from calm periods.
Size the book so that a **3× increase in residual correlation** (§9.5) is survivable.
That, not the Sharpe ratio, is the binding constraint on the strategy.

---

## 9.9 Summary

| Step | Equation |
|---|---|
| Find the relationship | Johansen $\Pi=\alpha\beta'$, or PCA residual |
| Verify stationarity | ADF with EG critical values; Hurst $H<0.5$ |
| Characterize | $t_{1/2}=\ln2/\theta$, $\sigma_{\text{eq}}=\sigma_z/\sqrt{2\theta}$ |
| Check viability | $\sigma_{\text{eq}} \gg 2\times$ round-trip cost |
| Size | $\pi^\star = \theta(\bar\mu - z)/(\gamma\sigma_z^2)$, with a no-trade band |
| Expect | $\mathrm{SR}\propto\sqrt\theta$; breadth via $\sqrt{N_{\text{eff}}}$ |
| Monitor | CUSUM on the spread; top eigenvalue of residual covariance |

**The one-line summary:** everything in stat arb is a bet that $\theta > 0$ and will
stay that way. The equations tell you how to size and time the bet; nothing tells
you when $\theta$ becomes zero, which is why position limits exist.

---

**Next:** [10 — Alpha, Signals & Capacity](10-signals-alpha.md)
