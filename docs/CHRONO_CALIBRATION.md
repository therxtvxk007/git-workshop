# Strictly chronological calibration experiment

`chrono_calib_v1` — run `chrono_5b21941cae7d4e10`

Selects a calibration method under nested temporal validation and tests the frozen
choice on an untouched future block. Synthetic world. No real-world skill claim.

## Why this experiment exists

The M0 control (`e2e_v1`) scores probabilities with the identity calibrator and a
Brier skill score taken against the base rate *of the sample being scored*. That is a
useful diagnostic and an unusable claim: no forecaster knows the base rate of the
window it is forecasting. This experiment replaces it with references a forecaster
could actually have held at the cutoff.

## Four rules, each enforced in code

**1. Maturity gates the fit.** A fold is admissible for calibrating a forecast at
cutoff `T` only when `fold_cutoff + horizon + reporting_delay <= T`. Being
chronologically earlier is not sufficient — an earlier fold whose horizon has not
closed leaks outcomes from the forecast's own future. `chrono.is_mature` is the only
admission test. Here the lag is 33.0d, which at a 7d
step is 4.7 folds.

**2. The choice is frozen before the test block opens.** Methods are ranked on
validation folds drawn from the development block only (39 folds).
The winner is then applied to 17 test folds
(2025-12-02 to 2026-03-24) that took no part in ranking.

**3. Skill is measured against earlier-period references.** Climatology is the base
rate of matured earlier folds. Persistence repeats the previous matured window's
positive streams. Both are computable at the cutoff.

**4. No t-tests across overlapping folds.** A 30-day horizon at a 7-day step puts the
same days in 5 consecutive folds, so folds are not
independent draws. All intervals are moving-block bootstrap percentile intervals with
a block of 5 folds.

## Validation — development block only

| method | folds | mean Brier | skill vs climatology | skill vs persistence | Brier gain over identity |
|---|---:|---:|---|---|---|
| `identity` | 33 | 0.28330 | -0.1831 [-0.2494, -0.1061] | +0.0976 [-0.0018, +0.1674] | — |
| `platt` | 33 | 0.24028 | -0.0042 [-0.0185, +0.0020] | +0.2369 [+0.1717, +0.2781] | +0.04303 [+0.02209, +0.05995] **excludes 0** |
| `isotonic` | 32 | 0.23386 | +0.0223 [+0.0087, +0.0459] | +0.2560 [+0.2015, +0.2935] | +0.05005 [+0.03509, +0.06501] **excludes 0** |
| `beta` | 33 | 0.22828 | +0.0459 [+0.0230, +0.0720] | +0.2758 [+0.2175, +0.3138] | +0.05502 [+0.03995, +0.06919] **excludes 0** |

**Frozen choice: `beta`.** Selected on the development block, before the test
block was scored.

## Untouched future test

### Many-to-one matching, as the matcher ships

| method | folds | mean Brier | skill vs climatology | skill vs persistence |
|---|---:|---:|---|---|
| `identity` | 17 | 0.25894 | -0.1387 [-0.2081, -0.0432] | +0.2057 [+0.1517, +0.3228] |
| `platt` | 17 | 0.22712 | -0.0005 [-0.0037, +0.0057] | +0.2997 [+0.2289, +0.3805] |
| `isotonic` | 17 | 0.22542 | +0.0068 [-0.0173, +0.0274] | +0.3071 [+0.2506, +0.3735] |
| `beta` ← frozen | 17 | 0.22252 | +0.0199 [+0.0055, +0.0426] | +0.3151 [+0.2543, +0.3916] |

### One-to-one matching enforced (sensitivity)

| method | folds | mean Brier | skill vs climatology | skill vs persistence |
|---|---:|---:|---|---|
| `identity` | 17 | 0.15987 | -0.0781 [-0.1236, -0.0190] | +0.3381 [+0.3101, +0.4011] |
| `platt` | 17 | 0.14828 | +0.0005 [-0.0061, +0.0169] | +0.3838 [+0.3490, +0.4509] |
| `isotonic` | 17 | 0.14371 | +0.0311 [+0.0122, +0.0497] | +0.4044 [+0.3789, +0.4561] |
| `beta` ← frozen | 17 | 0.13914 | +0.0629 [+0.0491, +0.0861] | +0.4224 [+0.3902, +0.4893] |

The frozen choice holds out of sample. Under the shipped matcher, identity scores
-0.1387 [-0.2081, -0.0432] against climatology — worse than
a constant — while `beta` scores +0.0199 [+0.0055, +0.0426],
an interval excluding zero. The sign flip is confirmed on folds that took no part in
selecting the method.

Enforcing one-to-one matching does not change the ordering of methods and strengthens
every conclusion, so the result is not an artefact of the matching rule.

## Unique-outcome top-k

`recall_at_budget` counts label hits, and the matcher is many-to-one, so several
candidates pointing at one event count several times. An analyst reading a list of 100
finds distinct events, not hits. Duplication ratio is hits per distinct outcome.

| matching | budget | unique recall | duplication ratio |
|---|---:|---|---|
| many-to-one | 25 | 0.252 [0.224, 0.288] | 1.042 [1.023, 1.063] |
| many-to-one | 50 | 0.390 [0.339, 0.445] | 1.156 [1.111, 1.185] |
| many-to-one | 100 | 0.602 [0.555, 0.650] | 1.366 [1.308, 1.379] |
| one-to-one | 25 | 0.208 [0.190, 0.234] | 1.000 [1.000, 1.000] |
| one-to-one | 50 | 0.322 [0.283, 0.375] | 1.000 [1.000, 1.000] |
| one-to-one | 100 | 0.503 [0.466, 0.552] | 1.000 [1.000, 1.000] |

At budget 100 the shipped metric overstates distinct events recovered by about 37%. At
budget 25 it is nearly exact. Duplication grows with the budget, so the bias is largest
exactly where the review list is longest.

## Effect on the e2e_v1 control

The control's configuration is untouched and its pre-change report is frozen at
`research/controls/e2e_v1_control_cb34f9b.json`. Re-running it after this change
nevertheless produces a different `report_hash`, and the cause is worth recording.

`code_hash()` hashes the whole `src/pramaanx` tree; `snapshot_hash` includes it; and
`ForecastRecord.build_id` derives `forecast_id` from `snapshot_hash`. Because
`recall_at_budget` breaks probability ties by position in a list sorted on
`forecast_id`, **adding any module to the package reshuffles ties at the budget
boundary**. Measured effect on the control:

- every per-fold and pooled probability metric — Brier, log loss, ROC AUC, skill, ECE,
  calibration slope and intercept — is **bit-identical**;
- candidate recall and status counts are **bit-identical**;
- **7 of 36 budget cells moved by one hit**.

This is a latent reproducibility defect, not a consequence of this experiment: no
budgeted metric in the repository is stable across any source change. A fix would break
ties on a code-independent key such as `(event_type, region, actor)`. That change would
itself perturb the control, so it is left as a decision rather than applied here.
