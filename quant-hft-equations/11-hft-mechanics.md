# 11 — HFT Mechanics

Queues, latency, adverse selection, markouts. At this timescale the abstractions of
the previous chapters give way to the actual mechanics of a matching engine.

---

## 11.1 The limit order book as a queueing system

**State.** For each price level $p$, a FIFO queue of resting quantity $Q_p$, evolving
under three event types:

| Event | Rate | Effect on $Q_p$ |
|---|---|---|
| Limit order arrival | $\lambda(p)$ | $+q$, joins the back |
| Cancellation | $\theta(p)\cdot Q_p$ | $-q$, from a random position |
| Market order | $\mu$ | $-q$, from the **front** |

**Cont–Stoikov–Talreja model.** Treat the best bid/ask queues as birth-death
processes. For the best bid with net arrival rate $\lambda$ and departure rate
$\mu + \theta Q$:

$$\frac{dQ_t}{dt}\Big|_{\text{drift}} = \lambda - \mu - \theta Q_t$$

Stationary queue length $\bar Q = (\lambda-\mu)/\theta$.

**The key computable quantity — probability of a mid-price increase.** Starting from
bid queue $Q_b$ and ask queue $Q_a$, the ask depletes before the bid with
probability (for the symmetric random-walk approximation):

$$\boxed{\;\mathbb P(\text{mid up}) \approx \frac{Q_b}{Q_a+Q_b} = \frac{1+I}{2},\qquad I = \frac{Q_b-Q_a}{Q_b+Q_a}\;}$$

Exact expressions come from a Laplace-transform / first-passage analysis; the linear
approximation above is remarkably accurate for balanced books and is the theoretical
basis of the microprice (§06.8).

**Empirically the relationship is S-shaped**, not linear: extreme imbalance predicts
less strongly than linear extrapolation suggests, because extreme imbalance is
itself often stale or spoofed. Fit the map non-parametrically.

**Hawkes processes** capture the clustering that Poisson models miss:

$$\lambda(t) = \mu_0 + \sum_{t_i<t}\alpha\,e^{-\beta(t-t_i)}$$

with **branching ratio** $n = \alpha/\beta$ = expected offspring events per event.
Stationary intensity:

$$\bar\lambda = \frac{\mu_0}{1-n},\qquad \text{requires } n<1$$

**Empirically $n\approx 0.7$–$0.9$ in modern equity and futures markets** — meaning
70–90% of all order flow is *reactive* to other order flow rather than exogenous.
As $n\to1$ the market becomes critically reflexive and small shocks produce
arbitrarily large cascades. That is the mechanism of a flash crash, stated as a
number you can monitor in real time.

**Multivariate Hawkes** for the four event types (buy/sell market orders, limit
orders, cancels) with kernel matrix $\alpha_{ij}$ gives the cross-excitation
structure: $\alpha_{\text{MO}\to\text{cancel}}$ large is exactly the "liquidity
evaporates when it's needed" effect.

---

## 11.2 Queue position and fill probability

In a tick-constrained market this is the whole game.

**Setup.** You join a queue at position $Q_0$ (shares ahead of you). Two competing
processes:
- **Market orders** consume from the front at rate $\mu$.
- **Cancellations** ahead of you remove shares at rate $\theta$ per share.

**Your queue position evolves as:**

$$dQ_t = -\big(\mu + \theta Q_t\big)dt + \text{noise}$$

**Deterministic approximation:**

$$Q(t) = \Big(Q_0 + \frac{\mu}{\theta}\Big)e^{-\theta t} - \frac{\mu}{\theta}$$

**Expected time to reach the front** ($Q=0$):

$$\boxed{\;T_{\text{fill}} = \frac{1}{\theta}\ln\Big(1 + \frac{\theta Q_0}{\mu}\Big)\;}$$

**Fill probability before the price moves away.** Let the level's lifetime be
exponential with rate $\nu$ (the rate at which the book moves through your price).
Then

$$\boxed{\;P_{\text{fill}}(Q_0) = \mathbb P\big(T_{\text{fill}} < \tau_{\text{move}}\big) = \Big(1+\frac{\theta Q_0}{\mu}\Big)^{-\nu/\theta}\;}$$

**Power-law decay in queue position.** Not exponential — the tail is heavy, so being
deep in the queue is less catastrophic than a naive model suggests, but the front is
worth a lot.

**The value of queue position.** With $V_{\text{fill}}$ the net edge per fill:

$$V(Q_0) = P_{\text{fill}}(Q_0)\cdot V_{\text{fill}} - \big(1-P_{\text{fill}}(Q_0)\big)\cdot C_{\text{opportunity}}$$

**The critical asymmetry — adverse selection increases with queue depth.** Conditional
on filling from deep in the queue, the level was *swept*, which means the price is
moving through you:

$$\mathbb E\big[\text{markout}\mid\text{fill},\ Q_0 \text{ large}\big] \ \ll\ \mathbb E\big[\text{markout}\mid\text{fill},\ Q_0 \approx 0\big]$$

So $V_{\text{fill}}$ itself declines in $Q_0$, compounding the $P_{\text{fill}}$ decline.
**Being at the front of the queue is worth several times more than being in the
middle** — not twice, several times. This is the entire economic justification for
latency investment in tick-constrained names.

**Queue value in dollars.** Rough calibration for a liquid US equity: front-of-queue
fills might earn 0.4 of the half-spread net of adverse selection; back-of-queue fills
might earn 0.05 or go negative. On a \$0.01 spread with 500k shares/day of
opportunity, that difference is meaningful money — and it is bought entirely with
latency and with cancel/replace discipline.

**The queue-position estimation problem.** You cannot observe your position directly
from market data; you must infer it:

$$\hat Q_t = Q_{\text{joined}} - (\text{trades at this level since join}) - \widehat{(\text{cancels ahead})}$$

Cancels are the hard part: a cancel at your level might be ahead of or behind you.
Under the assumption that cancels are uniform across the queue,

$$\mathbb E[\text{cancels ahead}] = \text{total cancels}\times\frac{\hat Q_t}{Q_t^{\text{total}}}$$

Better: models where cancel probability decreases with queue age (front-of-queue
orders are more committed), which empirically fits better and gives a less
pessimistic $\hat Q$.

---

## 11.3 Latency

**The latency chain:**

$$L_{\text{total}} = \underbrace{L_{\text{market data}}}_{\text{exchange}\to\text{you}} + \underbrace{L_{\text{decision}}}_{\text{your stack}} + \underbrace{L_{\text{order}}}_{\text{you}\to\text{matching engine}} + \underbrace{L_{\text{queue}}}_{\text{gateway}\to\text{book}}$$

**Order-of-magnitude budget (2020s equities/futures):**

| Component | Time |
|---|---|
| Speed of light, 1 km fiber | 5 µs (fiber is ~2/3 c) |
| Microwave, same distance | 3.3 µs |
| Chicago ↔ NY, fiber | ~6.5 ms round trip |
| Chicago ↔ NY, microwave | ~4.0 ms round trip |
| Colocated cross-connect | 1–5 µs |
| NIC + kernel bypass | 1–2 µs |
| FPGA tick-to-trade | 20–100 ns |
| Software (optimized C++) tick-to-trade | 500 ns – 5 µs |
| Exchange matching engine | 10–100 µs |

**The value of latency — the race model.** Suppose $N$ participants race to a stale
quote, and only the fastest wins. If latencies are i.i.d. from distribution $F$,
your win probability at latency $\ell$ is

$$P_{\text{win}}(\ell) = \big(1 - F(\ell)\big)^{N-1}$$

**Marginal value of a latency reduction:**

$$\frac{\partial P_{\text{win}}}{\partial \ell} = -(N-1)\big(1-F(\ell)\big)^{N-2}f(\ell)$$

**The crucial property:** the value of speed is largest where the latency
distribution is *dense*. If you are far behind the pack, marginal improvements are
worthless; if you are near the front, they are enormously valuable. **The returns
to latency investment are convex near the frontier and near-zero away from it** —
which is exactly why the arms race has a winner-take-most structure and why
mid-tier speed is the worst place to be.

**Budish–Cramton–Shim: the latency arbitrage tax.** In a continuous limit order
book, a stale quote is a free option for the fastest. The cost is borne by liquidity
providers, who must widen:

$$\text{Spread widening} \approx \frac{\text{(sniping frequency)}\times\text{(value per snipe)}}{\text{volume}}$$

Per-unit-time value of the sniping option scales as $\sigma\sqrt{\Delta t_{\text{latency}}}$.
Their proposed fix — frequent batch auctions at, say, 100ms intervals — converts the
speed race into a price race, and the mathematics is straightforward: batching
eliminates the option because there is no stale-quote interval to exploit.

**Latency's effect on your own strategy.** With reaction latency $\ell$, a signal
with decay time $\tau_{\text{signal}}$ retains only

$$\text{captured alpha} = \alpha_0\,e^{-\ell/\tau_{\text{signal}}}$$

For an order-book signal with $\tau_{\text{signal}} = 1$ ms, a 500 µs latency captures
$e^{-0.5}=61\%$. At 5 ms latency: $e^{-5} = 0.7\%$. **The signal is gone.** This
equation, not any abstract argument, is what determines whether a given strategy is
viable on your infrastructure.

---

## 11.4 Adverse selection and the free option

**The core problem for any passive quote.** A resting limit order is a free option
granted to the market:

- If the fair value moves against your quote, you get filled (you lose).
- If it moves in your favor, you don't get filled (you gain nothing).

**Option value of a stale quote.** A quote at distance $\delta$ from fair value,
exposed for time $\ell$ (your cancellation latency), with volatility $\sigma$:

$$\boxed{\;V_{\text{option}} \approx \sigma\sqrt{\ell}\ \varphi\!\Big(\frac{\delta}{\sigma\sqrt\ell}\Big) - \delta\,\Phi\!\Big(-\frac{\delta}{\sigma\sqrt\ell}\Big)\;}$$

This is exactly a Bachelier option value — because it *is* an option. **The cost of
being slow is $\propto\sigma\sqrt{\ell}$**: square-root in latency, so the first
microseconds saved matter most.

**Implication for quoting.** You must widen by at least the option value you're
giving away:

$$\delta_{\min} = \delta_{\text{AS-free}} + c\,\sigma\sqrt{\ell}$$

At $\sigma = 20\%$ annual ($\approx 0.0004$ per $\sqrt{\text{second}}$ on a \$100 stock),
a 1 ms latency gives $\sigma\sqrt\ell \approx 0.0013$ cents — negligible. At 100 ms:
0.013 cents. At 1 second: 0.04 cents — a meaningful fraction of a penny spread.
**Latency requirements are set by volatility.** In a 100-vol crypto market, the
same latency is 5× as costly.

---

## 11.5 Markouts — the fundamental HFT diagnostic

$$\boxed{\;\mathrm{MO}(\Delta) = q\cdot\big(m_{t+\Delta} - p_{\text{fill}}\big)\;}$$

with $q=+1$ for your buys, $-1$ for your sells. Plot $\mathrm{MO}$ against $\Delta$ on
a log scale: **100µs, 1ms, 10ms, 100ms, 1s, 10s, 1min, 5min, 30min.**

**How to read the curve:**

| Shape | Diagnosis |
|---|---|
| Starts at $+\tfrac S2$, decays, **flattens positive** | Healthy market making — you keep some spread |
| Starts positive, crosses **zero and keeps falling** | Adverse selection exceeds your spread. You are the exit liquidity |
| Rises with $\Delta$ | You have genuine alpha; consider being more aggressive |
| Sharp drop in the first 1–10 ms | Being picked off by faster participants — a latency problem |
| Drop concentrated at 1–30 s | Trading against informed metaorders — a toxicity problem |
| Drop at 5+ min only | Fundamental information, not microstructure — widen or avoid the name |

**The decomposition** (§06.5 restated at the individual-fill level):

$$\underbrace{\text{Effective spread}}_{\text{what you captured}} = \underbrace{\text{Realized spread}}_{\text{what you kept}} + \underbrace{\text{Price impact}}_{\text{markout loss}}$$

**Markouts by segment** is where the money is. Compute the markout curve broken out by:
- Counterparty (where available) — some flow is systematically toxic
- Venue — venue toxicity varies enormously
- Order type (hidden, midpoint, displayed)
- Time of day (open and close are much more toxic)
- Queue position at fill (§11.2)
- Size bucket

**Then route around the toxic segments.** This is the highest-return analysis in
electronic trading, and it requires no modelling — only careful bookkeeping.

**Markout in basis points, normalized:**

$$\mathrm{MO}_{\text{bp}}(\Delta) = \frac{\mathrm{MO}(\Delta)}{m_t}\times10^4,\qquad
\mathrm{MO}_{\text{normalized}}(\Delta) = \frac{\mathrm{MO}(\Delta)}{\sigma\sqrt\Delta}$$

The second form is the right one for comparing across names and regimes — it asks
"how many standard deviations of adverse move did I suffer" rather than a raw
number that is dominated by which stock you traded.

---

## 11.6 Order book reconstruction and time

**Event time vs. clock time.** Almost every microstructure regularity is cleaner in
**event time** (per trade, per book update) or **volume time** (per $V$ shares) than
in clock time. Volume-time sampling:
- Makes returns much closer to i.i.d. Gaussian (the subordination result: price is
  a Brownian motion **time-changed by volume**).
- Removes intraday seasonality automatically (§03.8).
- Is the basis of VPIN (§08.5) and of volume bars / dollar bars in ML pipelines.

$$P_t = B_{\Theta(t)},\qquad \Theta(t) = \text{cumulative volume or trade count}$$

**Timestamp discipline.** The single largest source of fake HFT alpha:

- **Exchange timestamp** (when the matching engine processed it) vs. **capture
  timestamp** (when your NIC saw it). Always use capture timestamps for anything
  decision-related; exchange timestamps for reconstruction.
- **Sequence numbers**, not timestamps, define ordering. Timestamps can tie or go
  backwards across gateways.
- A signal computed on exchange timestamps but traded on capture timestamps has
  a built-in lookahead of the market-data latency. This will manufacture spectacular
  backtest results and lose money live.

**Book reconstruction correctness checks:**
1. Crossed book ($P_b \ge P_a$) should never persist for more than the gateway
   propagation time. Persistent crossing = a bug.
2. Total volume from your reconstructed book must match the exchange's official
   volume for the session.
3. Every trade should be consumable against resting quantity you know about.
4. Replay determinism: reconstructing the same session twice must give identical
   state.

---

## 11.7 Strategy families and their equations

### Latency arbitrage / stale quote sniping

Detect: $|m_A - m_B| > $ threshold across correlated venues or instruments; hit the
stale side. Expected P&L per opportunity:

$$\mathbb E[\pi] = P_{\text{win}}(\ell)\times\big(|m_A-m_B| - \text{fees}\big)$$

Pure speed. Capacity is set by the frequency of dislocations, which is itself
decreasing as the field speeds up.

### Cross-venue / cross-asset lead-lag

The ES future leads SPY; SPY leads its constituents. The predictive regression:

$$\Delta m^{\text{lag}}_{t+\ell} = \beta\,\Delta m^{\text{lead}}_t + \varepsilon$$

with $\beta$ the hedge ratio and $\ell$ the lead time — typically hundreds of
microseconds to a few milliseconds, and shrinking every year. Requires that your
total latency be less than $\ell$; otherwise you are trading noise.

**Hayashi–Yoshida estimator** for the lead-lag correlation with asynchronous data
(the correct tool — naive synchronization creates the **Epps effect**, a spurious
decay of correlation at high frequency):

$$\widehat{\mathrm{Cov}}_{HY} = \sum_{i,j}\Delta X_i\,\Delta Y_j\,\mathbf 1\{(t_{i-1},t_i]\cap(s_{j-1},s_j]\ne\emptyset\}$$

Sum over **overlapping** intervals only, with no synchronization at all. The lead-lag
time is found by maximizing $\widehat{\mathrm{Cov}}_{HY}$ over a shift applied to one series.

### Market making

§08, plus the queue and latency mechanics of this chapter.

### Order anticipation

Detect a large metaorder in progress (persistent one-sided flow, §06.6 order flow
autocorrelation), trade ahead of its remaining impact. Detection statistic — the
run-length or the OFI persistence:

$$\hat\gamma = \text{autocorrelation decay exponent of signed flow}$$

Legally and reputationally fraught if it shades into front-running client flow;
mathematically it is just conditioning on the well-documented long memory of order
flow.

### Rebate / fee arbitrage

$$\pi = r_{\text{maker}} - f_{\text{taker}} \pm \text{price movement}$$

Requires being flat in expectation and earning the fee differential. Only viable at
enormous volume and with careful markout control — the flow attracted by
rebate-chasing is systematically toxic (§06.10).

---

## 11.8 Risk controls at high frequency

Speed removes the human from the loop, so the controls must be in the path.

**Pre-trade (in the order path, hard limits):**

| Control | Rule |
|---|---|
| Max order size | $q \le q_{\max}$ |
| Max position | $|Q| \le Q_{\max}$ per instrument and aggregate |
| Price collar | $|p_{\text{order}} - m| \le c\,\sigma\sqrt{\Delta t}$ |
| Message rate | orders/sec $\le R_{\max}$ (exchange limits and self-protection) |
| Fat finger | notional per order $\le N_{\max}$ |
| Self-trade prevention | cancel-newest / cancel-oldest |

**Real-time kill switches:**

$$\text{Halt if: } \mathrm{P\&L}_{\text{intraday}} < -L\quad\text{or}\quad |Q| > Q_{\max}\quad\text{or}\quad \text{fill rate} > k\times\text{expected}$$

**The fill-rate trigger is the most important one and the most often missing.**
A sudden spike in fill rate means either (a) your quotes are stale, (b) the market
has moved and your pricing is wrong, or (c) a software bug. All three require
immediate withdrawal. The Knight Capital loss (\$460m in 45 minutes) was precisely
an uncaught fill-rate anomaly.

**Statistical monitors:**

$$\text{Markout monitor: } \ \bar{\mathrm{MO}}(\Delta)\ \text{over a rolling window},\ \text{alert if} < \text{threshold}$$
$$\text{Toxicity: } \ \mathrm{VPIN},\ \text{alert on percentile breach}$$
$$\text{Reflexivity: } \ \text{Hawkes branching ratio } n,\ \text{alert as } n\to1$$

**The formal position-limit calculation.** With inventory $q$ and horizon $\tau$
until you can flatten:

$$\mathbb P\big(\text{loss} > L\big) = \Phi\Big(\frac{-L}{|q|\sigma\sqrt\tau}\Big) \quad\Longrightarrow\quad
Q_{\max} = \frac{L}{z_\alpha\,\sigma\sqrt{\tau_{\text{liquidate}}}}$$

with $\tau_{\text{liquidate}}$ from §07 (size / participation rate). **Position limits
must scale inversely with volatility.** A fixed share limit is a limit that gets
looser exactly when risk rises — which is backwards, and is how firms die.

---

## 11.9 The HFT equation summary

| Quantity | Equation |
|---|---|
| Fill probability | $P_{\text{fill}} = (1+\theta Q_0/\mu)^{-\nu/\theta}$ |
| Time to front of queue | $T = \frac1\theta\ln(1+\theta Q_0/\mu)$ |
| Mid-move probability | $\mathbb P(\uparrow) \approx Q_b/(Q_a+Q_b)$ |
| Microprice | $(Q_bP_a+Q_aP_b)/(Q_a+Q_b)$ |
| Stale-quote option cost | $\approx \sigma\sqrt\ell\,\varphi(\delta/\sigma\sqrt\ell) - \delta\Phi(-\delta/\sigma\sqrt\ell)$ |
| Alpha captured at latency $\ell$ | $\alpha_0e^{-\ell/\tau_{\text{signal}}}$ |
| Race win probability | $(1-F(\ell))^{N-1}$ |
| Hawkes branching ratio | $n=\alpha/\beta$; criticality at $n\to1$ |
| Markout | $q(m_{t+\Delta}-p_{\text{fill}})$ |
| Position limit | $Q_{\max}=L/(z_\alpha\sigma\sqrt{\tau_{\text{liq}}})$ |
| MM Sharpe scaling | $\mathrm{SR}\propto\sqrt{n_{\text{fills}}}$ |

**The one thing to take away:** at this frequency, edge per trade is a fraction of a
tick and *cannot be increased much*. Everything is won on (a) fill count, (b) queue
position, (c) avoiding toxic fills. The equations above measure exactly those three
things.

---

**Next:** [12 — Estimation & Numerics](12-estimation-numerics.md)
