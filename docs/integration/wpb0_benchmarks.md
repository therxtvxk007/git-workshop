# WP-B0 — benchmark registry and exact-reproduction harness

**Status: harness complete, zero reproductions run, all thirteen contracts
`contract_incomplete`.**

This package builds the referee, not a player. It defines the contracts that
HydraNet, STK-Adapter, DyMRL, MemoTime and CPTC challengers must satisfy before
any of them may be described as reproduced, challenged or exceeded. None of
those models is implemented here, and none must be until its contract is
complete.

## What it is

```
research/benchmarks/registry.yaml     index
research/benchmarks/contracts/        13 contracts, one YAML file each
research/benchmarks/reproductions/    run manifests (empty)
src/pramaanx/benchmarks/              the harness
configs/benchmarks/default.yaml       paths and the reproduction protocol
```

The command surface is `python -m pramaanx.benchmarks`. It is deliberately
**not** registered on the main `pramaanx` CLI; a later integration package can
mount it once there is something to mount. `tests/contracts/test_benchmark_registry.py`
asserts that it has not been.

```
python -m pramaanx.benchmarks list
python -m pramaanx.benchmarks validate
python -m pramaanx.benchmarks show <benchmark_id>
python -m pramaanx.benchmarks verify-source <benchmark_id>
python -m pramaanx.benchmarks plan <benchmark_id>
python -m pramaanx.benchmarks reproduce <benchmark_id>
python -m pramaanx.benchmarks compare <benchmark_id> --control-run … --challenger-run …
python -m pramaanx.benchmarks report <benchmark_id>
```

Every command takes an explicit `--registry` path, emits canonical JSON under
`--json`, produces deterministic output, refuses to overwrite an existing
artefact, and exits `3` when a benchmark is blocked. Anything that would execute
third-party code defaults to `--dry-run`, and a dry run performs no network
access, no clone, no download, no container execution and no filesystem write —
enforced by `DryRunGuard`, and asserted by observing that the executor records
zero calls.

## Source verification: what was actually checked

The environment this registry was built in refuses outbound traffic to
`arxiv.org`, `aclanthology.org` and `journals.sagepub.com` at the egress proxy.
GitHub is reachable. So repositories could be verified and **papers could not**.

That asymmetry is the single most important fact about this registry, and it is
recorded per field rather than smoothed over.

| Benchmark | Repository | Licence | Commit | Published score |
|---|---|---|---|---|
| `hydranet_views_*` (×3) | ✅ `views-platform/views-hydranet` | ✅ MIT (code) | ❌ no paper-linked tag | ❌ unverified |
| `views_fatality_distribution` | ✅ `prio-data/prediction_competition_2023` | ❌ none found | ❌ no tag | ❌ none recorded |
| `stk_adapter_*` (×4) | ❌ none exists | ❌ | ❌ | ❌ unverified |
| `dymrl_multimodal_tkg` | ❌ none found | ❌ | ❌ | ❌ none recorded |
| `memotime_temporal_reasoning` | ✅ `SteveTANTAN/MemoTime` | ❌ NOASSERTION | ❌ no tag | ❌ none recorded |
| `cptc_conformal` | ✅ `Rose-STL-Lab/CPTC` | ⚠️ MIT per README only | ❌ no tag | ❌ none recorded |
| `distribution_aware_conformal` | ❌ names a research area, not a benchmark | ❌ | ❌ | ❌ none recorded |
| `india_district_30d` | ✅ this repository | ✅ ACLED forbids redistribution | ❌ pinned at freeze | n/a — internal track |

Verified directly, from the repositories themselves:

- **views-hydranet** — exists, MIT, default branch `main`, README names
  `pyproject.toml`, `poetry.lock` and `environment.yml`. Its README's paper link
  is a placeholder. Its only tag is `archive/vpc-3.0.0-from-git`
  (`fa10327aa5a742f88d31499e15794835472e04ee`); HEAD at verification time was
  `fb1af9a7670b8fff0daa14f27d33065b83fd87ce` (2026-08-15). **Neither is evidence
  of the commit the published results came from**, so `official_commit` is null
  with a blocker recording both observations.
- **prediction_competition_2023** — exists, metrics named verbatim in the README
  as `crps`, `ign` and `mis`; aggregation levels country-month (`cm`) and
  PRIO-GRID-month (`pgm`); retrospective windows Y2018–Y2021; entrypoint
  `python -m evaluation.evaluate_submissions -s … -a …`. Replication data is
  distributed through a Dropbox link, not a versioned hashed release, which is
  itself a blocker: a run against it cannot be shown to have used the same bytes
  twice.
- **MemoTime** — exists, not a fork, `main`, created 2026-02-18, last pushed
  2026-06-15, licence reported by GitHub as `NOASSERTION`. Datasets MultiTQ and
  TimeQuestions.
- **CPTC** — exists, `main`, `requirements.txt`, six datasets named in the
  README, entrypoint `python run_all_baselines.py --methods REDSDS CP ACI CPTC
  AgACI DtACI MVP`. MIT is stated in the README; the `LICENSE` file itself was
  not read, and the Bee/Electricity/Traffic datasets carry separate terms.
- **STK-Adapter and DyMRL** — no official code release found for either.
  Searches of the arXiv listings, the ACL anthology entry and GitHub returned
  none. Without released code these are re-implementation targets, not
  reproduction targets, and that is a categorical difference the registry
  records with `BlockerCode.NO_OFFICIAL_CODE`.

Source verification never executes downloaded code, under any mode. Verifying a
repository by running its setup script would make the verification step an
arbitrary code execution step. No external repository is vendored into this
commit; `configs/benchmarks/default.yaml` points third-party caching at
`.cache/benchmarks`, which is git-ignored.

## The published gates are recorded as claims, not facts

The brief supplied HydraNet/VIEWS and STK-Adapter gate values and asked that
they be verified against primary sources before acceptance. They could not be:
the primary sources are egress-blocked. They are therefore recorded with
`verified_against_primary: false`, a `verification_note` naming the block, and a
blocker on `published_score` — which is what forces every one of those contracts
to `contract_incomplete`. The strict rule
`published_score_verified` treats a number quoted from a design document as *not*
a published score, exactly as the brief requires.

Two specific findings worth carrying forward:

- **A conflict in the one-sided violence figure.** The brief gives average
  precision `0.162`. A secondary summary of the same paper reports `0.138`, and
  attributes it to VIEWS rather than to HydraNet. The two cannot be reconciled
  without the paper's table, and it is not established which system either number
  describes. Both are recorded in `hydranet_views_one_sided.notes`; neither is
  silently preferred.
- **The STK-Adapter scale is inferred, not read.** The brief asks explicitly
  whether the paper reports percentages or fractions. Hit@k is bounded in [0,1]
  as a fraction and the reported values exceed 1, so the table must be in
  percent — but that is an inference from the metric's definition, not a reading
  of the paper, and it is labelled as such. If it is wrong, every tolerance on
  those four contracts is off by two orders of magnitude, so it is a blocker
  rather than a footnote.

Also unresolved for STK-Adapter: whether its ranking protocol is time-aware
filtered or raw. The two give materially different Hit@1, so it blocks the
contract rather than being deferred.

## The India contract

`india_district_30d` is this project's own track, not a reproduction of anyone's
paper. The harness knows the difference: `is_internal_track` exempts it from
needing a published score, and caps its strongest honest status at `running` —
it can never reach `reproduced`, because there is nothing to have reproduced.

It specifies the unit (district × monthly cutoff × event family), a 30-day
horizon, both targets (occurrence and count), the three event families
(terrorism, left-wing extremism, insurgency), average precision as the primary
metric, and all thirteen secondary metrics with directions. Four windows are
declared — expanding training, model selection, calibration, and a frozen final
test — because a calibrator fitted on the selection window inherits its selection
bias.

**Every date is blocked**, with `BlockerCode.AWAITING_MEASUREMENT`. They depend
on measuring real-data completeness per source, which has not been done. The
brief says not to invent them, and a fabricated window would make every number
downstream unfalsifiable.

The reporting-delay rule, the historical effective-dated district universe, and
the final-test access policy are all recorded on the contract.
`redistribution_allowed` is `false`: ACLED's terms forbid it, so data may be
cached locally for a run but never committed or republished.

## Test-set isolation

`FinalTestLedger` seals the frozen period. Before opening: test labels cannot be
loaded, the test metric command refuses to run, and challenger selection cannot
read test results — the last of those is refused *even after* opening, because a
selection informed by the test period is the post-test tuning that invalidates a
result.

Opening requires a frozen contract hash, frozen model artefact hashes, frozen
prompt/config hashes and a one-time authorisation record. It cannot happen
twice. Afterwards, `detect_post_test_changes` names every artefact that has moved,
and any movement drives the benchmark to `invalidated` — a definite verdict, not
a softening to "incomplete". A second run is recorded as a rerun via
`is_rerun_of`; it never replaces the first.

## What "exceeded" requires

Eight gates, each recorded with its own verdict so a refusal can always name
itself:

1. the control reproduced the published score inside tolerance;
2. the challenger was evaluated on identical units;
3. the primary metric moved in the declared direction;
4. the paired confidence interval excludes *no improvement*;
5. the declared secondary protections pass;
6. the minimum seed count was met;
7. test period and metric code were identical;
8. no post-test tuning is recorded.

Comparisons are paired wherever units can be paired — two models scored on the
same district-months are one sample scored twice, not two independent samples.
Contracts over temporally dependent units declare a block length and get a
moving-block bootstrap; `tests/unit/test_benchmark_statistics.py` asserts that
this genuinely widens the interval relative to the i.i.d. bootstrap on
autocorrelated data, which is the reason it exists.

## First reproduction: blocked, and by what

No official benchmark in this registry is currently both legally downloadable
and computationally feasible here.

`cptc_conformal` is the closest and is the recommended first target: CPU-only,
small datasets, code released under a README-stated MIT licence, and a clear
entrypoint. It is blocked on two things, neither of them compute:

- the `LICENSE` file and the separate Bee/Electricity/Traffic dataset terms have
  not been read, so automatic acquisition is refused;
- no commit is pinned, and the data arrives via a Dropbox link rather than a
  hashed release.

The host itself is a further, independent blocker for the GPU benchmarks. The
environment probe reports no NVIDIA driver and 4 CPU cores, so
`hydranet_views_*`, `stk_adapter_*`, `dymrl_*` and `memotime_*` are additionally
`compute_unavailable`. That is reported as a blocker rather than worked around.

`python -m pramaanx.benchmarks reproduce cptc_conformal` refuses and names all
four blockers. **No reproduction has been run, and nothing in this package
claims otherwise.** The synthetic fixture in `tests/fixtures/benchmarks/`
exercises the harness; it describes a benchmark that does not exist, says so in
its own notes, and proves nothing about any published model.

## Unblocking, in order

1. Read the primary sources for the eight published-score gates and set
   `verified_against_primary`, or correct the values. This alone moves nothing to
   `reproduced`, but it is the precondition for everything else.
2. Read the CPTC `LICENSE` and dataset terms; pin a commit; hash the data. That
   is the shortest path to a first real reproduction.
3. Resolve the HydraNet one-sided 0.162/0.138 conflict and identify the
   paper's commit and data version.
4. Establish whether STK-Adapter and DyMRL have code anywhere. If they do not,
   reclassify them from reproduction targets to re-implementation targets — a
   different and weaker kind of claim, which the registry should say out loud.
5. Measure real-data completeness for the India sources, then fix the four
   windows and freeze the contract.
