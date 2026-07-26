# 05 — Risk Measures

Two jobs: size positions, and survive. The equations here are simple; the failure
modes are where all the value is.

---

## 5.1 Value at Risk

$$\mathrm{VaR}_\alpha = -\inf\big\{x : \mathbb P(L \le x)\ge\alpha\big\} = -q_{1-\alpha}(R)$$

"With probability $\alpha$, losses will not exceed $\mathrm{VaR}_\alpha$ over horizon $h$."

**Parametric (Gaussian):**

$$\boxed{\;\mathrm{VaR}_\alpha = -\big(\mu h + \sigma\sqrt h\,\Phi^{-1}(1-\alpha)\big) = \sigma\sqrt h\,z_\alpha - \mu h\;}$$

with $z_{0.95}=1.645$, $z_{0.99}=2.326$, $z_{0.999}=3.090$.

**Portfolio form:** $\mathrm{VaR}_\alpha = z_\alpha\sqrt{w'\Sigma w}\cdot\sqrt h$.

**Component VaR** (Euler decomposition — VaR is homogeneous degree 1 in $w$):

$$\mathrm{CVaR}_i = w_i\frac{\partial\mathrm{VaR}}{\partial w_i} = w_i z_\alpha\frac{(\Sigma w)_i}{\sqrt{w'\Sigma w}},\qquad \sum_i\mathrm{CVaR}_i = \mathrm{VaR}$$

This is how you attribute firm risk to desks. It's also the number that tells you
a "diversified" book is really one trade.

**Cornish–Fisher expansion** — corrects the Gaussian quantile for skew $S$ and excess
kurtosis $K$:

$$z_\alpha^{CF} = z_\alpha + \frac{(z_\alpha^2-1)S}{6} + \frac{(z_\alpha^3-3z_\alpha)K}{24} - \frac{(2z_\alpha^3-5z_\alpha)S^2}{36}$$

At $S=-1$, $K=5$, $\alpha=99\%$: $z^{CF} = 2.326 + 0.735 + 0.998 - 0.169 = 3.89$.
**The Gaussian VaR understates by 67%.** Valid only for moderate $S,K$ — the
expansion is non-monotone for large values, which is itself a warning.

### VaR is not coherent

A coherent risk measure satisfies monotonicity, translation invariance, positive
homogeneity, and **subadditivity**: $\rho(X+Y)\le\rho(X)+\rho(Y)$.

**VaR violates subadditivity.** Counterexample: two independent bonds, each
defaulting with probability 4% and losing 100.
- $\mathrm{VaR}_{95}$(single bond) $=0$ (4% < 5%).
- Portfolio of both: $\mathbb P(\text{at least one defaults}) = 1-0.96^2 = 7.84\% > 5\%$,
  so $\mathrm{VaR}_{95}$(portfolio) $= 100 > 0 + 0$.

**Diversification appears to increase risk.** This isn't academic pedantry: it means
VaR can be gamed by moving risk just past the quantile — writing deep OTM options is
the canonical example, and it produced the structured-credit blowups of 2008.

---

## 5.2 Expected Shortfall

$$\boxed{\;\mathrm{ES}_\alpha = \mathbb E\big[L \mid L \ge \mathrm{VaR}_\alpha\big] = \frac{1}{1-\alpha}\int_\alpha^1\mathrm{VaR}_u\,du\;}$$

**Coherent.** Subadditive by construction, and it sees the whole tail, not one point.
Basel FRTB replaced VaR with ES$_{97.5}$ for exactly these reasons.

**Gaussian closed form:**

$$\boxed{\;\mathrm{ES}_\alpha = \mu + \sigma\,\frac{\phi\big(\Phi^{-1}(\alpha)\big)}{1-\alpha}\;}$$

*Derivation.* $\mathbb E[Z|Z>z] = \frac{1}{1-\Phi(z)}\int_z^\infty x\phi(x)dx$, and since
$\int x\phi(x)dx = -\phi(x)$, this equals $\phi(z)/(1-\Phi(z))$. $\square$

At $\alpha=97.5\%$: $\mathrm{ES}/\sigma = \phi(1.96)/0.025 = 0.0584/0.025 = 2.34$ —
almost exactly $z_{0.99}$. **That equivalence is why FRTB chose 97.5%**: it keeps
capital roughly level while switching to a coherent measure.

**Student-$t$ ES** (df $\nu$, standardized):

$$\mathrm{ES}_\alpha = \frac{\nu + t_\nu^{-1}(\alpha)^2}{\nu-1}\cdot\frac{f_\nu\big(t_\nu^{-1}(\alpha)\big)}{1-\alpha}\cdot\sigma\sqrt{\frac{\nu-2}{\nu}}$$

At $\nu=4$ the $99\%$ ES is roughly 1.5× the Gaussian value.

**Elicitability caveat.** VaR is elicitable (has a strictly consistent scoring
function — the pinball loss), ES is not. So ES is harder to **backtest** directly;
practice uses joint (VaR, ES) backtests or the Acerbi–Székely tests.

---

## 5.3 Extreme value theory

Don't model the whole distribution when you only care about the tail.

**Peaks over threshold.** For $u$ large, conditional exceedances converge to the
**Generalized Pareto Distribution**:

$$\mathbb P(X - u \le y \mid X>u) \to G_{\xi,\beta}(y) = 1 - \Big(1+\frac{\xi y}{\beta}\Big)^{-1/\xi}$$

- $\xi>0$: heavy tail (Fréchet) — equities, credit, all financial returns
- $\xi=0$: exponential tail (Gumbel)
- $\xi<0$: bounded tail (Weibull)

**Tail quantile and ES estimators.** With $N_u$ exceedances out of $n$:

$$\boxed{\;\widehat{\mathrm{VaR}}_\alpha = u + \frac{\hat\beta}{\hat\xi}\left[\Big(\frac{n}{N_u}(1-\alpha)\Big)^{-\hat\xi} - 1\right]\;}$$

$$\boxed{\;\widehat{\mathrm{ES}}_\alpha = \frac{\widehat{\mathrm{VaR}}_\alpha}{1-\hat\xi} + \frac{\hat\beta - \hat\xi u}{1-\hat\xi}\;}$$

The ES/VaR ratio $\to \frac{1}{1-\xi}$ in the tail — a single number summarizing how
bad "bad" gets. At $\xi = 0.3$ (typical for daily equity), ES is 1.43× VaR far out,
versus ~1.15× for a Gaussian.

**Hill estimator** for the tail index $\alpha_{\text{tail}} = 1/\xi$, using the top $k$
order statistics:

$$\hat\xi_{\text{Hill}} = \frac1k\sum_{i=1}^{k}\ln\frac{X_{(i)}}{X_{(k+1)}}$$

**Empirically $\alpha_{\text{tail}}\approx 3$ for equity returns** — the "inverse cubic law,"
remarkably stable across markets, assets, and decades. This means:
- Variance exists (needs $\alpha>2$) — vol is meaningful.
- **Kurtosis does not exist** (needs $\alpha>4$) — your sample kurtosis is a
  meaningless function of your sample size.
- The 4th-moment terms in Cornish–Fisher are on shaky ground.

---

## 5.4 Drawdown

The risk measure that actually ends careers — investors redeem on drawdown, not
on VaR.

$$\mathrm{DD}_t = \frac{\max_{s\le t}W_s - W_t}{\max_{s\le t}W_s},\qquad \mathrm{MDD}_T = \max_{t\le T}\mathrm{DD}_t$$

**Expected maximum drawdown** for a Brownian motion with drift $\mu$, vol $\sigma$
over horizon $T$ — Magdon-Ismail's asymptotic result:

$$\mathbb E[\mathrm{MDD}] \approx \frac{\sigma^2}{2\mu}\,\ln\!\Big(\frac{\mu^2T}{\sigma^2}\Big) \quad\text{for } \mu>0,\ \tfrac{\mu^2T}{\sigma^2}\gg1$$

Rewriting in terms of Sharpe ($\mathrm{SR}=\mu/\sigma$):

$$\boxed{\;\mathbb E[\mathrm{MDD}] \approx \frac{\sigma}{2\,\mathrm{SR}}\ln\big(\mathrm{SR}^2T\big)\;}$$

**Only $\ln T$, but $1/\mathrm{SR}$.** Doubling your track record barely raises the
expected worst drawdown; halving your Sharpe doubles it. A Sharpe-1, 10%-vol
strategy over 10 years: $\mathbb E[\mathrm{MDD}]\approx \frac{0.10}{2}\ln(10) = 11.5\%$.
A Sharpe-0.5 strategy at the same vol: $\approx 16\%$ — and takes 4× as long to recover.

**Maximum drawdown probability (Kelly-scaled).** Trading at fraction $c$ of full Kelly:

$$\mathbb P\big(\text{equity ever falls to fraction } x\big) = x^{\,2/c - 1}$$

*Derivation sketch.* Log-wealth is BM with drift $\mu_c = c(1-c/2)\mathrm{SR}^2$ and vol
$\sigma_c = c\,\mathrm{SR}$. For BM with drift, $\mathbb P(\text{ever hit } -a) = e^{-2\mu_c a/\sigma_c^2}$;
substitute $a = -\ln x$ and simplify. $\square$

| Kelly fraction $c$ | $\mathbb P$(50% DD) | $\mathbb P$(20% DD) | Growth retained |
|---|---|---|---|
| 1.00 | 50% | 80% | 100% |
| 0.50 | 12.5% | 51% | 75% |
| 0.33 | 3.1% | 33% | 56% |
| 0.25 | 1.6% | 25% | 44% |

**Related ratios:**

$$\text{Calmar} = \frac{\text{annualized return}}{\mathrm{MDD}},\qquad
\text{Sterling} = \frac{r}{\text{avg annual MDD}},\qquad
\text{Ulcer Index} = \sqrt{\frac1T\sum_t \mathrm{DD}_t^2}$$

The Ulcer Index is the best of these — it penalizes depth *and* duration, and it's
differentiable, so you can optimize against it.

---

## 5.5 Portfolio risk decomposition

$$\sigma_p = \sqrt{w'\Sigma w}$$

| Quantity | Formula |
|---|---|
| Marginal risk | $\mathrm{MCR}_i = (\Sigma w)_i/\sigma_p$ |
| Risk contribution | $\mathrm{RC}_i = w_i(\Sigma w)_i/\sigma_p$ |
| % contribution | $\mathrm{RC}_i/\sigma_p$ |
| Beta to portfolio | $\beta_{i,p} = (\Sigma w)_i/\sigma_p^2$ |

**Diversification ratio:**

$$\mathrm{DR} = \frac{\sum_i w_i\sigma_i}{\sigma_p}\ \ge 1$$

**Effective number of bets** (Meucci) — decorrelate via PCA into $N$ principal
portfolios with variance contributions $p_i$ (normalized to sum to 1), then

$$N_{\text{ent}} = \exp\Big(-\sum_i p_i\ln p_i\Big)$$

A 500-stock long-only equity book typically has $N_{\text{ent}}\approx 2$–$4$. That
number, not the position count, is your real diversification. Reporting "we hold
500 names" while $N_{\text{ent}}=2$ is the most common risk-reporting lie in the
industry.

**Factor vs idiosyncratic split:**

$$\sigma_p^2 = \underbrace{w'B\Omega_fB'w}_{\text{systematic}} + \underbrace{w'Dw}_{\text{specific}}$$

For a market-neutral book you want the second term dominant. If systematic risk
exceeds ~30% of total in a "neutral" book, your hedge is wrong.

---

## 5.6 Performance metrics and their statistics

**Sharpe ratio:**

$$\mathrm{SR} = \frac{\mathbb E[r]-r_f}{\sigma(r)},\qquad \mathrm{SR}_{\text{ann}} = \mathrm{SR}_{\text{period}}\sqrt{\text{periods/yr}}$$

**Standard error of the Sharpe ratio** (Lo, 2002) — i.i.d. normal returns, $T$ observations:

$$\boxed{\;\mathrm{SE}(\widehat{\mathrm{SR}}) \approx \sqrt{\frac{1+\tfrac12\mathrm{SR}^2}{T}}\;}$$

**This is the number that should govern every hiring, allocation, and go-live
decision.** With 3 years of daily data ($T=756$) and $\mathrm{SR}=1$:
$\mathrm{SE}=\sqrt{1.5/756}=0.045$ *per period*; annualized, $\mathrm{SE}\approx 0.045\times\sqrt{252}\ldots$
— careful: compute in annualized units directly. With $T$ **years** of data:

$$\mathrm{SE}(\mathrm{SR}_{\text{ann}}) \approx \sqrt{\frac{1+\tfrac12\mathrm{SR}^2}{T_{\text{years}}}}$$

So 3 years at SR=1 gives $\mathrm{SE} = \sqrt{1.5/3} = 0.71$. **A 95% CI of $[-0.4, 2.4]$.**
Three years of live track record cannot distinguish a great strategy from a bad one.

To establish $\mathrm{SR}=1$ at $t$-stat 2 requires $T \approx 4(1+0.5)/1 = 6$ years.

**Non-normality correction** (Mertens):

$$\mathrm{SE}(\widehat{\mathrm{SR}}) = \sqrt{\frac{1 + \tfrac12\mathrm{SR}^2 - \gamma_3\mathrm{SR} + \tfrac{\gamma_4-3}{4}\mathrm{SR}^2}{T}}$$

Negative skew ($\gamma_3<0$) **increases** the standard error. A short-vol strategy
with $\gamma_3=-3$, $\gamma_4=20$, apparent SR=2: the correction term is
$1 + 2 + 6 + 17 = 26$ versus 3 for the Gaussian case — the true SE is nearly 3× larger.

**Autocorrelation correction** (illiquid/smoothed returns — credit, PE, some
stat-arb marks):

$$\mathrm{SR}_{\text{ann}} = \frac{\mathrm{SR}_{\text{period}}\cdot q}{\sqrt{q + 2\sum_{k=1}^{q-1}(q-k)\rho_k}}$$

At $\rho_1=0.3$, monthly→annual, the naive $\sqrt{12}$ overstates Sharpe by ~25%.

**Other ratios:**

| Metric | Formula | Use |
|---|---|---|
| Sortino | $(\mathbb E[r]-r_f)/\sigma_{\text{down}}$ | asymmetric payoffs |
| Information ratio | $\alpha/\omega$ (tracking error) | benchmark-relative |
| Treynor | $(\mathbb E[r]-r_f)/\beta$ | systematic-risk-only |
| Omega | $\int_L^\infty(1-F)dx\,/\int_{-\infty}^LF\,dx$ | full distribution, no moments needed |
| Probabilistic SR | $\Phi\!\big((\widehat{\mathrm{SR}}-\mathrm{SR}^*)/\mathrm{SE}\big)$ | $\mathbb P(\text{true SR}>\mathrm{SR}^*)$ |

**Deflated Sharpe ratio** (Bailey–López de Prado) — corrects for the fact that you
tried $N$ strategies:

$$\mathrm{DSR} = \Phi\!\left(\frac{(\widehat{\mathrm{SR}} - \mathrm{SR}_0)\sqrt{T-1}}{\sqrt{1-\gamma_3\widehat{\mathrm{SR}} + \tfrac{\gamma_4-1}{4}\widehat{\mathrm{SR}}^2}}\right)$$

with the multiple-testing-adjusted threshold

$$\mathrm{SR}_0 = \sigma_{\mathrm{SR}}\left[(1-\gamma)\Phi^{-1}\!\Big(1-\frac1N\Big) + \gamma\,\Phi^{-1}\!\Big(1-\frac{1}{Ne}\Big)\right]$$

($\gamma\approx0.577$, Euler–Mascheroni; $\sigma_{\mathrm{SR}}$ = dispersion of Sharpe across
the trials.) **If you tested 1000 configurations, the expected max Sharpe of pure
noise is around 3.2 in-sample.** Report DSR or your backtest means nothing.

---

## 5.7 Stress testing and scenario analysis

Historical VaR is backward-looking by construction. Complement it with:

**Factor shock scenarios.** Shock $K$ factors by $\Delta f$, propagate:

$$\Delta P = w'B\,\Delta f + \text{(second order: } \tfrac12\Delta f'\,\Gamma\,\Delta f)$$

For options books the second-order term dominates — a delta-neutral book has
$w'B\Delta f = 0$ by construction but can lose enormously to gamma and vanna.

**Conditional correlation stress.** Replace $\Omega$ with the correlation matrix
estimated on the worst $q\%$ of market days. For equity books this typically
raises risk 40–80%.

**Coherent scenario weighting.** Given scenarios $s$ with probabilities $p_s$:

$$\mathrm{ES}^{\text{scenario}} = \max_{\mathbb Q\in\mathcal P}\ \mathbb E^{\mathbb Q}[L]$$

over a set of admissible measures — every coherent risk measure has this
representation (Artzner et al.). ES corresponds to $\mathcal P = \{\mathbb Q : d\mathbb Q/d\mathbb P \le 1/(1-\alpha)\}$.

**Liquidity-adjusted VaR:**

$$\mathrm{LVaR} = \mathrm{VaR}\cdot\sqrt{h^\star} + \frac12\text{(spread)}\cdot|w| + \text{impact}(|w|/\mathrm{ADV})$$

where $h^\star$ is the time to liquidate at acceptable participation. **The
liquidation horizon must scale with position size:** $h^\star \approx \frac{Q}{\theta\cdot\mathrm{ADV}}$
at participation rate $\theta$. A position that takes 10 days to exit has
$\sqrt{10}=3.2$× the VaR of the 1-day number, plus impact (§07).

---

## 5.8 The risk equations that matter most

1. $\mathrm{ES}_\alpha = \mu + \sigma\phi(\Phi^{-1}(\alpha))/(1-\alpha)$ — coherent, tail-aware, closed form.
2. $\mathrm{SE}(\mathrm{SR}) = \sqrt{(1+\mathrm{SR}^2/2)/T}$ — how little you know from a track record.
3. $\mathbb P(\text{DD to } x) = x^{2/c-1}$ — the true cost of leverage.
4. $\mathbb E[\mathrm{MDD}] \approx \frac{\sigma}{2\mathrm{SR}}\ln(\mathrm{SR}^2T)$ — what to warn investors about.
5. $\mathrm{RC}_i = w_i(\Sigma w)_i/\sigma_p$ — where your risk actually is.
6. $N_{\text{ent}} = e^{-\sum p_i\ln p_i}$ — how many bets you *really* have.
7. $\xi\approx1/3$ for equities — the tail is cubic; kurtosis doesn't exist.

**The meta-lesson.** Every one of these is an equation about *uncertainty in your
estimates*, not about the market. The market's risk is what it is; your risk is
dominated by how badly you've measured it.

---

**Next:** [06 — Market Microstructure](06-market-microstructure.md)
