# WP5 — classical statistical–spatial baseline ladder

Base: `e5eef3a270bab0adf518f425a68daa84e8bdf5b5` (tree `d1fa757187597c135708aea9cc41eb53c4cb2d38`),
imported from the verified district-foundation bundle.

This package produces **strong, reproducible classical controls** for three
targets on one row definition — `district × cutoff × event_family`:

1. probability of at least one qualifying event;
2. expected event count;
3. count-distribution parameters.

It contains no deep learning, no ensembling, no calibration and no serving
code, and it makes **no claim of real-world predictive skill**. Every number in
the test suite comes from a synthetic panel with a known generating process.

---

## What was added

| File | Purpose |
| --- | --- |
| `contracts.py` | The training-row contract and its refusals |
| `feature_registry.py` | 35 declared, versioned, hashable feature specs |
| `splits.py` | Rolling-origin folds, derived embargo, sealed reservations |
| `distributions.py` | Validated Poisson / NB2 / hurdle / ZINB / degenerate summaries |
| `count_models.py` | ML count regressions with explicit failure classification |
| `prediction.py` | The B0–B12 ladder behind one interface, plus cold start |
| `oof.py` | Out-of-fold records and their leakage guards |
| `artifacts.py` | Immutable, content-addressed manifests |
| `training.py` | Fit-across-folds orchestration and dry-run planning |
| `outcome_helpers.py` | Shared incident constructor for fixtures and demos |

`dataset.py`, `baselines.py` and `statistical.py` are **byte-identical** to the
foundation. `features.py` gained `build_extended_spatial_features`, which calls
the foundation's `build_spatial_features` unchanged and enriches its output, so
the windowed-count semantics the foundation's tests pin down still hold.

## The baseline ladder

| Rung | Model | Fitted on | Distribution |
| --- | --- | --- | --- |
| B0 | Uniform prior (0.5), never looks at data | — | Poisson |
| B1 | National historical occurrence rate | training rows | Poisson |
| B2 | State historical rate, shrunk to national | training rows | Poisson |
| B3 | District historical rate, shrunk to state | training rows | Poisson |
| B4 | Persistence / no-change | last observed count | Poisson |
| B5 | Recency-weighted (30-day half-life decay) | decay feature | Poisson |
| B6 | Gamma-Poisson base-rate control, matching engine G0 | 365-day district count | Poisson |
| B7 | Regularized logistic regression | standardized full matrix | Poisson (from p) |
| B8 | Histogram gradient boosting | standardized full matrix | Poisson (from p) |
| B9 | Poisson GLM | standardized count design | Poisson |
| B10 | Negative binomial NB2 | standardized count design | NB2 |
| B11 | Hurdle NB | standardized count design | Hurdle NB |
| B12 | Zero-inflated NB | standardized count design | ZINB |

B0–B8 are occurrence-first: the expected count is obtained by inverting
`P(at least one) = 1 − exp(−λ)`, so a rung's two outputs cannot contradict each
other. B9–B12 are count-first: the occurrence probability is `1 − P(Y=0)` read
off the fitted distribution, for the same reason.

**Count design matrix.** B9–B12 use five declared columns
(`district_count_30d`, `district_count_365d`, `district_decayed_count`,
`neighbour_count_365d`, `state_count_365d`) rather than the full matrix. The
history windows are nested sums of one another, and handing a GLM all of them
on a panel with tens of rows per fold produces a rank-deficient design whose
coefficients swing between folds — instability that would be misread as a
property of the count family. B8 keeps the full matrix, where collinearity is
harmless.

## Cold start

Wired **above** the estimator layer, in `RateHierarchy`:

```
district → state → national → uniform prior (0.5)
```

Rates are shrunk toward the level above with a pseudo-count of 5. The level
actually used is recorded on every prediction and every OOF record as
`fallback_level`. A district with no observed events never receives a rate of
zero: absence of observation is not evidence of absence of risk.

## Convergence and identifiability limitations

Recorded rather than hidden:

- **NB2 / ZINB are partially confounded.** Both explain excess zeros — one
  through dispersion, one through a structural-zero component. On synthetic
  data generated with `α = 0.6, π = 0.35`, the estimates come back near
  `α̂ ≈ 0.53, π̂ ≈ 0.41`. The likelihood is genuinely flat along that ridge; the
  fits converge, but the two parameters should not be interpreted separately.
- **ZINB inflation has no covariates.** A covariate-dependent inflation model
  is not identified at this panel density. Recorded as a future challenger.
- **`FitStatus.MAX_ITERATIONS` is not convergence.** It is reported distinctly
  so a run that hit the iteration guard cannot be read as a converged fit.
- **Degenerate folds fall back and say so.** An all-zero training window, or
  fewer rows than parameters, yields `DEGENERATE_DATA` and the declared
  fallback — never a fitted rate of zero.
- **Standardization is required, not cosmetic.** Without it the logistic fit
  hits its 2000-iteration cap without converging and the Poisson GLM's linear
  predictor saturates its overflow clip. The transform is fitted on training
  rows only and reused unchanged at prediction time.

## Integration requests

Items this package deliberately does **not** build, with what it needs:

1. **Attempted vs. completed incidents.** `NormalizedIncident` carries no
   completion field. `build_extended_spatial_features` accepts an optional
   `completion_status: Mapping[incident_id, str]`; when absent the three
   attempted/completed features are **omitted entirely rather than zeroed**.
   *Request: a completion status on the normalized incident, or a
   crosswalk WP5 can be handed.*
2. **Evidence and coverage features** (`coverage_*`, seven declared specs).
   Declared in the registry so the contract and its hash are complete, injected
   through `build_training_rows(source_coverage=...)`. WP5 does not build news
   or NLP features. *Request: WP1/WP2 to emit these per
   `(district, cutoff, event_family)` with their own availability timestamps.*
3. **Reporting-delay policy.** This foundation has no
   `outcomes/reporting_delay.py`; the delay is a parameter of
   `build_district_outcome_panel`. WP5 mirrors it in `ReportingDelayPolicy`
   and hashes it into every artefact. *Request: if a delay module lands later,
   WP5 should consume it instead of re-declaring the parameters.*
4. **Boosted count challengers.** LightGBM / CatBoost / XGBoost are **not**
   introduced by this package and no dependency was added. *Recorded as future
   challenger candidates.*
5. **Ensemble consumption.** `OofRecord` is the handoff. Records are guaranteed
   to be produced only by models that trained strictly before the scored row.
   *Request: the ensemble package consumes these and does not re-fit rungs.*

## What this package must never do

- Open the final-test reservation. `select_rows(..., FINAL_TEST)` raises
  `SealedSplitError`; there is no flag to override it.
- Emit calibrated probabilities. These are raw model outputs.
- Drop a difficult row from one model's evaluation set. A rung that cannot
  predict either falls back or marks the prediction unavailable — the row stays.
