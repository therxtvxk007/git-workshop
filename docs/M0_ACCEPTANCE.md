# M0 acceptance criteria

One milestone, explicit tests, then stop. Each deliverable below names the code
that implements it and the tests that hold it to account.

Run everything: `make check` — ruff, mypy, and 270 tests with an enforced
coverage floor.

| Suite | Tests | What it covers |
| --- | ---: | --- |
| `tests/unit` | 138 | Hashing, storage, config, HTTP/proxy, connectors, generator, recency, matcher, metrics, extraction |
| `tests/contracts` | 49 | Schema round-trips, validation, versioning, configuration typos |
| `tests/leakage` | 24 | `CutoffGuard`, snapshot immutability, leakage audit |
| `tests/metamorphic` | 8 | Future-document injection, determinism, chunk invariance |
| `tests/integration` | 51 | Full pipeline, outcome isolation, censoring, backtest reproducibility, CLI, `make demo` |
| `tests/network` | 1 | Live GDELT fetch. Opt-in, excluded from CI (`-m "not network"`) |

Counts are from `pytest --collect-only`; 270 offline plus 1 opt-in network test.

---

## 1. Clean repository

**Implementation** — `pyproject.toml`, `Makefile`, `configs/`, `.env.example`,
`.gitignore`, `LICENSE`.

**Accepted when** — `uv sync --frozen --extra dev` installs from the lock file,
`make check` runs lint, types and tests behind a coverage floor, `make demo`
runs end to end offline from a fresh clone, and no credential or licensed datum
is committed (`data/**` is git-ignored; credentials live in `.env`, which is not).

`tests/integration/test_make_demo.py` does not re-implement the demo: it *reads
the recipe out of the Makefile* and runs it, so the documented entry point
cannot drift from what is tested. It also checks the two things that actually
broke it — an argument the bootstrap script never accepted
(`test_bootstrap_accepts_every_documented_argument`) and an ingestion window too
short for the final fold (`test_ingestion_window_outruns_the_final_fold`).

## 2. The five core schemas

**Implementation** — `src/pramaanx/schemas/`: `Observation`, `EventMention`,
`EventHypothesis`, `ForecastRecord`, `OutcomeRecord`.

**Accepted when** — `tests/contracts/test_schemas.py`:

- every persisted record round-trips through JSON losslessly, sets included;
- naive datetimes are **rejected**, not assumed to be UTC
  (`test_naive_datetime_rejected`);
- offsets normalise to UTC (`test_offsets_normalise_to_utc`);
- categorical distributions must sum to 1 or be empty
  (`test_distribution_must_sum_to_one`); an empty one means "no opinion";
- unknown fields are rejected (`extra="forbid"`);
- a forecast without a snapshot hash cannot be constructed
  (`test_forecast_requires_snapshot_hash`);
- an outcome cannot resolve before it occurs;
- every record carries a `schema_version`, and an older version survives a
  round-trip unchanged (`TestVersioning`).

## 3. Content-hashed Parquet storage

**Implementation** — `src/pramaanx/hashing.py`, `src/pramaanx/storage.py`.

**Accepted when** — `tests/unit/test_hashing.py`, `tests/unit/test_storage.py`:

- canonical JSON is key-order independent and timezone-normalising;
- `stable_id` depends only on content — never `uuid4`, never a wall clock
  (`test_stable_id_depends_only_on_content`);
- object hashes are stable across processes, which rules out Python's salted
  built-in `hash()` (`test_hash_object_is_stable_across_processes`);
- the payload store is content-addressed: the same bytes are stored once, and
  mutation is detectable (`test_verify_detects_mutation`);
- appending the same records twice writes nothing new
  (`test_appending_the_same_records_twice_is_a_no_op`);
- identical batches produce identical file names — layout determinism is what
  makes byte-level comparison of runs possible.

## 4. `CutoffGuard`

**Implementation** — `src/pramaanx/timeguard/`.

**Accepted when** — `tests/leakage/test_cutoff_guard.py`,
`tests/leakage/test_snapshots_and_audit.py`:

- `first_observed_at <= cutoff_at` admits, `>` rejects, `==` admits;
- retrieval long after the cutoff is **normal**, not leakage — a historical
  backtest necessarily fetches its evidence today
  (`test_retrieval_long_after_the_cutoff_is_normal`);
- publication after the cutoff on a supposedly older document is rejected: the
  stored body is not the body that existed at the cutoff;
- strict mode **raises** rather than dropping, because a silently dropped
  record looks exactly like a thin news day (`test_strict_mode_raises_rather_than_dropping`);
- skew allowance is zero by default and must be granted explicitly;
- snapshot manifests carry sorted observation hashes, source versions, code hash
  and config hash (`test_manifest_carries_the_required_provenance`);
- the snapshot hash ignores creation time
  (`test_snapshot_hash_ignores_creation_time`);
- loading a snapshot detects a ledger that changed underneath it.

## 5. Synthetic and GDELT connectors

**Implementation** — `src/pramaanx/ingest/connectors/`.

**Accepted when** — `tests/unit/test_gdelt_connector.py`,
`tests/unit/test_connector_base.py`, `tests/metamorphic/`:

- GDELT's `first_observed_at` is the export slot plus publication lag, **not**
  `SQLDATE`, which would back-date every row
  (`test_first_observed_at_is_publication_not_event_date`);
- protected-attribute columns (ethnic, religion) are never read
  (`test_protected_attribute_columns_are_never_read`);
- a connector returning an out-of-window item is a hard error
  (`test_out_of_window_items_are_a_hard_error`);
- missing archive files are skipped and logged, not fatal;
- planning requires no network (`test_plan_needs_no_network`);
- the synthetic world is deterministic and chunk-invariant: ingesting one window
  or three yields an identical ledger (`test_ingestion_is_chunk_invariant`);
- re-ingesting a window writes nothing new
  (`test_reingesting_the_same_window_writes_nothing_new`).

Only two connectors are registered (`test_m0_registers_exactly_two_connectors`).
The other Tier-0/Tier-1 sources are **absent, not stubbed**: an empty connector
is indistinguishable from a quiet source, and that confusion would corrupt base
rates.

## 6. Base-rate generator (G0)

**Implementation** — `src/pramaanx/generators/`.

**Accepted when** — `tests/unit/test_base_rate_generator.py`:

- it satisfies the `CandidateGenerator` protocol structurally;
- time buckets are contiguous — reading printed bucket starts literally would
  leave uncovered gaps and the probabilities would not sum to one
  (`test_buckets_are_contiguous`);
- rare streams are shrunk toward a pooled prior, not zeroed and not inflated by
  a single sighting (`test_rare_streams_are_shrunk_not_zeroed`);
- only events that already occurred contribute to a rate, and events after the
  cutoff never do (`test_events_after_the_cutoff_are_excluded`);
- forward-looking chatter raises the score, and denials are retained as
  *contradicting* evidence rather than discarded;
- streams with no history still receive a candidate — a generator that can only
  predict repeats would never see anything new;
- output is deterministic under input reordering (`test_output_is_deterministic`);
- every proposal carries a trace with the posterior rate, the historical count
  and a credible interval.

## 7. Rolling-backtest skeleton

**Implementation** — `src/pramaanx/evaluation/`, `src/pramaanx/pipeline.py`,
`src/pramaanx/ledger/`.

**Accepted when** — `tests/integration/test_end_to_end.py`,
`tests/unit/test_matcher_and_metrics.py`:

- forecasts for cutoff T are written **before** any outcome is read, and only
  outcomes occurring after T are scored
  (`test_scored_outcomes_all_postdate_their_cutoff`);
- no candidate cites evidence outside its snapshot
  (`test_no_candidate_uses_post_cutoff_evidence`);
- **identical inputs reproduce identical reports** — the Phase 3 gate
  (`test_identical_inputs_reproduce_identical_reports`);
- the forecast ledger is append-only (`test_forecast_ledger_is_append_only`);
- the matcher's hard constraints cannot be overridden by a high soft score: a
  wrong location, wrong actor or wrong window never matches
  (`TestMatching`);
- rare-event edge cases are reported as undefined rather than faked — ROC AUC
  and calibration slope return `None` on a single-class fold
  (`test_roc_auc_undefined_with_one_class`).

## 7a. Outcome isolation (structural)

**Implementation** — `src/pramaanx/isolation.py`, `Backtester.forecasting_pass`
and `Backtester.scoring_pass`.

The ordering rule used to be enforced by the order of two statements in one
function. That is a convention, and conventions last until someone adds a line
in the wrong place — at which point nothing announces itself and the run simply
gets better. The rule is now enforced by the runtime: during the forecasting
pass, a context variable seals every outcome-reading entry point
(`EvidenceLedger.read_outcomes`, `read_resolved_events`, `write_outcomes`,
`build_outcome_registry`, `OutcomeMatcher.score`), and any access raises
`OutcomeAccessError` however deep in the call stack it happens.

**Accepted when** — `tests/integration/test_outcome_isolation.py`:

- pass A runs against a ledger that raises on any outcome access, and completes
  (`test_forecasting_pass_never_touches_outcomes`);
- what crosses between passes carries no outcome data — `CutoffPlan` has exactly
  five fields (`test_pass_a_output_carries_no_outcome_data`);
- pass B re-reads forecasts **from the ledger**, so what is scored is provably
  what was persisted before outcomes existed
  (`test_scoring_pass_reads_forecasts_back_from_the_ledger`);
- the seal releases on the way out, including on an exception;
- observations stay readable inside the seal — it must not block the evidence
  the forecasting pass legitimately needs.

## 7b. Right-censored evaluation

**Implementation** — `ResolutionBoundary`, `measure_resolution_boundary`,
`CensoredEvaluationError`, `evaluation.max_reporting_delay_days`.

A fold whose evidence stops before `cutoff + horizon + reporting delay` has not
seen the reports that would resolve it. Score it anyway and the missing reports
look exactly like events that never happened.

**Accepted when** — `tests/integration/test_censoring.py`:

- the delay allowance is the larger of the configured floor and the maximum
  actually observed in the registry (`test_delay_is_the_larger_of_configured_and_observed`);
- short folds are marked unscoreable with the shortfall stated in days, and are
  excluded from the aggregate — but are still forecast, because censoring is an
  evaluation limit, not a reason to skip the work;
- a walk with no scoreable fold raises `CensoredEvaluationError` rather than
  emitting a report of artefacts (`test_a_wholly_censored_walk_fails_loudly`);
- the report names the censored folds and says so in its interpretation limits;
- the shipped experiments fit inside the demo ingestion window
  (`TestShippedExperimentsAreNotCensored`).

## 8. Future-leakage tests

**The M0 gate.** `tests/metamorphic/test_future_injection.py`:

> Inject correctly-labelled future documents into the physical data directory.
> Forecast outputs for cutoff T must remain byte-identical, because the snapshot
> excludes them.

- `test_future_documents_do_not_change_a_past_snapshot` — same snapshot hash,
  same observation hashes, same count;
- `test_forecasts_are_byte_identical_after_injection` — canonical bytes of the
  full forecast set are unchanged.

Two negative controls stop this passing for the wrong reason:

- `test_injection_is_visible_at_a_later_cutoff` — the same documents *do* change
  a later cutoff, so the injection was real;
- `test_backdated_evidence_does_change_the_snapshot` — evidence that lies about
  its observation time **is** admitted, which is precisely why back-dating is a
  leak the ledger cannot catch alone, and why the auditor screens for duplicate
  content across dates.

## 9. CI, Ruff, type checking, Pytest

**Implementation** — `.github/workflows/ci.yaml`, `Makefile`, `pyproject.toml`.

**Accepted when** — two jobs pass: `quality` (ruff check, ruff format --check,
mypy, pytest with `--cov-fail-under=88`) and `m0-gate` (leakage + metamorphic +
contract suites verbosely, then `make demo`). Network-marked tests are excluded
from CI: a green build must never mean "GDELT happened to be reachable".

The coverage floor is **enforced**, not reported. CLI coverage is measured
honestly rather than excluded: the CLI suite runs in-process through Typer's
`CliRunner`, so its lines count, and only two subprocess tests remain — the ones
that prove the installed console script exists, which is a packaging fact, not a
code path.

CI tests Python 3.13 and nothing else. See
[docs/python_versions.md](python_versions.md) for why 3.14 is not in the matrix
and what would have to be true to add it.

## 10. Documentation

**Implementation** — `README.md`, this file, `research/preregistration.md`,
module docstrings.

**Accepted when** — the README states what M0 does *not* contain as
prominently as what it does, and every report emitted by the system leads with
its interpretation limits (`test_reports_state_their_limits`).

---

## What passing M0 does not establish

Worth stating plainly, because the suite above is green and green is
persuasive:

- **No forecasting skill has been demonstrated.** The demo runs on a synthetic
  world. Its numbers describe machinery, not reality.
- **No probability is calibrated.** Every forecast records
  `calibration: identity@uncalibrated`.
- **No miss-rate is controlled.** Statuses come from fixed thresholds recorded
  as `fixed_threshold@placeholder`. The miss-versus-false-alert trade-off is a
  human decision nobody has made.
- **No outcome is adjudicated.** The registry is machine-derived; every record
  is `PENDING` and every report states the unadjudicated fraction.
- **The matcher is unvalidated.** It must be checked against blinded dual-human
  labels before any headline number is believed.
- **Leak-freedom is not proven.** The audit catches mechanical leaks. Model
  memorisation, prompt contamination and label bleed need the counterfactual
  and prospective tracks.

## Next assignment

Phase 1, in isolation: the point-in-time evidence ledger against real sources.
ACLED, ReliefWeb/HDX and data.gov.in connectors under their access terms, plus a
frozen English news corpus. Same gate as M0 — future-document injection changes
no pre-cutoff snapshot, and every record carries provenance and a hash.
