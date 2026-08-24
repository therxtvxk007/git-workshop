# evpred — hybrid LLM + classical ML event prediction from unstructured text

A forecasting system built against the gap analysis in Bhattacharjee et al.,
*Survey and Gap Analysis on Event Prediction of English Unstructured Texts*
(C-DAC Pune / VIIT Pune, 2020).

**The question it answers:** given every English document published about region
*R* strictly before day *T*, what is the probability that a target event occurs
in *R* during `[T, T + h)` — and *which documents* drove that forecast?

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python experiments/run_demo.py      # end-to-end on simulated data, ~60s
.venv/bin/python experiments/run_seeds.py     # multi-seed evaluation, ~6min
.venv/bin/python -m pytest                    # 59 tests, ~15s
```

## Read this first

Two things about scope, stated up front rather than buried.

**This is not a survey of 2026 work.** The brief was to build on the cutting edge
to August 2026. My knowledge ends in **May 2026**, and the build environment had
**no outbound network** — every scholarly host was blocked at the egress proxy,
so I could not search or verify a single paper. I have therefore deliberately
cited nothing recent rather than invent plausible references. What is implemented
are methods I can state precisely and that are fully written out here, so you can
check them yourself. See [docs/04-limitations.md](docs/04-limitations.md) §1.

**The headline forecasting result is negative.** Across 8 simulator seeds the
full system is *not* reliably better than a two-feature baseline that just counts
documents. Details below. The parts that do work — evidence recovery and
calibrated abstention — are reported next to the parts that do not.

## Results (8 seeds × 4 walk-forward folds, simulated data)

| model | ROC-AUC | PR-AUC | Brier | Brier skill | ECE |
|---|---|---|---|---|---|
| **STACKED** | 0.567 ± 0.036 | 0.264 ± 0.050 | 0.191 ± 0.027 | −0.374 ± 0.330 | 0.161 |
| branch: tabular (L1 logistic) | 0.582 ± 0.062 | 0.283 ± 0.087 | 0.159 ± 0.020 | −0.104 ± 0.198 | 0.083 |
| branch: semantic (nested MIL) | 0.524 ± 0.044 | 0.228 ± 0.030 | 0.177 ± 0.024 | −0.245 ± 0.261 | 0.134 |
| baseline: volume only | 0.558 ± 0.073 | 0.266 ± 0.065 | 0.159 ± 0.022 | −0.091 ± 0.158 | 0.082 |
| baseline: region climatology | 0.520 ± 0.042 | 0.229 ± 0.024 | 0.166 ± 0.024 | −0.155 ± 0.228 | 0.097 |
| baseline: base rate | 0.500 | 0.199 ± 0.035 | 0.161 ± 0.023 | −0.112 ± 0.188 | 0.066 |
| *latent-state oracle (ceiling)* | *≈0.78* | *≈0.49* | — | — | — |

**Forecasting skill: not established.** Against the strongest baseline the
stacked model wins on 5 of 8 seeds, mean difference **+0.009 ± 0.049**, paired
*t* = **+0.48**. That is indistinguishable from zero. Anyone who ran a single
backtest here could have reported +0.04 or −0.08 depending on the seed — which is
precisely why `run_seeds.py` exists.

**Probabilities are unreliable.** Brier skill is negative for every model
including the baselines: per-fold base rates swing from 0.11 to 0.28, and a
calibration map fitted on past windows is simply wrong when the next window's
regime differs. Use the ranking, not the number.

**Two things do work:**

- **Conformal coverage: 0.889 ± 0.014 against a 0.900 target**, stable across
  every seed. The abstention mechanism is trustworthy even though the point
  probabilities are not — which is the entire argument for having it.
- **Precursor recovery: 0.78 precision@5 against a 0.11 corpus rate — 6.8× lift
  over random.** When the system says "these five articles drove this forecast",
  the articles are overwhelmingly the ones the generating process actually
  escalated from.

**A caveat that cuts against the semantic branch specifically:** the simulator
generates text from a fixed template set, so once you have counted the event
keywords there is no further meaning in the words. That structurally caps what a
dense-embedding branch can contribute and probably explains why it sits near
chance here. It is the one place where the simulator most clearly understates
what the architecture would do on real news.

## What's here

```
src/evpred/
  schema.py       nested MIL data model: Document -> Bag -> BagGroup
  extraction.py   LLM schema-constrained extraction; lexicon fallback
  embedding.py    hashing+SVD embedder (offline); pretrained encoder optional
  features.py     event-tuple features + time-decayed stream dynamics
  nmil.py         nested MIL, per-region multi-task heads, exact attribution
  stacking.py     two-branch fusion, calibration, conformal
  calibration.py  Platt/isotonic with a rank-preservation guard; split conformal
  evidence.py     precursor identification from the pooling gradient
  backtest.py     rolling-origin evaluation, lookahead assertions, baselines
  metrics.py      AUC, PR-AUC lift, Brier skill, ECE, precision@k
  synthetic.py    latent-tension simulator with ground-truth precursors
  adapters.py     CSV / JSONL / GDELT loaders, ACLED label builder
  cli.py          evpred demo | backtest | extract
```

| Doc | Contents |
|---|---|
| [01-survey-gap-analysis.md](docs/01-survey-gap-analysis.md) | The survey's 11 gaps, itemised, mapped to components — and the ones still open |
| [02-system-design.md](docs/02-system-design.md) | Architecture, and the design decisions that came from measurement rather than taste |
| [03-method.md](docs/03-method.md) | The maths: pooling, attribution, multi-task penalty, calibration, conformal |
| [04-limitations.md](docs/04-limitations.md) | Everything that would make these numbers wrong |

## The parts worth reusing

Even with the negative headline, three components stand on their own.

**Evidence that is the mechanism, not a story about it.** Precursor attribution
is the exact pooling gradient `dS/ds_i = beta_b · alpha_i`, in closed form. Not a
surrogate explainer fitted afterwards to approximate the model. The gradient is
verified against central finite differences in the test suite (agreement ~2.5e-9).

```
Forecast  region=region-01  origin=2024-08-25  horizon=7d
  probability = 0.500   conformal set = {1}
  top precursors (attribution weight):
    2024-08-23  w=0.673  [rally]
      The drivers syndicate called for a mass rally in downtown, escalating a dispute...
    2024-08-24  w=0.253  [rally]
      The farmers coalition called for a mass rally in downtown, escalating a dispute...
```

**A backtester that makes leakage hard.** Folds are contiguous blocks of forecast
origins; the embedder is refit per fold on training documents only;
`assert_no_lookahead` hard-fails on any document dated at or after its forecast
origin; a shuffled-label negative control is a test. Three baselines run through
the identical split.

**A record of what actually broke.** Every non-obvious default in this codebase
is there because a measured failure put it there — calibration collapsing a fold
to a constant, a probability average dominated by the wider-spread branch, a
selector confidently choosing the worse branch, a 24× speedup from pinning BLAS
threads. They are documented at the point of code and tabulated in
[docs/02-system-design.md](docs/02-system-design.md#design-decisions-that-came-from-measurement-not-taste).

## Using it on real data

```bash
evpred backtest --csv news.csv --acled acled_export.csv --dedup --evidence 5
```

`--csv` supplies documents (`date`, `region`, `text`); `--acled` supplies
realised events, which become the labels. Set `ANTHROPIC_API_KEY` and pass
`--extractor llm` to swap the lexicon extractor for schema-constrained LLM
extraction. The adapters are written against published schemas and unit-tested
against fixtures, but have **never been run against a live download** — check
your export's columns first.

## Requirements

Python ≥ 3.10, numpy, scipy, scikit-learn. Optional: `anthropic` for LLM
extraction, `sentence-transformers` for pretrained embeddings.
