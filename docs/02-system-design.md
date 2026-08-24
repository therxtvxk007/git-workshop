# System design

## The forecasting question

> Given every English document published about region *R* strictly before day *T*,
> what is the probability that a target event occurs in *R* during `[T, T + h)`?

Everything else follows from that sentence. It is deliberately the same shape as
the nMIL formulation the survey reviews, for one reason: it is the only framing
in the survey that can be scored against events that actually happened, which is
gap **G6**.

## Data model

```
Document          one article. text + date + region + source
   |              extraction -> list[Event] (actor, action, target, time, polarity)
   |              embedding  -> dense vector
   v
Bag               all documents for one (region, day)
   |
   v
BagGroup          lookback_days of bags for one region, ending strictly before
                  the forecast origin. Carries the label.
```

The label lives only on the `BagGroup`. Nobody labels individual articles as
"precursors", so precursor evidence has to be *recovered* by the model rather
than supervised — which is what makes the attribution mechanism load-bearing
rather than decorative.

## Pipeline

```
  unstructured text
         |
    [ extraction ]  LLM schema-constrained  |  lexicon fallback      G2, G4, G7
         |                                                     
    +----+----------------------------+
    |                                 |
[ embedding ]                  [ event tuples ]
 hashing+SVD                          |
    |                                 |
    +----------------+----------------+
                     |
        +------------+-------------+
        |                          |
  SEMANTIC BRANCH            TABULAR BRANCH
  nested MIL                 L1 logistic over
  per-region heads           time-decayed stream        G3, G5
  + attribution              dynamics
        |                          |
        +------------+-------------+
                     |
          [ standardised-logit average ]
                     |
              [ Platt calibration ]        rank-preservation guarded
                     |
              [ split conformal ]          abstain when uncommitted   G11
                     |
        probability + conformal set + ranked precursors
```

Evaluation wraps the whole thing in rolling-origin backtesting with baselines
(**G6**, **G10**).

## Why two branches

They fail differently, which is the only thing that makes an ensemble worth
having.

| | Semantic branch (nested MIL) | Tabular branch (L1 logistic) |
|---|---|---|
| Reads | what individual articles *say* | the *shape* of the document stream |
| Strength | fires on one decisive article — a called strike in a quiet region | robust when articles are noisy or extraction misfires |
| Weakness | overfits when labelled windows are few | blind to content; a burst of routine coverage looks like a burst of unrest |
| Gives | per-document attribution | signed, sparse coefficients |

Measured on this simulator they are unstable in *opposite* directions across
folds — on one test window the MIL branch scored 0.706 ROC-AUC against the
tabular branch's 0.567, and on the next 0.492 against 0.653. That instability is
the argument for averaging them and against trying to pick one (see
`HybridConfig.blend_rule`).

## Design decisions that came from measurement, not taste

Each of these was a bug or a wrong default found by running the thing. They are
documented at the point of code as well.

| Decision | What forced it |
|---|---|
| Calibration slice held out of branch training | Calibrating on data the branches had fitted made inputs in-sample and overconfident; the deployed model scored *worse than the base rate*. |
| Platt as default, not isotonic | Isotonic is only weakly monotone. On 2 of 4 folds it collapsed the entire fold to one probability (0.166 for every window), turning a 0.752 ROC-AUC ranking into exactly 0.500. |
| Rank-preservation guard on any fitted calibrator | Same failure, caught structurally rather than by luck: a map that outputs fewer than 3 distinct values, or that reorders, is rejected. |
| Average in *standardised logit* space | A plain probability average is not scale-free. The branch with wider spread dominates regardless of accuracy — averaging a 0.709 branch with a 0.509 branch gave 0.538. |
| Fixed averaging, not per-fit selection | A selector judging on ~90 held-out windows (~19 positives) picked the wrong branch at the exact fold where it mattered: it saw mil 0.682 / tabular 0.374 and chose mil, which then scored 0.492 against the tabular branch's 0.653. |
| Linear tabular branch, not gradient boosting | The booster averaged 0.521 ROC-AUC across folds against 0.574 for L1 logistic — and lost to a two-feature volume-only baseline, the signature of overfitting ~18 correlated features on a few hundred rows. |
| BLAS pinned to one thread during fit | The objective is hundreds of thin matrix products. Multithreaded BLAS spent more time in thread sync than arithmetic: the gradient GEMM measured 179ms multithreaded versus 3.7ms on one thread. Fit time went from 27s to 1.1s. |
| Multi-seed evaluation script | Two seeds of the same configuration gave stacked ROC-AUC 0.623 and 0.572, and disagreed about whether the model beat the best baseline. One seed cannot rank models here. |

## Extension points

- **Extractor** — implement `extract(text) -> list[Event]`. `LLMExtractor` shows
  the schema-constrained pattern; swapping the model is a constructor argument.
- **Embedder** — implement `fit`/`transform`. `SentenceTransformerEmbedder` is
  there for when pretrained weights are reachable.
- **Source** — write a loader returning `list[Document]`. Everything downstream
  is source-agnostic, and `source_diversity` becomes a live feature (**G8**).
- **Tabular model** — `HybridConfig.tabular_model`.
- **Blend rule** — `HybridConfig.blend_rule`, including `"auto"` to select per
  fit (off by default, for the reason in the table above).
