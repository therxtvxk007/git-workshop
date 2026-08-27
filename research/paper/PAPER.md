# From Gap Analysis to Falsifiable System: A Cutoff-Safe, Calibrated Architecture for Event Prediction from Unstructured Text

**Status:** working paper, draft 1. Nothing in this paper is an accuracy claim.
Section 11 states exactly which of the mechanisms described here have been
executed and which are written but unverified, and the distinction is load-bearing
throughout.

---

## Abstract

The 2020 survey *Survey and Gap Analysis on Event Prediction of English
Unstructured Texts* (Bhattacharjee, ShivaKarthik, Mehta, Kumar, Kothawade,
Katre, Dharkar, Pillai and Verma; ICTIS 2020, Springer LNNS 141) clustered the
field into probabilistic-logic, rule-based and machine-learning approaches,
tabulated their reported accuracies, and closed with a gap analysis. Two of its
gaps were methodological rather than algorithmic: that "the proposed models need
to be validated with actually occurred events," and that "validation of data and
approaches is an important shortcoming in the surveyed approaches." This paper
takes those two sentences as its starting point and argues they are not
residual caveats but the discipline's central obstacle: the reported accuracies
the survey tabulates are not comparable to one another, because nothing in the
surveyed methods establishes that a model's evidence was available before the
event it claims to predict.

We describe PRAMAAN-X, a system built to make that property checkable rather
than assumed. Its contributions are architectural, not a new estimator: a
four-stage decomposition (candidate discovery, adjudication, calibration,
risk-controlled alerting) that keeps recall failures distinguishable from
probability failures; temporal validity enforced as a structural property of an
append-only, content-addressed evidence ledger rather than as a procedure;
outcome isolation enforced by the runtime rather than by statement order;
censoring treated as a limit on what may be scored at all; and alerting governed
by an explicit, conformally-bounded miss rate that carries its own violated
assumption on every fit.

We then set out the design of a retrospective evaluation anchored on the 26
November 2008 Mumbai attacks. We argue that the scientifically valuable
quantity this case study can produce is not a prediction but a **ceiling**: an
estimate of how much of the pre-attack signal was ever present in open English
text at all. The documented warning record for 26/11 is unusually rich and
almost entirely classified in origin, which makes it the sharpest available test
of the upper bound on open-source textual event prediction. We argue that
measuring that bound honestly is worth more to the field than another
incomparable accuracy figure, and that a system which cannot state its own
ceiling should not be trusted with the alerts it emits.

**Keywords:** event prediction, temporal validity, data leakage, forecast
calibration, conformal risk control, evidence provenance, retrospective
evaluation.

---

## 1. Introduction

### 1.1 What the survey established

The 2020 survey set out to do three things: summarise the technical approaches
to future event prediction from text, identify the features those approaches
depend on, and produce a gap analysis. It grouped the literature into
probabilistic-logic approaches (Markov Logic Networks over event
representations transformed into OWL, with first-order causal rules and
large-scale ontologies as background knowledge), rule-based approaches (the
Pundit line of causality learning from news), and machine-learning approaches
(nested multi-instance learning for precursor discovery, LDA-based topic
modelling of newspaper text for political-violence prediction). It surveyed
evidence-gathering and scoring separately — DeClarE, the Watson evidence
pipeline — on the explicit grounds that a prediction without displayable
support is not usable.

That last commitment is stated plainly in the survey's introduction: for a
system to be "credible and determinantal in preventing the predicted events
from occurring," it is "essential for such a system to provide plausible
reasoning for its forecast." The survey is therefore not merely asking for
better numbers. It is asking for systems whose forecasts can be inspected.

### 1.2 The two gaps this paper treats as primary

The survey's Section 5 lists a dozen gaps. Most are algorithmic and local: MLN
frameworks depend on human-authored domain rules and degrade off-domain; Pundit
extracts events only from headlines and ignores the effect of time on causal
relations; nMIL was evaluated only on Latin-American articles and does not use
regularised multi-task learning; tweet location is an unused feature; hashtag
collection cannot guarantee relevance; dynamic and structural topic models are
unexplored; heterogeneous multi-source evidence is not considered, which the
survey says "in turn reduces the real life reliability."

Two are of a different kind:

> "Also, the proposed models need to be validated with actually occurred
> events."

> "It has been seen that validation of data and approaches is an important
> shortcoming in the surveyed approaches because of high processing needs and
> costs."

These are not gaps in any one method. They are a statement that the field's
comparative table — the survey's own Table 1, which lists datasets and reported
accuracies side by side — does not license the comparisons a reader will
naturally draw from it. If two systems were validated differently, or were
validated against corpora that already contained reporting about the events
being predicted, then their accuracy figures are not measurements of the same
quantity and the higher number is not the better system.

### 1.3 The claim of this paper

Our claim is that these two gaps dominate the others, and that closing them
requires infrastructure rather than modelling.

The argument is short. Every surveyed method consumes a text corpus and emits a
prediction about an event. The prediction is scored against whether the event
occurred. For that score to mean what it appears to mean, one property must
hold: *every document the model consumed must have been publicly available
before the model's forecast instant.* No surveyed method establishes this
property. Most could not, because the corpora they use — news archives, tweet
dumps, Event Registry exports — record the date a publisher claims, not the
date a document became retrievable, and are frequently re-crawled, revised and
back-filled after the fact.

The consequence is not noise. It is directional. Post-event reporting about an
event is, by construction, the most predictive text about that event that will
ever exist. A corpus that admits any of it produces a model that appears
excellent and forecasts nothing. And because the failure inflates the metric,
nothing in the ordinary development loop will catch it: every incremental leak
looks like progress.

So the question the survey's gap implies is not "which estimator is best?" but
"what would have to be true of a pipeline before any accuracy number computed
inside it is worth reading?" This paper answers that question with a system.

### 1.4 Contributions

1. **A reframing of the survey's validation gap** as the field's primary
   obstacle, with an argument for why it is self-concealing (§2).
2. **A four-stage decomposition** — discovery, adjudication, calibration,
   risk-controlled alerting — justified by the claim that conflating discovery
   with scoring makes recall failures and probability failures indistinguishable,
   though they have unrelated remedies (§3).
3. **Temporal validity as a structural property** rather than a procedure:
   availability-time semantics, an append-only content-addressed ledger,
   content-only snapshot hashing, and a runtime seal on outcome data — each
   chosen because it converts a discipline problem into an assertion that fails
   loudly (§4).
4. **Censoring as an admissibility condition on scoring**, not a correction to
   it: folds whose evidence window is too short are forecast but not scored, and
   are named in the report (§4.5).
5. **A separation of calibration from alert policy**, with alerting governed by
   a recall-first conformal bound that reports the exchangeability assumption it
   violates on every fit (§7).
6. **A retrospective case-study design on the 26/11 Mumbai attacks** whose
   target quantity is the open-source ceiling rather than a hit (§8).
7. **A preregistration and claim-discipline regime** that fixes what would count
   as evidence before results exist (§9), and an explicit statement of what
   remains unverified (§11).

---

## 2. Why the surveyed accuracies are not comparable

### 2.1 The leak is directional and self-concealing

Consider a model predicting civil unrest in a city over a seven-day horizon,
trained and evaluated on a news archive. Suppose the archive is assembled by
querying a news API for all articles mentioning the city, with each article
stamped by its publication date, and the evaluation splits documents randomly
into train and test.

Three separate leaks are now present, and none of them will produce an error.

**Random splitting.** A random split places articles published after an event in
the training set and articles published before it in the test set. The model
learns the vocabulary of aftermath reporting — casualty counts, condolence
statements, curfew announcements — and applies it to predict the event that
produced them. Accuracy rises. The model has learned to read the past tense.

**Publication date as availability.** A publication date is a claim a publisher
makes about a document, not a record of when a reader could retrieve it.
Archives back-fill; wire copy is revised in place under its original timestamp;
aggregators assign the date of first syndication to a body written days later.
Filtering on the claimed date admits documents whose current text did not exist
at the claimed instant.

**Re-crawling.** A corpus assembled today from URLs published in 2019 contains
the 2019 URLs and the 2026 bodies. For any story that was updated — which is
most stories about developing events — the text in hand is the text after the
outcome was known.

Each of these inflates the metric. None produces a crash, an exception, or an
anomalous distribution. The model simply gets better, which is what the
developer wanted, so the loop terminates.

### 2.2 Why this makes the survey's Table 1 unreadable as a ranking

The survey's summary table lists, per approach, the data source, the deep
features, and the reported accuracy. Read as a description of what each paper
reported, it is accurate and useful. Read as a ranking, it requires an
assumption the surveyed papers do not establish: that the accuracies measure the
same quantity.

They do not, and the differences are not small. A system evaluated on
headline-only inputs from a curated event registry, a system evaluated on
Spanish-language protest reporting under a temporal split, and a system
evaluated on a randomly-split archive of full articles are measuring three
different things, only one of which resembles forecasting. The survey's own gap
analysis says as much when it notes that nMIL "was only tested on articles
selected from Latin-American countries" and that models "need to be validated
with actually occurred events."

Our position is that a field cannot make progress on a quantity it cannot
measure consistently, and that building the measurement apparatus is therefore
prior to proposing another estimator. That is the work PRAMAAN-X attempts.

### 2.3 What "cutoff-safe" means here

We use *cutoff-safe* for the property that a forecast produced for instant `T`
consumed only evidence that was retrievable at or before `T`, and that this can
be demonstrated after the fact from the artefacts alone rather than asserted by
the developer.

The demonstration standard we adopt is the following gate, which we state now
and return to in §4.6:

> Injecting correctly-dated future documents into the evidence ledger must leave
> every earlier cutoff's snapshot identifier **byte-identical**.

This is a strong condition. It is not satisfied by filtering at query time,
because a filter is a line of code that a later edit can move. It is satisfied
only if the identity of a snapshot is a function of its admitted content, which
is what §4.3 constructs.

---

## 3. Architecture: four stages, kept apart

### 3.1 The decomposition

```
candidate discovery -> candidate adjudication -> calibration -> risk-controlled alerting
```

This is not an implementation convenience. It is a claim about failure
attribution.

A model cannot score a future event that never entered its candidate pool. If
discovery and scoring are one step, then a system that misses an event provides
no way to tell whether it never considered the event or considered it and
assigned it low probability. Those two failures have nothing in common: the
first is fixed by adding a generator, broadening retrieval, or raising the
candidate budget; the second is fixed by better evidence weighting or
recalibration. A system that cannot distinguish them will apply the wrong remedy
and observe no improvement.

So each stage gets its own interface, its own metrics, and its own failure mode:

| Stage | Question | Primary metric | Failure it isolates |
| --- | --- | --- | --- |
| Discovery | Did the event enter the pool? | Candidate recall at a fixed budget | Coverage |
| Adjudication | Given evidence, how likely? | Discrimination (AUC, log loss) | Reasoning |
| Calibration | Do the numbers mean what they say? | Brier, reliability by bin | Overconfidence |
| Risk control | Which forecasts become alerts? | Recall at alert budget, alerts/region-day | Policy |

The corresponding diagnostic is the **candidate oracle**: replace the discovery
stage with an oracle that always includes the true event, and re-score. The gap
between oracle-discovery performance and end-to-end performance is the exact
amount of loss attributable to discovery. This diagnostic is only available if
the union stage preserves which generator proposed each candidate — which is why
`merge_proposals` retains per-generator traces and the union of `generated_by`
even in the current single-generator configuration, where there is nothing to
merge. Retrofitting provenance after the fact is how the diagnostic quietly
becomes unavailable.

### 3.2 Absence is recorded, not stubbed

Stages that do not exist yet are named in every forecast record they would have
touched. A forecast produced by the current system carries
`calibration: identity@uncalibrated` and `alert_policy: fixed_threshold@placeholder`.

The reasoning is that an empty module returning plausible output is worse than a
missing one, because it makes a skipped requirement look finished. A downstream
consumer reading a probability field cannot tell whether it was calibrated
unless the artefact says. So the artefact says, in a string that is impossible
to misread, and the string is produced by the component itself rather than by a
constant somewhere else.

This has a testable consequence used in §11: when the placeholder components are
replaced by injectable ones with identity defaults, the forecast records must be
**byte-identical**. The acceptance hashes must not move. A refactor that changes
outputs while claiming to preserve behaviour is caught by equality, not by
review.

---

## 4. Temporal validity as a structural property

The mechanisms in this section share one design rule: *prefer a structure that
makes the error impossible or loud over a procedure that makes it discouraged.*

### 4.1 Availability time, never event time

Every observation carries `first_observed_at`, which answers exactly one
question: when could this system legitimately have seen this document? Not when
the described event occurred, and not when a publisher claims to have published.

This is the single field cutoff filtering runs on, and getting it wrong is the
only bug that silently defeats every guarantee downstream. Two consequences in
the connector layer:

- **GDELT.** The `SQLDATE` column is the date of the *event*, and using it would
  back-date every row into the period before the reporting existed. The
  connector uses the 15-minute export slot plus a conservative publication lag
  instead.
- **ReliefWeb.** The API serves only the current revision of a report and offers
  no version history. A report's availability is therefore
  `max(date.created, date.changed)` — never `date.created` alone. A report
  posted in 2020 and revised in 2026 enters a 2026 snapshot, because the body in
  hand is the 2026 body. This is deliberately conservative: it withholds from
  early cutoffs some evidence a contemporaneous reader really did have, rather
  than risk attributing to an early cutoff a sentence written later. All three
  raw instants survive into metadata under their own names, so the conservatism
  is inspectable rather than baked in.

The general rule is that where availability is uncertain, the system errs toward
withholding evidence, and records what it withheld.

### 4.2 Append-only, content-addressed evidence

Bronze storage is append-only and content-addressed. A story edited after the
cutoff cannot overwrite its earlier self; it becomes a *new* observation with a
*later* `first_observed_at`, which the guard then excludes.

This converts "detect that a document body was updated" — an unsolvable text-
forensics problem in general — into a structural property of the store. The
remaining hole is evidence that lies about its own observation time, which no
ledger can close. That residue is handled two ways: a leakage audit screens for
identical content appearing under distant dates, and the metamorphic test suite
contains an explicit **negative control** demonstrating that deliberately
back-dated evidence *does* get in. A test suite that only demonstrates successes
is a marketing document; the negative control is what marks the boundary of the
guarantee.

### 4.3 Content-only snapshot identity

A snapshot's identifier is computed over sorted observation hashes, source
versions, code hash and config hash. It does **not** cover creation time, file
layout, or run metadata.

Without this, the gate in §2.3 is untestable: "the forecast is unchanged" could
only ever mean "roughly similar," because every rebuild would produce different
bytes. With it, the assertion is literal equality.

Snapshot identity deliberately includes the **code hash**, so a snapshot pins the
evidence *and* the logic that selected it. Editing the guard produces a new
snapshot id over identical evidence. This is intended: the old identifier still
refers to what the old code admitted, and a forecast pinned to it remains
interpretable.

### 4.4 Outcome isolation enforced by the runtime

Backtests run in two passes. Pass A builds snapshots and persists forecasts;
pass B builds outcomes and scores what pass A froze. Pass A executes inside a
context manager that seals every outcome-reading entry point for its duration;
any read raises rather than returning data.

The distinction that matters is against the obvious alternative. An earlier
design had the same *ordering*, enforced by the sequence of statements in one
function. That works until an edit moves an outcome lookup earlier — and nothing
about such an edit looks wrong. The run succeeds, and the metrics improve. A
context variable makes the mistake raise instead, from wherever in the call
stack it occurs, however deep.

Pass B re-reads forecasts from the ledger rather than retaining them in memory,
so what is scored is provably what was persisted before any outcome existed.

The limitation is stated in the module itself: this cannot stop a determined
caller reading a Parquet file directly, and is not meant to. It makes the
mistake loud in the one place it is actually likely.

### 4.5 Censoring as an admissibility condition

Evidence that stops too early does not produce noisy metrics. It produces
confidently wrong ones, in a known direction, with no signature in the numbers.

The mechanism: reports that have not arrived yet are indistinguishable from
events that never happened. Recall is therefore understated and precision
overstated, and nothing about the resulting figures hints at it.

So a fold is **scoreable** only when the ledger reaches
`cutoff + horizon + reporting delay`, where the delay is the larger of a
configured floor and the maximum actually observed in the outcome registry.
Short folds are still forecast — the forecasting work is valid, only the scoring
is not — but they are marked unscoreable, excluded from the aggregate, and named
in the report. A walk with no scoreable fold raises rather than emitting a
report of artefacts.

We regard this as a substantive methodological position rather than an
implementation detail. Much of the surveyed literature evaluates on windows that
end at corpus end, which silently applies maximum censoring to the most recent
and most interesting folds.

### 4.6 Ground truth is derived, never injected

The synthetic evaluation world does not hand the pipeline its latent events. It
publishes reports *after* they happen, and the outcome registry is constructed
from those reports — the same path a real deployment would use. A
`ground_truth()` accessor exists for test assertions only and is never called by
the pipeline.

Injecting known answers would make the loop untestable in the one respect that
matters, because the system would be scored against information it could in
principle have reached.

### 4.7 Determinism as a precondition for everything above

No `uuid4`; no `datetime.now()` outside an injectable clock; no use of Python's
built-in `hash()` anywhere its value escapes the process, since it is salted per
process. Identifiers derive from content. Sorting is explicit at every
aggregation boundary.

This is not tidiness. A pipeline that cannot be shown deterministic cannot be
shown leak-free, because "the output changed" stops being evidence of anything.

---

## 5. Heterogeneous evidence and the independence problem

### 5.1 The survey's gap, and why source count is the wrong response

The survey observes that surveyed approaches "do not consider multiple and
heterogeneous data sources which in turn reduces the real life reliability."
This is correct, but the naive reading — add more sources — makes a different
problem worse.

News is syndicated. A wire item reproduced by forty outlets is one piece of
evidence appearing forty times. A model that counts documents will read the
reprint volume as corroboration and become more confident in proportion to how
widely a single claim was copied. Adding sources increases reprint volume faster
than it increases independent testimony.

The system therefore computes **independence groups** during deduplication, and
an event cluster's `effective_support` counts independent stories rather than
mentions. Retrieval populates an `independence_cluster` on every evidence
reference, and evidence packs are capped per independent story by round-robin,
so a pack cannot be filled with forty copies of one wire item.

### 5.2 Contradiction is seeded, not averaged away

Two rules govern disagreement:

- **Denials never merge away.** A denial does not vote against an assertion and
  lose; it marks the cluster `contested`. The consensus step in the extraction
  cascade marks contested fields `unresolved` rather than resolving them by
  majority.
- **Contradictions are seeded before the general fill.** An evidence pack is
  populated with known contradicting evidence first, then filled. A pack is
  therefore never unanimous when the corpus is not.

This is the mechanism that answers the survey's own explainability requirement —
that a system must "provide plausible reasoning for its forecast." A pack that
shows only supporting evidence is not reasoning; it is advocacy. The requirement
is met by displaying supporting *and* contradicting evidence with source
independence attached, which is only possible if the earlier stages refused to
average the disagreement away.

### 5.3 The four current sources and what each cannot do

| Source | Kind | Credential | Structural limitation for forecasting |
| --- | --- | --- | --- |
| GDELT | Machine-coded event records | none | Coding noise; event-time column unusable as availability |
| ReliefWeb | Curated humanitarian reporting | approved appname | Response-driven: reports follow events by design |
| data.gov.in | Administrative aggregate | API key | Annual retrospective; contextual base rates only |
| ACLED | Hand-coded conflict events | OAuth | Coded after the fact; living dataset, rows revised |

The honest summary is the one the system's own documentation carries: **by
construction none of these alone supplies pre-incident signal.** Three of the
four are retrospective by design. They support base rates, context and outcome
construction. They do not constitute the pre-event evidence stream a
retrospective such as §8 requires, and the largest unstarted dependency in the
project is a legally frozen English news corpus, Indian regional sources
included, with publication, retrieval and revision times stored separately.

Stating this is not a disclaimer. It is the reason §8 is a study design rather
than a result.

### 5.4 Protected attributes are dropped at ingestion

GDELT ships per-actor ethnic and religion code columns. The system forecasts
population-level and organisational events and must not use protected identity
as a risk proxy, so those columns are removed **at ingestion**, before anything
downstream can see them, rather than filtered at feature construction.

The reasoning is mechanical rather than declarative: evidence that never enters
bronze cannot become a feature by accident, cannot be reintroduced by a later
contributor who did not read the policy, and cannot survive in a cached
intermediate. A policy enforced at the boundary is a property; a policy enforced
downstream is a habit.

The same commitment appears in the preregistration as a scope limit: the system
predicts population-level and organisational events, and does not produce risk
scores for private individuals.

---

## 6. Extraction, entities, graph and features

### 6.1 Extraction: a cascade with an explicit unresolved state

The survey criticises Pundit for extracting events only from news headlines. The
extraction layer here operates on full prose: sentence segmentation, an
event-trigger lexicon, modality detection, and date resolution.

Two details carry the design weight.

**Modality has a precedence order.** Denial outranks planning, which outranks
hedging. "Officials denied reports of a planned strike" is a denial, not a
planning statement, and a flat classifier that scores each modality
independently will get this wrong in the direction that inflates candidate
counts.

**Relative dates resolve against the observation's availability instant, never a
wall clock.** "Yesterday" in a document available on 12 March means 11 March,
regardless of when the pipeline runs. Resolving against the wall clock would
make extraction output depend on execution time, which breaks both determinism
(§4.7) and replay.

The cascade defines a stage protocol; the shipped stage is rule-based. Learned
stages — span tagger, event-type classifier, constrained LLM verifier — are
deliberately **not** shipped, because a learned stage without a measured error
rate against a gold set is an unquantified claim. They implement the same
protocol and attach without touching the cascade, once a gold set exists.

The gold-set machinery is built to refuse misuse: a gold set cannot be
constructed without an annotator identity, a date and a guidelines version.

### 6.2 Entity resolution, and the gazetteer that is deliberately absent

Resolution is blocking plus scored merge, deterministic by construction — sorted
candidate pairs, union-find with lexicographically smallest representatives.

The system deliberately ships **no gazetteer**. A gazetteer for Indian location
resolution is a licensed *source* with provenance, versioning, renames and
hierarchy changes, and it belongs in the connector path under the same
availability and licence discipline as every other source — not in a helper that
reaches for a file on disk. Transliteration across major Indian languages is
subject to the same constraint.

This is a real capability gap and is recorded as one. It also means the survey's
gap about unused location features is only partly addressed: the structures
exist, the authoritative data does not.

Validation follows the same discipline: merges must be validated against human
labels, with **false-merge and false-split reported separately**, because they
have opposite causes and a combined error rate hides which one is happening.

### 6.3 The evidence graph has no current-state view

Every edge carries the instant it became knowable, and every query goes through
an `as_of()` accessor which **raises** rather than silently returning everything
when asked for a moment past its build cutoff.

The absence of a "current state" view is the point. A graph that can be queried
without a time argument will eventually be queried without a time argument, from
inside a forecasting pass, by a contributor who did not know the convention. The
API removes the option.

### 6.4 Features are declared before they are built

Every feature vector carries `as_of` and `graph_cutoff_at`. The question "could
this number have been computed on the day it claims?" is therefore answerable
from the artefact alone, without re-running the pipeline or trusting a log.

This addresses the survey's observation that "extracting event-specific features
and inculcating these into the methodology could [improve] the accuracy" — but
subject to the constraint that a feature which cannot state its own as-of time
is not admissible evidence of anything.

---

## 7. Calibration and risk-controlled alerting

### 7.1 Accuracy is the wrong metric, and the survey inherits it

The survey's summary table reports accuracy. Nearly all of the surveyed
literature does. For rare-event forecasting this is close to uninformative: a
model that predicts "no event" everywhere achieves excellent accuracy on any
realistic base rate, and two models with identical accuracy can have completely
different operational value.

What matters operationally is whether a stated probability means what it says —
whether events assigned 0.3 occur about 30% of the time — and, separately, what
policy converts probabilities into actions.

### 7.2 Calibration and policy are kept apart on purpose

Two protocols, deliberately not fused:

- A **calibrator** maps scores to probabilities and is judged by a proper scoring
  rule (Brier, log loss, reliability by bin).
- A **risk controller** maps probabilities to statuses and encodes a policy about
  how many misses are worth how many false alerts.

Fusing them hides the policy inside the model. A single tuned threshold embedded
in a scorer is a decision about the relative cost of a missed event and a
spurious alert, made implicitly by whoever tuned it, and invisible to the people
who bear the consequences.

Calibration must be fitted on strictly earlier folds, never the test period,
with the family chosen — identity, Platt, isotonic, beta — **before** final
testing, minimum sample sizes enforced, and raw scores preserved alongside
calibrated ones.

### 7.3 Recall-first conformal risk control

The default controller is a placeholder with constants nobody chose, and says so
in its version string. The fitted controller is RCPS: scan candidate thresholds,
bound the empirical risk at each with a Hoeffding upper confidence bound, and
take the largest threshold whose bound still clears the target — the fewest
alerts consistent with the guarantee.

The guarantee is deliberately **recall-first**: *of the events that actually
happen, at most α should fall below the alert threshold, with confidence 1 − δ.*

The direction is a position, not a convention. Bounding false alerts and hoping
recall follows is the wrong trade for an early-warning system, because a missed
mass-casualty event and a spurious alert are not symmetric errors, and a
controller that treats them symmetrically has silently made a policy decision
nobody signed off on.

Two refusals are built in:

- The controller **raises** when the calibration sample cannot support the
  requested guarantee, naming the positive count that would suffice. It never
  quietly loosens α. This matters because the bound depends on the *positive*
  count, not the sample size: a hundred thousand forecasts containing four hits
  support a guarantee built on four observations.
- Every fit carries an **exchangeability caveat**, and the report object refuses
  to validate without it. Finite-sample conformal validity assumes calibration
  and test data are exchangeable; temporal forecasting violates this, because
  regimes shift and reporting practice changes. The bound is therefore
  approximate under a condition known to be imperfect.

We consider the second refusal the more important of the two. A bound quoted
without its assumption is worse than no bound, because it invites exactly the
reliance it cannot support. Attaching the caveat to the artefact rather than to
the paper means it survives being copied into a slide.

### 7.4 The number that code cannot supply

α is a policy parameter. The default in the codebase is 0.10 and is labelled a
demo default, not a policy: the number belongs to whoever owns the consequences
of a miss.

More generally, the alert budget — alerts per region-day that a team can
actually triage — and the miss-versus-false-alarm exchange rate are decisions for
the people who would receive the alerts. They are recorded as unresolved
dependencies rather than filled with defaults, because a default here is a
policy adopted by accident.

---

## 8. Case study design: the 26/11 retrospective and the open-source ceiling

### 8.1 Why this case

The survey asks that models "be validated with actually occurred events." The 26
November 2008 Mumbai attacks are an unusually strong choice of validation
anchor, for four reasons:

1. **The outcome is unambiguous.** Ten attackers, arriving by sea, struck
   Chhatrapati Shivaji Terminus, the Taj Mahal Palace hotel, the Oberoi Trident,
   Nariman House, the Leopold Cafe and Cama Hospital across 26–29 November,
   killing more than 160 people. There is no adjudication problem about whether
   the event occurred, which removes the largest source of noise in outcome
   construction (§9.3).
2. **The pre-attack record is documented to an unusual degree**, through the
   Pradhan Committee (appointed by the Maharashtra government on 30 December
   2008, comprising R. D. Pradhan and V. Balachandran), US federal proceedings
   against David Coleman Headley, and extensive subsequent journalism.
3. **The date is old enough that reporting has fully settled**, so the censoring
   problem of §4.5 does not bind. Every report that will ever arrive has
   arrived.
4. **It is the case a security-analytics system will be asked about.** If a
   method cannot state what it would have done on 26/11, its claims about easier
   cases are not interesting.

### 8.2 What the pre-attack signal actually was

The documented warning record is substantial. The Pradhan Committee found
seventeen alerts since 7 August 2006 concerning the possibility of sea-borne
attacks and of multiple simultaneous fidayeen attacks. US intelligence warned
Indian counterparts in mid-October 2008 about a Lashkar-e-Taiba threat to Mumbai
sites frequented by Westerners, including the Taj; hotel security was reportedly
increased and then reduced again. On 18 November 2008, a satellite phone call to
a Lashkar figure was intercepted, indicating a sea-borne plan. Headley conducted
five surveillance trips to Mumbai between September 2006 and July 2008, taking
GPS readings, boat trips around the harbour in March 2008 to identify a landing
site, and video of the eventual targets, which he delivered to his handlers; he
pleaded guilty in March 2010 to twelve terrorism charges and was sentenced to 35
years.

The Committee's finding on the failure was that there was "total confusion in
processing intelligence alerts at the state level," while it "did not find any
failure to act on inputs by the central intelligence agencies."

Now observe the property of that record which matters for this paper.

**Almost none of it was open-source text.** The seventeen alerts were classified
intelligence products. The October warning was a liaison communication between
services. The 18 November intercept was SIGINT. Headley's reconnaissance was
covert by definition — its entire purpose was to not appear in public reporting,
and it did not.

### 8.3 The ceiling, and why it is the right target

This yields the case study's actual research question, which is not "would the
system have predicted 26/11?"

> **How much of the pre-attack signal for 26/11 existed in open English text
> before 26 November 2008 at all?**

Call this the **open-source ceiling**. It is an upper bound on the performance of
*any* system in the class the survey reviews — every method in that survey
consumes public text — and it is a property of the world, not of a model. No
architecture, however good, can exceed it. It is measurable, and to our knowledge
it has not been measured for a case of this significance.

The distinction this makes available is precisely the one §3.1 was built for.
There are two very different questions:

- **Discovery.** Before the attack, did open text support placing Mumbai, and
  hotel- and transit-class targets, in an elevated band relative to base rate?
  This is plausibly *yes*, and is testable. The threat environment was publicly
  discussed; prior mass-casualty attacks on Indian transit and urban targets were
  public record; Lashkar's activity and intent were the subject of open
  reporting.
- **Adjudication.** Did open text support the specific instance — this date,
  these targets, sea-borne infiltration, this cell? This is almost certainly
  *no*, and the reason is documentary rather than algorithmic: the information
  that specified the instance was, by design, never public.

A system that reports a raised regional hazard and abstains on the instance is
behaving correctly given its inputs. A system that reports the instance is either
reading a leak or fabricating. This is why the retrospective is scientifically
useful in either direction: a *negative* result — "the ceiling is low, and here
is the measurement" — is a real contribution to a field whose reported accuracies
imply the ceiling is high.

### 8.4 Study design

**Cutoff.** Primary cutoff `2008-11-25T00:00:00Z`, with a sweep at 7, 14, 30, 90
and 180 days prior to characterise how any signal behaves as a function of lead
time. A single cutoff cannot distinguish a real precursor from a coincidence at
one horizon.

**Corpus.** English reporting available before each cutoff, from a frozen archive
storing publication, retrieval and revision instants separately, with the
original bytes or permitted hashes preserved, and syndication metadata
sufficient to compute source independence (§5.1). This corpus does not currently
exist and is the study's blocking dependency (§5.3). Acquiring it under licence
is the single largest piece of outstanding work in the project.

**Admission.** Every document passes the cutoff guard on availability time
(§4.1). Given a 2008 corpus assembled in 2026, availability must come from
archival crawl records, not from publication metadata, and where it cannot be
established the document is excluded and the exclusion counted. *We expect the
excluded fraction to be large, and it is itself a reportable result about corpus
quality.*

**Forecast.** Produced inside a sealed forecasting pass (§4.4), pinned to a
snapshot hash, and written to the immutable ledger before any outcome is read.

**Scored quantities.**
- Candidate recall: did a Mumbai, hotel/transit-class, mass-casualty hypothesis
  enter the pool, at what budget, and at what lead time?
- Hazard ratio: the forecast probability for the region-window relative to the
  base rate the same generator assigns to comparable Indian regions.
- Evidence attribution: which documents drove any elevation, and are they
  independent stories or reprints of one another (§5.1)?
- Abstention: did the system decline to specify the instance?

**Negative controls**, all required before any figure is reported:
- *Future-document injection.* Post-attack reporting inserted with correct dates
  must leave the pre-cutoff snapshot hash byte-identical (§2.3).
- *Label shuffling.* Scoring against permuted outcomes must destroy performance.
- *Source removal.* Ablating each source must move results in an explicable
  direction.
- *Placebo cutoffs.* The same pipeline at matched cutoffs before comparable
  Indian city-months with no subsequent attack. **Without this control an
  elevated Mumbai score is meaningless**, because Mumbai is a large, heavily
  reported city and will attract elevated scores from volume alone.

The placebo control is the one most likely to be omitted and the one that
decides whether the study says anything.

### 8.5 What this study will not produce

It will not produce a claim about where a future attack will occur.

This is a limit of the method, not an editorial choice. The system forecasts
rates over regions and windows, and the retrospective measures whether those
rates were informative in one historical instance. Neither operation identifies a
next instance: the base rates are low, the adversary adapts to observation, and
the specifying information is — as §8.2 documents for the best-recorded case
available — systematically absent from the input modality.

A model asked for a next-instance target will produce one, because that is what
models do when queried. Its output would be a fluent restatement of the reporting
volume in its corpus, presented with an authority the underlying evidence cannot
support. The system's alert vocabulary therefore has no "next target" state, its
dashboard specification forbids maps implying tactical certainty, and no
automated action is permitted downstream of any alert.

We state this in the paper because the request is foreseeable. A security-
forecasting system that cannot say what it declines to do is not finished.

---

## 9. Preregistration and claim discipline

### 9.1 Why a preregistration exists before results

The failure this project is most exposed to is not a bug. It is a
plausible-looking number produced by a pipeline nobody has audited, quoted
without its caveats. Writing down what would count as evidence *before* running
the experiments is the cheapest available defence.

### 9.2 Committed now

1. **Temporal splits only.** No random document split may support any claim.
2. **Snapshot-pinned forecasts.** A forecast without a snapshot hash is invalid
   and is not counted.
3. **Forecast-before-outcome ordering**, enforced structurally (§4.4).
4. **Statement of limits.** Every report leads with what its numbers do not mean.
5. **No protected-attribute proxies** (§5.4).
6. **Human adjudication required for gold.** Machine-derived outcomes are
   `PENDING` and reported as such.

### 9.3 What must be registered before any headline number

Before metrics are believed: the matcher validation target against blinded
dual-human labels with the agreement threshold fixed in advance; the primary
metric and its alert budget, chosen by the people who would triage the alerts;
and the fold structure.

Before any superiority claim: the exact baselines and their evidence budgets;
the pre-committed direction of every comparison; the subgroups reported whether
or not they flatter the system — by language, geography, source availability,
domain and event rarity; and **what result would count as a failure**.

The experiment registry records every run that informed a decision, including the
ones that failed or embarrassed a hypothesis, on the stated grounds that a
registry recording only wins is a marketing document.

### 9.4 The one claim that is intended, and the one that will never be made

The intended claim, available only once the above are satisfied:

> PRAMAAN-X outperforms reproduced structured, open-ended and binary forecasting
> baselines on a common non-oracle, cutoff-safe event-forecasting benchmark while
> controlling missed-event risk and operational alert burden.

The claim that will not be made, because the underlying tasks and datasets are
not identical: that this system beats "all forecasting models everywhere."

---

## 10. How each surveyed gap is addressed

| # | Gap identified in the 2020 survey | Response | Status |
| --- | --- | --- | --- |
| 1 | No adaptability/scalability to parallel and distributed environments | Content-addressed append-only bronze and deterministic replay make distribution safe; distributed execution itself is not built | **Partly, honestly incomplete** |
| 2 | MLN depends on expert-authored domain rules; degrades off-domain | Generator portfolio (G0–G7) with union, per-generator provenance, marginal-recall measurement, and deletion of generators that only add burden | Designed; G0 live, G1/G6 written |
| 3 | Pundit extracts only from headlines; ignores time in causal relations | Full-prose extraction cascade; graph edges carry knowability instants; `as_of()` refuses post-cutoff queries | Written |
| 4 | Heterogeneous sources unconsidered; reduces real-life reliability | Four connectors on one ingestion surface, plus independence groups so reprints do not read as corroboration (§5.1) | Live for GDELT and data.gov.in |
| 5 | nMIL tested only on Latin-American articles | Preregistered subgroup reporting by language, geography, source availability, domain and rarity — reported whether or not flattering | Committed, not yet run |
| 6 | **Models need validation with actually occurred events** | The whole temporal-validity apparatus (§4) plus the 26/11 retrospective design (§8) | Apparatus built; study blocked on corpus |
| 7 | Event-specific features would improve accuracy | Declared-before-built features carrying `as_of` and `graph_cutoff_at` | Written |
| 8 | Tweet location unused as a feature | Entity resolution with independence clustering; gazetteer deliberately deferred as a licensed source | Partial — structures exist, data does not |
| 9 | Hashtag collection cannot guarantee relevance | Provenance and independence metadata on every evidence reference; contested fields marked `unresolved` rather than voted | Written |
| 10 | Dynamic/structural topic models unexplored | Slots in as a registered generator without touching the pipeline | Not built |
| 11 | **Validation of data and approaches is a shortcoming** | Preregistration, experiment registry recording failures, negative controls, and the reproducibility gate of §2.3 | Committed; registry holds synthetic demos only |
| — | Survey's own requirement: forecasts must carry plausible reasoning | Evidence packs showing supporting *and* contradicting evidence, contradictions seeded first, denials never merged away, source independence displayed | Written |

---

## 11. Verification status: what is executed and what is not

This section exists because the rest of the paper describes mechanisms, and a
mechanism that has been written is not a mechanism that has been run. In the
project's own vocabulary, **`DONE` means observed working; `WRITTEN` means code
exists that has never been executed or never been wired in.** The two are not
interchangeable and this paper does not treat them as such.

**Executed and observed working:** the temporal foundation — schemas, hashing and
storage, cutoff guard, snapshots, leakage audit; the synthetic connector; the G0
base-rate generator; the rolling backtest; the leakage and metamorphic suites
including the negative control; the end-to-end demo; the GDELT and data.gov.in
connectors, with data.gov.in verified live.

**Written but unverified:** the prose extraction cascade and gold-set machinery;
entity resolution and deduplication; the evidence graph and retrieval; feature
construction; the G1 temporal-rule generator and the G6 scenario interventions;
all four calibration families; the recall-first conformal controller.

**Not built at all:** candidate adjudication (no belief state, no adjudication
loop, in any branch); generators G2, G3, G4, G5, G7 and the union stage; the API
and dashboard; production engineering.

**Blocked on people, not code:** the licensed news corpus, which gates the
extraction, entity, retrieval, baseline-reproduction and retrospective stages
alike; blinded annotators for three separate gold sets; ReliefWeb appname
approval and ACLED credentials; the alert budget and the miss-versus-false-alarm
exchange rate; and external legal, domain and statistical review.

Approximately 25 of some 330 checklist items are closed. We report this
proportion rather than omitting it because a paper describing an architecture at
this stage, without stating how much of it has run, would commit precisely the
error §2 accuses the surveyed literature of committing.

---

## 12. Limitations

**No real-world forecasting result exists.** Every executed number to date comes
from a synthetic world with a machine-derived, unadjudicated outcome registry.
Those figures measure agreement with automated resolution, not with reality.

**The 26/11 study is a design, not a result.** Its blocking dependency is a
licensed, availability-stamped English corpus for 2006–2009. We expect the
fraction of documents whose availability cannot be established to be
substantial, and that fraction bounds the study before any model runs.

**Cutoff safety is necessary, not sufficient.** The ledger cannot detect
memorisation, prompt contamination or label bleed in learned components. No
regular expression finds those. They require the counterfactual and prospective
tracks, and the prospective track cannot be compressed: it is as long as its
reporting-delay window.

**The conformal guarantee rests on a violated assumption** (§7.3), and is
reported as approximate on every fit.

**Extraction is rule-based**, so recall on paraphrase and on Indian-English
register is unmeasured. Entity resolution lacks an authoritative gazetteer and
transliteration.

**Independence estimation is heuristic.** Syndication metadata is incomplete, and
undetected copying inflates effective support in the direction of overconfidence.

---

## 13. Conclusion

The 2020 survey ended by noting that qualitative predictive analytics on
unstructured streamed sources "still needs to be explored," and that models need
validating against events that actually occurred. This paper has argued that the
second of those is the harder and more urgent problem, and that it is
infrastructural: until a pipeline can demonstrate — from its artefacts, not from
its authors' assurances — that its evidence preceded its forecasts, its accuracy
figures are not measurements.

PRAMAAN-X is an attempt to make that demonstration routine. Its design principle
throughout is to prefer a structure that makes an error loud over a procedure
that makes it discouraged: availability time rather than event time,
append-only content-addressed evidence rather than mutable archives, content-only
snapshot identity so that reproducibility is literal equality, a runtime seal on
outcome data rather than a convention about statement order, censoring as a
condition on scoring rather than a correction to it, and calibration kept
separate from the alert policy so the policy stays visible to the people it
binds.

The 26/11 retrospective is the intended proving ground, and we have argued that
its target quantity should be the open-source ceiling rather than a hit. The
documented warning record for that attack was rich and almost entirely
classified in origin, which suggests the ceiling for open-text methods on
instance-level prediction is low — and that a system reporting elevated regional
hazard while abstaining on the instance is behaving correctly rather than
failing. Measuring that bound is a contribution the field can build on. Another
incomparable accuracy figure is not.

---

## References

1. Bhattacharjee, K., ShivaKarthik, S., Mehta, S., Kumar, A., Kothawade, R.,
   Katre, P., Dharkar, P., Pillai, N., Verma, D.: Survey and Gap Analysis on
   Event Prediction of English Unstructured Texts. In: Joshi, A., Khosravy, M.,
   Gupta, N. (eds.) Machine Learning for Predictive Analysis: Proceedings of
   ICTIS 2020. Lecture Notes in Networks and Systems, vol. 141. Springer,
   Singapore (2021). DOI: 10.1007/978-981-15-7106-0_49
2. Dami, S., Barforoush, A.A., Shirazi, H.: News events prediction using Markov
   logic networks. Journal of Information Science 44(1), 91–109 (2018)
3. Radinsky, K., Davidovich, S., Markovitch, S.: Learning causality for news
   events prediction. In: Proc. WWW, pp. 909–918 (2012)
4. Ning, Y., Muthiah, S., Rangwala, H., Ramakrishnan, N.: Modeling precursors
   for event forecasting via nested multi-instance learning. In: Proc. KDD,
   pp. 1095–1104 (2016)
5. Mueller, H., Rauh, C.: Reading between the lines: Prediction of political
   violence using newspaper text. American Political Science Review 112(2),
   358–375 (2018)
6. Schrodt, P.A., Yonamine, J., Bagozzi, B.E.: Data-based computational
   approaches to forecasting political violence. In: Subrahmanian, V.S. (ed.)
   Handbook of Computational Approaches to Counterterrorism, pp. 129–162.
   Springer (2013)
7. Ward, M.D., Greenhill, B.D., Bakke, K.M.: The perils of policy by p-value:
   Predicting civil conflicts. Journal of Peace Research 47(4), 363–375 (2010)
8. Perera, I., Hwang, J., Bayas, K., Dorr, B., Wilks, Y.: Cyberattack Prediction
   Through Public Text Analysis and Mini-Theories. In: IEEE Big Data,
   pp. 3001–3010 (2018)
9. Popat, K., Mukherjee, S., Yates, A., Weikum, G.: DeClarE: Debunking fake news
   and false claims using evidence-aware deep learning. arXiv:1809.06416 (2018)
10. Bates, S., Angelopoulos, A., Lei, L., Malik, J., Jordan, M.I.:
    Distribution-free, risk-controlling prediction sets. Journal of the ACM
    68(6), 1–34 (2021)
11. Government of Maharashtra: Report of the High Level Enquiry Committee on
    26/11 (Pradhan Committee), constituted 30 December 2008.
12. United States v. David Coleman Headley, N.D. Ill. — plea agreement (March
    2010) and sentencing (January 2013).
