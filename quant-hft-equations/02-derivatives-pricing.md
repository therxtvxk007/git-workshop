# 02 — Derivatives Pricing

The central insight: **a derivative's price is the cost of its replication strategy,
not the discounted expectation of its payoff under any belief you hold.**
Hedging replaces forecasting.

---

## 2.1 The Black–Scholes PDE

**Assumptions.** GBM with constant $\sigma$; constant $r$; continuous frictionless
trading; no dividends; short selling allowed; the option is European.

**Derivation (delta hedging).** Hold the option and short $\Delta$ shares:
$\Pi = V - \Delta S$. Over $dt$, treating $\Delta$ as locally constant
(self-financing):

$$d\Pi = dV - \Delta\,dS$$

Itô on $V(S,t)$ with $dS = \mu S\,dt + \sigma S\,dW$:

$$dV = \Big(V_t + \mu S V_S + \tfrac12\sigma^2S^2V_{SS}\Big)dt + \sigma S V_S\,dW$$

Therefore

$$d\Pi = \Big(V_t + \mu SV_S + \tfrac12\sigma^2S^2V_{SS} - \Delta\mu S\Big)dt + \sigma S\big(V_S - \Delta\big)dW$$

**Choose $\Delta = V_S$.** The $dW$ term vanishes and $\Pi$ is instantaneously
riskless, so no-arbitrage forces $d\Pi = r\Pi\,dt = r(V - SV_S)dt$:

$$V_t + \tfrac12\sigma^2S^2V_{SS} = rV - rSV_S$$

$$\boxed{\;\frac{\partial V}{\partial t} + \frac12\sigma^2S^2\frac{\partial^2V}{\partial S^2} + rS\frac{\partial V}{\partial S} - rV = 0\;}$$

**Note what disappeared: $\mu$.** Two traders who violently disagree about expected
return must agree on the option price. That is the whole trick.

**With carry.** Continuous dividend/repo/foreign rate $q$: replace $rS V_S$ with
$(r-q)SV_S$. For futures ($q=r$) the drift term vanishes entirely — Black's model.

---

## 2.2 The Black–Scholes formula

Solve the PDE with $V(S,T) = (S-K)^+$ (substitute $x=\ln S$, $\tau=T-t$ to reduce
to the heat equation), or evaluate the risk-neutral expectation directly:

$$C = e^{-r\tau}\,\mathbb E^{\mathbb Q}\big[(S_T-K)^+\big],\qquad S_T = S e^{(r-\sigma^2/2)\tau + \sigma\sqrt\tau Z}$$

Splitting the expectation into $\mathbb E[S_T\mathbf 1_{S_T>K}] - K\,\mathbb Q(S_T>K)$ and completing
the square in the first term gives:

$$\boxed{\;C = S e^{-q\tau}\Phi(d_1) - Ke^{-r\tau}\Phi(d_2)\;}$$
$$\boxed{\;P = Ke^{-r\tau}\Phi(-d_2) - Se^{-q\tau}\Phi(-d_1)\;}$$

$$d_1 = \frac{\ln(S/K) + (r-q+\tfrac12\sigma^2)\tau}{\sigma\sqrt\tau},\qquad d_2 = d_1 - \sigma\sqrt\tau$$

**Interpretation.**
- $\Phi(d_2) = \mathbb Q(S_T > K)$ — risk-neutral exercise probability.
- $\Phi(d_1) = $ exercise probability under the **share measure** (numéraire $S$), and
  numerically $= \Delta$.
- $Se^{-q\tau}\Phi(d_1)$ is the PV of the stock you'll receive conditional on exercise;
  $Ke^{-r\tau}\Phi(d_2)$ is the PV of the cash you'll pay.

**Put–call parity** (model-free, arbitrage only):

$$C - P = Se^{-q\tau} - Ke^{-r\tau}$$

**Useful ATM approximation** (forward-ATM, small $\sigma\sqrt\tau$):

$$C_{\text{ATM}} \approx 0.4\,S\sigma\sqrt\tau$$

A 1-month 20-vol ATM option on a \$100 stock: $0.4\times100\times0.20\times\sqrt{1/12}\approx\$2.31$.
Exact BS: \$2.30. Good enough to sanity-check a screen in your head.

---

## 2.3 The Greeks

With $\tau = T-t$, $\phi$ the normal pdf, and $q=0$ for brevity:

| Greek | Definition | Call | Put |
|---|---|---|---|
| Delta | $\partial V/\partial S$ | $\Phi(d_1)$ | $\Phi(d_1)-1$ |
| Gamma | $\partial^2V/\partial S^2$ | $\dfrac{\phi(d_1)}{S\sigma\sqrt\tau}$ | same |
| Vega | $\partial V/\partial\sigma$ | $S\phi(d_1)\sqrt\tau$ | same |
| Theta | $\partial V/\partial t$ | $-\dfrac{S\phi(d_1)\sigma}{2\sqrt\tau} - rKe^{-r\tau}\Phi(d_2)$ | $-\dfrac{S\phi(d_1)\sigma}{2\sqrt\tau} + rKe^{-r\tau}\Phi(-d_2)$ |
| Rho | $\partial V/\partial r$ | $K\tau e^{-r\tau}\Phi(d_2)$ | $-K\tau e^{-r\tau}\Phi(-d_2)$ |
| Vanna | $\partial^2V/\partial S\partial\sigma$ | $-\phi(d_1)\dfrac{d_2}{\sigma}$ | same |
| Volga | $\partial^2V/\partial\sigma^2$ | $S\phi(d_1)\sqrt\tau\,\dfrac{d_1d_2}{\sigma}$ | same |
| Charm | $\partial^2 V/\partial S\partial t$ | $-\phi(d_1)\dfrac{2r\tau - d_2\sigma\sqrt\tau}{2\tau\sigma\sqrt\tau}$ | same |

**The identity that makes Gamma and Vega the same trade:**

$$\mathcal V = \Gamma\,S^2\sigma\tau$$

*Proof.* $\Gamma = \phi(d_1)/(S\sigma\sqrt\tau)$, so $\Gamma S^2\sigma\tau = S\phi(d_1)\sqrt\tau = \mathcal V$. $\square$

**Gamma is short-dated, Vega is long-dated.** Both scale as $\phi(d_1)$, but
$\Gamma\propto1/\sqrt\tau$ while $\mathcal V\propto\sqrt\tau$. A 1-day option has enormous
gamma and negligible vega; a 2-year option is the reverse. Hence: gamma scalpers
trade the front, vol traders trade the back.

---

## 2.4 The theta–gamma relation and the P&L of a hedged option

Rewrite the BS PDE in Greek notation:

$$\boxed{\;\Theta + \tfrac12\sigma^2S^2\Gamma + rS\Delta - rV = 0\;}$$

For a delta-hedged book with $r\approx0$:

$$\Theta = -\tfrac12\sigma^2S^2\Gamma$$

**Theta is the rent you pay for gamma.** They are two views of one number.

**The P&L equation.** Suppose you buy an option at implied vol $\sigma_i$ and
delta-hedge continuously while the stock realizes $\sigma_r$. Your instantaneous P&L is

$$d\Pi = \Theta\,dt + \tfrac12\Gamma(dS)^2 = -\tfrac12\Gamma S^2\sigma_i^2\,dt + \tfrac12\Gamma S^2\sigma_r^2\,dt$$

$$\boxed{\;d\Pi = \frac12\,\Gamma\,S^2\big(\sigma_r^2 - \sigma_i^2\big)\,dt\;}$$

Integrating over the life of the trade:

$$\Pi_{\text{total}} = \frac12\int_0^T \Gamma_t S_t^2\big(\sigma_r^2 - \sigma_i^2\big)\,dt$$

**Three consequences that matter:**

1. **An option is a bet on variance, not direction.** You win iff realized variance
   exceeds implied — *in a gamma-weighted, path-dependent sense.*
2. **You can be right about vol and lose money.** The weight $\Gamma_tS_t^2$ is highest
   near the strike. If the stock realizes 40 vol while far from your strike and
   20 vol while near it, you lose despite a "correct" forecast.
3. **The dollar-gamma $\tfrac12\Gamma S^2$** is the right unit for risk limits, not
   raw gamma.

**Discrete hedging error.** Hedging $n$ times over $[0,T]$ rather than continuously
adds a mean-zero error with

$$\mathrm{Std}(\text{hedge error}) \approx \sqrt{\frac{\pi}{4n}}\;\big|\mathcal V\big|\sigma
\quad\Longrightarrow\quad \text{error} \sim n^{-1/2}$$

Halving the error costs 4× the hedges. Against linear transaction costs $\propto n$,
the optimal rehedge frequency trades off $n^{-1/2}$ against $n$; the Leland
adjustment absorbs costs into an effective vol:

$$\hat\sigma^2 = \sigma^2\Big(1 + \sqrt{\tfrac2\pi}\,\frac{\kappa}{\sigma\sqrt{\delta t}}\Big)$$

with $\kappa$ the round-trip cost rate. Sell at $\hat\sigma$, buy at the analogous
$\sigma^2(1-\cdots)$ — this *is* the bid/ask on your vol.

---

## 2.5 Implied volatility and the smile

**Implied vol** $\sigma_{\text{imp}}$ solves $C_{BS}(S,K,\tau,r,\sigma_{\text{imp}}) = C_{\text{mkt}}$.
Unique because $\mathcal V>0$; Newton converges fast:

$$\sigma_{n+1} = \sigma_n - \frac{C_{BS}(\sigma_n) - C_{\text{mkt}}}{\mathcal V(\sigma_n)}$$

Seed with the Brenner–Subrahmanyam ATM estimate $\sigma_0\approx\sqrt{2\pi/\tau}\,C/S$.

**Total implied variance** $w(k,\tau) = \sigma^2_{\text{imp}}(k,\tau)\,\tau$ with log-moneyness
$k=\ln(K/F)$ is the right coordinate — it is what must be monotone in $\tau$ for
no calendar arbitrage.

### Breeden–Litzenberger — the market's probability density

$$\boxed{\;q(K) = e^{r\tau}\,\frac{\partial^2C}{\partial K^2}\Big|_{K}\;}$$

*Derivation.* $C = e^{-r\tau}\int_K^\infty(S-K)q(S)dS$. Differentiate once:
$\partial C/\partial K = -e^{-r\tau}\int_K^\infty q(S)dS$. Differentiate again:
$\partial^2C/\partial K^2 = e^{-r\tau}q(K)$. $\square$

The full risk-neutral density is *observable* from a strike continuum. This is the
single most underused object on an options desk.

### Dupire local volatility

The unique local vol $\sigma_{\text{loc}}(K,T)$ consistent with all quoted European prices:

$$\boxed{\;\sigma_{\text{loc}}^2(K,T) = \frac{\dfrac{\partial C}{\partial T} + (r-q)K\dfrac{\partial C}{\partial K} + qC}{\tfrac12K^2\dfrac{\partial^2C}{\partial K^2}}\;}$$

In implied-variance coordinates ($w = \sigma_{\text{imp}}^2\tau$, $k=\ln K/F$), numerically far
more stable:

$$\sigma^2_{\text{loc}} = \frac{\partial_\tau w}{1 - \frac{k}{w}\partial_kw + \frac14\big(-\frac14 - \frac1w + \frac{k^2}{w^2}\big)(\partial_kw)^2 + \frac12\partial_{kk}w}$$

**Warning.** Local vol fits today's surface perfectly and forecasts its dynamics
badly — it flattens the smile forward, so it systematically misprices forward-start
and cliquet products. Use it for vanilla-consistent exotics, not for vol dynamics.

### SVI — the industry-standard smile parameterization

$$w(k) = a + b\Big\{\rho(k-m) + \sqrt{(k-m)^2 + \varsigma^2}\Big\}$$

Five parameters per slice: level $a$, angle $b$, skew $\rho$, shift $m$, curvature $\varsigma$.
It is arbitrage-free under explicit conditions (Gatheral–Jacquier), reproduces the
correct large-$|k|$ linear wings (Roger Lee: $w\sim 2|k|$ at most), and fits equity
surfaces to within bid/ask.

**Lee's moment formula.** If $\mathbb E[S_T^{1+p}]<\infty$ for $p\le p^\star$, then

$$\limsup_{k\to\infty}\frac{\sigma^2_{\text{imp}}(k)\tau}{k} = \psi(p^\star) \le 2$$

Implied vol can grow at most like $\sqrt{2|k|/\tau}$. Any wing extrapolation
steeper than that is an arbitrage.

---

## 2.6 Stochastic volatility

### Heston

$$dS = \mu S\,dt + \sqrt{v}\,S\,dW^S,\qquad dv = \kappa(\bar v - v)dt + \xi\sqrt v\,dW^v,\qquad d\langle W^S,W^v\rangle = \rho\,dt$$

Feller condition $2\kappa\bar v \ge \xi^2$ keeps $v>0$.

**Why it's the default:** the characteristic function is closed-form,

$$\varphi(u) = \mathbb E^{\mathbb Q}[e^{iu\ln S_T}] = e^{C(u,\tau)\bar v\kappa/\xi^2 + D(u,\tau)v_0 + iu\ln(Se^{r\tau})}$$

with $C,D$ explicit (Riccati solutions), so prices come from a single Fourier
integral (Carr–Madan, FFT across all strikes at once):

$$C(K) = \frac{e^{-\alpha \ln K}}{\pi}\int_0^\infty e^{-iu\ln K}\,\frac{e^{-r\tau}\varphi(u-(\alpha+1)i)}{\alpha^2+\alpha-u^2+i(2\alpha+1)u}\,du$$

**Parameter → smile mapping (memorize this):**

| Parameter | Controls |
|---|---|
| $v_0$ | ATM level, short end |
| $\bar v$ | ATM level, long end |
| $\kappa$ | term structure speed (how fast ATM reverts to $\sqrt{\bar v}$) |
| $\rho$ | **skew** — $\rho<0$ ⟹ puts bid, equity-like |
| $\xi$ | **convexity / smile curvature** — wings |

### SABR — the rates/FX standard

$$dF = \alpha F^\beta dW^1,\qquad d\alpha = \nu\alpha\,dW^2,\qquad d\langle W^1,W^2\rangle = \rho\,dt$$

Hagan's asymptotic implied vol (the reason SABR won):

$$\sigma_{\text{imp}}(K,F) \approx \frac{\alpha}{(FK)^{(1-\beta)/2}\Big[1+\frac{(1-\beta)^2}{24}\ln^2\frac FK + \frac{(1-\beta)^4}{1920}\ln^4\frac FK\Big]}\cdot\frac{z}{\chi(z)}\cdot\big[1 + \Xi\,\tau\big]$$

$$z = \frac{\nu}{\alpha}(FK)^{(1-\beta)/2}\ln\frac FK,\qquad \chi(z)=\ln\!\left(\frac{\sqrt{1-2\rho z+z^2}+z-\rho}{1-\rho}\right)$$

$$\Xi = \frac{(1-\beta)^2\alpha^2}{24(FK)^{1-\beta}} + \frac{\rho\beta\nu\alpha}{4(FK)^{(1-\beta)/2}} + \frac{2-3\rho^2}{24}\nu^2$$

ATM simplification (what traders actually quote):
$\sigma_{\text{ATM}}\approx \alpha/F^{1-\beta}$, so $\alpha$ is pinned by the ATM vol, leaving
$\rho$ for skew and $\nu$ for smile. **Known failure:** negative densities at low
strikes for long expiries — use the arbitrage-free/shifted variants.

### Rough volatility

Empirically, log-vol behaves like fractional Brownian motion with Hurst $H\approx0.1$:

$$\ln\sigma_t \sim \text{fBm}(H),\qquad \mathbb E|\ln\sigma_{t+\Delta}-\ln\sigma_t|^q \propto \Delta^{qH}$$

The payoff: the ATM skew term structure

$$\psi(\tau) = \Big|\frac{\partial\sigma_{\text{imp}}}{\partial k}\Big|_{k=0} \propto \tau^{H-1/2}$$

matches the observed $\tau^{-0.4}$ power law, which no conventional (Markovian)
stochastic vol model reproduces — Heston gives $\psi(\tau)\to$ const as $\tau\to0$.

---

## 2.7 Variance swaps — model-free replication

A variance swap pays $N_{\text{var}}(\sigma^2_{\text{realized}} - K_{\text{var}})$. The fair strike is
**model-free**:

$$\boxed{\;K_{\text{var}} = \frac{2e^{r\tau}}{\tau}\left[\int_0^{F}\frac{P(K)}{K^2}dK + \int_{F}^\infty\frac{C(K)}{K^2}dK\right]\;}$$

**Derivation.** By Itô, $d\ln S = \frac{dS}{S} - \frac12\sigma_t^2dt$, so

$$\int_0^\tau\sigma_t^2\,dt = 2\int_0^\tau\frac{dS_t}{S_t} - 2\ln\frac{S_\tau}{S_0}$$

The first term is a continuously rebalanced position holding \$1 of stock (zero
cost under $\mathbb Q$, expectation $r\tau$). The second is a **log contract**, and the
Carr–Madan static replication identity

$$f(S_\tau) = f(F) + f'(F)(S_\tau-F) + \int_0^F f''(K)P(K)dK + \int_F^\infty f''(K)C(K)dK$$

with $f = -2\ln(\cdot)$, $f'' = 2/K^2$, gives the result. $\square$

**This is why the VIX is what it is** — VIX$^2$ is precisely this integral on SPX,
discretized:

$$\text{VIX}^2 = \frac{2}{\tau}\sum_i\frac{\Delta K_i}{K_i^2}e^{r\tau}Q(K_i) - \frac1\tau\Big(\frac{F}{K_0}-1\Big)^2$$

**Caveats.** The replication assumes continuity; jumps introduce a third-moment
error term $\approx -\frac{2}{3}\mathbb E[\sum(\Delta\ln S)^3]$. Volatility swaps
(payoff linear in $\sigma$, not $\sigma^2$) are *not* model-free — by Jensen,
$K_{\text{vol}} < \sqrt{K_{\text{var}}}$, and the gap is the **convexity adjustment**
$\approx -\frac{\mathrm{Var}(\sigma)}{8\,\mathbb E[\sigma]^{3}}\cdot$const.

---

## 2.8 American options and optimal stopping

$$V(S,t) = \sup_{\tau\in[t,T]}\mathbb E^{\mathbb Q}\big[e^{-r(\tau-t)}\Psi(S_\tau)\big]$$

Equivalently, a **linear complementarity problem**: everywhere,

$$\min\Big\{-\big(V_t + \mathcal L V - rV\big),\ V - \Psi\Big\} = 0$$

- In the continuation region, the BS PDE holds with equality and $V>\Psi$.
- In the exercise region, $V=\Psi$ and the PDE becomes an inequality.

**Smooth pasting** at the free boundary $S^\star(t)$:

$$V(S^\star,t) = \Psi(S^\star),\qquad \frac{\partial V}{\partial S}(S^\star,t) = \Psi'(S^\star)$$

**Practical facts.**
- An American call on a **non-dividend** stock is never exercised early ⟹ equals the
  European. (Proof: $C \ge S - Ke^{-r\tau} > S-K$.)
- Early exercise of a call is optimal only just before a dividend, and only if
  $D > K(1-e^{-r\Delta})$.
- American puts always carry early-exercise premium (the money has time value).
- **Longstaff–Schwartz**: regress the discounted continuation value on basis
  functions of $S_t$ over in-the-money paths, exercise when $\Psi(S_t)$ exceeds the
  fitted continuation. This is the only practical method above ~3 factors.

---

## 2.9 Interest rates

**Short-rate models:**

| Model | SDE | Property |
|---|---|---|
| Vasicek | $dr=\kappa(\bar r-r)dt+\sigma dW$ | Gaussian, closed-form, allows $r<0$ |
| CIR | $dr=\kappa(\bar r-r)dt+\sigma\sqrt r\,dW$ | $r\ge0$, non-central $\chi^2$ |
| Hull–White | $dr=(\theta(t)-\kappa r)dt+\sigma dW$ | fits the initial curve exactly |

**Vasicek bond price** (Feynman–Kac on $P=\mathbb E^{\mathbb Q}[e^{-\int r}]$; affine ansatz $P=e^{A-Br}$):

$$P(t,T) = A(t,T)e^{-B(t,T)r_t},\qquad B = \frac{1-e^{-\kappa(T-t)}}{\kappa}$$
$$\ln A = \frac{(B-(T-t))(\kappa^2\bar r - \sigma^2/2)}{\kappa^2} - \frac{\sigma^2B^2}{4\kappa}$$

**HJM no-arbitrage drift condition.** If $df(t,T) = \alpha(t,T)dt + \sigma_f(t,T)dW$,
then under $\mathbb Q$ the drift is *not free*:

$$\boxed{\;\alpha(t,T) = \sigma_f(t,T)\int_t^T\sigma_f(t,u)\,du\;}$$

The entire forward curve's drift is determined by its volatility structure. This is
the rates analogue of "$\mu$ drops out."

**Convexity adjustment** (futures vs forwards): a futures rate exceeds the forward
rate because of daily margining,

$$f_{\text{fut}} - f_{\text{fwd}} \approx \sigma^2 t T \quad\text{(Gaussian, first order)}$$

---

## 2.10 Credit

**Merton structural model.** Equity is a call on firm assets $V$ struck at debt face $D$:

$$E = V\Phi(d_1) - De^{-rT}\Phi(d_2),\qquad d_1 = \frac{\ln(V/D)+(r+\sigma_V^2/2)T}{\sigma_V\sqrt T}$$

Risk-neutral default probability $= \Phi(-d_2)$. **Distance to default:**

$$\mathrm{DD} = \frac{\ln(V/D) + (\mu_V - \sigma_V^2/2)T}{\sigma_V\sqrt T}$$

The unobservable $(V,\sigma_V)$ are backed out from observable $(E,\sigma_E)$ using the
second equation $\sigma_E E = \Phi(d_1)\sigma_V V$ (from Itô on $E(V)$).

**Reduced-form / intensity.** Default at the first jump of a Cox process with
intensity $h_t$:

$$\mathbb Q(\tau>T) = \mathbb E\Big[e^{-\int_0^T h_s ds}\Big]$$

**The credit triangle** — the approximation every credit trader uses:

$$\boxed{\;s \approx h\,(1-R)\;}$$

Spread ≈ hazard rate × loss given default. At $R=40\%$, a 300bp spread implies a
5% annual default probability.

**CDS par spread** (piecewise-flat hazard, $Z$ = discount factor):

$$s = \frac{(1-R)\int_0^T Z(t)\,(-dQ(t))}{\int_0^T Z(t)Q(t)\,dt}$$

---

## 2.11 The pricing hierarchy — what to reach for

| Situation | Tool |
|---|---|
| Vanilla European, liquid | BS with the market's implied vol (a quoting convention, not a model) |
| Full surface, vanilla-consistent exotic | Dupire local vol |
| Forward vol / cliquet / vol-of-vol sensitive | Heston, or LSV (local-stochastic) |
| Short-dated skew term structure | Rough vol |
| Rates/FX smile | SABR |
| Anything path-dependent, >3 factors | Monte Carlo + Longstaff–Schwartz |
| Barrier/American, ≤2 factors | PDE finite difference (Crank–Nicolson + Rannacher startup) |

---

**Next:** [03 — Volatility Modelling & Estimation](03-volatility-models.md)
