# PRAMAAN-X

Compute-cascade event forecasting: cheap high-recall models examine every
document, expensive models see only what survives. Built Python/PyTorch-first,
with every heavy component behind an interface so the whole system runs on CPU
with no downloads and swaps to Qwen3.8 / Jina v5 / Qdrant / Neo4j by changing a
string in a config file.

```
stage 0  dedup and validate     28.7% of the stream removed before any model runs
stage 1  cheap high-recall scan 100% precursor recall at 39% retention
stage 2  four-stage retrieval   R@10 0.535, MRR 0.751 with learned fusion
stage 3  expensive reasoning    budgeted, cached, schema-validated
stage 4  risk models            not yet built
stage 5  conformal risk control not yet built
```

## Quick start

```bash
pip install -e ".[boost,serve,llm,dev]"

pramaan profiles                       # hardware profiles and what each selects
pramaan ingest --days 240              # build and index a synthetic corpus
pramaan search "reservoir levels approached the seasonal spill threshold" \
        --as-of 2025-06-01T00:00:00Z
pramaan bench --days 300               # measure Recall@K across cascade stages
pramaan serve                          # API + analyst console on :8000
```

Or with Docker:

```bash
docker compose up api                  # just the service
docker compose --profile vector --profile tracking up   # + Qdrant + MLflow
```

## What is measured, not asserted

Every number below came from a run in this repository and is guarded by a test.

| Property | Measured | Where |
| --- | --- | --- |
| Duplicate collapse | 27.7% of corpus, 0.4% false merges | `tests/test_dedup.py` |
| Precursor survival through dedup | 100% | `tests/test_dedup.py` |
| Stage-1 precursor recall | 100% at 39% retention | 36-point grid, `Stage1Config` |
| Retrieval, heuristic ordering | R@10 0.199 · nDCG@10 0.177 · MRR 0.324 | `pramaan bench` |
| Retrieval, learned fusion | R@10 **0.535** · nDCG@10 **0.527** · MRR **0.751** | `pramaan bench` |
| CUSUM operating point | ARL₀ 410 days, 2.7-day detection delay | `burst.cusum` docstring |
| Publication-cutoff violations | 0 | `tests/test_retrieval.py`, `tests/test_api.py` |

The retrieval numbers are the reason the design brief says not to hand-set the
component weights: training LambdaMART on the same candidates nearly tripled
nDCG@10 over a hand-tuned ordering.

## Layout

```
pramaan_x/
  config.py            hardware profiles; every component named here, not at the call site
  types.py             Document, EventTuple, Target, Candidate, Forecast, Tier
  data/
    synth.py           synthetic corpus with ground truth and deliberate failure modes
    store.py           Polars + Parquet + DuckDB, with as_of() as the only read path
    versioning.py      content-hash manifests, DVC stubs, leakage audit
  stage0_ingest/       exact + MinHash + SimHash dedup, cleaning, timestamp validation
  stage1_scan/         BM25, embedders, learned log-odds lexicon, extractors,
                       relevance model, CUSUM + BOCPD, the union router
  stage2_retrieve/     cascade, engines, late interaction, RRF + LambdaMART,
                       rerankers, temporal graph, ITHI, LANTERN, MTRM
  stage3_reason/       LLM client (vLLM/SGLang/OpenAI-compatible + offline),
                       Pydantic output contracts, constrained decoding
  eval/                metrics, retrieval benchmark
  service.py api.py cli.py tracking.py static/
```

## Design decisions worth knowing

**The cascade narrows, and each stage justifies itself.** `Stage1Result.unique_contribution()`
reports how many documents each detector is *solely* responsible for retaining.
A detector with zero unique contribution is pure cost and should be deleted.

**Stage 1 takes the union of detectors, never the intersection.** Intersecting
makes a filter look precise while destroying the recall everything downstream
depends on. A document only one detector notices is exactly the one worth keeping.

**Source independence counts syndication families, not source ids.** Thirty
copies of one wire story must not read as thirty corroborating sources. This is
a feature fed to the risk model, not a diagnostic, and the analyst console warns
when a cluster's independence is low.

**Nothing reads the corpus without a cutoff.** `DocumentStore.as_of()` is the
only supported read path for a forecast, extraction stamps
`publication_cutoff_valid` on every tuple, and `edges_from_tuples` drops invalid
ones at the graph boundary — an invalid edge in a temporal graph is permanent
and no later filter can undo it.

**The offline backends are real, not mocks.** Feature hashing, in-process BM25,
exact numpy vector search and the rule extractor are weak but genuine methods.
That is what makes them a usable floor: when the bake-off says Jina v5 beats the
hashing embedder, the margin means something.

## Hardware profiles

`--profile` selects the whole component set. The profile drives model choice,
quantisation, context length and the stage-3 call budget.

| Profile | VRAM | LLM | Embedder | Stage-3 budget |
| --- | --- | --- | --- | --- |
| `cpu_only` | 0 | offline responder | hashing 1024d | 0 (degrades, never skips) |
| `gpu_24gb` | 24 | Qwen3.8-27B AWQ-int4, 16K ctx | Jina v5 small | 400 calls/run |
| `gpu_80gb` | 80 | Qwen3.8-27B FP8, 64K ctx | Jina v5 + Qwen3-VL | 4,000 calls/run |
| `cluster` | 640 | Qwen3.8-27B BF16, 262K ctx | + A95B teacher, FSDP2 | 100,000 calls/run |

## Not yet built

Stated plainly so nobody mistakes scaffolding for a system:

- **Stage 4** — LightGBM/XGBoost/CatBoost out-of-fold stack, discrete-time
  hazard network, XGBoost AFT, open-set detection, calibration bake-off.
- **Stage 5** — Conformal Risk Control, limited-FP conformal sets,
  Alert/Watch/Monitor tiering, hashed prospective forecast ledger.
- **Bake-off harness** — Pareto frontier over (recall, −FAR, −latency, −VRAM, −cost).
- **GLiNER-Relex and Jina v5** are wired as adapters but have never been run
  against real checkpoints in this environment; only the offline backends have
  measured numbers behind them.

Until stage 5 exists, this system retrieves and explains evidence. It does not
yet produce a calibrated forecast, and no number here should be presented as one.

## Development

```bash
pytest tests -q          # 104 tests, ~75s
ruff check pramaan_x tests
```

CI runs lint, the test suite on 3.11 and 3.12, the retrieval benchmark as a
separate job, and a Docker build with an HTTP smoke test.
