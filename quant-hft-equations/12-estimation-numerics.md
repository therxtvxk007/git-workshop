# 12 — Estimation & Numerics

Every equation in the preceding chapters takes parameters you must estimate. This
chapter is about the estimates being wrong, and what to do about it.

---

## 12.1 Random matrix theory: separating signal from noise in $\hat\Sigma$

**The problem.** With $N$ assets and $T$ observations, the sample correlation matrix
has $N(N+1)/2$ parameters from $NT$ numbers. Define $Q = T/N$. When $Q$ is not
large, most of $\hat\Sigma$'s eigenvalue spectrum is pure noise.

**Marchenko–Pastur law.** For i.i.d. returns with variance $\sigma^2$, as
$N,T\to\infty$ with $Q=T/N$ fixed, the eigenvalue density of $\hat\Sigma$ converges to

$$\rho(\lambda) = \frac{Q}{2\pi\sigma^2}\frac{\sqrt{(\lambda_+-\lambda)(\lambda-\lambda_-)}}{\lambda},\qquad \lambda\in[\lambda_-,\lambda_+]$$

$$\boxed{\;\lambda_\pm = \sigma^2\Big(1 \pm \frac{1}{\sqrt Q}\Big)^2 = \sigma^2\Big(1\pm\sqrt{\tfrac NT}\Big)^2\;}$$

**Any eigenvalue inside $[\lambda_-,\lambda_+]$ is statistically indistinguishable
from noise.**

**Worked example.** $N=500$ stocks, $T=1000$ days (4 years), $\sigma^2=1$ (correlation
matrix): $Q=2$, so

$$\lambda_+ = (1+0.707)^2 = 2.91,\qquad \lambda_- = (1-0.707)^2 = 0.086$$

Empirically, a US equity correlation matrix has one huge eigenvalue (~100, the
market), maybe 10–20 above 2.91 (sectors, styles), and **the remaining ~480 fall
inside the MP band — indistinguishable from noise.** Yet $\Sigma^{-1}$ weights them
by $1/\lambda$, so the noisiest directions get the *largest* weight in any optimizer.
This is precisely why naive MVO fails (§04.2).

**Eigenvalue clipping.** The simplest effective fix:

$$\tilde\lambda_i = \begin{cases}\lambda_i & \lambda_i > \lambda_+\\ \bar\lambda_{\text{bulk}} & \text{otherwise}\end{cases}$$

where $\bar\lambda_{\text{bulk}}$ is set to preserve the trace. Rebuild
$\tilde\Sigma = \sum_i\tilde\lambda_iv_iv_i'$. Out-of-sample portfolio risk typically
improves 20–40%.

**Better: rotationally invariant estimators (Ledoit–Péché / Bouchaud–Potters).**
Rather than clipping, shrink each eigenvalue by its **oracle** counterpart:

$$\xi_i = \frac{\lambda_i}{\big|1 - Q^{-1} + Q^{-1}\lambda_i\,\mathfrak s(\lambda_i)\big|^2}$$

with $\mathfrak s$ the Stieltjes transform of the empirical spectrum. This is
provably optimal among estimators that keep the sample eigenvectors, and it beats
clipping consistently.

**Condition number as a health check.**

$$\kappa(\Sigma) = \frac{\lambda_{\max}}{\lambda_{\min}}$$

If $\kappa > 10^4$, your inverse is numerically meaningless before it's statistically
meaningless. Check this before every optimization.

---

## 12.2 Shrinkage

**Ledoit–Wolf.** Shrink the sample covariance toward a structured target $F$:

$$\boxed{\;\hat\Sigma_{LW} = \alpha F + (1-\alpha)\hat\Sigma\;}$$

with the **optimal intensity** minimizing expected Frobenius loss:

$$\alpha^\star = \frac{1}{T}\cdot\frac{\sum_{i,j}\widehat{\mathrm{Var}}(\hat\sigma_{ij})}{\sum_{i,j}(f_{ij}-\sigma_{ij})^2} = \frac{\pi - \varrho}{\varkappa\,T}$$

where $\pi$ estimates the total variance of the sample entries, $\varrho$ the
covariance between sample and target errors, and $\varkappa$ the misspecification of
the target. Clip $\alpha^\star$ to $[0,1]$.

**Common targets:**

| Target $F$ | When |
|---|---|
| $\bar\sigma^2 I$ | maximum shrinkage; very small $T$ |
| Constant correlation $\bar\rho$ | **default** — very effective for equities |
| Single-index (market) model | when a natural single factor exists |
| Multi-factor $B\Omega B'+D$ | when you already have a risk model |

**Why it works.** Bias–variance trade-off in matrix form: $\hat\Sigma$ is unbiased but
high-variance; $F$ is biased but low-variance. The convex combination minimizes MSE.
Typical $\alpha^\star$ for $N=500$, $T=1000$: 0.2–0.4 — you should be shrinking
**a third of the way** to the target.

**Shrinking returns matters more.** James–Stein:

$$\hat\mu_{JS} = \bar\mu\mathbf 1 + \Big(1 - \frac{(N-2)\sigma^2/T}{\|\hat\mu - \bar\mu\mathbf1\|^2}\Big)^+\big(\hat\mu - \bar\mu\mathbf1\big)$$

For $N\ge3$ this **dominates** the sample mean in MSE — a famous and initially
shocking result. In portfolio terms, return estimation errors hurt roughly an order
of magnitude more than covariance errors, so this is the higher-value shrinkage
even though it gets less attention.

---

## 12.3 The Kalman filter

The optimal recursive estimator for linear-Gaussian state space models — and the
right tool for any time-varying parameter (a drifting hedge ratio, a slowly moving
beta, an unobserved fair value).

**Model:**

$$\text{state: } x_t = F x_{t-1} + w_t,\quad w_t\sim\mathcal N(0,Q)$$
$$\text{observation: } y_t = Hx_t + v_t,\quad v_t\sim\mathcal N(0,R)$$

**Predict:**

$$\hat x_{t|t-1} = F\hat x_{t-1|t-1},\qquad P_{t|t-1} = FP_{t-1|t-1}F' + Q$$

**Update:**

$$\tilde y_t = y_t - H\hat x_{t|t-1}\qquad\text{(innovation)}$$
$$S_t = HP_{t|t-1}H' + R\qquad\text{(innovation covariance)}$$
$$\boxed{\;K_t = P_{t|t-1}H'S_t^{-1}\;}\qquad\text{(Kalman gain)}$$
$$\hat x_{t|t} = \hat x_{t|t-1} + K_t\tilde y_t,\qquad P_{t|t} = (I - K_tH)P_{t|t-1}$$

**The gain is the whole story:** $K$ balances how much you trust the model ($P$)
against how much you trust the observation ($R$). Large $Q/R$ ⟹ fast adaptation,
noisy estimates. Small $Q/R$ ⟹ smooth, laggy estimates. **The $Q/R$ ratio is the
only real tuning knob**, and it is exactly the smoothing/responsiveness trade-off
of any moving average — but derived optimally rather than guessed.

**Trading applications:**

| Use | State $x$ | Observation $y$ |
|---|---|---|
| Time-varying hedge ratio | $\beta_t$ | $y_t = \beta_tx_t + v$ |
| Dynamic pairs trading | $(\alpha_t,\beta_t)$ | leg prices |
| Fair value from noisy quotes | efficient price | observed trades/quotes |
| Stochastic vol filtering | $\ln\sigma_t^2$ | squared returns (needs EKF/UKF) |
| Trend extraction | level + slope | price |

**Log-likelihood** for parameter estimation (fit $Q,R$ by MLE):

$$\ln L = -\frac12\sum_t\Big[\ln|S_t| + \tilde y_t'S_t^{-1}\tilde y_t\Big] + \text{const}$$

**Innovation diagnostics — the free model check.** If the model is right,
$\tilde y_t/\sqrt{S_t}$ should be i.i.d. $\mathcal N(0,1)$. Test for autocorrelation
(Ljung–Box) and normality. **Autocorrelated innovations mean your state equation is
misspecified**, and this test catches more bugs than any amount of backtesting.

**Nonlinear extensions:** EKF (linearize), UKF (sigma points — better for strong
nonlinearity), particle filter (fully general, expensive, and the only real option
for non-Gaussian state noise).

---

## 12.4 Regression pitfalls specific to finance

**Newey–West HAC standard errors.** Financial residuals are autocorrelated and
heteroskedastic; OLS standard errors are consequently far too small:

$$\hat V_{NW} = (X'X)^{-1}\Big[\sum_{j=-L}^{L}w_j\,\hat\Gamma_j\Big](X'X)^{-1},\qquad w_j = 1 - \frac{|j|}{L+1}$$

with lag truncation $L\approx \lfloor 4(T/100)^{2/9}\rfloor$. **Using OLS standard
errors on overlapping-horizon return regressions overstates t-stats by 2–3×** — the
single most common statistical error in published finance research.

**Overlapping observations.** Regressing $h$-period forward returns sampled daily
creates $h-1$ overlap. The effective sample size is $T/h$, not $T$. Hansen–Hodrick
or Newey–West with $L\ge h$ is mandatory.

**Spurious regression.** Two independent random walks regressed on each other give
$R^2\to$ nonzero and $|t|\to\infty$ as $T$ grows. **Always test for unit roots
first**, and regress in differences unless you have established cointegration (§09.1).

**Errors in variables.** Regressor measured with error $\Rightarrow$ attenuation:

$$\mathrm{plim}\,\hat\beta = \beta\cdot\frac{\sigma^2_{x^\star}}{\sigma^2_{x^\star}+\sigma^2_u} < \beta$$

Pervasive in factor models (estimated betas as regressors) — hence the Shanken
correction in Fama–MacBeth (§04.7).

**Look-ahead bias sources, ranked by frequency of occurrence:**
1. Fundamental data indexed by period end rather than reporting date.
2. Index membership without point-in-time reconstitution.
3. Restated financials.
4. Survivorship in the security master.
5. Using close prices for a signal traded at that same close.
6. Exchange vs. capture timestamps (§11.6).

Each of these can single-handedly turn a null result into a 3-Sharpe backtest.

---

## 12.5 Numerical methods

**Cholesky decomposition** — the workhorse. $\Sigma = LL'$ with $L$ lower triangular.

- Correlated random draws: $x = L z$ with $z\sim\mathcal N(0,I)$.
- Solving $\Sigma w = b$: forward then back substitution, $O(N^2)$ after the
  $O(N^3/3)$ factorization. **Never form $\Sigma^{-1}$ explicitly.**
- Failure of Cholesky is a *feature*: it detects non-positive-definiteness
  immediately.

**Nearest positive definite matrix.** Sample correlation matrices from incomplete or
mismatched data are frequently indefinite. Fix by eigenvalue projection:

$$\tilde\Sigma = \sum_i\max(\lambda_i,\epsilon)\,v_iv_i'$$

then rescale the diagonal to 1. Higham's alternating-projections algorithm gives the
true nearest correlation matrix in Frobenius norm if you need optimality.

**Woodbury identity** — for factor-structured covariance (§04.7):

$$(D + BB')^{-1} = D^{-1} - D^{-1}B(I + B'D^{-1}B)^{-1}B'D^{-1}$$

$O(NK^2)$ instead of $O(N^3)$. At $N=3000$, $K=50$: a ~3600× speedup.

**Monte Carlo variance reduction:**

| Technique | Variance reduction |
|---|---|
| Antithetic variates ($z$ and $-z$) | ~2× (free) |
| Control variates | $1/(1-\rho^2)$ where $\rho$ = corr with the control |
| Importance sampling | orders of magnitude for rare events |
| Quasi-MC (Sobol) | $O(1/n)$ vs $O(1/\sqrt n)$ in low effective dimension |
| Stratification / Latin hypercube | moderate, robust |
| Brownian bridge construction | concentrates Sobol's good dimensions |

**Standard error of an MC estimate:** $\mathrm{SE} = \hat\sigma/\sqrt n$. To halve it,
quadruple the paths — always report it alongside the price.

**PDE solvers:**
- **Crank–Nicolson** — second-order accurate, unconditionally stable, but oscillates
  on non-smooth payoffs. **Always use Rannacher startup** (two fully-implicit
  half-steps first) for options with kinks or barriers.
- Stability of explicit schemes: $\Delta t \le \frac{\Delta x^2}{\sigma^2 x^2}$ —
  the reason nobody uses explicit for finance.

**Root finding:** Newton for implied vol (§02.5), with a bisection fallback for
deep OTM where vega is nearly zero and Newton diverges. Always bracket.

---

## 12.6 Bootstrap and resampling

**IID bootstrap** breaks time dependence — wrong for financial time series.

**Block bootstrap.** Resample blocks of length $b$ to preserve dependence. Optimal
block length for a series with autocorrelation:

$$b^\star \approx \Big(\frac{6\,\hat\varrho^2}{\ldots}\Big)^{1/3}T^{1/3} \sim T^{1/3}$$

**Stationary bootstrap** (Politis–Romano) uses geometrically distributed block
lengths with mean $1/p$, which keeps the resampled series stationary — preferred
over fixed blocks.

**Applications:**
- Confidence intervals for Sharpe ratios (better than the asymptotic formula of
  §05.6 when returns are non-normal).
- **White's Reality Check / Hansen's SPA test** — the correct way to test whether the
  best of $N$ strategies beats a benchmark after accounting for data snooping:
  $$\text{SPA statistic} = \max_k \frac{\sqrt T\,\bar d_k}{\hat\omega_k}$$
  with the null distribution obtained by stationary bootstrap of the loss
  differentials $d_k$. **This is the honest version of "we tested 500 strategies and
  this one worked."**
- Combinatorially purged cross-validation (§10.5) for PBO.

---

## 12.7 The estimation checklist

Before trusting any number produced by the previous eleven chapters:

**Covariance matrices**
- [ ] $T/N > 2$, ideally $> 5$. If not, use a factor model — no exceptions.
- [ ] Shrinkage or RMT cleaning applied.
- [ ] Condition number $< 10^4$.
- [ ] Positive definite (Cholesky succeeds).
- [ ] Half-life of the estimation window matches the holding period.

**Expected returns**
- [ ] Shrunk toward a prior (equilibrium, cross-sectional mean, or zero).
- [ ] $t$-stats computed with HAC standard errors.
- [ ] Adjusted for the number of hypotheses tested.
- [ ] Economic story exists that is independent of the data.

**Backtests**
- [ ] Point-in-time data, no restatements, no survivorship.
- [ ] Purged and embargoed cross-validation.
- [ ] Transaction costs from a calibrated model (§07.4), not a flat assumption.
- [ ] Capacity computed (§10.6), and the backtest size is below $M^\star$.
- [ ] Deflated Sharpe reported (§05.6).
- [ ] Results stable across parameter perturbations of ±30%.

**Live systems**
- [ ] Capture timestamps for decisions, sequence numbers for ordering.
- [ ] Innovation diagnostics on every filter.
- [ ] Markout curves monitored per venue/segment (§11.5).
- [ ] Realized vs. predicted cost regression run daily (§07.10).
- [ ] Position limits scale with volatility (§11.8).

---

## 12.8 The estimation equations

| Purpose | Equation |
|---|---|
| Noise threshold in $\hat\Sigma$ | $\lambda_\pm = \sigma^2(1\pm\sqrt{N/T})^2$ |
| Covariance shrinkage | $\hat\Sigma_{LW} = \alpha F + (1-\alpha)\hat\Sigma$ |
| Mean shrinkage | James–Stein toward the grand mean |
| Optimal filtering | $K_t = P_{t|t-1}H'S_t^{-1}$ |
| Robust std errors | Newey–West with $L\ge$ overlap |
| Fast inverse | Woodbury on $D+BB'$ |
| MC accuracy | $\mathrm{SE}=\hat\sigma/\sqrt n$ |
| Data-snooping test | White/Hansen SPA via stationary bootstrap |
| Overfit probability | PBO via combinatorial purged CV |

---

## Closing note

The equations in this compendium are the easy part. Every one of them is exact
under assumptions that are false, and useful anyway — but only if you know which
assumption you are violating and by how much.

The recurring pattern across all twelve chapters:

- **Continuous-time results** assume you can trade continuously. You cannot; the
  error is $O(n^{-1/2})$ in the number of rebalances.
- **Gaussian results** assume thin tails. Tails are cubic; the error is unbounded.
- **Optimization results** assume you know $\mu$ and $\Sigma$. You know neither; the
  error is proportional to $N/T$.
- **Impact models** assume your trading is small relative to the market. At
  optimal size you keep one-third of your alpha; the other two-thirds is the error.
- **Backtests** assume the future resembles the past selected by the backtest. It
  does not; the error is the difference between in-sample and deflated Sharpe.

Get the sizing right and the model roughly right, and you have a business. Get the
model exactly right and the sizing wrong, and you don't.

---

**Back to:** [README / Index](README.md)
