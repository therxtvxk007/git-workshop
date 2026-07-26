# 06 — Market Microstructure

Where does the spread come from, and what does order flow actually do to price?
These models are the theoretical backbone of every HFT strategy.

---

## 6.1 The three components of the spread

$$\text{Spread} = \underbrace{\text{order processing}}_{\text{fixed costs, fees}} + \underbrace{\text{inventory}}_{\text{risk of holding}} + \underbrace{\text{adverse selection}}_{\text{trading against information}}$$

Only the third is interesting, and in modern electronic markets it dominates. The
first two are competed to near zero; the third cannot be, because it is a transfer
from uninformed to informed traders that market makers must price.

---

## 6.2 Roll's model — the spread from prices alone

**Setup.** Efficient price is a random walk $m_t = m_{t-1} + u_t$, $u_t$ i.i.d. Trades
occur at $m_t \pm c$ where $c = \text{spread}/2$, with direction $q_t=\pm1$ i.i.d.,
independent of $u$:

$$p_t = m_t + c\,q_t$$

**Derivation.** Price changes:

$$\Delta p_t = u_t + c(q_t - q_{t-1})$$

Autocovariance at lag 1 (all cross terms vanish by independence):

$$\mathrm{Cov}(\Delta p_t,\Delta p_{t-1}) = c^2\,\mathbb E[(q_t-q_{t-1})(q_{t-1}-q_{t-2})] = -c^2\mathbb E[q_{t-1}^2] = -c^2$$

$$\boxed{\;\text{Spread} = 2c = 2\sqrt{-\mathrm{Cov}(\Delta p_t,\Delta p_{t-1})}\;}$$

**Estimate the spread from trade prices alone — no quote data required.** That was
revolutionary in 1984 and remains the standard fallback for illiquid or historical
markets.

**Also:** $\mathrm{Var}(\Delta p) = \sigma_u^2 + 2c^2$. The **bid-ask bounce inflates measured
volatility** — this is exactly the microstructure noise of §03.3, and it's why naive
RV explodes at high frequency. The noise term $2c^2$ per observation times $n$
observations gives the divergence.

**Failure mode:** when the covariance is positive (trending order flow, which is
common), the estimator returns an imaginary number. Real order flow is strongly
autocorrelated (§6.6), violating the i.i.d.-$q$ assumption. Roll's estimator
therefore *underestimates* the spread in practice, and Hasbrouck's Bayesian
Gibbs-sampler version is the modern fix.

---

## 6.3 Glosten–Milgrom — the spread from asymmetric information

**Setup.** Asset worth $V\in\{V_H, V_L\}$, equal prior. A fraction $\alpha$ of traders
are **informed** (know $V$, always trade the profitable direction); $1-\alpha$ are
**noise** traders (buy or sell 50/50). The market maker is competitive (zero expected
profit) and sets quotes equal to conditional expectations.

**Derivation.** Conditional buy probabilities:

$$\mathbb P(\text{buy}\mid V_H) = \alpha + \frac{1-\alpha}{2} = \frac{1+\alpha}{2},\qquad
\mathbb P(\text{buy}\mid V_L) = \frac{1-\alpha}{2}$$

By Bayes with a uniform prior, the ask is $\mathbb E[V\mid\text{buy}]$:

$$A = \frac{\tfrac12\cdot\tfrac{1+\alpha}{2}V_H + \tfrac12\cdot\tfrac{1-\alpha}{2}V_L}{\tfrac12\cdot\tfrac{1+\alpha}{2} + \tfrac12\cdot\tfrac{1-\alpha}{2}} = \frac{1+\alpha}{2}V_H + \frac{1-\alpha}{2}V_L$$

Symmetrically $B = \frac{1-\alpha}{2}V_H + \frac{1+\alpha}{2}V_L$. Therefore

$$\boxed{\;S = A - B = \alpha\,(V_H - V_L)\;}$$

**The spread is exactly the probability of informed trading times the magnitude of
private information.** With $\alpha=0$ the spread is zero: a market maker facing only
noise traders quotes at the midpoint and makes nothing — and needs nothing.

**Consequences that shape real trading:**

1. **Prices are a martingale.** $\mathbb E[V\mid\mathcal F_t]$ updates on each trade; quotes
   are unbiased. Market making is not a bet on direction.
2. **Every trade moves the quote.** After a buy at $A$, the new mid rises. This is
   *permanent* impact — information, not liquidity.
3. **Market breakdown.** If $\alpha$ is high enough (or $V_H-V_L$ large enough relative
   to noise volume), the spread exceeds what noise traders will pay and the market
   closes. This is the microstructural description of a flash crash and of the
   halt-worthy moments around scheduled news.
4. **Learning.** With repeated trades the market maker's posterior converges to $V$;
   the informed trader's advantage decays. The **speed** of that decay is the half-life
   of your alpha.

**PIN (probability of informed trading).** The empirical implementation. With
informed arrival $\mu$ (on news days, probability $\alpha_{\text{news}}$), uninformed buy/sell
rates $\epsilon_b,\epsilon_s$:

$$\mathrm{PIN} = \frac{\alpha_{\text{news}}\mu}{\alpha_{\text{news}}\mu + \epsilon_b + \epsilon_s}$$

estimated by MLE on daily buy/sell counts via a Poisson mixture likelihood.
Typical values: 0.10–0.20 for large caps, 0.30+ for small caps.

---

## 6.4 Kyle's model — the price of information

The single most important microstructure model. It gives the **linear price impact
coefficient** $\lambda$ that appears in every execution algorithm.

**Setup (one period).**
- Asset value $v\sim\mathcal N(p_0,\Sigma_0)$, known to a single risk-neutral **insider**.
- Noise traders submit $u\sim\mathcal N(0,\sigma_u^2)$, independent of $v$.
- Insider submits $x$; total order flow $y = x+u$.
- Market maker observes only $y$ and sets a competitive (zero-profit) price $p=p(y)$.

**Look for a linear equilibrium:** $x = \beta(v-p_0)$ and $p = p_0 + \lambda y$.

**Step 1 — insider's optimization.** Given the MM's rule,

$$\pi = \mathbb E\big[(v-p)x\big] = \mathbb E\big[(v - p_0 - \lambda(x+u))x\big] = (v-p_0)x - \lambda x^2$$

(using $\mathbb E[u]=0$). FOC: $(v-p_0) - 2\lambda x = 0$, so

$$x = \frac{v-p_0}{2\lambda}\quad\Longrightarrow\quad \beta = \frac{1}{2\lambda}$$

Second-order condition requires $\lambda>0$. Note the insider trades **only half** of
what would equate price to value — deliberately holding back to avoid moving the price.

**Step 2 — market maker's efficiency.** $p = \mathbb E[v\mid y]$. Since $(v,y)$ are jointly
Gaussian with $\mathrm{Cov}(v,y)=\beta\Sigma_0$ and $\mathrm{Var}(y)=\beta^2\Sigma_0+\sigma_u^2$:

$$\lambda = \frac{\mathrm{Cov}(v,y)}{\mathrm{Var}(y)} = \frac{\beta\Sigma_0}{\beta^2\Sigma_0+\sigma_u^2}$$

**Step 3 — solve the fixed point.** Substitute $\beta = 1/(2\lambda)$:

$$\lambda = \frac{\frac{1}{2\lambda}\Sigma_0}{\frac{1}{4\lambda^2}\Sigma_0 + \sigma_u^2}
\ \Longrightarrow\ \lambda\Big(\frac{\Sigma_0}{4\lambda^2}+\sigma_u^2\Big) = \frac{\Sigma_0}{2\lambda}
\ \Longrightarrow\ \frac{\Sigma_0}{4\lambda} + \lambda\sigma_u^2 = \frac{\Sigma_0}{2\lambda}$$

$$\lambda\sigma_u^2 = \frac{\Sigma_0}{4\lambda}\ \Longrightarrow\ \lambda^2 = \frac{\Sigma_0}{4\sigma_u^2}$$

$$\boxed{\;\lambda = \frac{1}{2}\sqrt{\frac{\Sigma_0}{\sigma_u^2}} = \frac{\sigma_v}{2\sigma_u},\qquad \beta = \frac{\sigma_u}{\sigma_v}\;}$$

**Reading the result.**

- **Market depth is $1/\lambda = 2\sigma_u/\sigma_v$.** Depth is proportional to noise-trader
  volume and inversely proportional to fundamental uncertainty. Liquidity is
  *provided* by uninformed volume and *consumed* by information.
- **The insider's expected profit** is $\mathbb E[\pi] = \frac{\Sigma_0}{4\lambda} = \frac{\sigma_v\sigma_u}{2}$.
  Half of the information value; the other half is lost to the price impact of
  trading on it.
- **Post-trade variance** $\mathrm{Var}(v\mid y) = \Sigma_0/2$: exactly **half** the private
  information is impounded into price in one round. In the $N$-period version,
  $\Sigma_n = \Sigma_0\frac{N-n}{N}$ — information is revealed **linearly in time**,
  and the insider trades at a constant rate. That's the theoretical justification
  for TWAP.
- **Continuous-time limit:** $\lambda$ is constant over the trading day, and the
  insider's optimal strategy is $dx_t = \beta_t(v-p_t)dt$ — trade proportionally to
  the remaining mispricing.

**The empirical form used everywhere:**

$$\Delta p = \lambda\,Q \quad\text{with}\quad \lambda \approx \frac{c\,\sigma}{\mathrm{ADV}}$$

Estimate by regressing 5-minute midprice changes on signed volume. **Typical values:**
a large-cap US equity moves ~1 bp per \$1M of net signed flow; a small cap, 20–50 bp.
This single number determines your strategy's capacity (§10.6).

---

## 6.5 Amihud illiquidity and empirical impact measures

$$\boxed{\;\mathrm{ILLIQ}_i = \frac1{D_i}\sum_{d=1}^{D_i}\frac{|r_{i,d}|}{\mathrm{Vol}_{i,d}}\;}$$

Average absolute return per dollar of volume — a crude but extremely robust proxy
for Kyle's $\lambda$, computable from daily data on any market back to the 1960s.
Priced in the cross-section (illiquid stocks earn a premium).

**Effective vs quoted vs realized spread.** The decomposition every execution
analyst needs, with $q=+1$ for buys, $-1$ for sells:

| Measure | Formula | Meaning |
|---|---|---|
| Quoted spread | $A_t - B_t$ | what's advertised |
| Effective spread | $2q\,(p_t - m_t)$ | what you actually paid |
| Realized spread | $2q\,(p_t - m_{t+\Delta})$ | what the maker **kept** |
| Price impact | $2q\,(m_{t+\Delta} - m_t)$ | what the taker **moved** |

**The identity:**

$$\boxed{\;\text{Effective spread} = \text{Realized spread} + \text{Price impact}\;}$$

This is the fundamental accounting of market making. The maker earns the effective
spread on the fill and immediately gives back the price impact through adverse
selection. **Realized spread is the market maker's actual gross P&L per share.**

In liquid US equities at $\Delta=5$min: effective ≈ 1.5 bp, price impact ≈ 1.0 bp,
realized ≈ 0.5 bp. Market makers keep about a third of the quoted spread — and
that third pays for technology, fees, and inventory risk.

**Choice of $\Delta$ matters enormously.** At $\Delta=1$s, realized spread looks
great; at $\Delta=5$min it's much thinner; at $\Delta=1$day it can be negative. The
horizon at which realized spread goes to zero is the horizon over which your
counterparty's information plays out. See markouts, §11.5.

---

## 6.6 Order flow autocorrelation and the propagator model

**The stylized fact.** Trade signs are *long-memory* autocorrelated:

$$\mathrm{Corr}(\epsilon_t,\epsilon_{t+\ell}) \sim \ell^{-\gamma},\qquad \gamma\approx0.5$$

Positive out to thousands of trades. Cause: **order splitting** — large parent
orders are worked over hours, so consecutive child orders share a sign.

**The paradox.** If order flow is predictable and each trade moves price permanently
by $\lambda$, prices would be trivially predictable. They are not. Something must
cancel.

**Resolution — the propagator model (Bouchaud et al.).** Impact is transient:

$$\boxed{\;p_t = \sum_{s<t} G(t-s)\,\epsilon_s\,f(v_s) + \text{noise}\;}$$

with $G$ a **decaying** impact kernel and $f(v)\approx v^{0.2}$ (weakly concave in size).

**The no-arbitrage condition** forces the decay exponent to match the flow
autocorrelation. For price diffusivity (variance linear in time) one needs

$$G(\ell) \sim \ell^{-\beta}\quad\text{with}\quad \boxed{\;\beta \approx \frac{1-\gamma}{2}\;}$$

At $\gamma=0.5$: $\beta\approx0.25$. **Impact decays as a slow power law, precisely
tuned so that predictable order flow produces unpredictable prices.**

**Why this matters operationally:**
- Impact is **not** permanent. If you split an order, a large fraction of the
  temporary impact decays back — this is why patient execution is cheaper than the
  naive $\lambda Q$ suggests.
- But it decays **slowly** (power law, not exponential). Your impact from this
  morning is still partly in the price this afternoon.
- Naive backtests that assume a fixed slippage per trade get this doubly wrong:
  they overcharge for splitting and undercharge for persistence.

---

## 6.7 The square-root law of market impact

The most robust empirical regularity in all of trading. Across equities, futures,
FX, crypto, decades, and venues:

$$\boxed{\;\frac{\Delta P}{\sigma_{\text{daily}}} = Y\left(\frac{Q}{V_{\text{daily}}}\right)^{\delta},\qquad \delta\approx0.5,\ Y\approx0.5\text{–}1\;}$$

$Q$ = order size, $V$ = daily volume, $\sigma$ = daily volatility.

**Read it as:** trading 1% of ADV costs about $0.1\sigma_{\text{daily}}$; trading 10% of
ADV costs about $0.3\sigma_{\text{daily}}$. At $\sigma_{\text{daily}}=2\%$, a 10%-of-ADV order
costs ~60 bp. **This is usually larger than the entire alpha of a medium-frequency
signal**, and it is why capacity, not accuracy, limits most strategies.

**Why square root? Three arguments, none conclusive, all illuminating.**

1. **Latent liquidity / locally linear order book.** If the latent supply-demand
   curve vanishes linearly near the current price ($\rho(x)\propto x$), then
   consuming volume $Q = \int_0^{\Delta P}\rho\,dx \propto \Delta P^2$, hence
   $\Delta P\propto\sqrt Q$. (Tóth et al.'s "locally linear latent order book.")

2. **Fair pricing / martingale argument (Farmer–Gerig–Lillo–Waelbroeck).** A
   metaorder's impact must equal the market's conditional expectation of the
   information it reveals; combining the power-law distribution of metaorder sizes
   with martingale consistency yields $\delta = 1/2$.

3. **Dimensional / propagator consistency.** Integrating the propagator kernel
   $G(\ell)\sim\ell^{-1/4}$ over an autocorrelated flow of length $N$ gives
   $\Delta P\sim N^{1-\beta-\gamma/\ldots}$ — with the empirical exponents this lands near $\sqrt N$.

**Crucially: impact is concave, not linear.** Kyle's linear $\lambda$ applies to
*aggregate order flow imbalance over a fixed interval*; the square root applies to
a *single metaorder*. These are different objects and are frequently confused.

**Post-trade decay.** After the metaorder completes, impact relaxes to a permanent
level:

$$\Delta P_{\text{permanent}} \approx \frac23\,\Delta P_{\text{peak}}$$

(the "2/3 rule," empirically robust). So roughly one-third of your impact is
temporary and comes back — but only if you stop trading.

---

## 6.8 Order flow imbalance — the strongest short-horizon predictor

Cont–Kukanov–Stoikov. Define, over each event, the change in depth at the best quotes:

$$e_n = \underbrace{\mathbf 1_{P^b_n\ge P^b_{n-1}}q^b_n - \mathbf 1_{P^b_n\le P^b_{n-1}}q^b_{n-1}}_{\text{bid side}} - \underbrace{\big(\mathbf 1_{P^a_n\le P^a_{n-1}}q^a_n - \mathbf 1_{P^a_n\ge P^a_{n-1}}q^a_{n-1}\big)}_{\text{ask side}}$$

$$\mathrm{OFI}_t = \sum_{n\in\text{interval }t} e_n$$

**The regression:**

$$\boxed{\;\Delta m_t = \beta\,\mathrm{OFI}_t + \varepsilon_t,\qquad \beta \approx \frac{c}{\text{depth}}\;}$$

$R^2$ of **0.65–0.85** at 10-second horizons in liquid US equities. Nothing else in
finance predicts anything that well. Two caveats: (i) it is contemporaneous, not
predictive, unless you can observe OFI faster than the price updates — which is
exactly what the latency race is about; (ii) $\beta$ scales inversely with depth,
so it must be renormalized continuously.

**The simpler cousin — queue imbalance:**

$$I = \frac{Q_b - Q_a}{Q_b + Q_a}\ \in[-1,1]$$

$$\mathbb P(\text{next mid tick up}) \approx \frac{1+I}{2}\quad\text{(approximately, empirically)}$$

**The microprice** — the imbalance-weighted fair value:

$$\boxed{\;P_{\text{micro}} = \frac{Q_b\,P_a + Q_a\,P_b}{Q_a+Q_b} = m + \frac{S}{2}\,I\;}$$

Note the weights are **crossed**: a large bid queue pulls the fair price toward the
*ask*. Intuition: a thick bid means it's hard to get filled buying passively and the
next trade is more likely to lift the offer.

The microprice materially outperforms the mid as a short-horizon predictor and as
a mark for inventory. Stoikov's refinement iterates the conditional expectation to
a fixed point, since imbalance itself is autocorrelated:

$$P^\star = \lim_{n\to\infty}\mathbb E\big[m_{\tau_n}\mid I_t, S_t\big]$$

giving a non-linear (typically S-shaped) map from imbalance to fair value rather
than the linear one above.

---

## 6.9 Hasbrouck's VAR and information share

**Trade-price VAR.** Model quote revisions and trades jointly:

$$r_t = \sum_{i=1}^{p} a_i r_{t-i} + \sum_{i=0}^{p} b_i x_{t-i} + \varepsilon_{1,t}$$
$$x_t = \sum_{i=1}^{p} c_i r_{t-i} + \sum_{i=1}^{p} d_i x_{t-i} + \varepsilon_{2,t}$$

with $x_t$ signed trade flow. The **long-run impact of a trade innovation** is the
cumulative impulse response:

$$\text{Information content of a trade} = \Big(\sum_{i} \psi_i\Big)\cdot\varepsilon_{2,t}$$

This separates the **permanent** (information) from the **transient** (inventory,
liquidity) component of a trade's effect — the empirical version of the Kyle/Roll
decomposition.

**Information share (price discovery across venues).** With $n$ cointegrated price
series for the same asset, the common efficient price has innovation variance
$\psi\Omega\psi'$. Venue $j$'s share is

$$\mathrm{IS}_j = \frac{\big([\psi F]_j\big)^2}{\psi\Omega\psi'}$$

with $F$ the Cholesky factor of $\Omega$. Order-dependent when venues are correlated,
so report upper and lower bounds over orderings, or use Gonzalo–Granger component
shares instead.

**Practical answer for US equities:** the ES future and SPY lead the cash market;
within equities, price discovery concentrates on the primary listing venue at the
open and disperses intraday.

---

## 6.10 Tick size, queue value, and the make-take spread

**The tick constraint.** When the spread is one tick, price cannot express the
equilibrium spread. The excess rent shows up as **queue value** instead.

Let $S$ = one tick, and let $\pi$ be the maker's expected profit per filled share.
When $S > S^{\text{equilibrium}}$, competition moves from *price* to *time priority*:
makers queue up, and the marginal maker is indifferent, i.e. the expected value of
a queue position at the back is zero.

**Queue position value.** With queue length $Q$ ahead of you, fill probability
$P_{\text{fill}}(Q)$, and adverse selection cost $A$ per fill:

$$V(\text{position}) = P_{\text{fill}}(Q)\cdot\Big(\frac S2 + \text{rebate} - A\Big) - \big(1-P_{\text{fill}}(Q)\big)\cdot C_{\text{adverse move}}$$

**This is why queue position is worth real money in tick-constrained names** (see
§11.2) and worth nothing in names where the spread is many ticks wide.

**Maker-taker economics.** With a maker rebate $r_m$ and taker fee $f_t$:

$$\text{Maker net} = \frac S2 + r_m - A,\qquad \text{Taker net} = -\frac S2 - f_t$$

The exchange's net take is $f_t - r_m$. In a tick-constrained name, competition
drives $\frac S2 + r_m - A \to 0$, so **the rebate is fully capitalized into
adverse selection**: makers accept worse fills to capture the rebate. This is a
real, measurable effect and the reason rebate structure changes alter queue
dynamics within hours.

---

## 6.11 Summary table

| Model | Gives you | Key equation |
|---|---|---|
| Roll | Spread from prices only | $S = 2\sqrt{-\mathrm{Cov}(\Delta p_t,\Delta p_{t-1})}$ |
| Glosten–Milgrom | Spread from information | $S = \alpha(V_H-V_L)$ |
| Kyle | Linear impact coefficient | $\lambda = \sigma_v/(2\sigma_u)$ |
| Amihud | Empirical illiquidity | $|r|/\mathrm{Vol}$ |
| Propagator | Transient impact | $p_t=\sum G(t-s)\epsilon_s$, $G\sim\ell^{-1/4}$ |
| Square-root law | Metaorder cost | $\Delta P/\sigma = Y\sqrt{Q/V}$ |
| OFI | Short-horizon price change | $\Delta m = \beta\,\mathrm{OFI}$, $R^2\sim0.7$ |
| Microprice | Fair value given the book | $(Q_bP_a+Q_aP_b)/(Q_a+Q_b)$ |
| Hasbrouck | Permanent vs transient | VAR impulse response |

**The through-line.** Spread compensates for adverse selection; impact is the price
of revealing information; both are concave in size and decay in time. Every
execution and market-making equation in the next two chapters is an optimization
against these three facts.

---

**Next:** [07 — Optimal Execution](07-optimal-execution.md)
