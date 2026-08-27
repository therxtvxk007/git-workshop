# PRAMAAN-X checklist status — what is done, what remains, split two ways

Audit date: **2026-08-27**. Evidence: the GitHub repository state of
`therxtvxk007/git-workshop` on that date — branch list, pull requests, tags,
Actions runs 1–25, and the trees of `main`,
`claude/forecasting-roadmap-completion-pq1tey` and
`claude/pramaan-x-phase2-downstream`.

Every status below is sourced from something checkable, not from a branch's own
claims about itself. Where a branch asserts a capability that has never been
executed, it is recorded as **written, unverified** — which is not *done*.

---

## 1. Repository state, as observed

| Fact | Observed value |
| --- | --- |
| `main` | `a98fa0d` — PR #1 only. M0 and nothing else. |
| Tags in the repository | **none** |
| Branch protection on `main` | **off** (`protected: false`) |
| Open PRs | #2 (Codex plugin), unrelated to PRAMAAN-X |
| Phase 1 integration branch | `claude/forecasting-roadmap-completion-pq1tey` @ `37ecf03`, 18 commits ahead, **CI green** (run 24) |
| Phase 1 mergeability | **fast-forward onto `main`**, no conflicts |
| Phase 2 branch | `claude/pramaan-x-phase2-downstream` @ `bc64856`, 2 commits, **CI red** (run 25) |
| Phase 2 file overlap with Phase 1 | **zero** — the two diffs touch disjoint file sets |
| `live-gdelt.yaml` workflow runs | **0** — the live smoke has never been executed |

### The Phase 2 CI failure is smaller than the checklist assumes

Run 25 (`bc64856`) fails on the **first** step, `ruff check`: 10 lint errors, 3
auto-fixable, the rest import-ordering and one unused unpacked variable
(`RUF059` in `tests/unit/test_scenarios.py:73`). Format, mypy and the test suite
were **skipped**, not failed — so the branch's own admission that no test in it
has ever run still stands, on both Python 3.13 and 3.14.

Two corrections to the checklist's Stage 3.2 assumptions:

- **The M0 acceptance gate already passes on Phase 2** (run 25, job "M0
  acceptance gate": leakage + reproducibility gates and `make demo` both green).
  There is no M0 failure left to diagnose; only *keeping* it green matters.
- Ruff is the whole visible blocker. What mypy, the six unit modules and the
  coverage floor do once lint clears is **unknown**, not known-bad.

---

## 2. Stage scoreboard

`DONE` = observed working. `WRITTEN` = code exists, never executed or never
wired in. `PARTIAL` = some items closed, most open. `OPEN` = nothing in the repo.

| Stage | Status | One-line reason |
| --- | --- | --- |
| 1.1 Protect M0 baseline | **PARTIAL** | Acceptance doc + gate exist; **no tag, no branch protection, no review rule** |
| 1.2 Merge Phase 1 | **OPEN** | Branch is green and fast-forwardable; **PR never opened** |
| 2.1 Live source verification | **PARTIAL** | data.gov.in verified 2026-08-27; ReliefWeb and ACLED **not**; GDELT smoke never run |
| 2.2 Missing evidence sources | **OPEN** | No news corpus of any kind in the repository |
| 2.3 Source replay system | **PARTIAL** | Bronze ledger + content-hashed snapshots exist; no replay command, no replay tests |
| 3.1 Rebase Phase 2 | **OPEN** | Phase 2 sits on `main`, not on an integrated Phase 1 |
| 3.2 Repair Phase 2 quality | **OPEN** | 10 ruff errors gate everything behind them |
| 3.3 `pipeline.py` integration | **OPEN** | Phase 2 does not touch `pipeline.py` at all |
| 3.4 CLI + config surfaces | **OPEN** | CLI has 10 commands; `graph`, `calibrate`, `adjudicate`, `scenario` are not among them |
| 4.1 Connect prose sources | **WRITTEN** | `register_prose_source()` exists; ReliefWeb and news are not registered through it |
| 4.2 Extraction gold set | **WRITTEN** | `gold.py` types and scoring exist; **no annotated data, no guidelines, no annotators** |
| 4.3 Learned extraction stages | **OPEN** | Deliberately absent — span tagger, type classifier, LLM verifier all unshipped |
| 5.1 Entity resolution | **WRITTEN** | Blocking + scored merge + stemmer; **no gazetteer, no transliteration, no human validation** |
| 5.2 Event deduplication | **WRITTEN** | Clustering + independence groups; no blinded labels, no error reports |
| 6 Evidence graph + retrieval | **WRITTEN** | `as_of()` refuses post-cutoff queries, contradictions seeded first; recall never measured |
| 7 Generator portfolio | **PARTIAL** | G0 on `main`; G1 and G6 written in Phase 2; **G2, G3, G4, G5, G7 and the union OPEN** |
| 8 Candidate adjudication | **OPEN** | No belief state, no adjudication loop, anywhere in any branch |
| 9 Trustworthy outcomes | **PARTIAL** | `PENDING` semantics + matcher on `main`; no ontology, no human adjudication interface |
| 10 Calibration | **WRITTEN** | Platt, isotonic, beta, identity implemented; never fitted, never compared, never selected |
| 11 Risk-controlled alerting | **WRITTEN** | `RecallFirstController` + conformal bound implemented; budget undecided, unintegrated |
| 12 Hypothetical input | **WRITTEN** | Four interventions + `hyp_` namespace via `stable_id`; no CLI, no API, no contamination tests |
| 13 Preregister benchmark | **PARTIAL** | `research/preregistration.md` is an explicit **draft**; nothing frozen, no hash published |
| 14 Reproduce baselines | **OPEN** | Registry holds two synthetic demo entries and supports no real claim |
| 15 Retrospective evaluation | **OPEN** | Leakage/injection tests exist for M0 only; no real folds, no real outcomes |
| 16 Prospective evaluation | **OPEN** | Not started; also wall-clock bound once it is |
| 17 API + dashboard | **OPEN** | No `api/`, no server, no interface |
| 18 Production engineering | **OPEN** | No container, no scheduler, no migrations, no monitoring, no SBOM |
| 19 Safety / legal / governance | **PARTIAL** | Protected-attribute drop at ingestion + claim discipline done; licences, red-team, audit logs, external review open |
| 20 Release gates | **OPEN** | 1 of 19 gates is even close (Phase 1 mergeable, not merged) |

**Roughly 25 of ~330 checklist items are closed.** Two of the twenty stages
have no work at all in any branch: **Stage 8 (adjudication)** and **Stage 17
(API/dashboard)**.

---

## 3. The split

The two tracks below are cut so that **two agents can work simultaneously
without touching the same files**. This is not a difficulty split or a
sequential split — it follows the seam the repository already has: Phase 1 was
upstream (connectors, ingestion, HTTP, CLI plumbing), Phase 2 was downstream
(extraction, entities, graph, generators, calibration, scenarios), and their
diffs against `main` share **zero files**.

### Gate zero — before either track starts

One task, owned by Track A, blocking both:

1. Open the PR from `claude/forecasting-roadmap-completion-pq1tey` into `main`,
   review the 18 commits as one change, merge it (fast-forward is available).
2. Tag `M0` at `a98fa0d` and `phase1-integrated` at the merge commit.
3. Turn on branch protection for `main`: require both CI jobs on 3.13 and 3.14,
   require one review for anything under `src/pramaanx/{generators,calibration,evaluation,timeguard}`.

Both tracks then branch from `phase1-integrated`. Track B's first act is the
Phase 2 rebase, which is clean by construction — the file sets are disjoint.

---

### Track A — Evidence and Platform

*Owns:* `src/pramaanx/ingest/`, `storage.py`, `ledger/`, `.github/`, source
configs, `docs/` for sources, and everything under a future `api/` and `ops/`.

*Question it answers:* **can this system get trustworthy evidence in, and can a
person safely see what comes out?**

| Stage | Work |
| --- | --- |
| **1.1 / 1.2** | Gate zero above: merge, tag, protect. |
| **2.1** | Obtain an approved ReliefWeb `appname` and run the live contract test to a pass. Create the myACLED account under the EULA, run the credentialed live test, confirm what its timestamps actually mean. Re-run the GDELT and data.gov.in smokes against merged code — GDELT's has literally never run. Pin resource IDs and schema versions; add a scheduled freshness/drift workflow; write source-contract versions into every ingestion manifest. |
| **2.2** | Acquire and freeze a legally usable English news corpus, Indian regional sources included. Store publication / retrieval / revision times separately, preserve original bytes or permitted hashes, add syndication and source-independence metadata, add source-health and missingness statistics. This is the single largest unstarted dependency in the whole project — Stages 4, 5, 6, 14 and 15 are all downstream of it. |
| **2.3** | Deterministic replay from bronze, pinned to source/config/code hash, byte-identical output. Tests for deleted, revised, delayed, duplicated and malformed records, and for outages and partial responses. Fail closed on incomplete acquisition. |
| **9** | Outcome ontology, outcome registry from delayed reports, reporting-delay distributions, right censoring, never-reported events. Build the **human adjudication interface** and dual-adjudication workflow, version every correction, keep outcomes unreadable before forecast commitment. |
| **17** | The whole API and dashboard: authenticated ingestion, snapshot, forecast, scenario, evidence/provenance, outcome-adjudication and health endpoints; rate limits; versions on every response. Dashboard shows probability with uncertainty, supporting *and* contradicting evidence, source independence, cutoff, calibration/policy versions, outages — and separates real from hypothetical runs. No maps implying tactical certainty. |
| **18** | Containerization, production store, migrations, scheduler, retry/dead-letter queues, source-health and drift monitoring, structured logs, secrets, encryption, backups and restore tests, DR, vulnerability scanning, SBOM, pinned deps, staged deploy and rollback, load testing, cost documentation. |
| **19** | Licence confirmation per source with redistribution restrictions recorded *programmatically*, human authorization before any alert leaves the research environment, audit logs on every forecast viewed or exported, permitted/prohibited use policy, red-team testing, incident response, retraction mechanism, model/data/benchmark cards, external legal review. |

---

### Track B — Inference and Evaluation

*Owns:* `src/pramaanx/{extraction,entities,graph,features,generators,calibration,scenarios,evaluation}/`,
`pipeline.py`, `research/`.

*Question it answers:* **does this system actually forecast better than the
floor, and are its numbers believable?**

| Stage | Work |
| --- | --- |
| **3.1 / 3.2** | Rebase Phase 2 onto `phase1-integrated` (clean — disjoint files). Fix the 10 ruff errors, then run format, mypy and the six unit modules plus the leakage module **for the first time** and fix what they find. Restore the coverage floor, keep the M0 gate green (it already is), add Phase 2 CI jobs. |
| **3.3** | The `pipeline.py` patch: injectable `Calibrator` and `RiskController` on `run_cutoff()`, defaulting to `IdentityCalibrator` / `FixedThresholdController`, replacing direct probability and threshold assignment, recording both versions in every forecast — and **proving byte-identical M0 forecasts** with the defaults. Keep the fixed-threshold path as a tested control arm. |
| **3.4** | Strict config blocks and the four missing CLI commands: `graph`, `calibrate`, `adjudicate`, `scenario`. `--dry-run` on every write command, a content-hashed manifest from every command, unknown options rejected. |
| **4** | Register ReliefWeb and news prose through `register_prose_source()` once Track A lands the corpus. Then the gold set — guidelines, taxonomy, two blinded annotators, separate adjudication, versioned, hashed, frozen, with an untouched final test set. Then the learned stages: span tagger, event-type classifier, constrained LLM verifier that must cite spans and may not invent fields. Measure field-level P/R/F1 by source and rarity, measure extraction-confidence calibration, freeze the cascade before final testing. |
| **5** | Versioned Indian gazetteer with legal provenance, renames and hierarchy changes, organization aliases over time, transliteration for major Indian languages. Validate merges against human labels; report false-merge and false-split **separately**. Blinded validation of event clustering; freeze thresholds before final evaluation. |
| **6** | Wire the graph in: cutoff-safe snapshots, future-edge injection tests, later-corrections tests, source-copy independence tests. Measure retrieval recall against human-labelled evidence and add the oracle-retrieval diagnostic, so retrieval failure can be told apart from reasoning failure. |
| **7** | Refit G0 pre-cutoff only. Validate and ablate G1's three rules. Then build **G2** (temporal KG model, architecture preregistered), **G3** (analogy, with retrospectives kept out of earlier searches), **G4** (change-point, reporting volume modelled separately from real change), **G5** (bounded agent, no open web during backtests, every tool call logged), **G7** (open-set novelty with abstention). Finish **G6** by wiring the existing interventions in. Then the union: dedupe across branches, keep per-generator provenance, share one budget, measure marginal recall, delete generators that only add burden, freeze before test. |
| **8** | Entirely new: versioned belief state, supporting/contradicting/neutral packs, independent corroboration distinguished from repetition, explicit unresolved states, bounded loop, logged updates, seeded multi-trial reasoning aggregated in logit space with disagreement measured, abstention on thin evidence, structured fields protected from reasoning prose. Evaluate against oracle candidates and oracle evidence, and against simpler non-LLM adjudicators. |
| **10 / 11** | Strictly earlier calibration folds, never the test period. Fit and compare identity/Platt/isotonic/beta on Brier and log loss, reliability by bin, calibration by event type / region / horizon, drift over time, minimum sample sizes enforced, choice made **before** final testing, raw scores preserved. Then the alert policy: budget and miss-vs-false-alarm cost decided (human input), thresholds fit on calibration data only, `RecallFirstController` integrated, exchangeability limits stated, alerts/region-day, recall at budget, lead time; abstain/watch/elevated/high states; human review before escalation; no automated action. |
| **12** | Scenario input schema and validation, hypothetical storage separated from real bronze, entity resolution on hypothetical objects, interventions applied to *copied* graph state, generation + adjudication + calibration re-run under intervention, baseline-vs-scenario comparison with the causing assumptions named, adversarial contamination tests, one-command CLI, and the API endpoint (schema agreed with Track A). |
| **13** | Freeze and publish: primary metric, alert budget, fold boundaries, geographies, event types, lead-time windows, matcher tolerances, baseline versions, evidence budgets, comparison directions, failure definition, subgroup reporting. Publish the preregistration hash **before** looking at final-test results. |
| **14 / 15** | Reproduce base-rate, logistic and tree baselines plus relevant published systems under equal cutoff and equal budget. Run the retrospective benchmark: multiple temporal folds, frozen snapshots, forecasts before outcomes, negative controls (label shuffling, source removal, future-document injection), oracle diagnostics, generator and calibration ablations. Publish failures too; get an independent clean-clone reproduction. |
| **16** | The prospective trial: pick a start date, freeze code/config/sources, forecast on a schedule, hash and timestamp before outcomes, no retroactive edits, wait the full reporting-delay window, report everything including abstentions and outages, compare with the retrospective estimate. |

---

## 4. The shared seam

Three files both tracks want. The rule that keeps them apart:

| File | Track A owns | Track B owns |
| --- | --- | --- |
| `src/pramaanx/config.py` | source blocks, HTTP/proxy, storage | extraction, entities, graph, features, generator, calibration, risk, scenario blocks |
| `src/pramaanx/cli/commands/` | `ingest`, `sources`, `snapshot`, `outcomes` | `extract`, `candidates`, `graph`, `calibrate`, `adjudicate`, `scenario`, `backtest`, `report` |
| `src/pramaanx/pipeline.py` | — | sole owner |

The API surface in Stage 17 is the one genuine cross-track contract: Track B
defines the scenario and forecast **response schemas**, Track A implements the
transport, auth and rate limiting around them.

---

## 5. What neither track can close by writing code

These are the real schedule risks, and every one of them needs a person:

- **ReliefWeb `appname` approval** and **ACLED account + EULA acceptance** — Stage 2.1 cannot pass without them, and the current environment answers `403` at `CONNECT` for ReliefWeb regardless.
- **News corpus licensing** — Stage 2.2 gates Stages 4, 5, 6, 14 and 15.
- **Annotators** — two independent, blinded, for extraction, entity and outcome gold sets.
- **The alert budget and the miss-versus-false-alarm exchange rate** — Stage 11 is a policy decision, not a fitting problem, and it must come from the people who would triage the alerts.
- **External legal, domain and statistical review** — Stage 19.
- **Calendar time** — Stage 16 cannot be compressed; a prospective trial is only as long as its reporting-delay window allows.

## 6. Immediate next three actions

1. Open and merge the Phase 1 PR; tag `M0` and `phase1-integrated`; enable branch protection.
2. Track A: start the ReliefWeb appname and ACLED credential applications the same day — they have external latency and block Stage 2.1 indefinitely otherwise.
3. Track B: rebase Phase 2, clear the 10 ruff errors, and run its test suite for the first time. That single step converts ~7,300 lines from *written* to *known*.
