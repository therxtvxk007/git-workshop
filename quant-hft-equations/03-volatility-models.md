# 03 — Volatility Modelling & Estimation

Volatility is the one quantity in finance that is *actually estimable* from data.
Drift needs decades to identify; vol needs hours. This asymmetry is the foundation
of most systematic trading.

---

## 3.1 The estimation asymmetry (why vol, not drift)

For GBM observed over horizon $T$ with $n$ samples:

$$\mathrm{Std}(\hat\mu) = \frac{\sigma}{\sqrt T}\qquad\text{(depends only on \emph{span}, not sampling frequency)}$$
$$\mathrm{Std}(\hat\sigma^2) \approx \sigma^2\sqrt{\frac{2}{n}}\qquad\text{(depends on \emph{count} — sample faster, get better)}$$

**Derivation of the first.** $\hat\mu = \frac1T\ln(S_T/S_0) + \sigma^2/2$, and
$\ln(S_T/S_0)\sim\mathcal N((\mu-\sigma^2/2)T,\sigma^2T)$, so $\mathrm{Var}(\hat\mu)=\sigma^2/T$.
Sampling more finely within $[0,T]$ adds *nothing*. $\square$

**The consequence.** To distinguish a 5% drift from zero at $\sigma=20\%$ with
$t$-stat 2 requires $T = (2\times0.20/0.05)^2 = 64$ years. Meanwhile 5-minute data
pins down today's $\sigma$ to a few percent relative error by lunchtime.

**Corollary:** any strategy whose edge rests on estimating a mean return from price
history alone is statistically hopeless. Edges must come from cross-section,
conditioning information, or microstructure — not from a long time-series average.

---

## 3.2 Estimators from OHLC data

Close-to-close (the naive one):

$$\hat\sigma^2_{cc} = \frac{1}{n-1}\sum_{i=1}^n\big(r_i - \bar r\big)^2,\qquad r_i = \ln\frac{C_i}{C_{i-1}}$$

Better estimators use the intraday range, gaining efficiency by a factor of 5–8:

**Parkinson (1980)** — uses high/low, 5.2× more efficient than close-to-close:

$$\hat\sigma^2_P = \frac{1}{4n\ln2}\sum_{i=1}^n\Big(\ln\frac{H_i}{L_i}\Big)^2$$

*Why $4\ln2$:* for driftless BM, $\mathbb E[(\ln H/L)^2] = 4\ln2\cdot\sigma^2$.

**Garman–Klass (1980)** — adds open/close, 7.4× efficient:

$$\hat\sigma^2_{GK} = \frac1n\sum_i\Big[\frac12\Big(\ln\frac{H_i}{L_i}\Big)^2 - (2\ln2-1)\Big(\ln\frac{C_i}{O_i}\Big)^2\Big]$$

**Rogers–Satchell (1991)** — the only one that is **drift-unbiased**:

$$\hat\sigma^2_{RS} = \frac1n\sum_i\Big[\ln\frac{H_i}{C_i}\ln\frac{H_i}{O_i} + \ln\frac{L_i}{C_i}\ln\frac{L_i}{O_i}\Big]$$

**Yang–Zhang (2000)** — handles overnight gaps *and* drift; the practical default:

$$\hat\sigma^2_{YZ} = \hat\sigma^2_{\text{overnight}} + k\,\hat\sigma^2_{\text{open-to-close}} + (1-k)\,\hat\sigma^2_{RS}$$
$$k = \frac{0.34}{1.34 + \frac{n+1}{n-1}}$$

**Caveat on range estimators:** all assume continuous observation of the path. With
discrete ticks, the observed high/low are biased *downward* (you miss the true
extremes), so range estimators underestimate. The bias grows as liquidity falls —
worst exactly where you need the estimate most.

---

## 3.3 Realized volatility and high-frequency estimation

$$\mathrm{RV}_t^{(\Delta)} = \sum_{i=1}^{n} r_{t,i}^2, \qquad r_{t,i} = \ln\frac{P_{t,i}}{P_{t,i-1}},\ n = \frac{1}{\Delta}$$

As $\Delta\to0$, $\mathrm{RV}\to\int_0^1\sigma_s^2ds$ — the **integrated variance**. This
consistency is the whole reason high-frequency data is valuable.

**Asymptotic distribution:**

$$\sqrt n\,\big(\mathrm{RV} - \mathrm{IV}\big) \xrightarrow{d} \mathcal N\big(0,\ 2\,\mathrm{IQ}\big),\qquad \mathrm{IQ}=\int_0^1\sigma_s^4ds$$

with a feasible standard error using realized quarticity $\widehat{\mathrm{IQ}} = \frac n3\sum r_i^4$.

### The microstructure noise problem

Observed price = efficient price + noise: $\tilde p = p^\star + u$, $u$ i.i.d. mean-zero.
Then

$$\mathbb E[\mathrm{RV}^{(\Delta)}] = \mathrm{IV} + \underbrace{2n\,\mathbb E[u^2]}_{\text{noise, }\to\infty\text{ as }\Delta\to0}$$

**Sampling faster makes it worse.** RV at 1-second sampling measures the bid-ask
bounce, not volatility.

**The three responses:**

1. **Signature plot + sparse sampling.** Plot $\mathrm{RV}$ vs $\Delta$; it explodes at
   small $\Delta$ and flattens around 5–15 minutes. Sample where it flattens.
   Crude, robust, and still what most desks do.

2. **Two-scale realized volatility (Zhang–Mykland–Aït-Sahalia):**
   $$\widehat{\mathrm{IV}}_{\text{TSRV}} = \overline{\mathrm{RV}}^{(\text{slow})} - \frac{\bar n}{n}\mathrm{RV}^{(\text{fast})}$$
   Converges at rate $n^{-1/6}$ (or $n^{-1/4}$ with the multi-scale version).

3. **Realized kernel (Barndorff-Nielsen et al.)** — rate-optimal $n^{-1/4}$:
   $$\mathrm{RK} = \sum_{h=-H}^{H} k\!\Big(\frac{h}{H+1}\Big)\gamma_h,\qquad \gamma_h = \sum_i r_ir_{i-|h|}$$
   with $k$ a Parzen kernel. The autocovariance terms cancel the noise's negative
   first-order autocorrelation.

### Separating jumps from diffusion

**Bipower variation** is robust to jumps (two adjacent returns are rarely both jumps):

$$\mathrm{BV} = \frac{\pi}{2}\cdot\frac{n}{n-1}\sum_{i=2}^{n}|r_i||r_{i-1}| \ \xrightarrow{p}\ \int\sigma^2ds$$

$$\boxed{\;\widehat{\text{jump contribution}} = \max\big(\mathrm{RV}-\mathrm{BV},\,0\big)\;}$$

Typically 5–15% of total variation in equity indices. Jumps and the continuous part
have **completely different forecasting properties** — the continuous part is highly
persistent, jumps are nearly unforecastable. Separating them materially improves
vol forecasts.

---

## 3.4 GARCH

**GARCH(1,1):**

$$r_t = \mu + \varepsilon_t,\qquad \varepsilon_t = \sigma_t z_t,\ z_t\sim\text{i.i.d.}(0,1)$$
$$\boxed{\;\sigma_t^2 = \omega + \alpha\varepsilon_{t-1}^2 + \beta\sigma_{t-1}^2\;}$$

**Stationarity** requires $\alpha+\beta<1$, giving unconditional variance

$$\bar\sigma^2 = \frac{\omega}{1-\alpha-\beta}$$

*Derivation.* Take unconditional expectations: $\bar\sigma^2 = \omega + \alpha\bar\sigma^2+\beta\bar\sigma^2$
(using $\mathbb E[\varepsilon^2_{t-1}]=\bar\sigma^2$). Solve. $\square$

**Multi-step forecast** — mean reversion to $\bar\sigma^2$ at rate $(\alpha+\beta)$:

$$\boxed{\;\mathbb E_t[\sigma^2_{t+k}] = \bar\sigma^2 + (\alpha+\beta)^{k-1}\big(\sigma^2_{t+1} - \bar\sigma^2\big)\;}$$

*Derivation.* $\mathbb E_t[\sigma^2_{t+k}] = \omega + (\alpha+\beta)\mathbb E_t[\sigma^2_{t+k-1}]$
since $\mathbb E_t[\varepsilon^2_{t+k-1}] = \mathbb E_t[\sigma^2_{t+k-1}]$. Recurse. $\square$

**Term-structure aggregation** — variance over the next $h$ periods:

$$\mathbb E_t\Big[\sum_{k=1}^h\sigma^2_{t+k}\Big] = h\bar\sigma^2 + \frac{1-(\alpha+\beta)^h}{1-(\alpha+\beta)}\big(\sigma^2_{t+1}-\bar\sigma^2\big)$$

This is directly the fair strike of a variance swap under GARCH — and the reason
implied vol term structures slope up when spot vol is low and down when it's high.

**Typical daily equity index estimates:** $\alpha\approx0.08$, $\beta\approx0.90$,
$\alpha+\beta\approx0.98$ ⟹ vol half-life $\approx \ln2/\ln(1/0.98)\approx 34$ days.

**Variants worth knowing:**

| Model | Equation | Captures |
|---|---|---|
| EWMA / RiskMetrics | $\sigma_t^2=\lambda\sigma^2_{t-1}+(1-\lambda)r^2_{t-1}$, $\lambda=0.94$ | GARCH with $\omega=0,\alpha+\beta=1$; no mean reversion |
| GJR-GARCH | $+\,\theta\varepsilon^2_{t-1}\mathbf1_{\varepsilon_{t-1}<0}$ | **leverage effect** — down moves raise vol more |
| EGARCH | $\ln\sigma_t^2 = \omega+\alpha(|z_{t-1}|-\mathbb E|z|)+\theta z_{t-1}+\beta\ln\sigma^2_{t-1}$ | asymmetry, no positivity constraints |
| GARCH-t | $z_t\sim t_\nu$ | fat tails; $\nu\approx5$ typical |

**Leverage is real and large.** For SPX, GJR's $\theta$ is often comparable to
$\alpha$ itself — a $-1\%$ day raises tomorrow's variance roughly twice as much as a
$+1\%$ day. Any risk model without asymmetry is systematically late.

---

## 3.5 HAR-RV — the model that beats GARCH

Corsi's Heterogeneous Autoregressive model. Trivially simple, hard to beat:

$$\boxed{\;\mathrm{RV}_{t+1} = c + \beta_D\,\mathrm{RV}_t^{(D)} + \beta_W\,\mathrm{RV}_t^{(W)} + \beta_M\,\mathrm{RV}_t^{(M)} + \varepsilon_{t+1}\;}$$

with $\mathrm{RV}^{(W)}_t = \frac15\sum_{i=0}^{4}\mathrm{RV}_{t-i}$ and
$\mathrm{RV}^{(M)}_t = \frac1{22}\sum_{i=0}^{21}\mathrm{RV}_{t-i}$.

It's an OLS regression. It approximates long memory ($\mathrm{Corr}(\mathrm{RV}_t,\mathrm{RV}_{t-h})\sim h^{-0.4}$)
with three components representing daily, weekly, and monthly trader horizons.

**Improvements that actually help:**
- Fit in **logs** ($\ln\mathrm{RV}$ is much closer to Gaussian; RV is right-skewed).
- **HAR-RV-J**: separate the jump component, $+\beta_J J_t$.
- **HAR-RV-CJ**: split into continuous ($\mathrm{BV}$) and jump parts as separate regressors —
  $\beta_C \gg \beta_J$, confirming jumps don't persist.
- Add **implied vol** (VIX) as a regressor; it usually gets a significant coefficient,
  meaning options markets contain information beyond the realized path.

Typical $R^2$ for 1-day-ahead log-RV: 0.65–0.75. GARCH on daily returns: ~0.35.

---

## 3.6 The variance risk premium

$$\mathrm{VRP}_t = \mathbb E^{\mathbb Q}_t[\mathrm{RV}_{t,t+\tau}] - \mathbb E^{\mathbb P}_t[\mathrm{RV}_{t,t+\tau}] \approx \mathrm{VIX}_t^2 - \widehat{\mathrm{RV}}_{t+\tau}$$

Persistently **positive** — on SPX, implied variance exceeds subsequent realized
variance roughly 85% of months, averaging 2–4 vol points. This is the compensation
for bearing crash risk, and it is the economic basis of short-vol strategies.

**It is not free money.** The payoff profile is the archetype of negative skew:

$$\text{Sharpe}_{\text{short vol}} \approx 1.0,\qquad \text{Skew} \approx -3,\qquad \text{Kurtosis} > 20$$

A Sharpe ratio computed on a short-vol P&L series is a *lie* — see §05.6 for why
Gaussian-calibrated risk metrics catastrophically understate it. Size these with
tail measures (ES, maximum drawdown under stress), never with volatility.

---

## 3.7 Volatility scaling and aggregation

**Square-root-of-time** rule (valid only for i.i.d. returns):

$$\sigma_{h\text{-period}} = \sigma_{1\text{-period}}\sqrt h$$

**With autocorrelation $\rho_1$ in returns**, the correct scaling is

$$\sigma_h^2 = \sigma_1^2\Big[h + 2\sum_{k=1}^{h-1}(h-k)\rho_k\Big]$$

For $h$ large and AR(1) returns: $\sigma_h^2 \approx h\sigma_1^2\frac{1+\rho_1}{1-\rho_1}$.

**Variance ratio test** — the cleanest test of the random walk:

$$\mathrm{VR}(h) = \frac{\mathrm{Var}(r_t^{(h)})}{h\cdot\mathrm{Var}(r_t^{(1)})} = 1 + 2\sum_{k=1}^{h-1}\Big(1-\frac kh\Big)\rho_k$$

- $\mathrm{VR}>1$ ⟹ **trending / momentum** (positive autocorrelation)
- $\mathrm{VR}<1$ ⟹ **mean reverting** (the stat-arb regime)
- $\mathrm{VR}=1$ ⟹ random walk

Heteroskedasticity-robust test statistic (Lo–MacKinlay):

$$z(h) = \frac{\mathrm{VR}(h)-1}{\sqrt{\hat\theta(h)}},\qquad \hat\theta(h) = \sum_{k=1}^{h-1}\Big[\frac{2(h-k)}{h}\Big]^2\hat\delta_k$$

Use the heteroskedasticity-robust version — the homoskedastic one rejects the
random walk constantly for the wrong reason.

**Practical annualization constants:**

| From | Multiply daily σ by |
|---|---|
| daily → annual (equities) | $\sqrt{252}\approx15.87$ |
| daily → annual (crypto/FX 24-7) | $\sqrt{365}\approx19.10$ |
| 5-min → daily (US equities, 78 bars) | $\sqrt{78}\approx8.83$ |
| monthly → annual | $\sqrt{12}\approx3.46$ |

**Rule of 16:** annual vol ≈ 16 × daily vol. A 16% annual vol name moves ~1%/day.

---

## 3.8 Intraday seasonality

Volatility follows a pronounced U-shape. Ignoring it makes every intraday model wrong.

$$\sigma^2_{t,i} = \underbrace{s_i^2}_{\text{time-of-day}}\cdot\underbrace{\sigma_t^2}_{\text{daily level}}\cdot\underbrace{\tilde\sigma^2_{t,i}}_{\text{stochastic}}$$

Estimate the seasonal factor by averaging across days:

$$\hat s_i^2 = \frac{1}{T}\sum_{t=1}^T\frac{r_{t,i}^2}{\hat\sigma_t^2}$$

Then **deseasonalize** ($\tilde r_{t,i} = r_{t,i}/\hat s_i$) before doing anything else.
Typical US equity pattern: the first 30 minutes carry 3–5× median variance, the
last 30 minutes 2–3×, midday ~0.5×.

**This has direct trading consequences:**
- VWAP schedules must track the **volume** U-shape (correlated with, but not equal
  to, the vol U-shape).
- Market-making spreads should widen at the open, not because of "uncertainty" in
  the abstract but because $\gamma\sigma^2(T-t)$ in the Avellaneda–Stoikov quote (§08)
  scales directly with $\sigma^2$.
- Any vol breakout signal computed on non-deseasonalized data fires at 9:31 every
  single day.

---

## 3.9 Volatility of volatility, and the correlation of correlation

**Vol-of-vol** drives smile convexity (§02.6). Empirically $\nu = \mathrm{vol}(\ln\sigma)\approx 0.8$–$1.5$ annualized
for equity indices — volatility is *more volatile than the underlying.*

**Correlation dynamics.** The critical stylized fact for portfolio risk:

$$\rho \nearrow \text{ when } \sigma \nearrow$$

Diversification fails exactly when you need it. A simple usable model — DCC-GARCH:

$$Q_t = (1-a-b)\bar Q + a\,z_{t-1}z_{t-1}' + b\,Q_{t-1},\qquad R_t = \mathrm{diag}(Q_t)^{-1/2}Q_t\,\mathrm{diag}(Q_t)^{-1/2}$$

where $z_t$ are GARCH-standardized residuals. Two extra parameters for the whole
correlation matrix — that's the reason it's used.

**Stress-test shortcut** that beats most models: recompute portfolio risk with all
pairwise correlations shocked toward the average of their historical 95th percentile.
For equity long/short books this typically raises measured risk by 40–80%.

---

## 3.10 Summary: which estimator, when

| Need | Use |
|---|---|
| Daily risk from daily data | EWMA ($\lambda=0.94$) or GJR-GARCH |
| Daily risk with only OHLC | Yang–Zhang |
| Best 1-day-ahead vol forecast | HAR-RV-CJ on 5-min data, in logs |
| Intraday, live | Deseasonalized EWMA on 1-min bars, or realized kernel |
| Option pricing input | Implied, adjusted down by the VRP if forecasting realized |
| Tail risk | Do **not** use vol — use ES with a fat-tailed or EVT model (§05) |
| Ultra-HF (sub-second) | Realized kernel or TSRV; naive RV is pure noise |

---

**Next:** [04 — Portfolio Construction](04-portfolio-optimization.md)
