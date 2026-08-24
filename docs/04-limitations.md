# Limitations

Read this before quoting any number from this repository.

## 1. The literature review is bounded by what I could actually check

The request was to build on the cutting edge "till Aug 23rd 2026". I could not
do that, and the design does not claim to.

- My training data ends in **May 2026**. I have no knowledge of work published
  between then and August 2026.
- The development environment had **no outbound network access**. Every external
  host was blocked at the egress proxy — `researchgate.net`, `doi.org`,
  `arxiv.org`, `semanticscholar.org`, `scholar.google.com`, `api.crossref.org`
  all returned 403 on CONNECT. Only PyPI was reachable. So I could not search,
  fetch, or verify a single paper while building this.

What that means concretely: **this system is not grounded in a fresh literature
sweep, and I have deliberately not cited recent papers**, because I cannot check
that any given citation exists, says what I would claim, or has not been
superseded. Inventing plausible-looking references is the single most damaging
thing I could do to a research codebase.

What it *is* grounded in: methods I can state precisely and that are implemented
here in full, so you can check them against the literature yourself —
nested multiple-instance learning with smooth-max pooling, Evgeniou–Pontil
regularised multi-task learning, Platt and isotonic calibration, split-conformal
prediction with Mondrian (class-conditional) thresholds, rolling-origin
backtesting, and stacked generalisation with forward-chaining out-of-fold
predictions. None of these are 2026-new. The contribution here is the
*combination*, the leakage discipline, and the evidence mechanism — not novel
mathematics.

**If you want the 2026 state of the art**, the honest path is: run a literature
search yourself on event forecasting / temporal knowledge-graph forecasting /
LLM forecasting agents for 2025–2026, and treat this repo as a baseline and a
harness to evaluate whatever you find. The backtester and baselines are the
reusable part; a new model only has to implement `fit`/`predict_proba` over
`BagGroup`s to be measured on equal terms.

## 2. All reported numbers are from a simulator

No real corpus was used. `synthetic.py` generates news-like text from templates
driven by a latent tension process. That buys three things real data cannot —
a known achievability ceiling, ground-truth precursor labels, and reproducible
difficulty — and it costs the only thing that ultimately matters:

**Template text is far easier than real news.** No irony, no reported speech, no
denials ("the union denied planning a strike"), no duplicated wire copy, no
mixed-language content, no articles about *other* regions. The lexicon extractor
in particular is flattered by templates built from the same verb list. Expect
the extraction quality gap between the lexicon and LLM backends to be much wider
on real text than it appears here.

**And template text is simultaneously *harder* for the semantic branch than real
news**, in a way that biases the results. Because the escalation sentences are
drawn from a fixed pool, a model that counts the event keywords has extracted
everything there is; the dense embedding of the surrounding words is noise by
construction. So this simulator cannot demonstrate the value of a semantic
branch even in principle. Read the near-chance MIL result as "not measurable
here", not as "does not work".

The adapters for GDELT, ACLED, CSV and JSONL are written against published
schemas and unit-tested against fixtures. **They have never been run against a
live download**, because the network was blocked. Check the column layout of
your export before trusting a large run.

## 3. The model's probabilities are not trustworthy under drift

This is the clearest weakness in the results and it is not hidden in the table.

Brier **skill** is negative across folds — the calibrated probabilities are worse
than simply predicting the historical base rate. The cause is visible in the
per-fold base rates, which range from 0.11 to 0.28 across a single run. Any
calibration map is fitted on the most recent *training* windows; when the test
window's base rate is materially different, the map is wrong, and no amount of
care about leakage fixes that. It is genuine non-stationarity.

Practical consequence: **use the ranking, not the number**. ROC-AUC and PR-AUC
are the meaningful outputs — "which windows most warrant attention" — and the
conformal set is the meaningful decision signal, because its coverage is
measured and holds up (see the results table). Do not put the probability in
front of a decision-maker as though 0.30 means 30%.

## 4. Forecasting skill over the simplest baseline is not established

This is the headline result and it is negative.

The `volume_only` baseline is two features — how many documents were published
and how many events were extracted — with no content at all. Across 8 simulator
seeds:

| | ROC-AUC |
|---|---|
| STACKED | 0.567 ± 0.036 |
| baseline: volume only | 0.558 ± 0.073 |
| difference (paired by seed) | **+0.009 ± 0.049** |

The system wins on 5 of 8 seeds; paired *t* across seeds is **+0.48**. At n=8
you would want |t| above roughly 2.4 to say anything. This is indistinguishable
from zero.

Note also that the *stacked* model does not beat its own tabular branch
(0.582 ± 0.062). The ensemble is not adding value on this data.

Two things follow.

First, **run `experiments/run_seeds.py`, never a single backtest.** The
seed-to-seed spread (±0.036 to ±0.073) is several times the effect being
measured. Two runs of the identical configuration during development gave
stacked ROC-AUC 0.623 and 0.572 and disagreed about whether the model beat the
best baseline. Reporting one favourable seed would reproduce exactly the
validation weakness (**G6**, **G10**) that motivated this project.

Second, **the simulator may be the wrong instrument for this particular
question.** Its text is generated from a fixed template set, so once the event
keywords are counted there is no residual meaning in the words. That caps what
the dense-embedding semantic branch can contribute almost by construction, and
is the most likely explanation for it sitting near chance (0.524 ± 0.044). A
fair test of the semantic branch needs real news, which needs network access
this build did not have.

## 5. Gaps from the survey that remain open

- **G8 (heterogeneous sources) is half-closed.** Source-typed documents,
  diversity features and adapters exist, but `deduplicate()` is exact-shingle
  matching, not cross-source entity resolution. Two outlets covering one protest
  still count twice and inflate volume features.
- **G1 (distributed execution) is architectural only.** Hashing embeddings and
  per-document extraction do not *prevent* sharding, and `iter_batches` is
  there for it. Nothing here has been run on Spark or Ray. That is a weaker
  claim than a demonstration.
- **Causality is not attempted.** The survey reviews DoWhy and MLN causal rules.
  This system is frankly predictive and will happily use a correlate. Do not
  read the precursor evidence as a causal claim: it says "these documents drove
  the forecast", not "these events cause the outcome".

## 6. Scope of the evidence mechanism

Precursor attribution is exact with respect to *the model* — it is the pooling
gradient. It is not a guarantee about the world. If the model has learned a
spurious correlate, attribution will faithfully show you the spurious correlate.
That is the intended behaviour, and it is why `aggregate_precursor_actions` is
worth reading: if attribution mass sits on plausible escalation predicates the
model has probably learned something real, and if it sits on routine coverage it
has not.

## 7. Not evaluated at all

- Any language other than English.
- Documents whose stated `region` differs from the region the events are *about*
  (`Event.location` is extracted but is not yet used to re-route documents).
- Horizons other than 7 days and lookbacks other than 14, beyond the fact that
  both are parameters.
- The LLM extraction path end-to-end. `LLMExtractor` is unit-tested for parsing,
  schema handling and fallback behaviour, but no API key was available, so it has
  never been exercised against a live model.
