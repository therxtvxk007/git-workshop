# Subproblem Frontier (to Aug 2026) and a Blueprint That Can Beat the Current Top

The main problem: **given multilingual, unstructured news up to time _t_, output a calibrated probability that an event of type _T_ involving actor _A_ in location _L_ occurs in window _[t+δ, t+δ+w]_, with auditable supporting evidence.**

Nobody wins this end-to-end any more. It is won by composing the best current answer to each subproblem, and the subproblem frontiers have moved *unevenly* — which is exactly where the exploitable gain is. Below: each subproblem, the current edge, and the specific lever.

⚠ = number taken from a search summary; verify against the primary PDF before quoting.

---

## S1. Ingestion and source bias

**Edge.** POLECAT vs GDELT has now been compared *specifically for forecasting utility* (Data 11(7):158, 2026) rather than for coding accuracy. MediaGraph (2604.20982) demonstrates measurable, structured reporting preferences across Indian news outlets.

**Lever.** Everyone's "world news" view of India is one or two English wires. Model the source-selection bias explicitly (outlet × event-type × region propensity) and correct for it — an inverse-propensity or capture–recapture correction on event counts. This is a real accuracy gain, not a fairness gesture: uncorrected counts make quiet regions look peaceful.

## S2. Event coding / extraction

**Edge.** Dictionary coders are dead. **NGEC** (transformers + expert annotation + Wikipedia actor data) produces POLECAT under the **PLOVER** ontology — 18 event types in an event–mode–context structure, replacing 250+ CAMEO codes. On the NLP side: code-based structured extraction (*Structure-Aware Lightweight Document-Level EE via Code-Based LLMs*, Electronics 15(6):1187), **DiCoRe** divergent–convergent zero-shot event detection (2506.05128), adaptive schema-aware EE with RAG (2505.08690), multi-agent generate-and-extract zero-shot document-level argument extraction (2603.02909). **TextEE** (16 datasets, 5 standardised splits, 14 re-implemented methods) is the honest measuring stick, and it reports that LLMs are *not* yet good at this.

**Lever.** Extraction is still the weakest link in every forecasting stack, and it is the link where Indic and code-mixed input degrades worst. Do the coding with a strong LLM, then **distil into a small model** for throughput, and publish TextEE-style numbers on an Indic split. Nobody has.

## S3. Actor resolution and geolocation

**Edge.** NGEC resolves actors via Wikipedia rather than hand-built dictionaries. For Indic: IndicNER/Naamapadam, MuRIL, IndicTrans2 (22 scheduled languages, BPCC ~230M bitext pairs), plus transliteration handling for romanised text.

**Lever.** Resolution to **admin-2 (district)** with an Indian gazetteer, plus alias handling across scripts and romanisations. Country-level forecasts are useless to an operational user; district-level forecasts are the product.

## S4. Representation

**Edge.** Triples are provably insufficient — geopolitical facts routinely have >2 primary entities. *Toward Better Temporal Structures for Geopolitical Events Forecasting* (2601.00430) formalises **hyper-relational temporal knowledge generalized hypergraphs (HTKGH)**, backward-compatible with TKG/HTKG, and releases **htkgh-polecat**. Parallel lines: event causality graphs, complex event schema induction.

**Lever.** Build on the hypergraph formalism rather than re-implementing 2021-era TKG. It is new enough that the baseline table is short.

## S5. Temporal modelling

**Edge, three separate stacks that people rarely combine:**
- *Graph*: TKG/HTKGH models — but see the recurrence critique below.
- *Point processes*: **FIM-PP** (2509.24762) does in-context TPP inference — pretrained on synthetic Hawkes families, estimates intensities on real data with no training; **TPP-LLM** fuses pretrained LLM semantics with temporal encodings via LoRA; **LAMP** adds LLM *abductive* reasoning — propose future events, have the LLM suggest causes, retrieve matching past events, score whether they could have caused it.
- *Time series*: zero-shot foundation models have gotten genuinely good — **Chronos-2** tops GIFT-Eval (97 tasks / 55 datasets) on WQL and MASE over TiRex and TimesFM-2.5; Moirai 2.0 close behind. ⚠

**Lever.** Run all three as **separate channels** over the same panel and stack them. Nearly all published systems commit to one. The channels fail in different regimes (recurrence-dominated vs shift-dominated — see 2607.09232), so the stack is where free accuracy lives.

## S6. Retrieval

**Edge — and this is a landmine field.** Search-engine date filters leak post-resolution information (2602.00758); real-time data revisions leak what was not known at forecast time (2608.05883); and prompting a model to forget its own knowledge **does not work** — a 52% gap between simulated and true ignorance across 477 questions and 9 models, unfixed by chain-of-thought (2601.13717 ⚠).

**Lever.** Build a **frozen, publication-timestamped news index** with hard as-of-date retrieval, and evaluate **prospectively only**. This is unglamorous infrastructure and it is currently the single most credible thing a new entrant can own.

## S7. Reasoning shape

**Edge.** *The Power of Simplicity* (REALM 2025): plain RAG beats ReAct at **10% of token cost**; **structured statistical context improves accuracy while unstructured semantic context — news titles — degrades it**; long reasoning traces hurt small models and help ~70B ones. *When AI Navigates the Fog of War* (2603.16642): frontier models do reason strategically about live conflicts, best where the setting is economically and logistically structured. *Do LLMs Know Conflict?* (2505.09852): parametric knowledge alone is weak; structured external context carries the performance.

**Lever.** Invert the standard design. Do **not** hand the LLM a pile of articles. Hand it a compact statistics table plus a short evidence bundle, and use the LLM for hypothesis generation, causal narrative and evidence assembly — with the *number* coming mostly from the classical channel.

## S8. Aggregation

**Edge.** **InfoDelphi** (2607.01661): identical evidence ⇒ deliberation herds; partitioned evidence (shared-public + disjoint-private) ⇒ **+12–18% Brier, +4–8 pts accuracy** on 375 market questions; remove the asymmetry and the gain vanishes. ⚠ **ForecastAgentSearch** (NUS): rank and route expert agents by regional knowledge, domain expertise, reliability and *complementarity*. **AIA Forecaster**: a supervisor agent reconciling disparate forecasts for the same event. Counterweight: *The Deliberative Illusion* documents factual attrition and stance homogenisation in multi-agent deliberation.

**Lever.** Manufacture *real* information asymmetry along the axis you uniquely have: English wire ⟂ Hindi press ⟂ regional-language press ⟂ structured event panel. That is four genuinely disjoint evidence partitions, which is the exact input InfoDelphi shows is the active ingredient — and it is not reproducible by an English-only Western pipeline.

## S9. Calibration and uncertainty

**Edge.** VIEWS moved conflict forecasting to full predictive distributions. AIA applies explicit statistical calibration against LLM behavioural biases. Conformal prediction / distribution-free risk control is mature and now being applied to LLMs (ICML 2026 workshop on statistical frameworks for uncertainty in agentic systems; robust CP from internal representations, 2604.16217).

**Lever.** Report **adaptive conformal intervals valid under distribution shift**, plus a **decision-cost curve** (cost of false alarm vs cost of miss vs alert budget). Almost nobody in the LLM-forecasting literature does either. It is cheap and it is the language an operational user actually thinks in.

## S10. Training signal

**Edge.** Time is a free labeller. Outcome-based RL (2505.17989); Foresight Learning generates questions from news streams that are hard now and verifiable later, then rewards with proper scoring rules — **Qwen3-32B trained beats Qwen3-235B untrained by 27% Brier**, and Foresight V3 sits **#1 on ProphetArena** above GPT-5.2, Gemini 3 Pro, Claude Opus 4.5 and Grok 4.1; GRPO on a 1.5B model beats Claude Sonnet 3.5 (2606.15917); FutureWorld is a live RL environment with real outcome rewards. ⚠

**Lever.** This is the affordability unlock. You do not need a frontier budget — you need a news stream, a question generator, a 4–12 week resolution lag and GRPO on a 7–32B open model. AIRAWAT/PARAM-class compute is sufficient.

## S11. Evaluation

**Edge.** Live/contamination-free benchmarks (FutureX, ForecastBench, ProphetArena, Foresight Arena, Kalshibench, POLY-GYM). Strikingness-aware TKG evaluation. Distribution-shift synthetic evaluation. The recurrency baseline. The no-change baseline.

**Lever.** Stratify every reported number by **novel vs recurring**. >80% of ICEWS test events already occurred in history; a tuning-free recurrency baseline matches 11 published methods on 3 of 5 datasets. Whoever reports the novel-event stratum honestly resets the leaderboard, because that is where the published gains mostly are not.

## S12. Decision value and governance

**Edge.** *EMBERS at 4 Years* published misses, ethical issues and operating limits. CSCW 2021 (*Future Protest Made Risky*) is a direct critique of social-media-based unrest prediction products.

**Lever.** Publish a failure log and a misuse-limits section: aggregate-level forecasting only, no individual-level targeting, full audit trail per alert. In this specific subfield that is not decoration — it is a credibility differentiator, and reviewers now look for it.

---

## The blueprint

An LLM + classical-ML hybrid whose design is *justified line-by-line* by the findings above.

```
L0  INGEST      Multilingual Indian + international news, publication-timestamped,
                frozen index.  Structured spines: GDELT, POLECAT, ACLED.
                → source-propensity model for coverage-bias correction (S1)

L1  CODE        LLM event coder → PLOVER schema, code-style structured output.
                Indic path: transliteration normalisation, MuRIL/IndicNER,
                admin-2 gazetteer geocoding.  Distil to a small model. (S2,S3)

L2  PANEL       Feature store on (actor × district × week):
                event counts & escalation rates; topic shares (Mueller–Rauh style);
                planned-event / "future mention" features; prices, calendar,
                mobilisation signals.                                      (S1,S2)

L3  CLASSICAL   (a) LightGBM hurdle / negative-binomial + quantile GBDT — counts
                (b) discrete-time hazard model — onset
                (c) Chronos-2 zero-shot channel — trend
                (d) neural TPP / FIM-PP — intensity
                MANDATORY reference: no-change + recurrency baselines.   (S5,S11)

L4  LLM         RAG over the frozen as-of-date index. Prompt = structured stats
                table + short evidence bundle. NOT raw articles.
                Multi-agent with DESIGNED information asymmetry:
                  agent_en | agent_hi | agent_regional | agent_structured
                Supervisor agent reconciles.                            (S6,S7,S8)

L5  FUSE        Stack L3 + L4 (logistic / isotonic), then adaptive conformal
                calibration under shift. Output: probability + interval +
                evidence + causal narrative.                                (S9)

L6  TRAIN       Auto-generate forecast questions from the news stream;
                resolve at 4–12 weeks; GRPO / proper-scoring-rule RL on a
                7–32B open model.  Free supervision, forever.               (S10)

L7  EVALUATE    Prospective registry, public weekly scoreboard.
                Stratified: novel vs recurring.  Lead-time curves.
                Decision-cost curves.  Published failure log.        (S11,S12)
```

### Why this beats the current top rather than merely matching it

| Their weakness | This system's counter |
|---|---|
| Leaderboard gains are mostly recurrence | Novel-event stratum reported separately; recurrency baseline shipped as a first-class reference |
| Conflict models lose to no-change | no-change is a hard gate, not an afterthought |
| Brier only, no valid uncertainty | adaptive conformal + decision-cost curves |
| Raw prose fed to the LLM despite evidence it hurts | structured stats in, prose out |
| Multi-agent deliberation herds | four genuinely disjoint evidence partitions by language and modality |
| Retrieval and evaluation leak | frozen publication-timestamped index; prospective-only |
| English-centric view of South Asia | Indic + code-mixed native path, district resolution |
| Frontier-scale training assumed necessary | outcome-RL on a 7–32B open model |

### The three deliverables that would make this undeniable

1. **A live, contamination-free South Asia forecasting benchmark** — daily questions, public resolution, FutureX-style. This does not exist for the region. Building it makes you the scorekeeper, which is a stronger position than being a competitor.
2. **A prospective scoreboard with a beaten no-change baseline** at district level, with calibrated intervals. VIEWS' own challenge says most teams cannot do this.
3. **An open Indic socio-political event corpus** under the PLOVER schema, with TextEE-style extraction numbers. This is the asset C-DAC was uniquely placed to build in 2020 and did not, and it is still unclaimed in 2026.

### Sequencing, honestly

The benchmark and the frozen index (L0, L7) come first and are the least glamorous. They are also what converts everything downstream from a claim into evidence — which, per the analysis in `01-competitive-analysis.md`, is the exact difference between the C-DAC line of work and the groups that led. Building the model first and the evaluation afterwards reproduces the original mistake with better GPUs.
