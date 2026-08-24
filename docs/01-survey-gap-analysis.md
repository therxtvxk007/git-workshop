# Gap analysis: what the survey found, and what this repo does about it

Source: Bhattacharjee, K., ShivaKarthik, S., Mehta, S., Kumar, A., Kothawade, R.,
Katre, P., Dharkar, P., Pillai, N., Verma, D. — *Survey and Gap Analysis on Event
Prediction of English Unstructured Texts* (C-DAC Pune / VIIT Pune, 2020).

## 1. What the survey covers

The paper clusters event-prediction work into four groups and reviews the tooling
around them.

| Cluster | Representative work | Reported result |
|---|---|---|
| Probabilistic logic | Markov Logic Networks over OWL-encoded news events, with DBpedia/WordNet as background knowledge (Dami et al.) | Precision 89.74%, coverage 92.26% |
| Rule-based | Pundit — causality graph over 150 years of news + ~200 linked-data ontologies (Radinsky et al.) | Accuracy 63% (human 42%) |
| Machine learning | nested Multiple-Instance Learning for protest forecasting with precursor discovery (Ning et al.) | Accuracy 0.709, F1 0.702 |
| Machine learning | LDA topics → panel regression for conflict onset | ROC 82% civil war, 73% armed conflict |
| Evidence gathering | Credibility scoring of retrieved articles (Popat et al.); Supporting Evidence Retrieval in DeepQA/Watson | — |

Tooling reviewed: **DoWhy** (causal inference), **Tuffy** (MLN inference over
PostgreSQL), **IBM Watson / DeepQA**, **Event Registry** (news event clustering).

## 2. The gaps, itemised

The survey's Section 5 states these fairly compactly. Numbered here so the rest
of the repo can refer to them.

| ID | Gap as stated | Where it bites |
|---|---|---|
| **G1** | No adaptability or scalability to parallel/distributed environments | MLN inference and ontology joins do not shard |
| **G2** | MLN relies on domain-specific rules written by human experts; accuracy drops on out-of-domain data | Every new domain needs a new rule set |
| **G3** | Pundit ignores the effect of **time** on causal relations and forecasted effects | "A causes B" treated as timeless; a 30-day-old article counts like yesterday's |
| **G4** | Pundit extracts events from **headlines only** | Body text, where most precursor detail lives, is discarded |
| **G5** | nMIL was validated on one geography (Argentina/Brazil/Mexico) and does **not use regularised multi-task learning** | No transfer to new regions; low-data regions overfit |
| **G6** | Models are not validated against **events that actually occurred** | Reported metrics may not survive honest temporal evaluation |
| **G7** | Event-specific features are under-exploited | Predictions run on bag-of-words rather than event structure |
| **G8** | Approaches use single sources; **heterogeneous multi-source** fusion is missing | Real-world reliability suffers |
| **G9** | Twitter work ignores **location**; hashtag-collected corpora have no relevance guarantee | Noisy, geographically unanchored inputs |
| **G10** | Validation is a shortcoming across the board due to processing cost | No baselines, no error bars, no ablations |
| **G11** | Prediction without **supportive evidence** is not actionable ("credible and close to infallible", with "plausible reasoning for its forecast") | Analysts cannot audit or act on a bare score |

## 3. How this repo addresses each gap

| Gap | Component | Mechanism |
|---|---|---|
| G1 | `embedding.py` | `HashingVectorizer` — no vocabulary-fitting pass, so shards embed independently. Stateless per-document extraction and embedding are embarrassingly parallel; only the final fit is centralised. |
| G2 | `extraction.py` | `LLMExtractor` does schema-constrained extraction with **no hand-written rules**, and degrades to a lexicon extractor when offline. Domain transfer becomes a prompt change, not a first-order-logic rewrite. |
| **G3** | `features.py` | Explicit `DecayConfig` exponential recency kernel (tunable half-life) applied to every text signal, plus lag-banded features (`lag1_neg`, `lag3_neg`, `lag7_neg`), `acceleration`, `burst_ratio_3_14` and `trend_slope`. **When** a precursor appeared changes the forecast. |
| G4 | `schema.py`, `synthetic.py` | The unit is a full `Document`, not a headline. Multi-sentence bodies are extracted and scored sentence-by-sentence. |
| **G5** | `nmil.py` | Per-region task heads `w_r = w0 + v_r` with `lambda_task * \|\|v_r\|\|^2` shrinkage toward a shared trunk (Evgeniou–Pontil regularised MTL). Unseen regions fall back to the trunk — an explicit cold-start path. `region_divergence()` reports whether sharing is actually happening. |
| **G6** | `backtest.py` | Rolling-origin walk-forward evaluation against realised outcomes; `assert_no_lookahead` hard-fails on any document dated at or after the forecast origin; the embedder is refit per fold on training text only. |
| G7 | `features.py` | Ten event-tuple features per document (polarity mass, confidence-weighted conflict intensity, distinct-action count, temporal-reference presence) feeding the instance vector, plus actor/action entropy at group level. |
| G8 | `schema.py`, `adapters.py` | `Document.source` is first-class; `source_diversity` is a model feature; adapters normalise GDELT/ACLED/CSV into the same `Document` type so fusion is a concatenation. |
| G9 | `schema.py`, `features.py` | `region` is a required field on every document and the multi-task key; `Event.location` is extracted separately from the document's region so a report *about* elsewhere can be distinguished from local activity. |
| **G10** | `backtest.py`, `metrics.py` | Three baselines (base rate, per-region climatology, volume-only) run through the identical split; per-branch ablations reported alongside the stack; Brier **skill** score against climatology; ECE; the simulator's `oracle_scores` gives an achievability ceiling. |
| **G11** | `evidence.py`, `calibration.py` | Precursor attribution is the exact pooling gradient `dS/ds_i = beta_b * alpha_i`, not a post-hoc surrogate. Calibration makes the number mean something; split-conformal sets let the system **abstain** rather than guess. |

## 4. Gaps this repo does *not* close

Stated plainly, because a gap analysis that claims to have solved everything is
not a gap analysis.

- **G8 is only half-closed.** The plumbing for multi-source fusion is there
  (source-typed documents, diversity features, adapters), but no cross-source
  entity resolution or deduplication is implemented. Two wire services covering
  the same protest currently count twice, which inflates volume features.
- **G1 is architectural, not demonstrated.** Nothing here runs on Spark or Ray.
  The claim is that the design does not *prevent* sharding, which is weaker than
  showing a distributed run.
- **No real-corpus results.** Everything reported in this repo is on simulated
  data (see `docs/04-limitations.md`). The adapters are written but were not
  runnable in the development environment, which had no outbound network.
- **Causal inference is not attempted.** The survey reviews DoWhy and MLN causal
  rules; this system is frankly predictive, not causal. It will happily use a
  correlate. That is a real limitation for the "explain why" use case, and
  conflating prediction with causation would be the easiest way to oversell it.
