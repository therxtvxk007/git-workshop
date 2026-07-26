# 10 — Alpha, Signals & Capacity

How good is a signal, how do you combine signals, and how much money can they carry?
This chapter connects forecast quality to dollars.

---

## 10.1 The fundamental law of active management

**Grinold's law.** For a strategy with information coefficient $\mathrm{IC}$ and
breadth $\mathrm{BR}$ (independent bets per year):

$$\boxed{\;\mathrm{IR} \approx \mathrm{IC}\cdot\sqrt{\mathrm{BR}}\;}$$

**Derivation.** Suppose a signal $g_i$ (standardized) forecasts standardized returns
$z_i$ with correlation $\mathrm{IC}$. The optimal position in the single-bet case gives
Sharpe $= \mathrm{IC}/\sqrt{1-\mathrm{IC}^2}\approx\mathrm{IC}$ per bet. With $\mathrm{BR}$
independent bets per year, Sharpes add in quadrature (§04.1):

$$\mathrm{IR}_{\text{annual}} = \sqrt{\sum_{i=1}^{\mathrm{BR}}\mathrm{IC}^2} = \mathrm{IC}\sqrt{\mathrm{BR}}\qquad\square$$

**Calibrate your intuition:**

| IC | BR | IR |
|---|---|---|
| 0.05 | 500 (500 stocks, annual rebalance) | 1.12 |
| 0.03 | 3000 (500 stocks, 6 rebalances/yr) | 1.64 |
| 0.10 | 50 (macro, weekly) | 0.71 |
| 0.02 | 250,000 (HFT: 1000 trades/day) | 10.0 |
| 0.30 | 4 (concentrated discretionary) | 0.60 |

**The three lessons:**

1. **Breadth dominates.** An IC of 0.02 with enormous breadth beats an IC of 0.30
   with none. This is the entire mathematical case for systematic over discretionary
   investing — and for HFT over anything else.
2. **IC is tiny in practice.** A "good" equity cross-sectional signal has IC 0.03–0.06.
   Anyone claiming IC > 0.15 out of sample on liquid markets is measuring something
   wrong (usually lookahead).
3. **Sharpe scales as $\sqrt{\mathrm{BR}}$, so the marginal value of more bets
   decays.** Going from 100 to 400 bets doubles IR; from 400 to 1600 doubles it
   again. Costs, however, scale *linearly* with bets — which is where the ceiling
   comes from.

### The transfer coefficient — the version that's actually true

The clean law assumes an unconstrained portfolio. Real portfolios are constrained
(long-only, position limits, turnover, factor neutrality). Define the **transfer
coefficient** as the correlation between the actual portfolio's active weights and
the unconstrained optimal ones:

$$\mathrm{TC} = \mathrm{Corr}\big(w_{\text{actual}},\ w_{\text{optimal}}\big)$$

$$\boxed{\;\mathrm{IR} = \mathrm{TC}\cdot\mathrm{IC}\cdot\sqrt{\mathrm{BR}}\;}$$

**Typical TC values:**

| Constraint set | TC |
|---|---|
| Unconstrained long/short | 0.90–0.98 |
| Long/short with position limits | 0.80–0.90 |
| Long-only, benchmark-relative | 0.30–0.60 |
| Long-only with tight tracking error | 0.20–0.40 |

**A long-only manager throws away half to three-quarters of their signal.** The
short-side information simply cannot be expressed. This single number explains most
of the performance gap between long/short and long-only managers running identical
research.

**BR is also usually overstated.** Breadth counts *independent* bets. 500 stocks
with a common factor exposure might have $N_{\text{eff}} = 20$ independent bets.
Use the effective-number-of-bets calculation (§05.5):

$$\mathrm{BR}_{\text{eff}} = \frac{N}{1 + (N-1)\bar\rho_{\text{signal}}}$$

At $N=500$ and average signal cross-correlation $\bar\rho=0.1$: $\mathrm{BR}_{\text{eff}}=10$,
not 500. **Signal correlation destroys breadth quadratically fast.**

---

## 10.2 The information coefficient

$$\mathrm{IC} = \mathrm{Corr}\big(\text{forecast}_t,\ \text{realized return}_{t+1}\big)$$

**Variants and when to use them:**

| Type | Definition | Use |
|---|---|---|
| Pearson IC | linear correlation | when forecasts are well-scaled |
| **Rank IC (Spearman)** | correlation of ranks | **default** — robust to outliers |
| Risk-adjusted IC | corr with vol-normalized returns | when vol varies cross-sectionally |
| IC decay | $\mathrm{IC}(h)$ vs horizon $h$ | determines rebalance frequency |

**Statistical significance.** With $T$ periods of cross-sectional IC observations:

$$t\text{-stat} = \frac{\overline{\mathrm{IC}}}{\mathrm{Std}(\mathrm{IC}_t)}\sqrt T$$

The **IC information ratio** $\overline{\mathrm{IC}}/\mathrm{Std}(\mathrm{IC}_t)$ is more useful
than the mean IC alone — a signal with IC 0.03 ± 0.05 is better than IC 0.06 ± 0.20.

**IC decay and optimal horizon.** Fit

$$\mathrm{IC}(h) = \mathrm{IC}_0\,e^{-h/\tau_{\text{signal}}}$$

$\tau_{\text{signal}}$ (the signal half-life) determines everything downstream:
rebalance frequency, achievable breadth, and cost sensitivity. Rebalancing much
faster than $\tau$ pays costs for nothing; much slower wastes the signal.

**Optimal rebalance frequency** — trade off signal capture against cost:

$$\max_f\ \ \mathrm{IR}(f) \approx \frac{\mathrm{IC}\sqrt{f\cdot N}\cdot(1 - e^{-1/(f\tau)})\ldots}{\ldots} - \frac{\text{cost}\cdot f\cdot\text{turnover}}{\sigma}$$

The practical rule that falls out: **rebalance at roughly the signal half-life.**
Faster only if costs are negligible relative to the alpha decay.

---

## 10.3 From signal to position

**Grinold's alpha formula** — converting a standardized score into an expected return:

$$\boxed{\;\alpha_i = \mathrm{IC}\cdot\sigma_i\cdot z_i\;}$$

where $z_i$ is the cross-sectionally standardized signal ($\mathbb E[z]=0$, $\mathrm{Std}(z)=1$)
and $\sigma_i$ the asset's forecast volatility.

**Derivation.** Regress return on score: $r_i = \beta z_i + \epsilon$. Then
$\beta = \mathrm{Cov}(r,z)/\mathrm{Var}(z) = \mathrm{Corr}(r,z)\sigma_r = \mathrm{IC}\cdot\sigma_i$. $\square$

**This is the correct way to scale a signal into an optimizer.** Feeding raw
z-scores into MVO produces nonsense because the units are wrong — the $\sigma_i$
factor is what makes a 2-sigma signal on a volatile stock worth more than a 2-sigma
signal on a quiet one.

**Position sizing** then follows §04.1:

$$w = \frac{1}{\gamma}\Sigma^{-1}\alpha = \frac{\mathrm{IC}}{\gamma}\Sigma^{-1}\big(\sigma\odot z\big)$$

**Signal transformations, and when each is right:**

| Transform | Formula | When |
|---|---|---|
| Z-score | $(x-\bar x)/\sigma_x$ | signal is roughly normal |
| Rank / uniform | $\mathrm{rank}(x)/N - 0.5$ | outlier-heavy signals |
| Rank-normal | $\Phi^{-1}(\mathrm{rank}/(N+1))$ | **best default** — robust *and* correctly scaled |
| Winsorize | clip at $\pm3\sigma$ | preserve magnitude, kill outliers |
| Sign | $\mathrm{sgn}(x)$ | signal has information only in direction |

**Conditional expectation is the honest test.** Bucket the signal into deciles and
plot the mean forward return per bucket. If the relationship isn't monotone, a
linear model is wrong regardless of the IC. Non-monotonicity in the extreme buckets
is extremely common and usually means the tails of the signal are driven by data
errors or illiquidity.

---

## 10.4 Combining signals

Given $K$ signals with forecast correlations, the optimal combination is
mean–variance in signal space:

$$\boxed{\;w_{\text{combo}} \propto \Omega_s^{-1}\,\mathrm{IC}\;}$$

with $\Omega_s$ the correlation matrix of the signals and $\mathrm{IC}$ the vector of
individual ICs. Identical to §04.1 with signals as assets.

**Combined IC:**

$$\mathrm{IC}_{\text{combo}} = \sqrt{\mathrm{IC}'\,\Omega_s^{-1}\,\mathrm{IC}}$$

**Two uncorrelated signals of IC 0.03 each combine to $0.03\sqrt2 = 0.042$.** Two
signals correlated at 0.8 combine to only 0.0316 — a 5% improvement for twice the
research. **The value of a new signal is entirely in its orthogonality to what you
already have,** and this equation quantifies it exactly.

**Marginal contribution of a new signal $K+1$:**

$$\Delta\mathrm{IC}^2 = \frac{\big(\mathrm{IC}_{K+1} - \rho'\Omega_K^{-1}\mathrm{IC}_K\big)^2}{1 - \rho'\Omega_K^{-1}\rho}$$

with $\rho$ the correlations of the new signal to the existing ones. **This is the
number to compute before spending three months on a new dataset.** Note the
numerator: a signal with *low* raw IC but negative correlation to your book can
contribute more than a high-IC duplicate.

**Practical warning: $\Omega_s^{-1}$ is unstable.** With $K>10$ correlated signals
and limited history, the inverse amplifies noise exactly as in §04.2. Fixes:
- Shrink: $\tilde\Omega = \delta I + (1-\delta)\hat\Omega_s$, $\delta\approx0.2$–0.5.
- **Equal-weight the standardized signals.** Absurdly hard to beat out of sample;
  optimal when ICs are similar and correlations are moderate.
- Hierarchical grouping (value, momentum, quality, flow) — equal-weight within
  groups, optimize across groups where you have more data per parameter.

---

## 10.5 Cross-validation and backtest overfitting

**The multiple-testing reality.** If you test $N$ independent strategies on noise,
the expected maximum in-sample Sharpe is approximately

$$\mathbb E[\max \mathrm{SR}] \approx \sigma_{\mathrm{SR}}\Big[(1-\gamma)\Phi^{-1}\Big(1-\frac1N\Big) + \gamma\,\Phi^{-1}\Big(1-\frac{1}{Ne}\Big)\Big]$$

($\gamma\approx0.577$.) With $\sigma_{\mathrm{SR}}=1$ and $N=1000$: $\mathbb E[\max\mathrm{SR}]\approx3.26$
**from pure noise.** Report the deflated Sharpe (§05.6) or your backtest is
uninformative.

**Probability of backtest overfitting (PBO).** Combinatorially split the sample into
$S$ subsets, form all $\binom{S}{S/2}$ train/test partitions, and compute

$$\mathrm{PBO} = \mathbb P\big(\text{the in-sample-best strategy ranks below median out of sample}\big)$$

PBO > 0.5 means your selection process is worse than random. It routinely is.

**Walk-forward is not enough.** Standard cross-validation leaks in time series
through:
- **Overlapping labels.** A 20-day forward return at $t$ and at $t+1$ share 19 days.
  Use **purging** (drop training samples whose label window overlaps the test set)
  and **embargo** (drop a further gap after the test set).
- **Survivorship bias.** Point-in-time universes, always.
- **Lookahead in data timestamps.** Fundamentals must be lagged by actual reporting
  dates, not period end. This one error can manufacture an IC of 0.10.

**Deflated backtest length.** The minimum track record needed to establish
$\mathrm{SR}^\star$ at confidence $\alpha$:

$$\boxed{\;T_{\min} = 1 + \Big(1 - \gamma_3\mathrm{SR} + \frac{\gamma_4-1}{4}\mathrm{SR}^2\Big)\left(\frac{\Phi^{-1}(\alpha)}{\mathrm{SR}-\mathrm{SR}^\star}\right)^2\;}$$

At $\mathrm{SR}=1$, $\mathrm{SR}^\star=0$, Gaussian, 95%: $T_{\min}\approx 1 + 1.5\times 2.71 = 5.1$ years.

---

## 10.6 Capacity

The equation that determines whether a strategy is a business.

**Setup.** Gross alpha $\alpha$ (in return terms), turnover $\tau$ (fraction of the
book traded per year), AUM $= M$. Costs from the square-root law (§06.7):

$$\text{Cost per unit traded} = Y\sigma\sqrt{\frac{Q}{V}} = Y\sigma\sqrt{\frac{\tau M w_i}{V_i}}$$

**Net return:**

$$R_{\text{net}}(M) = \alpha - \tau\cdot Y\,\sigma\sqrt{\frac{\tau M}{V_{\text{eff}}}}$$

**Capacity** — where net alpha hits zero:

$$\boxed{\;M_{\max} = \frac{V_{\text{eff}}}{\tau}\left(\frac{\alpha}{\tau\,Y\,\sigma}\right)^2\;}$$

**Optimal AUM** — maximizing *dollar* profit $M\cdot R_{\text{net}}(M)$:

$$\frac{d}{dM}\Big[M\alpha - \tau YM\sigma\sqrt{\tfrac{\tau M}{V}}\Big] = 0
\ \Longrightarrow\ \alpha = \frac32\,\tau Y\sigma\sqrt{\frac{\tau M}{V}}$$

$$\boxed{\;M^\star = \frac49\,M_{\max},\qquad R_{\text{net}}(M^\star) = \frac{\alpha}{3}\;}$$

**Two beautiful and brutal results:**

1. **Run at 4/9 of your theoretical capacity.** Beyond that, extra AUM destroys
   dollar profit.
2. **At optimal size you keep exactly one-third of your gross alpha.** Two-thirds
   goes to the market in impact. This is a universal consequence of square-root
   costs and holds regardless of the strategy's details.

**The turnover penalty.** Capacity scales as $\tau^{-3}$:

$$M_{\max}\propto \frac{\alpha^2}{\tau^3\sigma^2 Y^2}$$

**Doubling turnover cuts capacity by 8×.** This is why:
- HFT strategies have tiny capacity (millions) despite enormous Sharpe.
- Value strategies have huge capacity (billions) despite mediocre Sharpe.
- The Sharpe–capacity frontier is a hyperbola, and every fund sits somewhere on it.

**Worked example.** Cross-sectional equity signal: $\alpha = 4\%$ gross,
$\tau = 4$/yr, $\sigma=20\%$ daily-annualized, $Y=0.5$, effective daily volume
across the universe $V_{\text{eff}} = \$50$bn/day $\approx \$12.5$tn/yr.

$$M_{\max} = \frac{1.25\times10^{13}}{4}\left(\frac{0.04}{4\times0.5\times0.20}\right)^2 = 3.1\times10^{12}\times0.01 = \$31\text{bn}$$

$$M^\star = \tfrac49\times31 = \$14\text{bn},\qquad \text{net alpha} = 1.33\%$$

Sensible for a large quant equity fund. Now rerun with $\tau=50$ (weekly turnover):
capacity falls by $(50/4)^3\approx 1950\times$ to **\$16m**. Same signal, different
horizon, entirely different business.

---

## 10.7 Alpha decay and crowding

**Post-publication decay.** Academic anomalies lose roughly 30–60% of their returns
after publication (McLean–Pontiff), and roughly 60%+ after a decade. Model it as

$$\alpha_t = \alpha_0\,e^{-t/\tau_{\text{decay}}}$$

with $\tau_{\text{decay}}$ of 3–8 years for published equity anomalies, and far
shorter — weeks to months — for microstructure signals.

**Crowding measures worth tracking:**

| Measure | Definition |
|---|---|
| Short interest / days-to-cover | position concentration in the short leg |
| 13F overlap | fraction of your book held by peer funds |
| Return correlation to peer indices | HFRX/HFRI quant equity |
| Residual eigenvalue (§09.5) | top eigenvalue of the residual covariance |
| Signal decay acceleration | drop in $\tau_{\text{signal}}$ over time |

**The crowding equation.** If $N$ managers each run capital $M_i$ against the same
signal with total capacity $M_{\max}$, each earns

$$\alpha_{\text{net},i} = \alpha - Y\sigma\tau\sqrt{\frac{\tau\sum_j M_j}{V}}$$

**Costs depend on aggregate crowd size, revenue on your own size.** This is a
classic tragedy of the commons: the Nash equilibrium overshoots the socially optimal
capacity, everyone earns less than $\alpha/3$, and the strategy dies faster than any
single participant intends. It also implies the *exit* is correlated, which is the
mechanism behind §09.5's quant quake.

---

## 10.8 Signal families and their characteristics

| Family | Horizon | IC | Turnover | Capacity | Notes |
|---|---|---|---|---|---|
| Value (B/P, E/P, FCF yield) | 1–5 yr | 0.02–0.04 | 0.5–2×/yr | very high | long drawdowns (2018–20) |
| Momentum (12-1) | 3–12 mo | 0.03–0.05 | 4–8×/yr | high | crash risk, needs beta hedge |
| Quality / profitability | 1–3 yr | 0.02–0.04 | 1–2×/yr | very high | negatively correlated to value |
| Low vol / betting-against-beta | 1–3 yr | 0.02–0.03 | 1–2×/yr | high | leverage-constraint story |
| Short-term reversal | 1–5 d | 0.03–0.06 | 100×/yr | low | liquidity provision; cost-dominated |
| Earnings drift (PEAD) | 1–3 mo | 0.04–0.07 | 10×/yr | medium | event-driven, needs point-in-time data |
| Analyst revisions | 1–6 mo | 0.03–0.05 | 6–12×/yr | medium | |
| Flow / order imbalance | min–hr | 0.05–0.15 | 500×/yr | very low | §06.8 |
| Order book microstructure | ms–s | 0.10–0.30 | huge | tiny | latency-bound |
| News / NLP sentiment | hr–d | 0.02–0.06 | 50×/yr | medium | decays fastest of all |

**The pattern:** IC rises and capacity collapses as horizon shortens. That is the
$\tau^{-3}$ law of §10.6 in tabular form. **There is no free lunch anywhere on this
table** — every row's Sharpe-times-capacity product is roughly comparable, which is
what an efficient market of *arbitrageurs* (not of prices) looks like.

---

## 10.9 Machine learning: what changes and what doesn't

**What doesn't change.** The fundamental law still binds. ML raises IC, not breadth.
Costs and capacity are unaffected. An ML model with IC 0.06 instead of 0.04 is a
50% IR improvement — real, but not transformative.

**What ML is genuinely good at here:**
- **Non-linearity and interactions.** Signals whose payoff depends on regime, on
  liquidity, or on other signals.
- **High-dimensional feature spaces** — order book states, text, alternative data.
- **Ranking**, not level prediction. Optimize the objective you care about
  (cross-sectional rank correlation), not MSE.

**What breaks:**
- **Non-stationarity.** Financial relationships change; ML assumes i.i.d. sampling
  from a fixed distribution. Retrain constantly, and expect performance decay.
- **Signal-to-noise.** $R^2$ of 0.005 is a *good* return prediction. Standard ML
  practice (built for $R^2>0.5$ problems) massively overfits at this SNR.
- **Sample size.** 30 years of daily data is 7,500 observations. Deep learning
  needs orders of magnitude more, which is why the successful applications are
  cross-sectional (7,500 × 3,000 stocks) or high-frequency.

**The practical discipline:**
1. Purged, embargoed cross-validation (§10.5). Non-negotiable.
2. Heavy regularization; prefer gradient-boosted trees or linear models with strong
   priors over deep nets on tabular financial data.
3. **Ensemble across time.** Average models trained on different windows rather than
   picking the best.
4. Sample weighting by uniqueness (López de Prado) to handle overlapping labels.
5. Feature importance via permutation on *out-of-sample* data, not in-sample gain.
6. Always compare to the linear baseline. If a gradient-boosted model doesn't beat
   ridge regression on the same features out of sample, use ridge.

---

## 10.10 The chapter in five equations

$$\mathrm{IR} = \mathrm{TC}\cdot\mathrm{IC}\cdot\sqrt{\mathrm{BR}} \qquad\text{(what determines Sharpe)}$$

$$\alpha_i = \mathrm{IC}\cdot\sigma_i\cdot z_i \qquad\text{(signal} \to \text{expected return)}$$

$$\mathrm{IC}_{\text{combo}} = \sqrt{\mathrm{IC}'\Omega_s^{-1}\mathrm{IC}} \qquad\text{(value of a new signal)}$$

$$M^\star = \frac49 M_{\max},\quad R_{\text{net}} = \frac\alpha3 \qquad\text{(optimal size, and what you keep)}$$

$$M_{\max}\propto \frac{\alpha^2}{\tau^3\sigma^2} \qquad\text{(turnover destroys capacity cubically)}$$

---

**Next:** [11 — HFT Mechanics](11-hft-mechanics.md)
