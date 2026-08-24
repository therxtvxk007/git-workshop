# PRAMAAN-X

**A precursor-evidence retrieval cascade. It does not forecast events.**

Stages 0–3 (dedup and validation, a cheap scan, a four-stage retrieval cascade,
an offline reasoning layer) are implemented. Stages 4 (risk models) and 5
(conformal risk control) are not implemented, so nothing here produces a
probability, a tier, a lead time or a calibrated forecast. Every retrieval
number below is a statement about finding documents for a target that was
**handed to the system**, and about nothing else.

If you are looking for what changed and why, start with
[The evaluation firewall](#the-evaluation-firewall).

```
stage 0  dedup and validate      implemented, in the served pipeline and the benchmark
stage 1  cheap high-recall scan  implemented, NOT wired into either
stage 2  four-stage retrieval    implemented, in the served pipeline and the benchmark
stage 3  offline reasoning       implemented, NOT wired into either
stage 4  risk models             not implemented
stage 5  conformal risk control  not implemented
```

## Quick start

```bash
uv sync --all-extras          # from uv.lock; reproducible
uv run pramaan profiles       # hardware profiles and what each selects
uv run pramaan bench          # oracle_target_retrieval, both methods
uv run pramaan serve          # API + analyst console on :8000
```

`pip install -e ".[boost,serve,llm,dev]"` also works, but resolves fresh
versions; `uv.lock` is the reproducible path.

## What the benchmark measures

The benchmark is called **`oracle_target_retrieval`** and the name is the
disclaimer:

> This benchmark assumes the target location and event type are already known.
> It measures precursor-evidence retrieval only and is **not** an
> event-forecasting evaluation.

A query is built as `"<location> <learned terms for event_type>"`. Both halves
come from the ground truth. The system is never asked *which* target will have
an event, or *when*, or *whether* — that is what stages 4 and 5 would do, and
they do not exist. Recall@K, Precision@K, nDCG@K and MRR from this benchmark
describe retrieval quality under an oracle target and **must not be reported as
forecasting performance**.

## The evaluation firewall

Six things were wrong with the previous evaluation. Each is now a mechanism
with a test that fails without it.

### 1. Information availability, not just publication date

```
available_at = max(published_at, retrieved_at)
```

A document is usable at forecast origin `T` only when `published_at < T` **and**
`retrieved_at < T`, both strictly. A document published on Monday and crawled on
Friday could not have informed a Wednesday forecast, however early it was
published.

A missing `retrieved_at` is **rejected**, never filled in. Substituting
`published_at` asserts zero crawl latency, which is the most optimistic possible
answer to the question being asked. The one exception is an explicit
`trusted_historical_snapshot` flag on the document — an operator assertion about
a licensed archive delivery, not an inference the code may make.

Timestamps are compared as instants in UTC. A naive timestamp has no instant and
is rejected rather than assumed.

`pramaan_x/eval/availability.py` · tests: `tests/test_availability.py`

### 2. Nothing is fitted on the future

At every forecast origin, BM25 corpus statistics, the hashing IDF table and the
vector index are built from the documents available strictly before that origin
and from nothing else. `SnapshotIndexProvider` caches one index per origin;
caching is a performance decision and cannot widen what an index sees, because
the cache key *is* the origin.

The learned fusion ranker (LambdaMART) is fitted only on training-window
queries, using candidates drawn from those same per-origin indexes.

### 3. Four executable invariants

| Invariant | What it checks | Legacy method |
| --- | --- | --- |
| `no_future_document_fitted` | every fitted index's recorded max availability precedes its own origin | **fails** |
| `no_test_labels_in_training` | no training query, label or origin comes from outside the training window | **fails** |
| `no_post_origin_results` | no returned document violates the availability rule at its query's origin | **fails** |
| future-append invariance | appending arbitrary post-origin documents leaves every earlier ranking byte-identical | **fails** |

The last one is the decisive test. `tests/test_retrieval.py` runs it both ways:
snapshot indexing is invariant, and the same test applied to full-corpus fitting
raises — so the test is proven to have teeth rather than merely passing.

`pramaan_x/eval/invariants.py`

### 4. A locked temporal protocol

```
|<-- train -->|<- embargo ->|<-- calibration -->|<- embargo ->|<-- TEST -->|
```

One object (`TemporalProtocol`) fixes the training window, the calibration
window, the embargo, the locked test window, the forecast-origin grid, the
availability rule, the query-generation rule and the list of permitted fitting
operations. It is fingerprinted and recorded in every artefact.

The embargo is `max(embargo_days, label_lookahead_days)`, because an embargo
narrower than the forward lookahead used to build labels does not separate the
windows whatever it is called. Splits are temporal and contiguous;
`tests/test_protocol.py` asserts the module contains no shuffling or
random-split helper at all.

The test window selects nothing — no threshold, no ranker parameter, no
retrieval width, no vocabulary, no model variant, no operating point. The
calibration window exists for that.

### 5. Machine-verifiable artefacts

Every run writes JSON under `benchmark_results/<method>/seed-<n>/<digest>.json`,
carrying the git commit, the dirty-worktree flag and file list, the dataset's
logical hash *and* file hash, the config fingerprint, the protocol and its
fingerprint, the temporal windows, the forecast origins, query and
relevant-document counts, availability violations by reason, the concrete
backend identities, Recall@K, Precision@K, nDCG@K, MRR, latency and the seed.

The path is a deterministic function of what the run *means*, so re-running the
same protocol on the same commit overwrites the same file rather than
accumulating near-identical results to choose between. Nothing in that directory
is typed by hand.

### 6. `contaminated_legacy_diagnostic`, kept and measured

The old method still runs, under a name that says what it is. It is the only way
to quantify the contamination rather than assert it. Its artefacts record its
failed invariants; nothing in this repository reports its numbers as a result.

## Results

Three seeds (11, 29, 20260824), one 540-day synthetic corpus per seed,
identical protocol on both arms. Stop point: the full cascade (`rerank`).
`mean ± sd` is over seeds, n=3 — a spread from three runs is itself noisy, so
read it as a spread and not as a confidence interval.

| Metric | `contaminated_legacy_diagnostic` | `strict_temporal` | Δ |
| --- | --- | --- | --- |
| recall@10 | 0.532 ± 0.090 | 0.643 ± 0.070 | +0.111 |
| recall@20 | 0.623 ± 0.115 | 0.719 ± 0.068 | +0.095 |
| recall@50 | 0.725 ± 0.063 | 0.759 ± 0.039 | +0.034 |
| recall@100 | 0.753 ± 0.039 | 0.768 ± 0.034 | +0.016 |
| precision@10 | 0.199 ± 0.031 | 0.189 ± 0.015 | -0.009 |
| ndcg@10 | 0.503 ± 0.058 | 0.556 ± 0.053 | +0.053 |
| mrr | 0.677 ± 0.033 | 0.667 ± 0.042 | -0.010 |

Per seed:

| Seed | Method | R@10 | R@100 | P@10 | nDCG@10 | MRR | Availability violations | Invariants | Artefact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 11 | `contaminated_legacy_diagnostic` | 0.618 | 0.795 | 0.233 | 0.562 | 0.714 | 3060 | 3/4 fail | [`6071779e665a.json`](benchmark_results/contaminated_legacy_diagnostic/seed-11/6071779e665a.json) |
| 11 | `strict_temporal` | 0.696 | 0.805 | 0.205 | 0.609 | 0.716 | 0 | all pass | [`d83b002f2851.json`](benchmark_results/strict_temporal/seed-11/d83b002f2851.json) |
| 29 | `contaminated_legacy_diagnostic` | 0.539 | 0.746 | 0.192 | 0.499 | 0.668 | 4585 | 3/4 fail | [`e86618444a91.json`](benchmark_results/contaminated_legacy_diagnostic/seed-29/e86618444a91.json) |
| 29 | `strict_temporal` | 0.669 | 0.760 | 0.187 | 0.555 | 0.646 | 0 | all pass | [`1b812b9047e1.json`](benchmark_results/strict_temporal/seed-29/1b812b9047e1.json) |
| 20260824 | `contaminated_legacy_diagnostic` | 0.439 | 0.717 | 0.171 | 0.447 | 0.649 | 3748 | 3/4 fail | [`0b6df94e70cd.json`](benchmark_results/contaminated_legacy_diagnostic/seed-20260824/0b6df94e70cd.json) |
| 20260824 | `strict_temporal` | 0.564 | 0.739 | 0.176 | 0.503 | 0.639 | 0 | all pass | [`735d890586b2.json`](benchmark_results/strict_temporal/seed-20260824/735d890586b2.json) |

**Run shape** (seed 11): 22 locked forecast origins; 80 test / 101 training queries strict, 80/101 legacy. Strict builds 59 snapshot indexes over 89–8644 documents (mean 4123); legacy fits one index over all 9086 documents at every origin.

**Latency**, strict method, per query at the full stop point: mean 33.2 ms, p50 32.6 ms, p95 37.3 ms.

### Reading the difference

**The strict method scores higher, and that is not good news.** Recall@10 is
+0.111 and nDCG@10 is +0.053 under the firewall; Precision@10 and MRR are within
seed-to-seed noise of each other. The temptation is to report this as "the
firewall cost nothing". It is not what happened.

The most likely cause is in the run-shape line above: a snapshot index holds
between 89 and 8,644 documents depending on how far into the test window its
origin falls, a mean of 4,123, while the legacy index holds all 9,086 at every
origin. Half as many documents means half as many distractors competing for the
top-k slots, and Recall@10 goes up for a reason that has nothing to do with
retrieval quality.

That is the finding, stated plainly: **contamination did not make the old
numbers optimistic, it made them a measurement of something else.** A leak is
not a thumb on the scale in a known direction; it changes what is being
measured, and the sign of the change is not predictable in advance. Anyone
expecting a leakage fix to reveal a smaller number should not read this table as
reassurance — the two columns are not two estimates of one quantity.

Three things differ between the arms at once (index scope, availability rule,
and origin placement), so this comparison establishes what the old numbers were
worth without decomposing why. Isolating the three would need a third arm and is
out of scope here.

**Nothing on the strict side was tuned against these results.** The protocol
fractions, the origin stride, the embargo, the cascade widths and the ranker
hyper-parameters were fixed before the run and are unchanged since. The test
window selected nothing.

## Implementation status

Four states, applied honestly. "Integrated and measured" means it runs in the
served pipeline or the benchmark **and** a test or artefact records what it
does.

| Component | State | Evidence |
| --- | --- | --- |
| Stage 0 dedup / clean / timestamp validation | integrated and measured | `tests/test_dedup.py`, `/status` |
| BM25 sparse index | integrated and measured | benchmark artefacts |
| Hashing embedder + exact `MemoryEngine` vector search | integrated and measured | benchmark artefacts |
| Late interaction (MaxSim over hashed tokens) | integrated and measured | benchmark artefacts |
| Lexical reranker | integrated and measured | benchmark artefacts |
| RRF + LambdaMART learned fusion | integrated and measured | benchmark artefacts |
| Learned lexicon (log-odds) | integrated and measured | query generation in every run |
| Availability rule, temporal protocol, invariants, artefacts | integrated and measured | `tests/test_availability.py`, `test_protocol.py`, `test_retrieval.py`, `test_artefact.py` |
| `DocumentStore` (Polars/Parquet/DuckDB) | integrated and measured | `tests/test_store.py` |
| Local experiment tracking | integrated and measured | driven by `pramaan bench`; `tests/test_logging_tracking.py` |
| Stage 1 scan: CUSUM, BOCPD, relevance model, rule extractor, `Stage1Router` | implemented but disconnected | unit-tested; **nothing imports the router** |
| Stage 2 temporal graph, ITHI, LANTERN, MTRM | implemented but disconnected | importable; not reachable from the API, CLI or benchmark |
| Stage 3 offline responder, Pydantic output contracts | implemented but disconnected | `tests/test_llm_integration.py`; not reachable from the service |
| Content-hash manifests and pointers | implemented but disconnected | `tests/test_store.py`; the benchmark hashes datasets directly |
| Jina v5 / Qwen3-VL embedders, Jina reranker | adapter only, never run | no checkpoint has been downloaded in this environment |
| GLiNER-Relex extractor | adapter only, never run | same |
| Qdrant, Vespa engines | adapter only, never run | no server has been started |
| Kùzu, Neo4j graph backends | adapter only, never run | same |
| MLflow tracker | adapter only, never run | falls back to the local store; only the fallback is tested |
| vLLM / SGLang / OpenAI-compatible LLM providers | adapter only, never run | only the offline stub has been executed |
| Stage 4 risk models | not implemented | `pramaan_x/stage4_risk/__init__.py` is empty |
| Stage 5 conformal risk control | not implemented | `pramaan_x/stage5_control/__init__.py` is empty |
| Bake-off harness | not implemented | — |

Everything above operates on a **synthetic** corpus generated by
`pramaan_x/data/synth.py`. No component in this repository has been run against
real-world data, and no number here is evidence about real-world reporting.

## Claims withdrawn

These appeared in earlier documentation and code comments as measurements. No
script produces them, no artefact records them and no test fails if they are
wrong, so they have been removed rather than restated.

| Withdrawn claim | Where it was | Why |
| --- | --- | --- |
| "Stage-1 precursor recall 100% at 39% retention", from a "36-point grid" | README, `Stage1Config` | The sweep does not exist in this repository. Stage 1 is not wired into anything that could measure it. |
| "CUSUM operating point: ARL₀ 410 days, 2.7-day detection delay", "120 replications each" | `burst.cusum` docstring | No such experiment exists. The default `h=5.0` is a conventional SPC choice, uncharacterised on this corpus. |
| "Every number below came from a run in this repository and is guarded by a test" | README | It was not true of the two rows above, and the retrieval rows came from a contaminated evaluation. |
| "R@10 0.535 · nDCG@10 0.527 · MRR 0.751" as retrieval performance | README, `tests/test_retrieval.py` docstring | Produced by full-corpus fitting with publication-only cutoffs. Superseded by the table above. |
| ITHI / LANTERN / MTRM / temporal graph / Qdrant / MLflow / the LLM "in the current service" | README layout section | None of them is reachable from the API, CLI or benchmark. See the status table. |
| "1.0.0" and "Compute-cascade event forecasting with conformal risk control" | `pyproject.toml`, API metadata, Docker tag | The forecasting stages are absent. The version is now `0.4.0` and the description says what runs. |
| `artifacts/corpus.parquet.dvc` with an `md5:` field | tracked file | The value was the first 32 hex characters of a SHA-256 over the frame's *logical* content: not an MD5, not the bytes DVC hashes, not resolvable by `dvc checkout`. Deleted; see below. |

## Reproducibility

* **`.gitignore`** exists. `__pycache__`, `*.pyc`, generated `artifacts/` and the
  virtualenv are no longer tracked. `benchmark_results/` **is** tracked: a claim
  whose artefact is not in the repository is an assertion.
* **`uv.lock`** is a real lockfile (147 packages, hashes). CI has a
  `clean-install` job that builds from it alone and runs the suite.
* **DVC is not configured** and nothing pretends it is. `write_dvc_stub` has been
  replaced by `write_content_pointer`, which writes `<file>.pointer.json` with
  `file_sha256` (bytes on disk) and `logical_sha256` (order-independent digest of
  the rows), each labelled with the algorithm that produced it. No `.dvc` file is
  written anywhere; `tests/test_store.py` asserts that.
* **Experiment tracking is connected** to `pramaan bench` — parameters, metrics
  and the artefact path per run. `tests/test_logging_tracking.py` runs the real
  command and reads the run back out.
* **Localhost HTTP tests bypass an inherited proxy** additively: the
  `loopback_direct` fixture prepends the loopback hosts to `no_proxy` and leaves
  `HTTP_PROXY` in place for everything else. No TLS verification is disabled.
  `tests/test_localhost_http.py` proves it against a dead proxy, with a negative
  control showing the unguarded case fails. CI's Docker smoke test uses
  `curl --noproxy '*'`.

## Claim to evidence

Every claim this repository makes, the command that checks it, and what the
check produces. Nothing in this table is asserted without a way to falsify it.

| Claim | Command | Artefact | Status |
| --- | --- | --- | --- |
| The availability rule is `max(published_at, retrieved_at)` with strict inequality, and missing acquisition time is rejected | `pytest tests/test_availability.py -q` | — | 19 tests, incl. published-before/retrieved-after, exactly-at-T, timezone conversion, missing time, republished and late-crawled updates |
| Splits are temporal, the embargo covers the label lookahead, and the test window selects nothing | `pytest tests/test_protocol.py -q` | — | 18 tests, incl. a source check that the module contains no random-split helper |
| No fitted index saw a document from its own future | `pytest tests/test_retrieval.py -q` | `benchmark_results/strict_temporal/**` (`invariants`) | passes strict; the same assertion raises on the legacy arm |
| No test label reached ranker training or preprocessing | `pytest tests/test_retrieval.py -q` | artefact `invariants.no_test_labels_in_{training,preprocessing}` | passes strict, with negative controls that fire on poisoned inputs |
| No post-origin document is returned | `pytest tests/test_retrieval.py -q` | artefact `availability_violations.total` | 0 strict; 3,060–4,585 legacy |
| Appending arbitrary future documents leaves earlier rankings identical | `pytest tests/test_retrieval.py -q` | — | passes under snapshot indexing; the same test raises under full-corpus fitting |
| Results do not depend on `PYTHONHASHSEED` or thread count | `pytest tests/test_artefact.py -q` | — | two subprocesses, different hash seeds and thread counts, identical metrics |
| Every artefact carries commit, hashes, windows, origins, counts, backends and metrics | `pytest tests/test_artefact.py -q` | `benchmark_results/**/*.json` | 19 tests |
| The README's numbers come from committed artefacts and the status table matches the code | `pytest tests/test_documentation.py -q` | — | 18 tests, incl. verifying `stage4_risk` and `stage5_control` are empty |
| Localhost HTTP bypasses an inherited proxy without weakening it | `pytest tests/test_localhost_http.py -q` | — | 5 tests against a dead proxy, with a negative control |
| Tracking is connected to the benchmark, not an unused adapter | `pytest tests/test_logging_tracking.py -q` | `artifacts/runs/<run>/events.jsonl` | runs the real `bench` command and reads the run back |
| No `.dvc` file claims a hash it does not hold | `pytest tests/test_store.py -q` | `<file>.pointer.json` | pointer names `file_sha256` and `logical_sha256`; no `.dvc` is written |
| The legacy-vs-strict comparison | `pramaan bench --days 540 --seeds 20260824,11,29` | `benchmark_results/` + `summary.json` | see [Results](#results) |

## Layout

```
pramaan_x/
  config.py            hardware profiles; every component named here
  types.py             Document, EventTuple, Target, Candidate, Forecast, Tier
  data/
    synth.py           synthetic corpus with ground truth and deliberate failure
                       modes, including acquisition lag and missing crawl times
    store.py           Polars + Parquet + DuckDB; available_at() is the backtest
                       read path, as_of() is publication-only and says so
    versioning.py      content-hash manifests and pointers (NOT DVC)
  eval/                availability rule, temporal protocol, oracle-target
                       benchmark, invariants, run artefacts, harness, metrics
  stage0_ingest/       exact + MinHash + SimHash dedup, cleaning, timestamps
  stage1_scan/         BM25, embedders, learned lexicon, extractors, relevance,
                       CUSUM + BOCPD, the union router  [router disconnected]
  stage2_retrieve/     cascade, engines, late interaction, RRF + LambdaMART,
                       rerankers  [graph, ITHI, LANTERN, MTRM disconnected]
  stage3_reason/       LLM client and output contracts  [disconnected]
  stage4_risk/         empty
  stage5_control/      empty
  service.py api.py cli.py tracking.py static/
benchmark_results/     generated run artefacts; the evidence for the results table
```

## Design decisions worth knowing

**Stage 1 takes the union of detectors, never the intersection.** Intersecting
makes a filter look precise while destroying the recall everything downstream
depends on. (Stage 1 is not currently wired into anything — see the status
table.)

**Source independence counts syndication families, not source ids.** Thirty
copies of one wire story must not read as thirty corroborating sources.

**The offline backends are real, not mocks.** Feature hashing, in-process BM25,
exact numpy vector search and the rule extractor are weak but genuine methods.
That is what makes them a usable floor. It also means the benchmark numbers are
a floor and not a ceiling: a stronger embedder would move them, and nobody here
has measured by how much.

**Evaluating on an origin grid is conservative on purpose.** A query at event
time `T` is evaluated at the last grid origin `O ≤ T`, so documents in `(O, T]`
are excluded from the index *and* from the relevant set alike. Recall is
measured against what was retrievable at `O`, never against a ground truth the
retriever could not have seen.

## Development

```bash
uv run pytest tests -q
uv run ruff check pramaan_x tests
uv run pramaan bench --days 540 --seeds 20260824,11,29
```

`ruff format --check` is enforced in CI on the paths this work formatted (the
`eval/` modules and the test files it rewrote). The rest of the tree predates
the formatter, is hand-wrapped, and was left alone: reformatting it would be a
large diff through modules nothing here changed.

CI runs lint, the format gate, the suite on 3.11 and 3.12, a clean install from
`uv.lock`, the benchmark with an assertion that the strict artefacts passed
every invariant, and a Docker build with an HTTP smoke test.

## Limitations

Stated so nobody has to discover them.

**The corpus is synthetic.** Every number in this repository was produced by
`pramaan_x/data/synth.py`. Nothing here has been run against real reporting, and
no result is evidence about how the cascade would behave on it. The generator's
failure modes (syndication, unforecastable events, post-event reporting,
acquisition lag, missing crawl times) are the ones we thought to build in, which
is not the same as the ones that exist.

**The benchmark is oracle-target.** The location and event type are given. This
is a real evaluation of a real subproblem, and it is not forecasting. There is
no evaluation in this repository of target selection, timing or probability,
because there is no code for any of them.

**The two arms differ in three ways at once**, so the gap between them is not a
single effect: the legacy arm fits on the whole corpus, uses a publication-only
availability rule, and places each query at its own event time rather than on
the origin grid. The comparison shows what the old method's numbers were worth;
it does not decompose *why*. Isolating the three would need a third arm, which
is out of scope for this phase.

**Contamination did not inflate this metric.** The strict arm scores higher on
Recall@K and nDCG@10 and is within noise on MRR and Precision@10. The likeliest
reason is index size: a snapshot index is a prefix of the corpus and therefore
has fewer distractors competing for the top-k slots than the full-corpus index
does. That is the point rather than a consolation — contamination does not make
a metric reliably optimistic, it makes it a measurement of something else. Do
not read the strict numbers as "the honest version of the old numbers".

**Three seeds is three seeds.** The standard deviations quoted are computed from
n=3 and are themselves noisy. Seed-to-seed spread on Recall@10 is larger than
most of the differences anyone would want to draw conclusions from.

**Only the offline backends have been executed.** Hashing embeddings, in-process
BM25, exact numpy vector search and a lexical reranker. These are genuine
methods and a legitimate floor, but they are a floor: no Jina, Qwen, Qdrant,
Neo4j or MLflow component has ever run here, so nothing is known about what a
stronger backend would change.

**Stage 1 and stage 3 are not in the measured path.** They are implemented and
unit-tested and nothing routes through them. Their configuration defaults are
therefore unmeasured, including the CUSUM operating point.

**Latency is measured in this container**, single process, CPU only, on a corpus
of roughly ten thousand documents. It is not a service-level number.

**The origin grid is 7 days.** A query is evaluated at the last grid origin at
or before its event, so the retriever is up to a week further from the event
than it needs to be. This is conservative in a known direction and it is a
protocol parameter, not a measurement.

**`ruff format` is enforced only on the paths this work formatted.** The rest of
the tree predates the formatter and is hand-wrapped. Reformatting it would be a
large diff through modules this phase did not otherwise touch.

**The Docker smoke test has not been run here.** The Docker CLI is present in
this container but no daemon is reachable, so the image has never been built or
started in this environment. The CI job that does it is defined and unverified.

**Stages 4 and 5 do not exist.** Not stubbed, not scaffolded, not planned in
code — empty packages. Until they exist, this system retrieves evidence and
explains it, and produces no forecast of any kind.
