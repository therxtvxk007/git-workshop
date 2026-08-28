# PRAMAAN-X: A Cutoff-Safe Architecture for Event Prediction from Unstructured Text, with a Base-Rate Hazard Evaluation for India

## Technical Report

---

### Document control

| Field | Entry |
| --- | --- |
| Report title | PRAMAAN-X: A Cutoff-Safe Architecture for Event Prediction from Unstructured Text, with a Base-Rate Hazard Evaluation for India |
| Report type | Technical report |
| Version | 1.0 (draft for review) |
| Status | Draft. Issued for technical review. Not approved for operational use. |
| Antecedent work | Bhattacharjee, K., ShivaKarthik, S., Mehta, S., Kumar, A., Kothawade, R., Katre, P., Dharkar, P., Pillai, N., and Verma, D., *Survey and Gap Analysis on Event Prediction of English Unstructured Texts*, ICTIS 2020, Springer LNNS Vol. 141 |
| Software reference | `pramaanx`, module `pramaanx.india`; registry `research/datasets/india_incidents.csv` |
| Classification of contents | Unclassified. All source material is in the public domain. |
| Principal limitation | One experimental result is reported (Section 9). All other quantitative material derives from a synthetic evaluation world and does not constitute evidence of real-world forecasting skill. |
| Operational status | This system is not authorised for operational alerting. No automated action is permitted downstream of any output described herein. |

---

## Executive summary

**ES.1** The antecedent survey classified the event-prediction literature into
probabilistic-logic, rule-based and machine-learning approaches, tabulated the
accuracies reported by each, and concluded with a gap analysis. Two items in
that gap analysis were methodological rather than algorithmic: that "the
proposed models need to be validated with actually occurred events", and that
"validation of data and approaches is an important shortcoming in the surveyed
approaches".

**ES.2** This report takes those two findings as its point of departure and
submits that they are not residual qualifications but the principal obstacle
confronting the discipline. It is established in Section 2 that the accuracies
tabulated in the antecedent survey are not mutually comparable, for the reason
that no surveyed method demonstrates that the evidence consumed by the model was
publicly available prior to the event the model purports to predict. It is
further established that this deficiency is self-concealing, in that every
instance of temporal contamination inflates the reported metric, with the
consequence that the ordinary development cycle terminates upon it rather than
detecting it.

**ES.3** This report describes PRAMAAN-X, a system constructed so that temporal
validity is demonstrable from the retained artefacts rather than asserted by the
investigator. Its contributions are architectural rather than algorithmic and
are enumerated at Section 1.4.

**ES.4** One experimental result is reported. A recency-weighted Gamma-Poisson
hazard model over Indian `(state, target class)` cells was fitted and scored by
walk-forward evaluation on a registry of 42 mass-casualty incidents occurring
between 1993 and 2025. The principal findings are as follows.

| Ref. | Finding | Value |
| --- | --- | --- |
| ES.4(a) | Lift over chance at rank 1 (cell) | **5.87** |
| ES.4(b) | Lift over chance at rank 10 (cell) | 1.57 |
| ES.4(c) | Lift over chance at rank 10 (state) | **0.98** (no skill) |
| ES.4(d) | Incidents falling in cells rankable only on the prior | **62.5%** |
| ES.4(e) | Rank of Maharashtra among states, cutoff 25 Nov 2008 | **2 of 11** |
| ES.4(f) | Rank of Maharashtra × hospitality cell, same cutoff | **47 of 66** |
| ES.4(g) | Prior incidents in that cell at that cutoff | **0** |

**ES.5** It is concluded from ES.4(a)–(c) that informative signal is present at
the extreme top of the ranking and decays rapidly with depth, such that the
state-level ranking is indistinguishable from chance at depth ten. It is
concluded from ES.4(d) that a majority of incidents occur in cells for which no
rate is estimable, and that this constitutes an upper bound on the performance
attainable by any rate-based method, irrespective of its sophistication.

**ES.6** It is concluded from ES.4(e)–(g) that the failure of the model in
respect of the events of 26 November 2008 was a failure of candidate discovery
and not of probability estimation: the regional signal was present and correctly
ranked, whereas the relevant target class possessed no precedent anywhere in the
registry and the corresponding hypothesis therefore lay outside the candidate
pool. These two failure modes admit unrelated remedies, and their conflation is
identified in Section 3.2 as a systematic defect of the surveyed literature.

**ES.7** Section 8 sets out the design of a retrospective evaluation of the
events of 26 November 2008 against contemporaneous open-source text. It is
submitted that the quantity such a study should estimate is not a prediction but
a **ceiling**, namely the proportion of pre-incident signal that was present in
open English-language text at all. The documented pre-attack record for that
event is extensive and almost wholly classified in origin, which renders it the
most stringent available test of the upper bound applicable to open-source
textual event prediction. That study is presently blocked upon acquisition of a
licensed corpus and is reported as a design, not as a result.

**ES.8** Recommendations are set out at Section 15. The principal recommendation
is that acquisition of a licensed, availability-stamped English-language news
corpus be treated as the critical-path dependency of the programme, five
subsequent stages being downstream of it.

---

## Table of contents

1. Introduction
2. The validity problem in the surveyed literature
3. System architecture
4. Temporal validity controls
5. Evidence sources and independence
6. Extraction, entity resolution, graph and features
7. Calibration and risk-controlled alerting
8. Retrospective case study design: 26 November 2008
9. Experimental results: base-rate hazard model
10. Preregistration and claim discipline
11. Disposition of the surveyed research gaps
12. Verification status
13. Limitations
14. Conclusions
15. Recommendations
- References
- Appendix A — Incident registry: schema, provenance and admissibility
- Appendix B — Reproduction procedure
- Appendix C — Detailed verification status

## List of tables

| Table | Title |
| --- | --- |
| 1 | Stage decomposition, metrics and isolated failure modes |
| 2 | Evidence sources and their structural limitations |
| 3 | Walk-forward rank skill against chance |
| 4 | Retrospective at cutoff 25 November 2008 |
| 5 | Forward hazard assessment, five highest-ranked cells |
| 6 | Disposition of the surveyed research gaps |
| 7 | Verification status by category |

## Abbreviations and definitions

| Term | Definition |
| --- | --- |
| ACLED | Armed Conflict Location and Event Data Project |
| CAMEO | Conflict and Mediation Event Observations coding scheme |
| Cell | A pair comprising one state and one target class, evaluated over a stated horizon |
| Cutoff | The instant at or before which evidence must have been available in order to be admissible |
| Cutoff safety | The property that a forecast issued for instant *T* consumed only evidence retrievable at or before *T*, demonstrably so from the retained artefacts |
| GDELT | Global Database of Events, Language and Tone |
| GTD | Global Terrorism Database |
| HUMINT | Human intelligence |
| Lift | The ratio of an observed hit rate to the hit rate obtainable by a uniformly random ranking |
| LNNS | Lecture Notes in Networks and Systems |
| MLN | Markov Logic Network |
| nMIL | Nested multi-instance learning |
| Prior-driven | Descriptive of a cell whose rank is determined by the pooled prior rather than by its own history |
| RCPS | Risk-controlling prediction sets |
| SATP | South Asia Terrorism Portal |
| SIGINT | Signals intelligence |

---

## 1. Introduction

### 1.1 Background

1.1.1 The antecedent survey addressed three objectives: to summarise the
technical approaches to future event prediction from text; to identify the
features upon which those approaches depend; and to produce a gap analysis. It
grouped the literature into probabilistic-logic approaches, comprising Markov
Logic Networks applied to event representations transformed into Web Ontology
Language with first-order causal rules and large-scale ontologies supplying
background knowledge; rule-based approaches, comprising the Pundit line of
causality learning from news; and machine-learning approaches, comprising nested
multi-instance learning for precursor discovery and latent Dirichlet allocation
applied to newspaper text for the prediction of political violence.

1.1.2 The antecedent survey treated evidence gathering and scoring as a separate
category, on the stated ground that a prediction unaccompanied by displayable
support is not usable. That requirement is expressed in its introduction, which
states that for a system to be "credible and determinantal in preventing the
predicted events from occurring", it is "essential for such a system to provide
plausible reasoning for its forecast".

1.1.3 It is accordingly to be noted that the antecedent survey does not confine
itself to requesting improved metrics. It requests systems whose forecasts admit
of inspection.

### 1.2 The findings of the antecedent gap analysis

1.2.1 Section 5 of the antecedent survey enumerates approximately twelve gaps.
The majority are algorithmic and local in character: that Markov Logic Network
frameworks depend upon domain rules authored by human experts and degrade when
applied off-domain; that the Pundit method extracts events from news headlines
only and disregards the effect of time upon causal relations; that the nested
multi-instance learning method was evaluated exclusively upon articles drawn
from Latin-American countries and does not employ regularised multi-task
learning; that the location of a tweet or of its author constitutes an unused
feature; that collection by hashtag cannot guarantee relevance; and that the
surveyed approaches do not consider multiple heterogeneous data sources, which
the antecedent survey states "in turn reduces the real life reliability".

1.2.2 Two findings are of a different character and are reproduced verbatim:

> "Also, the proposed models need to be validated with actually occurred
> events."

> "It has been seen that validation of data and approaches is an important
> shortcoming in the surveyed approaches because of high processing needs and
> costs."

1.2.3 These are not deficiencies attributable to any individual method. They
constitute a statement that the comparative table presented in the antecedent
survey, which sets out datasets and reported accuracies in adjacent columns,
does not license the comparison that a reader will naturally draw from it. Where
two systems have been validated by different procedures, or have been validated
against corpora already containing reporting concerning the events to be
predicted, their accuracy figures do not measure the same quantity, and the
larger figure does not denote the superior system.

### 1.3 Statement of the problem

1.3.1 The central proposition of this report is that the two findings at 1.2.2
are of greater consequence than the remainder, and that their resolution
requires infrastructure rather than modelling.

1.3.2 The argument may be stated concisely. Every surveyed method consumes a
corpus of text and emits a prediction concerning an event. The prediction is
scored against the occurrence of that event. In order that the resulting score
should measure what it appears to measure, one property must obtain: **every
document consumed by the model must have been publicly available prior to the
forecast instant.** No surveyed method demonstrates this property. The majority
could not do so, for the reason that the corpora employed — news archives,
collections of social media posts, and event registry exports — record the date
asserted by a publisher rather than the date upon which a document became
retrievable, and are in addition subject to recrawling, revision and
retrospective completion.

1.3.3 The consequence is not stochastic but directional. Reporting published
subsequent to an event is, by construction, the most predictive text concerning
that event that will ever exist. A corpus admitting any quantity of such
reporting yields a model that appears excellent and forecasts nothing.

1.3.4 It is material that the deficiency conceals itself. Because contamination
inflates the metric, no stage of the ordinary development cycle will detect it;
each incremental leak presents as progress.

1.3.5 The question implied by the antecedent gap analysis is therefore not which
estimator performs best, but what conditions must obtain within a pipeline
before any accuracy figure computed within it merits examination. This report
answers that question by exhibiting a system.

### 1.4 Objectives and contributions

1.4.1 This report makes the following contributions.

(a) A restatement of the validation gap identified in the antecedent survey as
the principal obstacle confronting the discipline, together with an account of
the mechanism by which it conceals itself (Section 2).

(b) A four-stage decomposition of the forecasting task — candidate discovery,
candidate adjudication, calibration, and risk-controlled alerting — justified
upon the ground that conflation of discovery with scoring renders recall
failures and probability failures indistinguishable notwithstanding that they
admit unrelated remedies (Section 3).

(c) The implementation of temporal validity as a structural property of the
evidence store rather than as a procedure, each mechanism having been selected
because it converts a matter of investigator discipline into an assertion that
fails audibly (Section 4).

(d) The treatment of censoring as a condition upon the admissibility of scoring
rather than as a correction applied to it (Section 4.5).

(e) The separation of calibration from alert policy, alerting being governed by
a recall-first conformal bound that reports upon every fit the exchangeability
assumption which temporal forecasting violates (Section 7).

(f) An executed experimental result: a recency-weighted Gamma-Poisson hazard
model over Indian region and target-class cells, scored by walk-forward
evaluation against chance, whose retrospective at 25 November 2008 separates a
regional signal that was present from an instance-level hypothesis that was
absent (Section 9).

(g) The design of a retrospective evaluation whose target quantity is the
open-source ceiling rather than a successful prediction (Section 8).

(h) A preregistration and claim-discipline regime fixing in advance what shall
count as evidence (Section 10), together with an explicit statement of what
remains unverified (Section 12).

### 1.5 Scope and exclusions

1.5.1 The following are within scope: architecture; temporal validity controls;
evidence acquisition and independence estimation; calibration and risk control;
the base-rate hazard evaluation reported at Section 9; and the retrospective
study design at Section 8.

1.5.2 The following are expressly excluded from scope.

(a) **Any assertion identifying the location, date, site or perpetrator of a
future attack.** The system estimates rates over regions and horizons. An
instance-level assertion is not a quantity it computes, and Section 8.5 sets out
the grounds upon which such an assertion is not derivable by narrowing the
horizon or by any other transformation of the outputs described herein.

(b) Any claim of real-world forecasting accuracy beyond the result reported at
Section 9, which is itself subject to the limitations recorded at Section 13.

(c) Any authorisation for operational use. No automated action is permitted
downstream of any output described in this report.

### 1.6 Structure of this report

1.6.1 Section 2 establishes the validity problem. Section 3 describes the
architecture. Section 4 describes the temporal validity controls. Sections 5 to
7 describe evidence handling, extraction and calibration respectively. Section 8
sets out the retrospective study design. Section 9 reports the experimental
result. Sections 10 to 13 address claim discipline, gap disposition,
verification status and limitations. Sections 14 and 15 state conclusions and
recommendations. Appendices A to C provide the registry specification, the
reproduction procedure and the detailed verification status.

---

## 2. The validity problem in the surveyed literature

### 2.1 Mechanisms of temporal contamination

2.1.1 Consider a model predicting civil unrest within a city over a horizon of
seven days, trained and evaluated upon a news archive assembled by querying a
news interface for all articles mentioning that city, each article being stamped
with its publication date, the evaluation partitioning documents at random
between training and test sets.

2.1.2 Three distinct mechanisms of contamination are then present. None produces
an error condition.

2.1.3 **Random partitioning.** A random partition places articles published
subsequent to an event within the training set and articles published prior to
it within the test set. The model acquires the vocabulary of aftermath reporting
— casualty counts, statements of condolence, announcements of curfew — and
applies it to predict the event that occasioned them. The reported accuracy
rises. The model has learnt to recognise the past tense.

2.1.4 **Publication date treated as availability.** A publication date is an
assertion made by a publisher concerning a document; it is not a record of the
instant at which a reader could retrieve that document. Archives are completed
retrospectively; wire copy is revised in place beneath its original timestamp;
aggregators assign the date of first syndication to a body composed
subsequently. Filtering upon the asserted date admits documents whose present
text did not exist at the asserted instant.

2.1.5 **Recrawling.** A corpus assembled at the present date from uniform
resource locators published in a prior year contains the locators of that prior
year and the document bodies of the present. In respect of any article
subsequently updated — which is to say, the majority of articles concerning
developing events — the text in hand is the text as it stood after the outcome
became known.

2.1.6 Each mechanism inflates the reported metric. None produces an exception,
an anomalous distribution, or any other signature detectable by inspection of
outputs. The model improves, which is the outcome sought by the investigator,
and the development cycle accordingly terminates.

### 2.2 Consequences for comparative assessment

2.2.1 The summary table of the antecedent survey sets out, for each approach,
the data source, the principal features, and the reported accuracy. Construed as
a record of what each cited work reported, it is accurate and of value.
Construed as a ranking, it presupposes a proposition that the cited works do not
establish, namely that the reported accuracies measure the same quantity.

2.2.2 They do not, and the divergence is not marginal. A system evaluated upon
headline-only inputs drawn from a curated event registry, a system evaluated
upon Spanish-language protest reporting under a temporal partition, and a system
evaluated upon a randomly partitioned archive of complete articles measure three
distinct quantities, of which one only bears resemblance to forecasting. The gap
analysis of the antecedent survey states as much in observing that the nested
multi-instance learning method "was only tested on articles selected from
Latin-American countries".

2.2.3 It is submitted that a discipline cannot advance in respect of a quantity
it is unable to measure consistently, and that construction of the measurement
apparatus is accordingly prior to the proposal of further estimators.

### 2.3 Definition: cutoff safety

2.3.1 The term **cutoff-safe** is used in this report to denote the property
that a forecast issued for instant *T* consumed only evidence retrievable at or
before *T*, and that this may be demonstrated subsequently from the retained
artefacts alone rather than upon the assurance of the investigator.

2.3.2 The standard of demonstration adopted is the following gate:

> The injection into the evidence ledger of correctly dated future documents
> shall leave the snapshot identifier of every earlier cutoff **byte-identical**.

2.3.3 This is a stringent condition. It is not satisfied by filtering at query
time, a filter being a statement that a subsequent amendment may relocate. It is
satisfied only where the identity of a snapshot is a function of its admitted
content, which is the construction set out at Section 4.3.

---

## 3. System architecture

### 3.1 The four-stage decomposition

3.1.1 The system is decomposed as follows:

```
candidate discovery -> candidate adjudication -> calibration -> risk-controlled alerting
```

3.1.2 This decomposition is not an implementation convenience. It embodies a
proposition concerning the attribution of failure.

### 3.2 Failure attribution

3.2.1 A model cannot assign a score to a future event that has not entered its
candidate pool. Where discovery and scoring constitute a single operation, a
system that fails to anticipate an event affords no means of determining whether
the event was never considered or was considered and assigned low probability.

3.2.2 These failures have no remedy in common. The first is addressed by the
addition of a generator, by broadening retrieval, or by increasing the candidate
budget. The second is addressed by improved weighting of evidence or by
recalibration. A system unable to distinguish them will apply the incorrect
remedy and observe no improvement.

**Table 1 — Stage decomposition, metrics and isolated failure modes**

| Stage | Question addressed | Principal metric | Failure mode isolated |
| --- | --- | --- | --- |
| Discovery | Did the event enter the candidate pool? | Candidate recall at fixed budget | Coverage |
| Adjudication | Given the evidence, what is its likelihood? | Discrimination (AUC, log loss) | Reasoning |
| Calibration | Do the stated probabilities mean what they state? | Brier score, reliability by bin | Overconfidence |
| Risk control | Which forecasts are escalated to alerts? | Recall at alert budget; alerts per region-day | Policy |

3.2.3 The corresponding diagnostic is the **candidate oracle**: the discovery
stage is replaced by an oracle that invariably includes the true event, and the
system is rescored. The difference between oracle-discovery performance and
end-to-end performance is the quantity of loss attributable to discovery.

3.2.4 This diagnostic is available only where the union stage preserves the
identity of the generator that proposed each candidate. For this reason the
merge operation retains per-generator traces notwithstanding that the present
configuration employs a single generator and there is accordingly nothing to
merge. Retrospective introduction of such provenance is the mechanism by which
the diagnostic ceases to be available.

3.2.5 Section 9.5 reports an instance in which this distinction is dispositive
upon historical data.

### 3.3 Representation of unimplemented stages

3.3.1 Stages not yet implemented are named within every forecast record they
would otherwise have affected. A forecast issued by the present system carries
the strings `calibration: identity@uncalibrated` and
`alert_policy: fixed_threshold@placeholder`.

3.3.2 The ground for this treatment is that a module returning plausible output
without performing its function is more damaging than an absent module, in that
it causes an omitted requirement to present as satisfied. A downstream consumer
reading a probability field cannot determine whether calibration was applied
unless the artefact so states. The artefact therefore so states, in terms that
do not admit of misconstruction, and the string is emitted by the component
itself rather than by a constant maintained elsewhere.

3.3.3 A testable consequence follows. Where the placeholder components are
replaced by injectable components carrying identity defaults, the resulting
forecast records shall be **byte-identical**. An amendment that alters outputs
while purporting to preserve behaviour is thereby detected by equality rather
than by review.

---

## 4. Temporal validity controls

4.0.1 The mechanisms described in this section share a common design rule: a
structure that renders an error impossible or audible is to be preferred to a
procedure that renders it discouraged.

### 4.1 Availability time

4.1.1 Every observation carries the field `first_observed_at`, which answers a
single question: the instant at which this system could legitimately have
obtained this document. It does not record the instant at which the described
event occurred, nor the instant at which a publisher asserts publication.

4.1.2 This is the sole field upon which cutoff filtering operates. Its incorrect
derivation is the only defect that silently defeats every downstream guarantee.

4.1.3 Two consequences arise within the connector layer.

(a) **GDELT.** The `SQLDATE` column records the date of the *event*. Its use
would retrospectively date every row into the period preceding the existence of
the reporting. The connector employs the fifteen-minute export slot together
with a conservative publication lag.

(b) **ReliefWeb.** The interface serves only the current revision of a report and
provides no version history. Availability is accordingly derived as
`max(date.created, date.changed)`, and never as `date.created` alone. A report
published in 2020 and revised in 2026 enters a 2026 snapshot, for the reason
that the body in hand is the body of 2026. This treatment is deliberately
conservative: it withholds from early cutoffs certain evidence that a
contemporaneous reader did in fact possess, in preference to attributing to an
early cutoff a sentence composed subsequently.

4.1.4 The general rule is that where availability is uncertain the system errs
toward withholding evidence, and records that which it has withheld.

### 4.2 Append-only content-addressed evidence

4.2.1 Primary storage is append-only and content-addressed. An article amended
subsequent to a cutoff cannot overwrite its earlier state; it becomes a *new*
observation bearing a *later* `first_observed_at`, which the guard excludes.

4.2.2 This construction converts the detection of amended document bodies, which
is in general an intractable problem in textual forensics, into a structural
property of the store.

4.2.3 The residual exposure is evidence that misreports its own observation
time, which no ledger can eliminate. That residue is addressed by two measures:
a leakage audit screens for identical content appearing under widely separated
dates; and the metamorphic test suite contains an explicit **negative control**
demonstrating that deliberately back-dated evidence is in fact admitted. A test
suite demonstrating successes alone does not establish the boundary of a
guarantee; the negative control establishes it.

### 4.3 Snapshot identity

4.3.1 The identifier of a snapshot is computed over sorted observation hashes,
source versions, the code hash and the configuration hash. It is **not** computed
over creation time, file layout, or run metadata.

4.3.2 In the absence of this construction the gate at 2.3.2 is not testable: the
proposition that a forecast is unchanged could signify no more than approximate
similarity, every rebuild producing distinct bytes. With it, the assertion is one
of literal equality.

4.3.3 Snapshot identity includes the code hash by design, with the consequence
that a snapshot pins both the evidence and the logic by which that evidence was
selected. Amendment of the guard produces a new snapshot identifier over
identical evidence. This is the intended behaviour: the former identifier
continues to denote that which the former code admitted, and a forecast pinned
to it remains interpretable.

### 4.4 Outcome isolation

4.4.1 Backtests execute in two passes. Pass A constructs snapshots and persists
forecasts. Pass B constructs outcomes and scores that which Pass A has frozen.
Pass A executes within a context manager that seals every entry point capable of
reading outcome data for its duration; any such read raises rather than
returning data.

4.4.2 The material distinction is against the obvious alternative. A prior design
enforced the same *ordering* by the sequence of statements within a single
function. Such an arrangement holds until an amendment relocates an outcome
lookup to an earlier position, and no aspect of such an amendment presents as
defective: the run succeeds and the metrics improve. A context variable causes
the error to raise instead, from whatever depth of the call stack it occurs.

4.4.3 Pass B re-reads forecasts from the ledger rather than retaining them in
memory, with the consequence that the object scored is demonstrably the object
persisted prior to the existence of any outcome.

4.4.4 The limitation is recorded within the module itself: the control cannot
prevent a determined caller from reading a stored file directly, and is not
intended to do so. It renders the error audible in the single circumstance in
which it is in fact probable.

### 4.5 Censoring

4.5.1 Evidence terminating prematurely does not produce noisy metrics. It
produces confidently incorrect metrics, in a known direction, bearing no
signature within the figures themselves.

4.5.2 The mechanism is as follows. Reports not yet received are indistinguishable
from events that did not occur. Recall is accordingly understated and precision
overstated.

4.5.3 A fold is therefore **scoreable** only where the ledger extends to
`cutoff + horizon + reporting delay`, the delay being the greater of a configured
floor and the maximum delay in fact observed within the outcome registry. Folds
of insufficient extent are forecast, the forecasting work being valid and the
scoring alone being invalid, but are marked unscoreable, excluded from the
aggregate, and identified within the report. A walk containing no scoreable fold
raises rather than emitting a report composed of artefacts.

4.5.4 This is submitted as a substantive methodological position rather than an
implementation detail. A substantial proportion of the surveyed literature
evaluates upon windows terminating at the end of the corpus, which applies
maximum censoring to the most recent and most consequential folds without
disclosure.

### 4.6 Derivation of ground truth

4.6.1 The synthetic evaluation world does not supply the pipeline with its latent
events. It publishes reports *subsequent* to their occurrence, and the outcome
registry is constructed from those reports, by the same path a deployment would
employ. An accessor returning ground truth exists for the purposes of test
assertion and is never invoked by the pipeline.

4.6.2 The injection of known answers would render the loop untestable in the
single respect that is material, the system being scored against information it
could in principle have reached.

### 4.7 Determinism

4.7.1 The following are excluded: random identifier generation; retrieval of wall
clock time otherwise than through an injectable clock; and use of the language's
built-in hash function at any point at which its value escapes the process, that
value being salted per process. Identifiers are derived from content. Ordering is
explicit at every aggregation boundary.

4.7.2 This is not a matter of tidiness. A pipeline that cannot be shown to be
deterministic cannot be shown to be free of leakage, the proposition that an
output has changed having ceased to be evidence of anything.

---

## 5. Evidence sources and independence

### 5.1 Source multiplicity and syndication

5.1.1 The antecedent survey observes that the surveyed approaches "do not
consider multiple and heterogeneous data sources which in turn reduces the real
life reliability". That observation is correct. It is submitted, however, that
the immediate reading — that further sources should be added — aggravates a
distinct problem.

5.1.2 News reporting is syndicated. A wire item reproduced by forty outlets
constitutes one item of evidence appearing forty times. A model that counts
documents will construe reprint volume as corroboration and will become more
confident in proportion to the breadth of reproduction of a single claim. The
addition of sources increases reprint volume more rapidly than it increases
independent testimony.

5.1.3 The system accordingly computes **independence groups** during
deduplication, the effective support of an event cluster counting independent
reports rather than mentions. Retrieval populates an independence cluster upon
every evidence reference, and evidence packs are capped per independent report by
round-robin selection, such that a pack cannot be composed of forty reproductions
of a single wire item.

### 5.2 Treatment of contradiction

5.2.1 Two rules govern disagreement.

(a) **Denials are not merged away.** A denial does not vote against an assertion
and lose; it marks the cluster as contested. The consensus step within the
extraction cascade marks contested fields as unresolved rather than resolving
them by majority.

(b) **Contradictions are seeded in advance of the general fill.** An evidence pack
is populated first with known contradicting evidence and thereafter completed. A
pack is accordingly never unanimous where the corpus is not.

5.2.2 This is the mechanism by which the explainability requirement of the
antecedent survey is satisfied. A pack exhibiting supporting evidence alone does
not constitute reasoning; it constitutes advocacy. The requirement is met by
displaying supporting and contradicting evidence together with source
independence, which is possible only where the preceding stages have declined to
average the disagreement away.

### 5.3 Current sources and their limitations

**Table 2 — Evidence sources and their structural limitations**

| Source | Character | Credential | Structural limitation for forecasting |
| --- | --- | --- | --- |
| GDELT | Machine-coded event records | None | Coding noise; event-time column unusable as availability |
| ReliefWeb | Curated humanitarian reporting | Approved appname | Response-driven; reports follow events by design |
| data.gov.in | Administrative aggregate | Interface key | Annual retrospective; supports contextual base rates only |
| ACLED | Hand-coded conflict events | OAuth | Coded subsequent to events; living dataset subject to revision |

5.3.1 It is recorded that **none of these sources, taken alone, supplies
pre-incident signal.** Three of the four are retrospective by construction. They
support base rates, context and outcome construction. They do not constitute the
pre-event evidence stream required by the study designed at Section 8.

5.3.2 The largest unstarted dependency of the programme is a legally frozen
English-language news corpus, inclusive of Indian regional sources, storing
publication, retrieval and revision instants separately. This is recorded not as
a qualification but as the reason for which Section 8 is a study design rather
than a result, and it is the subject of Recommendation R1.

5.3.3 It is further recorded that in the environment in which this report was
prepared, network egress to GDELT and ACLED was refused by policy at the connect
stage. No substitute figures were generated. The result reported at Section 9
derives from the incident registry specified at Appendix A and from no other
source.

### 5.4 Protected attributes

5.4.1 GDELT supplies per-actor ethnic and religion code columns. The system
forecasts population-level and organisational events and shall not employ
protected identity as a proxy for risk. Those columns are accordingly removed
**at ingestion**, prior to their availability to any downstream stage, rather than
filtered at feature construction.

5.4.2 The reasoning is mechanical rather than declaratory. Evidence that never
enters primary storage cannot become a feature by inadvertence, cannot be
reintroduced by a subsequent contributor unacquainted with the policy, and cannot
persist within a cached intermediate. A policy enforced at the boundary
constitutes a property; a policy enforced downstream constitutes a practice.

5.4.3 The same commitment is recorded within the preregistration as a limitation
of scope: the system predicts population-level and organisational events and does
not produce risk scores in respect of private individuals.

---

## 6. Extraction, entity resolution, graph and features

### 6.1 Extraction cascade

6.1.1 The antecedent survey criticises the Pundit method for extracting events
from news headlines only. The extraction layer described here operates upon
complete prose, comprising sentence segmentation, an event-trigger lexicon,
modality detection and date resolution.

6.1.2 Two provisions carry the design weight.

(a) **Modality is subject to a precedence order.** Denial takes precedence over
planning, which takes precedence over hedging. The sentence "officials denied
reports of a planned strike" constitutes a denial and not a planning statement,
and a classifier scoring each modality independently will misclassify it in the
direction that inflates candidate counts.

(b) **Relative dates resolve against the availability instant of the
observation, and never against the wall clock.** The term "yesterday" within a
document available on 12 March denotes 11 March, irrespective of the time at
which the pipeline executes. Resolution against the wall clock would render
extraction output dependent upon execution time, defeating both determinism
(4.7) and replay.

6.1.3 The learned stages contemplated by the design — span tagger, event-type
classifier, and constrained verifier — are **not** implemented, upon the ground
that a learned stage lacking a measured error rate against a gold set
constitutes an unquantified claim. Such stages implement the same protocol and
attach without amendment to the cascade once a gold set exists.

6.1.4 The gold-set machinery refuses construction in the absence of an annotator
identity, a date, and a guidelines version.

### 6.2 Entity resolution

6.2.1 Resolution comprises blocking together with scored merge, deterministic by
construction through sorted candidate pairs and union-find with
lexicographically smallest representatives.

6.2.2 The system implements **no gazetteer**. A gazetteer for Indian location
resolution constitutes a licensed *source* possessing provenance, versioning,
renames and hierarchy changes, and belongs within the connector path under the
same availability and licence discipline as every other source. Transliteration
across the major Indian languages is subject to the same constraint. This is a
capability gap and is recorded as such.

6.2.3 Validation is subject to the same discipline: merges shall be validated
against human labels, with **false-merge and false-split rates reported
separately**, those errors having opposite causes and a combined rate concealing
which is occurring.

### 6.3 Evidence graph

6.3.1 Every edge carries the instant at which it became knowable, and every
query is mediated by an as-of accessor which **raises** rather than silently
returning the whole graph when interrogated in respect of an instant beyond its
build cutoff.

6.3.2 The absence of a current-state view is deliberate. A graph that may be
queried without a time argument will in due course be queried without a time
argument, from within a forecasting pass, by a contributor unacquainted with the
convention. The interface removes the option.

### 6.4 Feature construction

6.4.1 Every feature vector carries an as-of instant and a graph cutoff instant.
The question whether a given quantity could have been computed upon the date it
asserts is accordingly answerable from the artefact alone, without re-execution
of the pipeline and without reliance upon a log.

---

## 7. Calibration and risk-controlled alerting

### 7.1 The inadequacy of accuracy as a metric

7.1.1 The summary table of the antecedent survey reports accuracy, as does the
substantial majority of the surveyed literature. For rare-event forecasting this
measure is close to uninformative: a model predicting the absence of an event
everywhere attains excellent accuracy upon any realistic base rate, and two
models of identical accuracy may possess entirely different operational value.

7.1.2 The quantities of operational consequence are whether a stated probability
means what it states — whether events assigned 0.3 occur in approximately thirty
per cent of instances — and, separately, what policy converts probabilities into
actions.

### 7.2 Separation of calibration from policy

7.2.1 Two protocols are maintained separately by design. A **calibrator** maps
scores to probabilities and is assessed by a proper scoring rule. A **risk
controller** maps probabilities to statuses and encodes a policy concerning the
number of missed events that shall be accepted in exchange for a given number of
false alerts.

7.2.2 Their fusion conceals the policy within the model. A single tuned threshold
embedded within a scorer constitutes a decision as to the relative cost of a
missed event and a spurious alert, taken implicitly by whoever performed the
tuning, and invisible to those bearing the consequences.

7.2.3 Calibration shall be fitted upon strictly earlier folds and never upon the
test period, the family being selected from among identity, Platt, isotonic and
beta **in advance of** final testing, with minimum sample sizes enforced and raw
scores preserved alongside calibrated scores.

### 7.3 Recall-first conformal risk control

7.3.1 The fitted controller implements risk-controlling prediction sets:
candidate thresholds are scanned, the empirical risk at each is bounded by a
Hoeffding upper confidence bound, and the largest threshold whose bound clears
the target is selected, being the fewest alerts consistent with the guarantee.

7.3.2 The guarantee is expressed in recall-first terms:

> Of the events that in fact occur, at most α shall fall below the alert
> threshold, with confidence 1 − δ.

7.3.3 The direction is a position and not a convention. Bounding false alerts in
the expectation that recall will follow is the incorrect trade for an
early-warning system, a missed mass-casualty event and a spurious alert not being
symmetric errors, and a controller treating them symmetrically having thereby
taken a policy decision to which no responsible party has assented.

7.3.4 Two refusals are implemented.

(a) The controller **raises** where the calibration sample cannot support the
requested guarantee, identifying the positive count that would suffice. It does
not silently relax α. This is material because the bound depends upon the
*positive* count and not upon sample size: one hundred thousand forecasts
containing four positive instances support a guarantee constructed upon four
observations.

(b) Every fit carries an **exchangeability caveat**, and the report object
refuses validation in its absence. Finite-sample conformal validity presupposes
that calibration and test data are exchangeable; temporal forecasting violates
this presupposition, regimes shifting and reporting practice altering over time.

7.3.5 The second refusal is submitted to be the more consequential. A bound
quoted without its assumption is more damaging than no bound, in that it invites
the reliance it cannot support. Attachment of the caveat to the artefact rather
than to the report ensures its survival when the figure is transcribed.

### 7.4 Parameters not derivable by computation

7.4.1 The parameter α is a policy parameter. The default value implemented is
0.10 and is designated a demonstration default rather than a policy; the value
properly belongs to the party bearing the consequences of a missed event.

7.4.2 The alert budget, expressed as alerts per region-day capable of being
triaged, and the exchange rate between missed events and false alerts, are
decisions for the parties who would receive the alerts. They are recorded as
unresolved dependencies rather than populated with defaults, a default in this
position constituting a policy adopted inadvertently. This is the subject of
Recommendation R4.

---

## 8. Retrospective case study design: 26 November 2008

### 8.1 Grounds for selection

8.1.1 The antecedent survey requires that models "be validated with actually
occurred events". The attacks of 26 November 2008 at Mumbai constitute a
particularly suitable validation anchor, upon four grounds.

(a) **The outcome is unambiguous.** Ten attackers, having arrived by sea, struck
Chhatrapati Shivaji Terminus, the Taj Mahal Palace hotel, the Oberoi Trident,
Nariman House, the Leopold Cafe and Cama Hospital between 26 and 29 November
2008, causing more than one hundred and sixty deaths. No question of adjudication
arises as to whether the event occurred, which removes the largest source of
noise in outcome construction.

(b) **The pre-attack record is documented to an unusual degree**, through the
Pradhan Committee, proceedings in the United States District Court for the
Northern District of Illinois against David Coleman Headley, and extensive
subsequent journalism.

(c) **The date is sufficiently remote that reporting has settled**, with the
consequence that the censoring problem described at 4.5 does not bind.

(d) **It is the case concerning which a security-analytics system will be
interrogated.** A method unable to state what it would have done in respect of
these events does not present interesting claims concerning simpler cases.

### 8.2 The documented pre-attack record

8.2.1 The documented warning record is substantial. The Pradhan Committee found
seventeen alerts issued since 7 August 2006 concerning the possibility of
sea-borne attacks and of multiple simultaneous fidayeen attacks. United States
intelligence warned Indian counterparts in mid-October 2008 of a
Lashkar-e-Taiba threat to sites at Mumbai frequented by Westerners, including the
Taj; hotel security was reportedly increased and subsequently reduced. On 18
November 2008 a satellite telephone call to a Lashkar figure was intercepted,
indicating a sea-borne plan. Headley conducted five surveillance visits to Mumbai
between September 2006 and July 2008, recording global positioning data, taking
boat journeys about the harbour in March 2008 in order to identify a landing
site, and recording video of the eventual targets, which material he delivered to
his handlers.

8.2.2 The Committee found that there was "total confusion in processing
intelligence alerts at the state level", while it "did not find any failure to
act on inputs by the central intelligence agencies".

8.2.3 The following property of that record is material to the present analysis.
**Substantially none of it constituted open-source text.** The seventeen alerts
were classified intelligence products. The October warning was a liaison
communication between services. The interception of 18 November constituted
signals intelligence. The reconnaissance conducted by Headley was covert by
definition, its entire purpose being that it should not appear within public
reporting, and it did not so appear.

### 8.3 The open-source ceiling

8.3.1 There follows the research question properly posed by this case study,
which is not whether the system would have predicted the attacks.

> What proportion of the pre-attack signal in respect of the events of 26
> November 2008 was present within open English-language text prior to that date?

8.3.2 This quantity is designated the **open-source ceiling**. It constitutes an
upper bound upon the performance of *any* system within the class reviewed by the
antecedent survey, every method within that survey consuming public text, and it
is a property of the world rather than of a model. No architecture, however
constructed, may exceed it. It is measurable, and it is not known to have been
measured in respect of a case of this significance.

8.3.3 The distinction thereby made available is that constructed at Section 3.1.
Two questions are to be separated.

(a) **Discovery.** Did open text, prior to the attack, support the placement of
Mumbai, and of hotel-class and transit-class targets, within an elevated band
relative to base rate? This is plausibly answered in the affirmative and is
testable.

(b) **Adjudication.** Did open text support the specific instance — the date, the
targets, sea-borne infiltration, the particular cell? This is almost certainly
answered in the negative, upon documentary rather than algorithmic grounds, the
information specifying the instance having been by design never public.

8.3.4 Section 9.5 measures precisely this distinction upon the incident registry
and finds it: Maharashtra ranked second of eleven states at a cutoff of 25
November 2008, whereas the hotel-class cell ranked forty-seventh of sixty-six,
possessing no precedent anywhere within the registry.

8.3.5 A system reporting elevated regional hazard and abstaining upon the
instance behaves correctly given its inputs. A system reporting the instance is
either reading a leak or fabricating. The retrospective is accordingly of
scientific value in either direction: a *negative* result, establishing that the
ceiling is low and reporting its measurement, constitutes a contribution to a
field whose reported accuracies imply that the ceiling is high.

### 8.4 Study design

8.4.1 **Cutoff.** Primary cutoff 25 November 2008 at 00:00 UTC, with a sweep at
7, 14, 30, 90 and 180 days prior in order to characterise the behaviour of any
signal as a function of lead time. A single cutoff cannot distinguish a genuine
precursor from a coincidence at one horizon.

8.4.2 **Corpus.** English-language reporting available prior to each cutoff, drawn
from a frozen archive storing publication, retrieval and revision instants
separately, preserving original bytes or permitted hashes, and carrying
syndication metadata sufficient for the computation of source independence. This
corpus does not presently exist and constitutes the blocking dependency of the
study.

8.4.3 **Admission.** Every document shall pass the cutoff guard upon availability
time. Given a corpus of 2008 assembled at the present date, availability must be
derived from archival crawl records and not from publication metadata. Where
availability cannot be established the document shall be excluded and the
exclusion counted. The excluded fraction is expected to be substantial and
constitutes in itself a reportable result concerning corpus quality.

8.4.4 **Forecast.** Produced within a sealed forecasting pass, pinned to a
snapshot hash, and written to the immutable ledger prior to the reading of any
outcome.

8.4.5 **Scored quantities.** Candidate recall, being whether a Mumbai,
hotel-class or transit-class mass-casualty hypothesis entered the pool, at what
budget and at what lead time; the hazard ratio, being the forecast probability
for the region-window relative to the base rate assigned by the same generator to
comparable Indian regions; evidence attribution, being which documents occasioned
any elevation and whether they constitute independent reports or reproductions;
and abstention, being whether the system declined to specify the instance.

8.4.6 **Negative controls.** The following shall be executed prior to the
reporting of any figure: future-document injection, post-attack reporting
inserted with correct dates being required to leave the pre-cutoff snapshot hash
byte-identical; label shuffling, scoring against permuted outcomes being required
to destroy performance; source removal, ablation of each source being required to
move results in an explicable direction; and placebo cutoffs, the same pipeline
being executed at matched cutoffs preceding comparable Indian city-months not
followed by an attack.

8.4.7 It is recorded that the placebo control is dispositive. In its absence an
elevated Mumbai score is without meaning, Mumbai being a large and heavily
reported city which will attract elevated scores upon volume alone. It is the
control most liable to omission.

### 8.5 Exclusions from scope

8.5.1 This study will not produce an assertion identifying the location of a
future attack.

8.5.2 This is a limitation of the method and not an editorial preference. The
system forecasts rates over regions and windows, and the retrospective measures
whether those rates were informative in one historical instance. Neither
operation identifies a subsequent instance: the base rates are low; the adversary
adapts to observation; and the specifying information is, as Section 8.2
documents in respect of the best-recorded case available, systematically absent
from the input modality.

8.5.3 A model interrogated for an instance-level target will produce one, that
being the behaviour of models under interrogation. Such an output would
constitute a fluent restatement of the reporting volume within its corpus,
presented with an authority the underlying evidence cannot support.

8.5.4 Accordingly the alert vocabulary of the system contains no next-target
state; the dashboard specification prohibits cartographic representations
implying tactical certainty; and no automated action is permitted downstream of
any alert.

8.5.5 This exclusion is stated expressly for the reason that the request is
foreseeable. A security-forecasting system unable to state that which it declines
to do is not complete.

---

## 9. Experimental results: base-rate hazard model

9.0.1 Section 8 describes a study blocked upon a licensed corpus. This section
reports one that is not. It advances a smaller claim upon a smaller dataset, and
constitutes the floor that any subsequent text-based result is required to clear.

### 9.1 Method

9.1.1 A recency-weighted Gamma-Poisson hazard model was constructed over
`(state, target class)` cells. Incidents within a cell are treated as a Poisson
process whose rate is estimated from decayed history and shrunk toward a pooled
global rate. An incident occurring *d* days prior to the cutoff contributes
weight `0.5 ** (d / half_life)`, the half-life being 1825 days. The same decay
defines the effective exposure, weighted counts being divided by a weighted
denominator rather than by a raw span.

9.1.2 For a cell of weighted count *k* and effective exposure *E* days, under
prior Gamma(*a₀*, *b₀*):

```
a = a0 + k
b = b0 + E
P(at least one incident within h days) = 1 - (b / (b + h)) ** a
```

9.1.3 This expression is the zero term of the negative-binomial posterior
predictive and accordingly carries estimation uncertainty, which the alternative
expression `1 - exp(-k/E * h)` would discard by treating a rate estimated from
two events as though it were known exactly.

9.1.4 The target-class taxonomy is **fixed a priori** rather than inferred from
the data. This provision is load-bearing, for the reason established at 9.5:
were the vocabulary inferred from history, the first hospitality-class attack
within the country would be *unrankable* rather than merely improbable, and a
discovery failure would be recorded as a probability failure.

### 9.2 Data

9.2.1 The registry comprises 42 mass-casualty incidents occurring within India
between 1993 and 2025, across 14 states and 6 target classes, compiled from
public reporting. Its schema, provenance, admissibility basis and limitations are
specified at Appendix A.

9.2.2 The admissibility basis is stated here in summary. For attacks of this
scale, four facts — that an attack occurred, its date, its city, and its broad
target class — are public within hours. Those four are the only fields the model
reads. Availability time is accordingly computable from event time as
`event_date + reporting_lag`, the lag defaulting to one day. The registry is
therefore not exempt from cutoff discipline; it constitutes a case in which that
discipline is inexpensive to satisfy. Attribution, claimed responsibility and
investigative findings are absent from the file by design, not having been
available upon the day. Fatality counts are retained for description and are
never a model input.

### 9.3 Walk-forward skill

9.3.1 Walk-forward evaluation was conducted over the registry. At each incident
the cutoff was set to the instant preceding that incident becoming public, the
model was fitted upon what was then known, and the cell and state of the incident
were located within the resulting ranking. The scored incident is never within
its own fitting window. Thirty-two trials were conducted upon a horizon of ninety
days.

**Table 3 — Walk-forward rank skill against chance (32 trials, 90-day horizon)**

| Depth | Cell hit@k | Chance | Lift | State hit@k | Chance | Lift |
| --- | --- | --- | --- | --- | --- | --- |
| k = 1 | 0.094 | 0.016 | **5.87** | 0.250 | 0.096 | **2.61** |
| k = 3 | 0.188 | 0.048 | **3.91** | 0.375 | 0.288 | 1.30 |
| k = 5 | 0.219 | 0.080 | **2.74** | 0.500 | 0.479 | 1.04 |
| k = 10 | 0.250 | 0.160 | 1.57 | 0.844 | 0.860 | **0.98** |

9.3.2 Median cell rank was 33 of approximately 66 to 84; median state rank was
5.5 of approximately 14; the mean reciprocal cell rank was 0.161.

9.3.3 It is emphasised that lift, and not hit rate, is the quantity to be read. A
random ranking attains `hit@k = k/n` by construction. An unqualified statement
that eighty-four per cent of attacks fell within the ten highest-ranked states
would constitute a statement concerning the number of states rather than
concerning the model.

9.3.4 Interpreted accordingly, the result exhibits a consistent structure.
**Informative signal is present at the extreme top of the ranking and decays
rapidly with depth.** The single highest-ranked cell contains the subsequent
incident approximately six times more frequently than chance; at depth ten the
cell ranking retains a lift of approximately 1.6, and the state ranking is at
chance or marginally below it. A system surfacing one cell performs work; the
same system interrogated for a watchlist of ten substantially reproduces the base
rate of Indian geography.

### 9.4 Structural bound

9.4.1 **62.5 per cent of incidents occurred within cells ranked by the model upon
the prior rather than upon their own history**, the pairing either possessing no
precedent or its precedent having decayed below threshold.

9.4.2 This is the most consequential figure within this section, and it
constitutes a property of the phenomenon rather than of the estimator. A cell
possessing no usable history carries no rate capable of estimation. No
improvement to the rate model recovers those cases, the quantity it estimates not
existing in respect of them.

9.4.3 It constitutes the quantitative form of the argument advanced qualitatively
at Section 8.3: the majority of attacks do not constitute the continuation of a
visible local pattern.

### 9.5 Retrospective at cutoff 25 November 2008

9.5.1 The model was fitted at a cutoff of 25 November 2008 upon the 21 incidents
then public, ranking 66 cells. The fit was computed prior to the outcome being
read, in that order.

**Table 4 — Retrospective at cutoff 25 November 2008**

| Quantity | Result |
| --- | --- |
| Maharashtra, **state** rank | **2 of 11** |
| Maharashtra × hospitality, **cell** rank | **47 of 66** |
| Prior incidents within that cell | **0** |
| Probability assigned to that cell | 0.0049 (the pooled prior) |
| Highest-ranked cell | Delhi × market, p = 0.0287 |

9.5.2 The two emphasised rows constitute the finding, and they point in opposite
directions by design.

9.5.3 The **regional** signal was present and correctly ranked. Maharashtra stood
second of eleven states upon 25 November 2008, upon the strength of the incidents
of 1993, of 2003, and of the suburban rail bombings of July 2006.

9.5.4 The **cell** signal was absent, and not by reason of the model assigning it
a low score. The hospitality class possessed **zero** precedent anywhere within
the registry prior to 26 November 2008. Upon a vocabulary inferred from history
the cell would not have existed at all.

9.5.5 This constitutes the discovery-versus-adjudication distinction of Section
3.2 arising upon historical data rather than in argument. The failure in respect
of 26 November 2008 was not that a probability was miscalibrated. It was that the
hypothesis lay outside the pool. Those failures admit unrelated remedies, and a
system reporting only that the event was missed would direct its builders to
recalibrate a model whose calibration was not at fault.

9.5.6 It is further demonstrated what the fixed taxonomy secures: the
unprecedented pairing holds rank 47 upon the prior — low, but present,
inspectable, and available to a subsequent generator possessing evidence that the
base rate does not.

### 9.6 Forward hazard assessment

9.6.1 The model was fitted upon all 42 incidents as at 27 August 2026, upon a
horizon of ninety days, ranking 84 cells.

**Table 5 — Forward hazard assessment, five highest-ranked cells (as at 27 August 2026, 90-day horizon)**

| Rank | State | Target class | P(≥1 within 90 days) | Rate per year, 90% CI | Prior incidents |
| --- | --- | --- | --- | --- | --- |
| 1 | Jammu and Kashmir | security | 0.030 | [0.025, 0.292] | 5 |
| 2 | Jammu and Kashmir | hospitality | 0.013 | [0.002, 0.169] | 1 |
| 3 | Jammu and Kashmir | transit | 0.012 | [0.002, 0.158] | 1 |
| 4 | Punjab | security | 0.008 | [0.000, 0.120] | 2 |
| 5 | Jammu and Kashmir | religious | 0.006 | [0.000, 0.097] | 1 |

9.6.2 Aggregated by state: Jammu and Kashmir 0.064; Maharashtra 0.017; Punjab
0.016; Bihar 0.015; Delhi 0.015.

9.6.3 Three matters are to be read together with the foregoing table, failing
which it will be misconstrued.

(a) **The intervals exceed the point estimates in width.** The rate of the
highest-ranked cell is bounded by [0.025, 0.292] per year, a range of an order of
magnitude. This is the appearance of a rate estimated from five decayed events
when the associated uncertainty is reported rather than suppressed.

(b) **The ranking is unsurprising, and this is an intended property rather than a
deficiency.** It recovers the known post-2015 concentration of attacks upon
security targets within Jammu and Kashmir. A base-rate model producing a
*surprising* ranking from 42 events would be reporting noise. This constitutes
the floor: the value of any subsequent text-based system is the margin it adds
over this table, and 9.3.4 establishes that such a margin must be measured at the
top of the ranking, where the base rate is already informative, and not at depth
ten, where it is not.

(c) **The table does not identify a subsequent attack.** It states a probability
per region-class-quarter, not exceeding three per cent within the highest-ranked
cell, in circumstances where 62.5 per cent of historical incidents fell within
cells this method ranks upon the prior. Narrowing the horizon does not sharpen
the estimate into an instance; it yields a worse estimate of the same quantity,
the event count within the fitting window not thereby increasing.

### 9.7 Reproduction and verification

9.7.1 The procedure for reproduction is specified at Appendix B.

9.7.2 The module is covered by 22 tests, including the metamorphic property of
principal consequence: the addition of incidents dated subsequent to a cutoff
leaves the fit at that cutoff unchanged, cell by cell and probability by
probability. The complete repository suite executes at 870 tests passing, with
statement coverage of 90.03 per cent against a required floor of 88 per cent.

---

## 10. Preregistration and claim discipline

### 10.1 Purpose

10.1.1 The failure to which this programme is most exposed is not a defect in
code. It is a plausible figure produced by an unaudited pipeline and quoted
without its qualifications. The recording in advance of what shall constitute
evidence is the least expensive available defence.

### 10.2 Commitments in force

10.2.1 (a) **Temporal partitions only.** No random document partition may support
any claim.

(b) **Snapshot-pinned forecasts.** A forecast lacking a snapshot hash is invalid
and shall not be counted.

(c) **Forecast-before-outcome ordering**, enforced structurally in accordance
with 4.4.

(d) **Statement of limits.** Every report shall be prefaced by a statement of
what its figures do not mean.

(e) **No protected-attribute proxies**, in accordance with 5.4.

(f) **Human adjudication required for gold data.** Machine-derived outcomes are
marked pending and reported as such.

### 10.3 Commitments required in advance of any headline figure

10.3.1 Prior to metrics being credited: the matcher validation target against
blinded dual-human labels, with the agreement threshold fixed in advance; the
primary metric and its alert budget, selected by the parties who would triage the
alerts; and the fold structure.

10.3.2 Prior to any claim of superiority: the exact baselines and their evidence
budgets; the pre-committed direction of every comparison; the subgroups to be
reported irrespective of whether they favour the system, being language,
geography, source availability, domain and event rarity; and **the definition of
a result constituting failure**.

10.3.3 The experiment registry records every run informing a decision, inclusive
of runs that failed or that embarrassed a hypothesis, upon the stated ground that
a registry recording successes alone constitutes a marketing document.

### 10.4 Permitted and prohibited claims

10.4.1 The claim intended, available only upon satisfaction of the foregoing:

> PRAMAAN-X outperforms reproduced structured, open-ended and binary forecasting
> baselines upon a common non-oracle, cutoff-safe event-forecasting benchmark,
> while controlling missed-event risk and operational alert burden.

10.4.2 The claim that shall not be made, the underlying tasks and datasets not
being identical: that this system exceeds the performance of all forecasting
models in all settings.

---

## 11. Disposition of the surveyed research gaps

**Table 6 — Disposition of the surveyed research gaps**

| Ref. | Gap identified in the antecedent survey | Response | Status |
| --- | --- | --- | --- |
| G1 | No adaptability to parallel or distributed environments | Content-addressed append-only storage and deterministic replay render distribution safe; distributed execution is not implemented | Partial |
| G2 | Markov Logic Networks depend upon expert rules and degrade off-domain | Generator portfolio with union, per-generator provenance and marginal-recall measurement | G0 executed; G1, G6 written |
| G3 | Pundit extracts from headlines only; disregards time in causal relations | Full-prose cascade; graph edges carry knowability instants; as-of accessor refuses post-cutoff queries | Written |
| G4 | Heterogeneous sources not considered | Four connectors upon a single ingestion surface, with independence groups so that reproductions do not present as corroboration | Two of four verified live |
| G5 | nMIL tested upon Latin-American articles only | Preregistered subgroup reporting by language, geography, source availability, domain and rarity | Committed, not executed |
| G6 | **Models require validation against events that occurred** | Temporal validity apparatus (Section 4); executed hazard evaluation (Section 9); retrospective design (Section 8) | **Apparatus executed; Section 9 result reported; corpus study blocked** |
| G7 | Event-specific features would improve accuracy | Features declared in advance of construction, carrying as-of and graph cutoff instants | Written |
| G8 | Tweet location unused as a feature | Entity resolution with independence clustering; gazetteer deferred as a licensed source | Partial |
| G9 | Hashtag collection cannot guarantee relevance | Provenance and independence metadata upon every evidence reference; contested fields marked unresolved | Written |
| G10 | Dynamic and structural topic models unexplored | Attaches as a registered generator without amendment to the pipeline | Not implemented |
| G11 | **Validation of data and approaches is a shortcoming** | Preregistration; registry recording failures; negative controls; reproducibility gate at 2.3.2 | Committed; Section 9 is the first executed instance |
| G12 | Survey requirement that forecasts carry plausible reasoning | Evidence packs exhibiting supporting and contradicting evidence, contradictions seeded first, denials not merged away | Written |

---

## 12. Verification status

12.0.1 This section is included for the reason that the preceding sections
describe mechanisms, and a mechanism that has been written is not a mechanism
that has been executed. In the vocabulary of the programme, **executed** denotes
observed working and **written** denotes code existing that has never been
executed or never been connected. The two are not interchangeable and are not
treated as such in this report.

**Table 7 — Verification status by category**

| Category | Components |
| --- | --- |
| **Executed and observed working** | The India hazard module of Section 9 — registry, recency-weighted Gamma-Poisson fit, walk-forward evaluation and three command-line commands, under 22 tests including the future-injection metamorphic property. The temporal foundation — schemas, hashing and storage, cutoff guard, snapshots, leakage audit. The synthetic connector. The G0 base-rate generator. The rolling backtest. The leakage and metamorphic suites including the negative control. The end-to-end demonstration. The GDELT and data.gov.in connectors, data.gov.in being verified live. |
| **Written but unverified** | The prose extraction cascade and gold-set machinery; entity resolution and deduplication; the evidence graph and retrieval; feature construction; the G1 temporal-rule generator and G6 scenario interventions; all four calibration families; the recall-first conformal controller. |
| **Not implemented** | Candidate adjudication, comprising belief state and adjudication loop, in any branch; generators G2, G3, G4, G5, G7 and the union stage; the interface and dashboard; production engineering. |
| **Blocked upon action by persons** | The licensed news corpus, which gates the extraction, entity, retrieval, baseline-reproduction and retrospective stages; blinded annotators for three separate gold sets; ReliefWeb appname approval and ACLED credentials; the alert budget and the missed-event exchange rate; external legal, domain and statistical review. |

12.0.2 Approximately 25 of some 330 checklist items are closed, together with the
module reported at Section 9, which lies outside that checklist not having formed
part of the original plan. This proportion is reported rather than omitted, for
the reason that a report describing an architecture at this stage of development
without stating the extent to which it has been executed would commit the precise
error attributed at Section 2 to the surveyed literature.

---

## 13. Limitations

13.1 **The result at Section 9 rests upon a small and biased registry.** It
comprises 42 incidents across 14 states and 6 classes, compiled from prominent
public reporting. It accordingly over-represents attacks within large cities and
under-represents chronic low-intensity violence within the north-eastern states
and the Maoist-affected belt, and every rate estimated from it inherits that
bias. It is not the Global Terrorism Database, ACLED or the South Asia Terrorism
Portal; should this work continue, one of those shall replace it and the figures
shall be recomputed. Upon 32 trials, the lift figures carry sampling error not
exhibited by the point estimates.

13.2 **State-level geography is too coarse to constitute a threat unit.** Jammu
and Kashmir and Maharashtra are not comparable cells.

13.3 **Every other executed figure derives from a synthetic world** possessing a
machine-derived and unadjudicated outcome registry. Such figures measure
agreement with automated resolution and not with reality.

13.4 **The study at Section 8 is a design and not a result.** Its blocking
dependency is a licensed, availability-stamped English-language corpus for the
period 2006 to 2009. The fraction of documents whose availability cannot be
established is expected to be substantial, and that fraction bounds the study
before any model is executed.

13.5 **Cutoff safety is necessary and not sufficient.** The ledger cannot detect
memorisation, prompt contamination or label bleed within learned components. Such
conditions require the counterfactual and prospective tracks, and the prospective
track cannot be compressed, its duration being that of its reporting-delay
window.

13.6 **The conformal guarantee rests upon a violated assumption**, as recorded at
7.3.4(b), and is reported as approximate upon every fit.

13.7 **Extraction is rule-based**, with the consequence that recall upon
paraphrase and upon Indian-English register is unmeasured. Entity resolution
lacks an authoritative gazetteer and transliteration.

13.8 **Independence estimation is heuristic.** Syndication metadata is
incomplete, and undetected copying inflates effective support in the direction of
overconfidence.

13.9 **Network egress to GDELT and ACLED was refused by policy** within the
environment in which this report was prepared, with the consequence that no live
multi-source evidence was exercised. No substitute figures were generated.

---

## 14. Conclusions

14.1 It is concluded that the two methodological findings of the antecedent gap
analysis, reproduced at 1.2.2, are of greater consequence than the algorithmic
findings, and that their resolution is infrastructural. Until a pipeline is
capable of demonstrating, from its artefacts rather than upon the assurances of
its authors, that its evidence preceded its forecasts, the accuracy figures
computed within it do not constitute measurements.

14.2 It is concluded that temporal validity is properly implemented as a
structural property. The design rule applied throughout — that a structure
rendering an error audible is to be preferred to a procedure rendering it
discouraged — yields availability time in place of event time, append-only
content-addressed evidence in place of mutable archives, content-only snapshot
identity such that reproducibility is literal equality, a runtime seal upon
outcome data in place of a convention as to statement order, censoring as a
condition upon scoring rather than a correction to it, and calibration maintained
separately from alert policy such that the policy remains visible to those it
binds.

14.3 It is concluded from the result at Section 9 that a base-rate hazard model
over Indian region and target-class cells exhibits informative signal at the
extreme top of its ranking, at a lift of 5.87 over chance at rank 1, and that
this signal decays to chance by depth ten. Any subsequent system is accordingly
to be evaluated upon the margin it adds at the top of the ranking.

14.4 It is concluded that 62.5 per cent of incidents within the registry occurred
within cells possessing no estimable rate, and that this constitutes an upper
bound upon the performance attainable by any rate-based method.

14.5 It is concluded from the retrospective at 25 November 2008 that the failure
of the model in respect of those events was a failure of candidate discovery and
not of probability estimation, the regional signal having been present and
correctly ranked at second of eleven states while the hotel-class hypothesis lay
outside the candidate pool upon zero national precedent. This finding is
submitted as empirical vindication of the decomposition at Section 3.

14.6 It is concluded that the appropriate target quantity for a text-based
retrospective upon these events is the open-source ceiling rather than a
successful prediction, the documented warning record having been extensive and
almost wholly classified in origin. It follows that a system reporting elevated
regional hazard while abstaining upon the instance behaves correctly rather than
failing.

14.7 It is concluded that the measurement of that bound constitutes a
contribution upon which the field may build, and that a further incomparable
accuracy figure does not.

---

## 15. Recommendations

**R1.** That acquisition of a legally usable, availability-stamped
English-language news corpus, inclusive of Indian regional sources and storing
publication, retrieval and revision instants separately, be treated as the
critical-path dependency of the programme. Five subsequent stages are downstream
of it, and the study at Section 8 cannot proceed without it. *Priority: highest.*

**R2.** That the incident registry at Appendix A be replaced by a licensed
authoritative source — the Global Terrorism Database, ACLED or the South Asia
Terrorism Portal — and that the figures at Section 9 be recomputed against it
before those figures are cited externally. *Priority: high.*

**R3.** That ReliefWeb appname approval and ACLED credentials be applied for
without delay, both possessing external latency and blocking live source
verification indefinitely otherwise. *Priority: high.*

**R4.** That the alert budget, expressed as alerts per region-day, and the
exchange rate between missed events and false alerts, be determined by the
parties who would triage the alerts. These are policy decisions and not fitting
problems, and Section 11 of the programme cannot be completed without them.
*Priority: high.*

**R5.** That two blinded annotators be engaged for each of the extraction, entity
and outcome gold sets, and that guidelines be versioned and frozen prior to final
testing. *Priority: medium.*

**R6.** That the preregistration be frozen and its hash published prior to any
inspection of final-test results. *Priority: medium.*

**R7.** That geographic resolution below state level be adopted before any
operational reading of the hazard output is contemplated, state-level cells being
too coarse to constitute threat units. *Priority: medium.*

**R8.** That external legal, domain and statistical review be obtained prior to
any external citation of the results reported herein. *Priority: medium.*

**R9.** That no operational alerting be authorised, and no automated action be
permitted downstream of any output, until Sections 10.3 and 12 are satisfied.
*Priority: standing.*

---

## References

1. Bhattacharjee, K., ShivaKarthik, S., Mehta, S., Kumar, A., Kothawade, R.,
   Katre, P., Dharkar, P., Pillai, N., Verma, D. Survey and Gap Analysis on Event
   Prediction of English Unstructured Texts. In: Joshi, A., Khosravy, M., Gupta,
   N. (eds.) *Machine Learning for Predictive Analysis: Proceedings of ICTIS
   2020*. Lecture Notes in Networks and Systems, Vol. 141. Springer, Singapore
   (2021). DOI: 10.1007/978-981-15-7106-0_49
2. Dami, S., Barforoush, A. A., Shirazi, H. News events prediction using Markov
   logic networks. *Journal of Information Science* 44(1), 91–109 (2018)
3. Radinsky, K., Davidovich, S., Markovitch, S. Learning causality for news events
   prediction. In: *Proceedings of WWW*, pp. 909–918 (2012)
4. Ning, Y., Muthiah, S., Rangwala, H., Ramakrishnan, N. Modeling precursors for
   event forecasting via nested multi-instance learning. In: *Proceedings of
   KDD*, pp. 1095–1104 (2016)
5. Mueller, H., Rauh, C. Reading between the lines: Prediction of political
   violence using newspaper text. *American Political Science Review* 112(2),
   358–375 (2018)
6. Schrodt, P. A., Yonamine, J., Bagozzi, B. E. Data-based computational
   approaches to forecasting political violence. In: Subrahmanian, V. S. (ed.)
   *Handbook of Computational Approaches to Counterterrorism*, pp. 129–162.
   Springer (2013)
7. Ward, M. D., Greenhill, B. D., Bakke, K. M. The perils of policy by p-value:
   Predicting civil conflicts. *Journal of Peace Research* 47(4), 363–375 (2010)
8. Perera, I., Hwang, J., Bayas, K., Dorr, B., Wilks, Y. Cyberattack Prediction
   Through Public Text Analysis and Mini-Theories. In: *IEEE International
   Conference on Big Data*, pp. 3001–3010 (2018)
9. Popat, K., Mukherjee, S., Yates, A., Weikum, G. DeClarE: Debunking fake news
   and false claims using evidence-aware deep learning. arXiv:1809.06416 (2018)
10. Bates, S., Angelopoulos, A., Lei, L., Malik, J., Jordan, M. I.
    Distribution-free, risk-controlling prediction sets. *Journal of the ACM*
    68(6), 1–34 (2021)
11. Government of Maharashtra. Report of the High Level Enquiry Committee on
    26/11 (Pradhan Committee), constituted 30 December 2008.
12. *United States* v. *David Coleman Headley*, N.D. Ill. Plea agreement (March
    2010); sentencing (January 2013).

---

## Appendix A — Incident registry: schema, provenance and admissibility

**A.1 File.** `research/datasets/india_incidents.csv`. 42 incidents, 14 states, 6
target classes, spanning 12 March 1993 to 22 April 2025.

**A.2 Schema.**

| Column | Meaning |
| --- | --- |
| `date` | Date of the attack, `YYYY-MM-DD` |
| `state` | Indian state or union territory |
| `city` | City or locality |
| `target_class` | One member of the taxonomy at A.3 |
| `fatalities` | Approximate deaths per public reporting. Description only; never a model input. |
| `note` | Short free-text descriptor |

**A.3 Taxonomy.** Fixed a priori at
`pramaanx.india.registry.TARGET_CLASS_TAXONOMY`: `government`, `hospitality`,
`market`, `religious`, `security`, `transit`. The taxonomy is declared rather
than inferred, for the reason established at 9.1.4.

**A.4 Admissibility.** For attacks of this scale, four facts are public within
hours: that an attack occurred; its date; its city; and its broad target class.
Those four are the only fields read by the model. Availability time is derived as
`event_date + reporting_lag`, the lag defaulting to one day, and is enforced by
`admissible_at()`. Attribution, claimed responsibility, casualty revisions and
investigative findings are absent by design, not having been available upon the
day.

**A.5 Limitations.** As recorded at 13.1 and 13.2: selection bias toward
prominent urban incidents; approximate fatality figures; coarse state-level
geography; and sparsity, almost every cell containing zero or one incident, which
is the reason estimates are shrunk toward a pooled prior and the credible
intervals are wide.

**A.6 Provenance.** Compiled from public reporting and reference summaries,
including Britannica's timeline of major terror attacks in Delhi and Mumbai,
Wikipedia articles concerning the individual incidents, and Al Jazeera's India
attack timelines. Individual rows were cross-checked for date and location;
fatality counts follow the most commonly reported figure where sources differ.
This file is compiled for methodological evaluation and is not an authoritative
incident database. See Recommendation R2.

---

## Appendix B — Reproduction procedure

**B.1 Environment.** Requires `uv` and Python 3.13 or 3.14.

```bash
uv sync --frozen --extra dev
```

**B.2 Commands reproducing Section 9.**

```bash
# Table 3 — walk-forward rank skill and the 62.5% structural bound
uv run pramaanx hazard backtest

# Table 4 — retrospective at 25 November 2008
uv run pramaanx hazard retrospective --cutoff 2008-11-25T00:00:00Z

# Table 5 — forward hazard assessment
uv run pramaanx hazard forecast --as-of 2026-08-27T00:00:00Z --top 10
```

**B.3 Output.** Each command emits a canonical JSON manifest to standard output
and accepts `--output` in order to persist it. Every manifest carries its own
`interpretation_limits` field. A ranking quoted without those limits is a
different and less honest object than that which the module computes.

**B.4 Verification.**

```bash
make check        # ruff, mypy, pytest with coverage floor
uv run pytest tests/unit/test_india_hazard.py -q
```

**B.5 Recorded state at issue of this report.** 870 tests passing; statement
coverage 90.03 per cent against a required floor of 88 per cent; 22 tests
covering the module of Section 9.

---

## Appendix C — Detailed verification status

**C.1** See Table 7 at Section 12 for the categorised status.

**C.2** The distinction between executed and written is maintained in
`docs/CHECKLIST_STATUS.md`, in which every status is sourced from an observable
artefact — repository state, branch list, continuous-integration run — and not
from a branch's assertions concerning itself. Where a branch asserts a capability
never executed, it is recorded as written and unverified, which does not
constitute completion.

**C.3** The metamorphic property of principal consequence for Section 9 is
implemented at
`tests/unit/test_india_hazard.py::TestLeakage::test_future_incidents_do_not_change_the_fit`.
The addition of incidents dated subsequent to a cutoff is required to leave the
fit at that cutoff unchanged, cell by cell and probability by probability.

**C.4** The corresponding property for the wider system is the gate stated at
2.3.2, implemented within the leakage and metamorphic suites, which additionally
contain a negative control demonstrating that deliberately back-dated evidence is
admitted — thereby establishing the boundary of the guarantee rather than
asserting its absence.
