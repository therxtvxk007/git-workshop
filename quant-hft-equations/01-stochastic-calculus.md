# 01 — Stochastic Calculus Foundations

Everything downstream is a corollary of this chapter. If you can do Itô, Girsanov,
and Feynman–Kac cold, you can rebuild derivatives pricing and optimal control from
scratch.

---

## 1.1 Brownian motion

$W_t$ is standard Brownian motion iff $W_0=0$, paths are continuous,
increments are independent, and $W_t - W_s \sim \mathcal N(0, t-s)$.

The property that drives everything:

$$\mathbb E[(dW)^2] = dt, \qquad (dW)^2 \to dt \ \text{ in } L^2$$

Quadratic variation is **deterministic and non-zero**:

$$\langle W\rangle_T = \lim_{\|\Pi\|\to0}\sum_i (W_{t_{i+1}}-W_{t_i})^2 = T \quad \text{a.s.}$$

*Derivation.* Let $\Delta_i = W_{t_{i+1}}-W_{t_i}$, $\delta_i = t_{i+1}-t_i$. Then
$\mathbb E[\sum\Delta_i^2] = \sum\delta_i = T$ and
$\mathrm{Var}(\sum\Delta_i^2) = \sum \mathrm{Var}(\Delta_i^2) = \sum 2\delta_i^2 \le 2\|\Pi\|T \to 0$.
Convergence in $L^2$ follows. $\square$

This is the whole reason a second-order term survives in Itô's lemma while it dies
in ordinary calculus. **Multiplication table:**

$$dt\cdot dt = 0,\qquad dt\cdot dW = 0,\qquad dW\cdot dW = dt,\qquad dW^{(i)}dW^{(j)} = \rho_{ij}\,dt$$

---

## 1.2 Itô's lemma

**Statement (scalar).** If $dX_t = a(X_t,t)\,dt + b(X_t,t)\,dW_t$ and $f\in C^{2,1}$, then

$$\boxed{\;df(X_t,t) = \Big(\frac{\partial f}{\partial t} + a\frac{\partial f}{\partial x} + \tfrac12 b^2\frac{\partial^2 f}{\partial x^2}\Big)dt \;+\; b\,\frac{\partial f}{\partial x}\,dW_t\;}$$

**Derivation.** Taylor-expand to second order:

$$df = f_t\,dt + f_x\,dX + \tfrac12 f_{xx}(dX)^2 + O(dt^{3/2})$$

Substitute $dX = a\,dt + b\,dW$ and use the multiplication table:

$$(dX)^2 = a^2dt^2 + 2ab\,dt\,dW + b^2(dW)^2 = b^2\,dt$$

Collect terms. The $\tfrac12 b^2 f_{xx}$ term is the **Itô correction** — the price of
convexity in a world with quadratic variation. $\square$

**Multivariate form.** For $dX^i = a^i dt + \sum_j b^{ij}dW^j$ with $d\langle X^i,X^k\rangle = \Sigma^{ik}dt$:

$$df = \Big(f_t + \sum_i a^i f_{x_i} + \tfrac12\sum_{i,k}\Sigma^{ik} f_{x_ix_k}\Big)dt + \sum_{i,j}b^{ij}f_{x_i}\,dW^j$$

**Itô product rule.**
$$d(X_tY_t) = X_t\,dY_t + Y_t\,dX_t + d\langle X,Y\rangle_t$$

The cross-variation term is what ordinary calculus misses; it is the source of
the "gamma rent" in hedging and the convexity adjustment in rates.

---

## 1.3 Geometric Brownian motion — the reference model

$$dS_t = \mu S_t\,dt + \sigma S_t\,dW_t$$

**Closed-form solution.** Apply Itô to $f = \ln S$: $f_S = 1/S$, $f_{SS} = -1/S^2$.

$$d\ln S = \Big(\mu S\cdot\frac1S + \tfrac12\sigma^2S^2\cdot\big(-\tfrac1{S^2}\big)\Big)dt + \sigma S\cdot\frac1S\,dW = \Big(\mu - \frac{\sigma^2}2\Big)dt + \sigma\,dW$$

Integrating:

$$\boxed{\;S_T = S_0\exp\Big[\Big(\mu-\frac{\sigma^2}{2}\Big)T + \sigma W_T\Big]\;}$$

so $\ln S_T \sim \mathcal N\big(\ln S_0 + (\mu-\sigma^2/2)T,\ \sigma^2T\big)$ and

$$\mathbb E[S_T] = S_0e^{\mu T},\qquad \mathrm{Var}(S_T) = S_0^2e^{2\mu T}\big(e^{\sigma^2T}-1\big)$$

**The $-\sigma^2/2$ is the single most expensive term in finance.** It is *volatility
drag*: the gap between arithmetic and geometric mean return.

$$g = \mu - \frac{\sigma^2}{2}$$

At $\mu=10\%$, $\sigma=40\%$: expected value grows at 10%/yr but the **median** path
grows at $10\% - 8\% = 2\%$/yr. Leverage $L$ scales this to $L\mu - L^2\sigma^2/2$, which
is maximized at $L^\star = \mu/\sigma^2$ — this *is* the Kelly criterion (§04.4),
falling directly out of Itô.

---

## 1.4 Ornstein–Uhlenbeck — the reference mean-reverting model

$$dX_t = \theta(\bar\mu - X_t)\,dt + \sigma\,dW_t,\qquad \theta>0$$

**Solution.** Use the integrating factor $e^{\theta t}$. Set $Y_t = e^{\theta t}X_t$; by the
product rule (no cross-variation since $e^{\theta t}$ is smooth):

$$dY = \theta e^{\theta t}X\,dt + e^{\theta t}dX = \theta e^{\theta t}\bar\mu\,dt + \sigma e^{\theta t}dW$$

Integrate and multiply back by $e^{-\theta t}$:

$$\boxed{\;X_t = \bar\mu + (X_0-\bar\mu)e^{-\theta t} + \sigma\!\int_0^t e^{-\theta(t-s)}dW_s\;}$$

By Itô isometry the stochastic integral is Gaussian with variance
$\sigma^2\int_0^t e^{-2\theta(t-s)}ds = \frac{\sigma^2}{2\theta}(1-e^{-2\theta t})$.

$$X_t \sim \mathcal N\Big(\bar\mu + (X_0-\bar\mu)e^{-\theta t},\ \frac{\sigma^2}{2\theta}\big(1-e^{-2\theta t}\big)\Big)$$

**The three numbers you actually quote:**

$$\text{stationary variance } \sigma_\infty^2 = \frac{\sigma^2}{2\theta},\qquad
\text{half-life } t_{1/2} = \frac{\ln 2}{\theta},\qquad
\mathrm{Corr}(X_t,X_{t+h}) = e^{-\theta h}$$

**Discrete estimation.** OU sampled at interval $\Delta$ is exactly an AR(1):
$X_{t+\Delta} = c + \rho X_t + \varepsilon$, with

$$\rho = e^{-\theta\Delta}\ \Rightarrow\ \theta = -\frac{\ln\rho}{\Delta},\qquad
\bar\mu = \frac{c}{1-\rho},\qquad \sigma^2 = \frac{2\theta\,\mathrm{Var}(\varepsilon)}{1-\rho^2}$$

So: **fit an AR(1), read off the half-life.** That is the entire calibration.

---

## 1.5 Jump diffusion (Merton)

$$\frac{dS_t}{S_{t^-}} = (\mu - \lambda_J\bar\kappa)\,dt + \sigma\,dW_t + (J-1)\,dN_t$$

with $N_t$ Poisson($\lambda_J$), jump sizes $J$ i.i.d., $\bar\kappa = \mathbb E[J-1]$.
The compensator $-\lambda_J\bar\kappa\,dt$ keeps $\mathbb E[S_T]=S_0e^{\mu T}$.

**Itô–Doeblin with jumps:**

$$df = \Big(f_t + a f_x + \tfrac12b^2f_{xx}\Big)dt + bf_x\,dW + \big[f(X_{t^-}+\Delta X) - f(X_{t^-})\big]dN$$

The jump term is *not* a Taylor expansion — it is a finite difference. This is why
jumps break delta hedging: you cannot hedge a discontinuity with a first derivative.
Gap risk is exactly the residual $f(x+\Delta) - f(x) - f'(x)\Delta$.

---

## 1.6 Girsanov's theorem — changing the drift

**Statement.** Let $\theta_t$ be adapted with $\mathbb E[\exp(\tfrac12\int_0^T\theta_s^2ds)]<\infty$ (Novikov).
Define the Radon–Nikodym derivative

$$\frac{d\mathbb Q}{d\mathbb P}\Big|_{\mathcal F_T} = Z_T = \exp\Big(-\int_0^T\theta_s\,dW_s - \frac12\int_0^T\theta_s^2\,ds\Big)$$

Then $W^{\mathbb Q}_t = W_t + \int_0^t\theta_s\,ds$ is a $\mathbb Q$-Brownian motion.

**What it buys you.** Under GBM, choose the **market price of risk**

$$\theta = \frac{\mu-r}{\sigma}$$

Then $dS = \mu S\,dt + \sigma S\,dW = \mu S\,dt + \sigma S(dW^{\mathbb Q} - \theta\,dt) = rS\,dt + \sigma S\,dW^{\mathbb Q}$.

**The drift is gone.** Under $\mathbb Q$ every tradable grows at $r$, and discounted
prices are martingales:

$$\boxed{\;V_t = e^{-r(T-t)}\,\mathbb E^{\mathbb Q}_t[V_T]\;}$$

This is the **First Fundamental Theorem of Asset Pricing**: no arbitrage $\iff$
an equivalent martingale measure exists. Completeness $\iff$ it is unique.

**Practical consequence:** you never need to forecast $\mu$ to price a derivative.
You need $\sigma$. That asymmetry — drift is unidentifiable in finite samples, vol is
estimable at high frequency — is why derivatives desks exist.

---

## 1.7 Feynman–Kac — the PDE ↔ expectation bridge

**Statement.** If $u(x,t)$ solves

$$\frac{\partial u}{\partial t} + a(x,t)\frac{\partial u}{\partial x} + \frac12 b^2(x,t)\frac{\partial^2u}{\partial x^2} - r\,u + h(x,t) = 0,\qquad u(x,T)=\Psi(x)$$

then

$$u(x,t) = \mathbb E\Big[e^{-r(T-t)}\Psi(X_T) + \int_t^T e^{-r(s-t)}h(X_s,s)\,ds\ \Big|\ X_t=x\Big]$$

where $dX = a\,dt + b\,dW$.

**Derivation.** Define $M_s = e^{-r(s-t)}u(X_s,s) + \int_t^s e^{-r(v-t)}h\,dv$. Apply Itô:

$$dM_s = e^{-r(s-t)}\Big[\underbrace{u_t + au_x + \tfrac12b^2u_{xx} - ru + h}_{=0\text{ by the PDE}}\Big]ds + e^{-r(s-t)}bu_x\,dW$$

So $M$ is a martingale. Then $u(x,t) = M_t = \mathbb E[M_T]$, which is the claimed
expectation. $\square$

**Why it matters.** Two solution technologies for the same object:
- **PDE / finite difference** — fast in 1–2 dimensions, handles early exercise naturally.
- **Monte Carlo** — cost is dimension-independent, handles path dependence naturally,
  but American exercise needs Longstaff–Schwartz regression.

Crossover is around 3–4 state variables.

---

## 1.8 The infinitesimal generator and Dynkin's formula

For $dX = a\,dt + b\,dW$, the generator is

$$\mathcal L f = a\frac{\partial f}{\partial x} + \frac12 b^2\frac{\partial^2f}{\partial x^2}$$

**Dynkin:** $\displaystyle \mathbb E[f(X_\tau)] = f(x) + \mathbb E\Big[\int_0^\tau \mathcal Lf(X_s)\,ds\Big]$ for stopping times $\tau$.

This is the workhorse for **first-passage problems** — expected time to hit a barrier,
probability of touching a stop before a target — which is how you actually evaluate
a stat-arb entry/exit rule (§09.3).

**Example — OU first passage.** For $dX = -\theta X\,dt + \sigma\,dW$ started at $x$, the
expected time to exit $(-b, b)$ solves $\mathcal L T(x) = -1$, $T(\pm b)=0$:

$$-\theta x\,T'(x) + \tfrac12\sigma^2T''(x) = -1$$

Solvable in closed form via the error function; this is what turns "the spread is
2 sigma wide" into "I expect to be flat in 4.2 days."

---

## 1.9 Stochastic optimal control — the HJB equation

The master equation behind execution (§07), market making (§08), and portfolio
choice (§04).

**Problem.** Control $u_t$, state $dX = a(X,u)dt + b(X,u)dW$, maximize

$$V(x,t) = \sup_{u}\ \mathbb E\Big[\int_t^T F(X_s,u_s,s)\,ds + G(X_T)\ \Big|\ X_t=x\Big]$$

**Hamilton–Jacobi–Bellman.**

$$\boxed{\;\frac{\partial V}{\partial t} + \sup_u\Big\{F(x,u,t) + a(x,u)\frac{\partial V}{\partial x} + \frac12 b^2(x,u)\frac{\partial^2V}{\partial x^2}\Big\} = 0,\quad V(x,T)=G(x)\;}$$

**Derivation (dynamic programming).** Over $[t,t+dt]$, optimality requires

$$V(x,t) = \sup_u\Big\{F\,dt + \mathbb E[V(X_{t+dt},t+dt)]\Big\}$$

Expand the expectation with Itô ($\mathbb E[dW]=0$):
$\mathbb E[dV] = (V_t + aV_x + \tfrac12b^2V_{xx})dt$. Substitute, cancel $V(x,t)$,
divide by $dt$. $\square$

**Verification theorem.** A smooth solution to the HJB with the right growth
conditions *is* the value function, and the maximizing $u^\star(x,t)$ is optimal.
In practice: guess an ansatz for $V$ (exponential for CARA, power for CRRA,
quadratic for mean–variance), reduce the PDE to ODEs, solve.

Every closed-form result in chapters 07–09 is this recipe applied with a different
running cost $F$.

---

## 1.10 Reference table

| Object | SDE | Key statistic |
|---|---|---|
| Brownian motion | $dX=\sigma dW$ | $\mathrm{Var} = \sigma^2 t$ |
| GBM | $dS=\mu S dt+\sigma S dW$ | $\mathbb E[\ln S_T/S_0] = (\mu-\sigma^2/2)T$ |
| OU | $dX=\theta(\bar\mu-X)dt+\sigma dW$ | half-life $\ln2/\theta$, $\sigma^2_\infty=\sigma^2/2\theta$ |
| CIR | $dX=\theta(\bar\mu-X)dt+\sigma\sqrt X dW$ | stays $\ge0$ iff $2\theta\bar\mu\ge\sigma^2$ (Feller) |
| Bessel / CEV | $dS=\mu S dt+\sigma S^\beta dW$ | $\beta<1$ ⟹ leverage effect |
| Jump diffusion | $+\,(J-1)dN$ | fat tails, unhedgeable gap |
| Heston | $dv=\kappa(\bar v-v)dt+\xi\sqrt v dW^v$ | smile from $\rho$, smirk from $\xi$ |
| Rough vol | $\ln v$ driven by fBm, $H\approx0.1$ | ATM skew $\sim \tau^{H-1/2}$ |

---

**Next:** [02 — Derivatives Pricing](02-derivatives-pricing.md)
