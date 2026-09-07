# Executing the PRAMAAN-X code plan — what is built, and what is not

The plan is 43 sections and 19 research stages. This document records which
part of it this work executes, which test proves each claim, and what remains
absent. Absent, not stubbed: a module that returns plausible-looking output is
worse than a missing one, because it makes a skipped requirement look finished.

The plan itself says where to start. Section 26.4 sets the order — fix the
panel contract first, add the model registry before the first LLM call — and
sections 40 and 41 turn that into engineering increments E0 to E4 and a first
month of work. That is the scope executed here.

---

## What was built

| Plan section | Delivered | Where |
| --- | --- | --- |
| S28–S30, S36.2–S36.3 | Revisions, chronology contexts, the as-of store, artifact keys, named RNG streams | `src/pramaanx/core/` |
| S2, S29.2, S34.1 | Source tiers, recorded approvals, the parameter-cutoff gate | `src/pramaanx/registry/` |
| S3, S31.2 | Versioned district rosters and crosswalks with unresolved mass | `src/pramaanx/geo/` |
| S4, S26.1, S29.1, S31.1, S31.3 | Families, windows, calendars, the panel grid, nullable outcomes | `src/pramaanx/panel/` |
| S32, S42 | Path and window samples, capability manifests, the forecast artifact | `src/pramaanx/models/` |
| S11 (rungs 1–5) | zero, climatology, persistence, hist12, empirical Bayes | `src/pramaanx/models/ladder/` |
| S15, S32.2, S33.3 | Proper scores that keep their endpoints; run lints | `src/pramaanx/verify/` |
| S16, S33.1–S33.2 | Role manifests, purge, the one-shot lockbox | `src/pramaanx/protocol/` |
| S36.1 | Durable run attempts, recorded before the work starts | `src/pramaanx/runtime/runner.py` |
| S18 (partial) | A generated world with reporting delay | `src/pramaanx/simlab/` |
| S39, S41 | The composed offline run and its CLI surface | `src/pramaanx/runtime/offline.py`, `pramaanx offline run` |

Run it:

```bash
uv run pramaanx offline run --root runs/offline --seed 0
uv run pramaanx store verify --root runs/offline
uv run pramaanx store recover --root runs/offline
```

No network, no credentials, deterministic given the seed. The manifest it
prints carries a `claim` field saying what the numbers are worth, which is:
nothing about real forecasting skill. It is a generated world.

---

## The five defects the plan's own review found

Section 26.1 lists five defects the paper had and the plan repaired on paper.
Each is now closed in code, with the test that proves it.

| # | Defect | Closed by | Test |
| --- | --- | --- | --- |
| 1 | `parameter_cutoff` was a field nothing read | `registry.models.may_use_model` | `tests/registry/test_gates.py::test_a_model_trained_past_the_origin_is_blocked` |
| 2 | The VIEWS comparator scores fatalities; nothing emitted them | **not closed** — `Capability.FATALITIES` is declared unsupported by every rung | `tests/models/test_ladder.py` capability assertions |
| 3 | CAST is a 28-day Friday-aligned rolling window, not a month | `panel.windows.cast_periods` | `tests/panel/test_families_and_windows.py::test_cast_periods_are_28_days_and_end_on_fridays` |
| 4 | The three families overlap and no counting rule existed | multi-label union counting | `tests/panel/test_families_and_windows.py::test_a_shared_incident_counts_once_in_each_family_and_once_in_the_union` |
| 5 | "Explicit zeros" was ambiguous | `y_observed` nullable plus a scoped lint | `tests/panel/test_grid_and_outcomes.py::test_an_outage_produces_unknown_labels_not_zeros` |

Defect 2 is deliberately open. A severity head is a model, not an adapter, and
`models/severity.py` is not built. Declaring the capability unsupported means a
run that needs fatalities fails loudly instead of scoring event counts against
a fatality contract.

---

## The P0 rows of the revision's own defect table

Section 27.1 lists fourteen defects, eleven of them P0. Where each stands:

| Weakness | Status | Evidence |
| --- | --- | --- |
| One timestamp filter and one test claimed to prove no leakage | Closed | `tests/core/test_asof_store.py`, eleven named tests |
| A batch-level `available_time` could overwrite row history | Closed | availability is a field on `Revision`; `write` takes no batch stamp |
| Corrections and deletions had no ordering contract | Closed | `test_a_tombstone_does_not_resurrect_the_row_it_deleted` |
| The full grid could be mistaken for observed labels | Closed | `test_an_outage_produces_unknown_labels_not_zeros` |
| Training and verification shared an ambiguous snapshot rule | Closed | `FitContext` / `ScoreContext`, `read_mature` vs `read_reference` |
| A pytest fixture was the ledger enforcement mechanism | Closed | `RunManager`; `test_a_killed_process_leaves_a_visible_running_row` |
| Daily samples were assumed to solve every output contract | Closed | capability manifests; `test_a_window_only_rung_refuses_a_different_window` |
| Zero comparator conflicted with the zero-probability lint | Closed | `diagnostic_zero_baseline`; `test_the_declared_zero_baseline_is_exempt` |
| Monte Carlo could turn a rare probability into a hard zero | Closed | `test_a_sampled_zero_is_not_a_claim_of_impossibility` |
| Two CLI commands could write concurrently | Closed | writer lock; `test_a_second_writer_fails_within_a_bounded_wait` |
| Seed alone treated as reproducibility | Closed | `RandomStreams`, `ArtifactKeyInputs`, `Environment` on every attempt |
| Translation and extraction cached only by content | Not reached | `text/` is not built |
| Tests used incorrect leakage criteria | Closed | invariance **and** boundary-crossing tests, per S38 |
| Deep interfaces scheduled before foundations | Closed | build order E0→E4 followed |

---

## Three findings the tests produced

These were not in the plan. They came out of running it.

**Persistence asserts impossibility.** With its degenerate distribution
declared as analytic rather than sampled, the no-hard-zero lint flags every
quiet cell persistence forecasts. That is correct and it is a finding about the
model: persistence is a point forecast and a point forecast at zero claims an
event cannot happen. The offline run records it rather than suppressing it.

**An infinite log loss is not JSON.** The canonical serialiser rejects
non-finite floats on purpose — a NaN inside a hashed config would let two
different configs hash the same — but an infinite log loss is a result. So
`ScoreResult.to_dict` writes `value: null`, `value_repr: "inf"` and a
`non_finite` state, which loses nothing.

**A predictive stream keyed on the input manifest is not invariant.** Seeding
on the full forecast context meant appending *post-cutoff* rows changed the
manifest hash, which reseeded the sampler, which moved a forecast that evidence
could never have informed. The stream is now keyed on
`ModelArtifact.parameter_identity` — model, parameters, training rows — which
depends only on eligible data.

---

## What is not built

Absent by decision, in the plan's own order:

- **`snapshot/`** — collectors and the archiver. The repository's existing
  `ingest/` connectors cover GDELT, ReliefWeb, data.gov.in and ACLED against
  the older evidence ledger; they are not yet routed through the as-of store.
- **`delay/`** — the reporting triangle and the discrete hazard. `simlab`
  generates delay so the store can be exercised; nothing estimates it.
- **`text/`, `genealogy/`, `audit/`** — no extraction, no linkage, no gold
  sample. The plan puts these at stages 8–11 and they need the earlier stages
  to be real first.
- **`features/`** — no feature builders, so the boundary-crossing test for
  features (S38) has nothing to run over yet.
- **Ladder rungs 6–12**, every `models/hier/` model, every challenger, the
  severity head, `joint/`, `ensemble/`, `decision/`, `report/`, `redteam/`.
- **`verify/`** beyond scores and lints: no decomposition, bootstrap, model
  confidence set, subgroup reporting, headroom or factorial ablation.
- **Contract YAMLs.** The twelve benchmark contracts of S2 are not written, so
  `registry check` cannot yet fail honestly on an unpinned comparator.

## What no amount of code here can supply

Unchanged from the plan's section 24. Retrospective snapshots for news and
official sources do not exist unless somebody archives them, and the archiver
has not started. The gold audit is human time. No source in this repository has
a recorded collection approval, so `may_collect` refuses every one of them,
which is the correct state and not a bug to work around.
