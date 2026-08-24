# Method

Notation: instances (documents) $i$, bags (region-days) $b$, groups
(region-windows) $g$, regions $r$.

## 1. Nested multiple-instance pooling

Each instance gets a logit from a region-specific head:

$$s_i = (w_0 + v_{r(i)})^\top x_i + (b_0 + c_{r(i)})$$

Instances pool into bags, bags pool into the group, both by mean-normalised
log-sum-exp:

$$u_b = \tau_1 \log\Big(\tfrac{1}{|b|}\textstyle\sum_{i \in b} e^{s_i/\tau_1}\Big),
\qquad
S_g = \tau_2 \log\Big(\tfrac{1}{|g|}\textstyle\sum_{b \in g} e^{u_b/\tau_2}\Big),
\qquad p_g = \sigma(S_g)$$

$\tau \to 0$ recovers max-pooling (classical MIL: the bag is positive iff some
instance is); $\tau \to \infty$ recovers mean-pooling. The intermediate regime is
the useful one. Hard max attributes a forecast to exactly one article, which is
useless as evidence and gives a gradient to one instance per step; mean pooling
lets a single decisive report be drowned by routine coverage.

### Attribution comes free

$$\frac{\partial S_g}{\partial s_i} = \beta_b \cdot \alpha_i,
\qquad
\alpha_i = \operatorname{softmax}_{i \in b}(s_i/\tau_1),
\qquad
\beta_b = \operatorname{softmax}_{b \in g}(u_b/\tau_2)$$

These weights are non-negative and sum to 1 over the group. They are an exact
sensitivity of the forecast to each document, in closed form — not a surrogate
model fitted afterwards to approximate the first. The evidence the system shows
is the evidence it used.

This is verified numerically, not asserted: `check_gradient` compares the
analytic gradient against central finite differences and the test suite requires
agreement below `1e-6` (observed: ~2.5e-9).

## 2. Regularised multi-task heads

$$\mathcal{L} = \sum_g \mathrm{BCE}(S_g, y_g)
\;+\; \lambda_{\text{global}} \lVert w_0 \rVert^2
\;+\; \lambda_{\text{task}} \sum_r \lVert v_r \rVert^2$$

$w_0$ is shared across regions; $v_r$ is region $r$'s deviation from it. The
penalty on $v_r$ interpolates between one global model
($\lambda_{\text{task}} \to \infty$) and independent per-region models
($\lambda_{\text{task}} \to 0$). This is the Evgeniou–Pontil regularised
multi-task formulation, and it is the survey's gap **G5** stated as an objective:
a region with few labelled windows borrows strength from the rest instead of
overfitting, and an unseen region falls back to $w_0$ alone.

`region_divergence()` reports $\lVert v_r \rVert$ per region — all zeros means
the multi-task structure is inert, very large values mean it is not sharing.

Optimised by L-BFGS-B with the analytic gradient. The objective is convex in
$(w_0, v, b_0, c)$ for fixed pooling temperatures.

## 3. Time-decayed features

Every text signal is weighted by an explicit recency kernel

$$\omega(\Delta) = 2^{-\Delta / H}$$

with $\Delta$ the document's age in days and $H$ a tunable half-life. This is
gap **G3** made concrete: the Pundit-style causal rules the survey criticises
treat "A causes B" as timeless, so a month-old article counts exactly as much as
yesterday's. Here it does not.

The tabular branch adds lag-banded negativity ($\Delta \in [0,1)$, $[1,3)$,
$[3,7)$), a burst ratio (3-day mass over 14-day mass), acceleration, and an
OLS trend slope over the lookback window.

## 4. Calibration

Platt scaling by default:

$$\hat{p} = \sigma(A \cdot S + B)$$

fitted on a held-out slice that the branches never trained on. Platt is
*strictly* increasing, so it cannot change how windows are ranked.

Isotonic regression is available and is the textbook choice, but it is only
*weakly* monotone. On a fold where the calibration slice shows no increasing
score-label relationship, isotonic's solution is a constant — and a constant has
no ranking at all. Observed here on 2 of 4 walk-forward folds: raw scores
ranking at 0.752 ROC-AUC came out of the calibrator as 0.166 for every single
window, scoring exactly 0.500. Any fitted calibrator is therefore checked for
rank preservation (at least 3 distinct outputs, Spearman $\geq$ 0.99 against its
input) and rejected if it fails.

## 5. Split-conformal abstention

Nonconformity $\;A_i = 1 - \hat{p}(y_i)$. On $n$ calibration points the
threshold is the $\lceil (n+1)(1-\alpha) \rceil / n$ empirical quantile — the
finite-sample correction that makes coverage exact rather than asymptotic. The
prediction set is

$$\Gamma(x) = \{\, y \in \{0,1\} : 1 - \hat{p}(y \mid x) \leq q_y \,\}$$

$|\Gamma| = 1$ is a committed forecast; $|\Gamma| = 2$ is an abstention;
$|\Gamma| = 0$ says neither label conforms, which is itself a drift signal.

Thresholds are class-conditional (Mondrian) by default. With a rare positive
class a single marginal threshold can hit 90% coverage overall while covering
few true positives — the failure mode that matters most in event forecasting.

**The guarantee is marginal and assumes exchangeability.** News streams drift, so
that assumption is not satisfied in practice. This is why the backtest *measures*
empirical coverage rather than quoting the theorem.

## 6. Evaluation protocol

Rolling-origin (walk-forward): folds are contiguous blocks of forecast origins in
time order; the model trains only on origins strictly before the fold's cut; the
embedder is **refit per fold on training documents only**, so no corpus statistic
crosses the cut; every group is asserted free of documents dated at or after its
origin.

Reported per fold and pooled:

- **ROC-AUC** — ranking, insensitive to base rate.
- **PR-AUC and lift over base rate** — the honest imbalanced-data metric.
- **Brier score and Brier *skill*** against climatology. Skill $\leq 0$ means the
  probabilities do not beat predicting the historical rate every time, however
  good the AUC looks.
- **ECE** — are the probabilities meaningful.
- **Conformal coverage / abstention rate**.

Against three baselines through the identical split: overall base rate,
per-region climatology, and a volume-only logistic (document and event counts,
no content). The last one is the one that matters: a text model that cannot beat
counting how much was written is not using the text.

Two negative controls guard the protocol itself: `assert_no_lookahead` on every
group, and a test that shuffling labels collapses skill (if it does not, the
pipeline is leaking rather than learning).
