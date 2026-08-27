# Phase 2 downstream — extraction, entities, graph, features, G1, calibration, scenarios

This is the downstream half of the Phase 2 split: roadmap steps 4, 6 and 7. The
upstream half owns connectors, ingestion and `pipeline.py`.

## Verification status

| Claim | Status | Evidence / blocker |
| --- | --- | --- |
| `implemented` | `true` | All six workstreams have working implementations, listed below. |
| `tests_written` | `true` | 6 test modules, ~150 assertions, covering each stage and one cross-cutting leakage module. |
| `tests_executed` | **`false`** | **No test in this branch has ever been run.** The authoring machine had no Python and no `uv`. Nothing here is verified. |
| `integrated_into_pipeline` | `false` | Requires the `pipeline.py` patch specified below, which this half does not own. |
| `validated_on_real_prose` | `false` | The prose connectors (Phase 1A ReliefWeb, 1B ACLED) are unmerged. The cascade has only been exercised against hand-written text in tests. |

The second row is the one that matters. Treat this branch as a reviewed design
with unexecuted tests, not as working code. Run `make check` before believing
any of it.

## What landed

### Step 4 — extraction: real text to `EventMention`

`src/pramaanx/extraction/` gains three modules alongside the existing
`structured.py`, which is untouched.

- `prose.py` — sentence segmentation, an event-trigger lexicon (conflict and
  humanitarian shaped), modality detection with denial outranking planning
  outranking hedging, and date resolution. Relative dates resolve against the
  observation's **availability instant**, never a wall clock.
- `cascade.py` — `ExtractionStage` protocol, `PatternStage` (rule-based, ships
  and works), and a consensus step that marks contested fields
  `unresolved` rather than voting them away.
- `gold.py` — `GoldSet` (refuses construction without annotator, date and
  guidelines version), a field-level `DefectKind` taxonomy, and
  `score_extraction`.

The learned stages named in the M0 docstring — span tagger, event-type
classifier, constrained LLM verifier — are deliberately **not** shipped. They
implement `ExtractionStage` and slot in without touching the cascade, but a
learned stage without a measured error rate against a gold set is an
unquantified claim.

### Step 4 — entity resolution and deduplication

`src/pramaanx/entities/`. Resolution is blocking plus scored merge, deterministic
by construction (sorted candidate pairs, union-find with lexicographically
smallest representatives). Deduplication clusters mentions into events **and**
computes independence groups, so `EventCluster.effective_support` counts
independent stories rather than reprints. Denials never merge away: they mark
the cluster `contested`.

`EventCluster.hypothetical` was added (default `False`) for the scenario work.

### Step 6 — retrieval, evidence graph, feature construction

`src/pramaanx/graph/` and `src/pramaanx/features/`.

The graph has no current-state view. Every edge carries the instant it became
knowable and every query goes through `as_of()`, which **raises** rather than
silently returning everything when asked for a moment past its build cutoff.

Retrieval finally populates `EvidenceRef.independence_cluster`, which the M0
schema declared and left empty. Packs are capped per independent story by
round-robin, and contradictions are seeded before the general fill so a pack is
never unanimous when the corpus is not.

Features are declared before they are built. Every `FeatureVector` carries
`as_of` and `graph_cutoff_at`, so "could this number have been computed on the
day it claims?" is answerable from the artefact alone.

### Step 6 — G1 through the existing protocol

`src/pramaanx/generators/temporal_rules.py`. Three named rules — recurrence,
escalation, diffusion — combined by noisy-OR so an ablation reads cleanly in one
direction. Each contributes its own trace entry, so the candidate-oracle
diagnostic can attribute a miss to a specific branch. The active rule set is
baked into `version`, because an ablation is a different model.

`generators/comparison.py` makes the preregistered floor comparison a
computation. It separates *did it find different candidates* (answered here)
from *did it forecast better* (answered by the evaluation harness). `FloorVerdict`
takes metrics as inputs and refuses to compute them, so a generator cannot grade
itself.

### Step 7 — calibration and conformal risk control

`src/pramaanx/calibration/`. Two protocols, kept apart on purpose: `Calibrator`
maps scores to probabilities and is judged by a Brier score; `RiskController`
maps probabilities to statuses and encodes a policy about how many misses are
worth how many false alerts. Fusing them hides the policy inside the model.

`IdentityCalibrator` and `FixedThresholdController` reproduce the M0 strings
`identity@uncalibrated` and `fixed_threshold@placeholder` **exactly**, so a
pipeline switched to injection produces byte-identical output until something
fitted is supplied. The M0 acceptance hashes should not move.

`RecallFirstController` is RCPS with a Hoeffding bound. It **raises** when the
calibration sample cannot support the requested guarantee, naming the positive
count that would — it never quietly loosens alpha. Every fit carries
`EXCHANGEABILITY_CAVEAT`, and `ConformalReport` refuses to validate without it:
the finite-sample guarantee assumes exchangeability, temporal forecasting
violates that, and a bound quoted without its assumption is worse than no bound.

### Step 7 — hypothetical scenarios

`src/pramaanx/scenarios/`. Four interventions: `AddEvent`, `RemoveEvent`,
`ShiftTime`, `ReplaceActor`. The last two are the counterfactual track the
evaluation package names.

Every artefact is marked `hypothetical` and carries a `hyp_` identifier prefix.
Assumed events carry **no fabricated mentions** — no invented `supporting_span`
ever enters an evidence pack. `apply_scenario` copies rather than mutates, so a
scenario cannot leave a trace in the evidence that produced it.

## Required `pipeline.py` patch — not applied here

Step 7 cannot be completed without editing `src/pramaanx/pipeline.py`, which the
split assigns to the upstream half. All four touchpoints are in that file:
`IDENTITY_CALIBRATION` (line 32), `PLACEHOLDER_POLICY` (line 37),
`assign_status()` (line 108), and the `calibrated_probability` / `model_versions`
writes in `run_cutoff()`.

This branch does not touch it. The patch it needs:

1. Import `IDENTITY_CALIBRATION` and `PLACEHOLDER_POLICY` from
   `pramaanx.calibration.base` instead of defining them, so the strings live in
   one place.
2. Give `run_cutoff()` two optional keyword arguments, `calibrator: Calibrator |
   None = None` and `controller: RiskController | None = None`, defaulting to
   `IdentityCalibrator()` and `FixedThresholdController(settings.alerting)`.
3. Replace `calibrated_probability=probability` with
   `calibrator.apply(probability)`.
4. Replace the `assign_status(...)` call with `controller.assign(...)`.
5. Take `model_versions["calibration"]` and `["alert_policy"]` from
   `calibrator.version` and `controller.version`.

With the defaults in place this is behaviour-preserving. `assign_status()` should
stay where it is as the control arm; `FixedThresholdController` is a verbatim
port of it and the two must not drift, or the conformal comparison is
meaningless.

## Open dependencies on the upstream half

1. **Integrated main.** This branch is cut from M0 (`a98fa0d`). Phase 1A, 1B and
   1C are unmerged, so it will need one rebase once integrated main lands.
2. **The frozen fixture.** The promised snapshot plus outcome registry does not
   exist yet. Until it does, the calibration and conformal fitters have no
   realistic sample and the backtest comparison against the floor cannot run.
3. **Prose connectors.** Until ReliefWeb and ACLED land, `PatternStage` has no
   real prose. `register_prose_source()` is the wiring point; it takes dotted
   field paths and refuses to silently replace an existing extractor.
4. **`config.py`.** Not in the ownership table and needed by both halves. It
   wants the same "add files, not lines" treatment `cli.py` is getting.

## What is deliberately absent

- Learned extraction stages (no gold set yet).
- A gazetteer for location resolution — that is a licensed *source* and belongs
  in the connector path, not in a helper that reaches for the filesystem.
- Any causal claim from the scenario interface. `ScenarioResult.interpretation`
  carries the sentence that must accompany any quoted scenario number.
