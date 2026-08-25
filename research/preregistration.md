# Preregistration

Status: **draft, M0 stage.** Nothing here is a claim; it is a commitment about
how claims will be permitted to be made later.

## Why this file exists before there are results

The failure mode this project is most exposed to is not a bug. It is a
plausible-looking number produced by a pipeline nobody has audited, quoted
without its caveats. Writing down what would count as evidence *before* running
the experiments is the cheapest available defence.

## Committed at M0

1. **Temporal splits only.** No random document split may support any claim. A
   random split lets tomorrow's reporting explain yesterday's forecast.
2. **Snapshot-pinned forecasts.** A forecast without a snapshot hash is invalid
   and will not be counted.
3. **Forecast-before-outcome ordering.** In backtests, forecasts for cutoff T
   are written before outcomes are read. In the prospective track, forecasts are
   hashed and timestamped before resolution.
4. **Statement of limits.** Every report leads with what its numbers do not
   mean. Uncalibrated probabilities are labelled uncalibrated; placeholder
   thresholds are labelled placeholder.
5. **No protected-attribute proxies.** Ethnic, religion, health-status and
   appearance fields are dropped at ingestion, not filtered downstream. This
   project predicts population-level and organisational events and does not
   produce risk scores for private individuals.
6. **Human adjudication is required for gold.** Machine-derived outcomes are
   `PENDING` and are reported as such.

## To be registered before Phase 3 metrics are believed

- Matcher validation target against blinded dual-human labels, with the
  agreement threshold fixed in advance.
- The primary metric and its budget: recall at a fixed alerts-per-region-day
  budget, with the budget chosen by the people who would triage the alerts.
- Fold structure: the date ranges, domains and the number of temporal folds.
- Which comparisons count as reproductions, and the tolerance for calling a
  published result reproduced.

## To be registered before any superiority claim

- The exact baselines, their versions and their evidence budgets.
- The pre-committed direction of every comparison.
- The subgroups that will be reported whether or not they flatter the system:
  by language, geography, source availability, domain and event rarity.
- What result would count as a failure.

## Claim discipline

The intended defensible claim, once and only once the above are satisfied:

> PRAMAAN-X outperforms reproduced structured, open-ended and binary forecasting
> baselines on a common non-oracle, cutoff-safe event-forecasting benchmark
> while controlling missed-event risk and operational alert burden.

The claim that will never be made, because the underlying tasks and datasets are
not identical: that this system beats "all forecasting models everywhere".
