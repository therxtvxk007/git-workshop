# Event Prediction from Unstructured Text: Where C-DAC's 2020 Paper Sits, and What the Field Did Next

**Scope of this document.** Reference paper: Bhattacharjee, ShivaKarthik, Katre, Mehta, Kumar (C-DAC Applied AI Group, Pune), *"Survey and Gap Analysis on Event Prediction of English Unstructured Texts"*, ICTIS 2020, Springer LNNS vol. 141. This document answers four questions:

1. Why would a competent government lab not do the best work it could have?
2. What did the groups that *did* lead do as follow-up, from 2020 to August 2026?
3. What did C-DAC miss, concretely?
4. What makes today's top papers top, and where are they still weak enough to be beaten?

**Evidence caveat.** This session's network egress blocks arXiv, ACL Anthology, Semantic Scholar, dblp and Google Scholar directly; findings below are assembled from web-search result summaries. Numbers marked with ⚠ should be re-verified against the primary PDF before being quoted in a submission.

---

## 0. The ranking question, settled briefly

The 2020 C-DAC paper is a survey with a gap-analysis table and a statement that "a new approach is being developed." It contains no algorithm, no dataset, no experiment, no baseline and no released code. It therefore does not enter a global ranking of event-forecasting research at all — not "rank 40th," but *category mismatch*. A survey is ranked by whether it becomes the field's reference survey. It did not: the reference surveys of that exact window are Zhao's *Event Prediction in the Big Data Era: A Systematic Survey* (ACM Computing Surveys 54(5), 2021) and Deng, Rangwala & Ning's *A Survey on Societal Event Forecasting with Deep Learning* (2021).

No follow-up implementation paper from the C-DAC group could be located in public indices through August 2026. The promised system either stayed internal or was not built out publicly.

---

## 1. Why a capable lab produces weaker public evidence

This is an incentive question, not a talent question. Every one of these is structural:

**1.1 The objective function is delivery, not discovery.** C-DAC is an R&D arm of MeitY. Its measured outputs are deployed systems, technology transfer, and mission deliverables — PARAM/AIRAWAT HPC, Bhashini/NLTM language stack, e-governance, cyber-security tooling. Publications are a byproduct of projects, not the product. A KDD paper does not advance a C-DAC scientist's file; a delivered system to a ministry does.

**1.2 Security-adjacent work cannot publish its evidence.** If the downstream user is a law-enforcement or intelligence customer, the data, the alerts, the accuracy numbers and the failure log are the parts that cannot be released. What is left to publish is exactly what they published: framing, taxonomy, and gaps. This explains the shape of the output honestly — and it does not license the assumption that the withheld work was strong. Withheld evidence is not evidence.

**1.3 Venue selection removes the forcing function.** ICTIS/Springer LNNS is a fast, low-selectivity proceedings track. Nothing in that review process demands an ablation, a baseline, a significance test or a reproducibility statement. The scientific rigour of a paper is largely produced by the reviewers who would reject it. Choose a venue that will not reject you and the rigour never has to appear.

**1.4 No PhD pipeline.** University labs produce papers because they are staffed by people whose degree depends on producing papers. A government engineering centre has staff engineers on project timelines. That single difference accounts for most of the publication-volume gap between C-DAC and Virginia Tech, Stevens, HIT, Tsinghua or NUS.

**1.5 Compute and data access in 2019–20.** Large-scale multilingual news licensing (LexisNexis-class), continuous GDELT-scale ingestion, and multi-hundred-GPU training were not routinely available to that group at that time. AIRAWAT came in 2022–23. EMBERS by contrast had been running 24×7 since 2012 on IARPA OSI money.

**1.6 No leaderboard, therefore no gradient.** Fields improve where a shared benchmark makes improvement visible and cheap to claim. The Indian event-prediction effort had no benchmark to climb. Without a scoreboard there is no local signal telling you that your model is 8 points behind.

**1.7 Talent economics.** The strongest Indian NLP researchers of that cohort were absorbed by AI4Bharat, industry research labs, and foreign PhD programmes. Government pay scales do not compete for that cohort.

**Conclusion.** They almost certainly *could* have done better on public evidence. Nothing in their environment paid them to. That is the honest answer, and it is a criticism of the incentive structure rather than of the people.

---

## 2. What the leaders did next (2020 → August 2026)

### 2.1 The operational-forecasting lineage (EMBERS successors)

EMBERS ended with IARPA's Open Source Indicators programme. The operational torch passed to three places:

- **ACLED CAST (Conflict Alert System).** Global, weekly-refreshed forecasts of battles, explosions/remote violence and violence against civilians, for rolling four-week periods, six periods ahead, at admin-1 (province) level for every country. LightGBM core with uncertainty estimation and hierarchical reconciliation, accuracy metrics republished each week alongside new forecasts, and a public pipeline at `github.com/ACLED/cast-public`. This is EMBERS's operational role, productised and open. ([methodology](https://acleddata.com/methodology/cast-methodology), [platform](https://acleddata.com/platform/cast-conflict-alert-system))
- **VIEWS (Uppsala/PRIO).** Moved the whole field from point estimates to *predictive distributions*, and ran the **2023/24 VIEWS Prediction Challenge**: 13 teams, 23 models, country- and PRIO-grid-level fatality forecasts with uncertainty, evaluated on a held-out window *and* a genuinely unobserved future window (Jul 2024–Jun 2025), written up in *Journal of Peace Research*. ([JPR](https://journals.sagepub.com/doi/10.1177/00223433241300862), [live results](https://viewsforecasting.org/news/views-prediction-challenge-2023-24-follow-live-results-and-performance-rankings/))
  - **The single most important result in this whole literature:** most submitted models were beaten, on standard metrics, by a naïve *no-change* model. The field's own flagship competition published that finding rather than hiding it. That is what scientific maturity looks like, and it is also the exact opening for anyone entering now.
- **IARPA** moved from OSI to hybrid human–machine forecasting (HFC/SAGE) and then to analyst-support programmes (REASON).

### 2.2 The graph-deep-learning lineage (Glean successors)

Deng, Rangwala and Ning did not stop at Glean (KDD 2020). Follow-ups pushed toward *causal* and *explainable* forecasting rather than raw accuracy:

- *Understanding Event Predictions via Contextualized Multilevel Feature Learning* (CIKM 2021)
- *Robust Event Forecasting with Spatiotemporal Confounder Learning* (KDD 2022)
- *Causality Enhanced Societal Event Forecasting with Heterogeneous Graph Learning* (ICDM 2022)
- *A Survey on Societal Event Forecasting with Deep Learning* (2021) — the survey C-DAC's paper would have had to beat
- Deng continued at UvA with de Rijke (KDD 2024)

### 2.3 The temporal-knowledge-graph lineage

2020–2023 saw an arms race: RE-NET → RE-GCN, CyGNet, xERTE, TITer, TLogic, CEN, CENET. Then the LLM turn: *Temporal KG Forecasting Without Knowledge Using In-Context Learning* (EMNLP 2023), GenTKG, zrLLM, Chain-of-History (2401.06072), and by 2025–26 explicit GNN⊕LLM hybrids — *Integrate Temporal Graph Learning into LLM-based TKG Model* (2501.11911), RECIPE-TKG (2505.17794), STK-Adapter, DynaGen.

**And then the field audited itself, which matters more than any of those models:**

- *On the Evaluation of Methods for Temporal Knowledge Graph Forecasting* — unified protocol; prior comparisons were unfair (inconsistent splits, inappropriate static filtering that ignores time validity).
- ***History Repeats Itself: A Baseline for TKG Forecasting*** (IJCAI 2024) — a hyperparameter-light **recurrency baseline** ranks 1st or 3rd on three of five standard datasets against 11 published methods. Over **80% of ICEWS test events have already occurred in prior history**. Most of the "progress" was memorisation of repeats. ([paper](https://www.ijcai.org/proceedings/2024/0444.pdf), [code](https://github.com/nec-research/recurrency_baseline_tkg))
- *Strikingness-Aware Evaluation for TKG Reasoning* (2605.13153) — score models on *surprising* facts, not repeats.
- *TKG Forecasting under Distribution Shifts: A Synthetic Evaluation* (Mannheim, 2607.09232) — robustness is signal-dependent; memory baselines stay competitive wherever recurrence dominates.
- LLM-era contamination: ICEWS/GDELT/WIKI/YAGO predate model cutoffs, so LLM "forecasts" may be recall.

### 2.4 The Chinese lineage (NEEG / script event prediction)

Continuous and productive: event-centric pretraining and prompt fine-tuning for script event prediction; script *event-stream* prediction (beyond the next single event); event-causality graphs (*What Would Happen Next? Predicting Consequences from an Event Causality Graph*, 2409.17480); document-level future event prediction fusing an event KG with LLM temporal reasoning under a metacognitive framework (Electronics, 2025); **OpenEP** — open-ended future event prediction rather than multiple-choice (2408.06578); *LLMs as Interpolated and Extrapolated Event Predictors* (2406.10492); multimodal forecasting (MM-Forecast, 2024).

### 2.5 The lineage that did not exist in 2020 and now dominates: LLM judgmental forecasting

This is the discontinuity. In 2020 nobody was doing it; by 2026 it is the centre of the field.

**Benchmarks**
- **ForecastBench** (ICLR 2025) — rolling, difficulty-adjusted Brier, market + dataset questions. October 2025 standings: superforecasters **0.081**, best LLM (GPT-4.5) **0.101** — roughly a 20% human edge; LLMs now beat the median member of the public. Frontier improvement measured at ~0.016 Brier/year, extrapolating to parity around Nov 2026 (95% CI Dec 2025–Jan 2028). ⚠
- **MIRAI** (NeurIPS 2025 D&B) — agentic international-event forecasting over 991,759 GDELT records / 59,161 events / 296,630 articles, with a code-based tool API. GPT-4o reaches **29.6 F1** on second-level relations — i.e. the honest headline is that agents are still bad at this. ([site](https://mirai-llm.github.io/), [code](https://github.com/yecchen/MIRAI))
- **FutureX** (2508.11987) — the largest *live* benchmark: 195 sites drawn from a pool of 2,008, daily updated, structurally contamination-free because the answers do not exist yet. 25 models/agents evaluated.
- Also: FutureBench (Together AI), ProphetArena, Foresight Arena (on-chain), Kalshibench (epistemic calibration via prediction markets), POLY-GYM.

**Systems**
- **AIA Forecaster** (Bridgewater AIA Labs, 2511.07678) — three ingredients: agentic search over high-quality news, a **supervisor agent** reconciling disparate forecasts for the same event, and **statistical calibration to counter LLM behavioural biases**. Result: statistically indistinguishable from human superforecasters on ForecastBench (~0.0753 vs 0.0740 on FB-Market ⚠). It still loses to liquid market consensus, but *ensembling it with the market beats the market* — i.e. it carries additive information.
- **ForecastAgentSearch** (NUS, 2606.31665) — treat forecasting as expert-agent *search*: rank candidate expert agents by regional knowledge, domain expertise, reliability and complementarity, then coordinate.
- **InfoDelphi** (CMU, 2607.01661) — the sharpest methodological result of 2026: with identical evidence, multi-agent deliberation collapses into **herding**, not belief revision. Deliberately partition evidence into shared-public and disjoint-private subsets so each agent holds exclusive knowledge. **+12–18% Brier and +4–8 pts accuracy** on 375 real prediction-market questions; removing the asymmetry removes most of the gain. ⚠
- Related: ThinkTank-ME (Middle East multi-expert), *The Wisdom of Deliberating AI Crowds*, *The Deliberative Illusion* (factual attrition and stance homogenisation in deliberation), agentic sequential Bayesian belief updating (2604.18576).

**Training — "time as a source of verifiable reward"**
- *Outcome-based Reinforcement Learning to Predict the Future* (2505.17989).
- *Advancing Event Forecasting through Massive Training of LLMs* (2507.19477) — position paper: the ingredients now exist to train superforecaster-level models at scale.
- **Foresight Learning / Foresight-32B** (Lightning Rod Labs) — resolved outcomes as free supervision under proper-scoring-rule rewards; a trained **Qwen3-32B beats an untrained Qwen3-235B by 27% Brier**; Foresight V3 sits **#1 on ProphetArena overall**, ahead of GPT-5.2, Gemini 3 Pro, Claude Opus 4.5 and Grok 4.1. ⚠
- *Reinforcement Learning for LLM-based Event Forecasting* (2606.15917) — GRPO on 1.5B–14B models with a Wikipedia-revisions / news-summary tool; a **1.5B Qwen 2.5 beats Claude Sonnet 3.5** on their dataset. ⚠
- **FutureWorld** (2604.26733) — a *live* RL environment with real-world outcome rewards.

**Reasoning-shape findings (these are design constraints, not trivia)**
- *The Power of Simplicity in LLM-Based Event Forecasting* (REALM 2025) — a plain RAG pipeline **beats ReAct at 10% of the token cost**; **structured statistical context helps, unstructured semantic context (news titles) hurts**; iterative reasoning traces hurt small models and help ~70B ones. ([paper](https://aclanthology.org/2025.realm-1.32/))
- *When AI Navigates the Fog of War* (2603.16642) — post-cutoff case study on the early 2026 Middle East conflict, 11 temporal nodes / 42 verifiable questions; frontier models show real strategic reasoning but unevenly, best where the situation is economically and logistically structured.
- *Do LLMs Know Conflict?* (2505.09852) — parametric knowledge alone is weak; structured external context (ACLED/GDELT via RAG) is what carries performance.

**Data infrastructure**
- **PLOVER / POLECAT / NGEC** replaced ICEWS and CAMEO: 18 event types in an event–mode–context ontology instead of 250+ CAMEO codes, machine-coded from multilingual news by a coder built from transformers + Wikipedia-sourced actor information instead of brittle dictionaries. ([Halterman et al.](https://www.andrewhalterman.com/publication/plover-polecat-new-event-data/))
- Comparative evaluation of GDELT vs POLECAT *for forecasting specifically* (Data 11(7):158, 2026).
- **htkgh-polecat** (2601.00430) — *Hyper-relational Temporal Knowledge Generalized Hypergraphs*: triples cannot express real geopolitical facts with more than two primary entities, so generalise the structure and rebuild the benchmark on POLECAT.

**Evaluation integrity — a whole new subfield**
- ***Simulated Ignorance Fails*** (2601.13717) — prompting a model to "ignore what you know after date X" does not work: a **52% gap between simulated and true ignorance** across 477 questions and 9 models; chain-of-thought does not suppress prior knowledge. Retrospective forecasting on pre-cutoff events is **methodologically invalid**. ⚠
- *Temporal Leakage in Search-Engine Date-Filtered Web Retrieval* (2602.00758) — date filters leak post-resolution information.
- *Information Leakage from Data Revisions in Retrospective Forecasts* (2608.05883) — revised "as-of-today" data leaks what was not known at forecast time.

---

## 3. What C-DAC missed, itemised

Measured against the above, and stated as gaps rather than judgements of people:

| # | Missed | What the leaders did instead |
|---|--------|------------------------------|
| 1 | Any public system with a prospective track record | EMBERS 2012–16; ACLED CAST weekly since 2023; VIEWS unobserved-future window |
| 2 | Any released dataset or benchmark | ICEWS/GDELT → POLECAT, MIRAI, FutureX, ForecastBench, POLY-GYM, htkgh-polecat |
| 3 | Proper scoring rules and predictive distributions | VIEWS moved the whole field to distributions + CRPS; ForecastBench difficulty-adjusted Brier |
| 4 | Baselines — especially the ones that win | no-change (VIEWS), recurrency baseline (IJCAI 2024), base rates |
| 5 | Code and data release | ACLED CAST, MIRAI, NEEG, recurrency baseline all public on GitHub |
| 6 | The ontology revolution | CAMEO → PLOVER; dictionary coders → NGEC |
| 7 | The TKG formulation entirely | ~200 papers 2020–2026 |
| 8 | The LLM turn (2022–2026) | ICL forecasting, RAG, agentic search, outcome-RL |
| 9 | Evaluation-integrity literature | contamination, simulated-ignorance failure, temporal leakage, revision leakage |
| 10 | An Indic-language event corpus — the one asset they were uniquely placed to own | India Police Events and ProtestNews-Hindi exist, but were built abroad and are small |
| 11 | Independent evaluation | EMBERS had MITRE scoring it prospectively |
| 12 | Published failure analysis and ethics | *EMBERS at 4 Years* published misses and ethical limits; CSCW 2021 critiques unrest-prediction products directly |

Item 10 is the expensive one. It is the only line in this table where C-DAC had a structural advantage over Virginia Tech, Stevens, HIT and NUS — and it is unclaimed to this day.

---

## 4. What makes today's top work top

Strip the papers down and the same ten choices recur. This is the checklist a new system must satisfy before it can even be compared:

1. **Prospective or live evaluation.** FutureX generates questions whose answers do not exist yet. Retrospective evaluation on pre-cutoff events is now considered invalid, not merely weak.
2. **Proper scoring rules, difficulty-adjusted.** Brier/log/CRPS, and a stated reference forecaster.
3. **Honest baselines that might beat you.** no-change; recurrency; market consensus; base rate.
4. **Time as verifiable reward.** Resolved outcomes are free labels; RL on them beats 7× larger untrained models.
5. **Agentic retrieval with strict as-of-date discipline**, over curated sources rather than open web.
6. **Structured context over prose.** Statistics in, headlines out.
7. **An aggregation layer that is not herding.** Supervisor agents, expert routing, engineered information asymmetry.
8. **Explicit statistical de-biasing and calibration** on top of the LLM's raw probability.
9. **Released code and data.**
10. **A published failure analysis.**

---

## 5. Where they are still weak — the actual attack surface

Every item here is a *documented* weakness in the current top systems, not a speculative one. This is what a new entrant should aim at.

**5.1 The recurrence trap.** TKG leaderboard gains are largely repeats: >80% of ICEWS test events already occurred; a tuning-free recurrency baseline matches 11 published methods. Nobody owns the **novel-event stratum** (onset, first escalation, unprecedented actor–location pairs). Report stratified by novel vs recurring, and the entire leaderboard re-sorts.

**5.2 No-change still wins in conflict.** VIEWS' own challenge showed most models lose to it. Beating no-change *with calibrated uncertainty* on a defined subnational grid is, by itself, a publishable result in 2026.

**5.3 Calibration under distribution shift is thin.** Almost everyone reports Brier; almost nobody reports distribution-free valid intervals under shift (adaptive conformal / risk control) plus a decision-cost curve. It is cheap, rigorous and differentiating.

**5.4 Everyone feeds raw news to the LLM even though the evidence says not to.** REALM 2025: structured stats help, raw article text hurts. Most agentic systems still dump retrieved prose into the context. A pipeline that converts news → structured event/indicator tables → classical model → LLM only for hypothesis generation and evidence assembly is under-explored *and* cheap.

**5.5 The evaluation substrate is leaky.** Date-filtered search leaks; revised data leaks; simulated ignorance fails. Whoever builds a **frozen, publication-timestamped news index with as-of-date retrieval** owns the only trustworthy substrate in the field.

**5.6 Deliberation herds.** InfoDelphi shows that multi-agent gains come from *information asymmetry*, not from debate. Genuine asymmetry is hard to manufacture in English-only Western pipelines — and is free if your sources span English, Hindi and regional-language press with materially different coverage.

**5.7 Language and region.** There is no live, contamination-free forecasting benchmark for South Asia in Indic and code-mixed text. MediaGraph (2604.20982) has already shown Indian news outlets have measurably different reporting preferences — so a single English-wire view of India is provably biased. This is an owned moat, not a consolation prize.

**5.8 Small models are now competitive if trained on outcomes.** 1.5B beat Claude Sonnet 3.5; 32B beat 235B. This makes the frontier reachable on AIRAWAT/PARAM-class compute rather than requiring a frontier lab budget.

---

## Sources

- [Survey and Gap Analysis on Event Prediction of English Unstructured Texts (ICTIS 2020)](https://link.springer.com/chapter/10.1007/978-981-15-7106-0_49)
- [Event Prediction in the Big Data Era: A Systematic Survey (ACM CSUR)](https://dl.acm.org/doi/abs/10.1145/3450287)
- [A Survey on Societal Event Forecasting with Deep Learning](https://arxiv.org/pdf/2112.06345)
- ['Beating the news' with EMBERS](https://arxiv.org/abs/1402.7035) · [EMBERS at 4 years](https://arxiv.org/abs/1604.00033)
- [ACLED CAST methodology](https://acleddata.com/methodology/cast-methodology) · [cast-public](https://github.com/ACLED/cast-public)
- [2023/24 VIEWS Prediction Challenge (JPR)](https://journals.sagepub.com/doi/10.1177/00223433241300862) · [live rankings](https://viewsforecasting.org/news/views-prediction-challenge-2023-24-follow-live-results-and-performance-rankings/) · [PRIO news](https://www.prio.org/news/3602)
- [Glean: Dynamic Knowledge Graph based Multi-Event Forecasting (KDD 2020)](https://dl.acm.org/doi/10.1145/3394486.3403209) · [Robust Event Forecasting with Spatiotemporal Confounder Learning (KDD 2022)](https://dl.acm.org/doi/10.1145/3534678.3539427)
- [Constructing Narrative Event Evolutionary Graph (IJCAI 2018)](https://www.ijcai.org/proceedings/2018/584) · [code](https://github.com/eecrazy/ConstructingNEEG_IJCAI_2018)
- [History Repeats Itself: A Baseline for TKG Forecasting (IJCAI 2024)](https://www.ijcai.org/proceedings/2024/0444.pdf) · [code](https://github.com/nec-research/recurrency_baseline_tkg)
- [On the Evaluation of Methods for TKG Forecasting](https://openreview.net/pdf?id=J_SNklR-KR)
- [Strikingness-Aware Evaluation for TKG Reasoning](https://arxiv.org/pdf/2605.13153) · [TKG Forecasting under Distribution Shifts](https://arxiv.org/abs/2607.09232)
- [MIRAI](https://arxiv.org/abs/2407.01231) · [site](https://mirai-llm.github.io/) · [code](https://github.com/yecchen/MIRAI)
- [FutureX](https://arxiv.org/abs/2508.11987) · [ForecastBench](https://arxiv.org/pdf/2409.19839) · [leaderboard](https://www.forecastbench.org/explore/)
- [AIA Forecaster Technical Report](https://arxiv.org/abs/2511.07678)
- [ForecastAgentSearch](https://arxiv.org/pdf/2606.31665) · [Diverse Evidence, Better Forecasts (InfoDelphi)](https://arxiv.org/html/2607.01661v1) · [ThinkTank-ME](https://arxiv.org/pdf/2601.17065)
- [Outcome-based RL to Predict the Future](https://arxiv.org/pdf/2505.17989) · [Advancing Event Forecasting through Massive Training](https://arxiv.org/abs/2507.19477) · [RL for LLM-based Event Forecasting](https://arxiv.org/abs/2606.15917) · [FutureWorld](https://arxiv.org/pdf/2604.26733) · [Lightning Rod: how we built the #1 AI forecaster](https://blog.lightningrod.ai/p/how-we-built-the-number-1-ai-forecaster)
- [The Power of Simplicity in LLM-Based Event Forecasting (REALM 2025)](https://aclanthology.org/2025.realm-1.32/)
- [Simulated Ignorance Fails](https://arxiv.org/abs/2601.13717) · [Temporal Leakage in Date-Filtered Retrieval](https://arxiv.org/pdf/2602.00758) · [Information Leakage from Data Revisions](https://arxiv.org/html/2608.05883)
- [When AI Navigates the Fog of War](https://arxiv.org/abs/2603.16642v1) · [Do LLMs Know Conflict?](https://arxiv.org/abs/2505.09852)
- [PLOVER and POLECAT](https://www.andrewhalterman.com/publication/plover-polecat-new-event-data/) · [GDELT vs POLECAT for forecasting](https://doi.org/10.3390/data11070158) · [Toward Better Temporal Structures for Geopolitical Events Forecasting](https://arxiv.org/abs/2601.00430)
- [OpenEP](https://arxiv.org/pdf/2408.06578) · [What Would Happen Next? Event Causality Graph](https://arxiv.org/pdf/2409.17480) · [LLMs as Interpolated and Extrapolated Event Predictors](https://arxiv.org/pdf/2406.10492)
- [The Hard Problem of Prediction for Conflict Prevention (Mueller & Rauh, JEEA 2022)](https://ideas.repec.org/a/oup/jeurec/v20y2022i6p2440-2467..html) · [global dataset on conflict forecasts and news topics](https://www.cambridge.org/core/journals/data-and-policy/article/introducing-a-global-dataset-on-conflict-forecasts-and-news-topics/AADA08BD5FC80EDD01E5CEBA7434F6E0)
- [Future Protest Made Risky (CSCW 2021)](https://dl.acm.org/doi/abs/10.1007/s10606-021-09409-0)
- [MediaGraph: reporting preferences in Indian news media](https://arxiv.org/pdf/2604.20982)
