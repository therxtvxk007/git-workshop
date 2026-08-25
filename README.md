# PRAMAAN-X Zero-Base — M0

A cutoff-safe, open-world future-event forecasting system. **This repository
currently contains milestone M0 only: the immutable temporal foundation.** It
does not forecast anything you should act on, and it makes no accuracy claim.

The scientific decomposition the full system is built around is:

```
candidate discovery -> candidate adjudication -> calibration -> risk-controlled alerting
```

M0 builds the first stage and the scaffolding every later stage depends on.
A model cannot score a future event that never entered the candidate pool, and
no accuracy claim survives contact with a leaky evidence ledger — so discovery
and point-in-time correctness come first, before anything that produces an
impressive number.

---

## What M0 contains

| # | M0 deliverable | Where |
| --- | --- | --- |
| 1 | Clean repository, config, CI, docs | `pyproject.toml`, `configs/`, `.github/workflows/ci.yaml` |
| 2 | Five core schemas | `src/pramaanx/schemas/` |
| 3 | Content-hashed Parquet storage | `src/pramaanx/hashing.py`, `src/pramaanx/storage.py` |
| 4 | `CutoffGuard` + snapshots + leakage audit | `src/pramaanx/timeguard/` |
| 5 | Synthetic and GDELT connectors | `src/pramaanx/ingest/connectors/` |
| 6 | Base-rate generator (G0) | `src/pramaanx/generators/base_rate.py` |
| 7 | Rolling-backtest skeleton | `src/pramaanx/evaluation/` |
| 8 | Future-leakage tests | `tests/leakage/`, `tests/metamorphic/` |
| 9 | Ruff, mypy, pytest, coverage floor, GitHub Actions | `Makefile`, `.github/workflows/ci.yaml` |
| 10 | Setup and architecture documentation | this file, `docs/` |

Acceptance criteria and the test that proves each one: **[docs/M0_ACCEPTANCE.md](docs/M0_ACCEPTANCE.md)**.

## What M0 deliberately does **not** contain

Absent, not stubbed. An empty module that returns plausible-looking output is
worse than a missing one, because it makes a skipped requirement look finished.

- **No adjudication.** No BLF-style belief state, tool loop, trials or logit
  aggregation.
- **No calibration.** Probabilities are raw generator output. Every forecast
  records `calibration: identity@uncalibrated` to keep this impossible to
  misread.
- **No risk control.** Statuses come from fixed thresholds recorded as
  `alert_policy: fixed_threshold@placeholder`. There is no conformal miss-rate
  guarantee, and the miss-versus-false-alert trade-off is a human decision that
  nobody has made yet.
- **No retrieval, graph, entity resolution or learned extraction.** Extraction
  is a deterministic mapping for sources that are already coded.
- **One generator.** G1–G7 (CRI rules, neural TKG, analogy, change-point,
  OpenForecaster, causal scenarios, open-set) are not built, so "candidate
  recall" here is a single-branch floor, not a union result.
- **No dashboard, API or containers.** Phase 10. A polished interface must not
  hide an unvalidated forecasting core.
- **No real-world accuracy claim.** The demo runs on a synthetic world with a
  machine-derived, unadjudicated outcome registry. Those numbers measure
  agreement with automated resolution, not with reality.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13. `requires-python` is
`>=3.13,<3.14`: the upper bound is deliberate, because the package does not
import on 3.14 with any currently published pydantic — see
**[docs/python_versions.md](docs/python_versions.md)**.

```bash
uv sync --frozen --extra dev           # install exactly what CI installs
make demo                              # bootstrap synthetic evidence + backtest
make check                             # ruff + mypy + pytest with a coverage floor
```

`make demo` runs offline from a fresh clone. No credentials, no network, no
licensed data. It ingests the synthetic world, builds a snapshot, screens for
leakage and runs the nine-fold backtest, printing a JSON manifest at each step.

### The commands

```bash
uv run pramaanx version                                   # what is registered and what is not
uv run pramaanx sources                                   # connectors and their licence terms
uv run pramaanx ingest --source synthetic --from 2025-01-01 --until 2026-04-01
uv run pramaanx snapshot build --cutoff 2026-01-15T00:00:00Z
uv run pramaanx snapshot list
uv run pramaanx extract --snapshot <snapshot-id>
uv run pramaanx outcomes build
uv run pramaanx candidates generate --snapshot <snapshot-id> --budget 500
uv run pramaanx audit leakage --cutoff 2026-01-15T00:00:00Z
uv run pramaanx backtest --experiment configs/experiments/e2e_v1.yaml
uv run pramaanx report --run-id <run-id>
```

Every command prints a canonical-JSON manifest to stdout and accepts `--output`
to write it to a file. Commands that *write* something also take `--dry-run`
(`ingest`, `snapshot build`, `extract`, `candidates generate`, `outcomes build`,
`backtest`); the read-only ones do not, because a no-op flag that pretends to do
something is worse than an absent one. `report` prints Markdown rather than a
manifest. Commands for unbuilt stages (`graph`, `adjudicate`, `calibrate`) do
not exist yet.

### Real evidence

```bash
uv run pramaanx ingest --source gdelt \
  --config configs/sources/gdelt_india_unrest.yaml \
  --from 2026-01-01T00:00:00Z --until 2026-01-01T06:00:00Z
```

GDELT needs no key. Other Tier-0 sources (ACLED, ReliefWeb, data.gov.in) require
accounts and licence review, which is why they are Phase 1 rather than M0 — see
`.env.example`. **No licensed data may be committed to this repository.**

Behind a proxy, the standard environment is honoured (`HTTPS_PROXY`,
`ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`), and every part of it is overridable
per source — `proxy`, `trust_env`, `ca_bundle`, `verify` — including SOCKS. A
policy denial (403/407) is reported immediately, naming the blocked host,
instead of being retried. To check egress end to end:

```bash
PRAMAANX_LIVE_GDELT=1 uv run pytest tests/network -m network -v
```

That test is opt-in and never runs in ordinary CI: a green build must mean the
code is correct, not that GDELT happened to be reachable.

## Architecture

```
connector  ->  bronze ledger  ->  CutoffGuard  ->  snapshot (hashed, immutable)
                                                        |
                                                        v
                                              structured extraction
                                                        |
                                                        v
                                       G0 base-rate / hazard generator
                                                        |
                                                        v
                                    forecast records  ->  immutable ledger
                                                        |
                                                        v
                                   outcome matcher  ->  metrics  ->  report
```

Later phases insert stages into this chain without changing what surrounds
them: generators register through `CandidateGenerator`, and adjudication,
calibration and risk control sit between the generator and the status field.

### The five contracts (`src/pramaanx/schemas/`)

`Observation` · `EventMention` · `EventHypothesis` · `ForecastRecord` ·
`OutcomeRecord`

Two rules hold across all of them: timestamps are timezone-aware UTC (naive
datetimes raise rather than being assumed), and schemas are versioned — a field
is never silently reinterpreted.

### Cutoff safety

The admission rule is one line:

```python
observation.first_observed_at <= cutoff_at
```

Everything else exists to catch records where that line passes but the record is
still untrustworthy: publication after the cutoff, timelines that cannot be
real, payload bytes that no longer match their recorded hash.

Three structural properties do the real work:

1. **Bronze is append-only and content-addressed.** A story edited after the
   cutoff cannot overwrite its earlier self; it becomes a *new* observation with
   a *later* `first_observed_at`, which the guard then excludes.
2. **`first_observed_at` is availability, not event time.** GDELT's `SQLDATE`
   would back-date every row; the connector uses the 15-minute export slot plus
   a conservative publication lag instead.
3. **Snapshot hashes are content-only.** Computed over sorted observation
   hashes, source versions, code hash and config hash — never over wall-clock
   time or file layout. This is what makes the leakage test meaningful:
   injecting correctly-dated future documents leaves an earlier cutoff's
   snapshot hash *byte-identical*.

What the automated audit cannot do: prove a run is leak-free. Memorisation,
prompt contamination and label bleed do not show up in a regex. Those need the
counterfactual and prospective tracks.

### Protected attributes

GDELT ships per-actor ethnic and religion code columns. This project forecasts
population-level and organisational events and must not use protected identity
as a risk proxy, so those columns are dropped **at ingestion**
(`EXCLUDED_COLUMNS` in `ingest/connectors/gdelt.py`) rather than filtered later.
Evidence that never enters bronze cannot become a feature by accident.

## What a human still has to do

Software completeness is not scientific completeness. M0 is largely
automatable; the following are not, and the code is written to surface them
rather than paper over them:

| Decision | Why code cannot close it |
| --- | --- |
| Whether an ambiguous event occurred | The registry is machine-derived; every record is `PENDING` until a human adjudicates. Reports state the unadjudicated fraction. |
| Whether two reports describe one event | Matcher tolerances are defaults to argue with. It must be validated against blinded dual-human labels before any headline number is believed. |
| Cost of a miss vs. a false alarm | Encoded in thresholds nobody has chosen. Hence `fixed_threshold@placeholder`. |
| Source licences and permitted use | Credentials and terms are institutional responsibility; `.env.example` names what is needed. |
| Whether a result means anything | Metrics can be computed; validity cannot. Every report leads with its interpretation limits. |

## Layout

```
configs/            base config, source overlays, experiment definitions
data/               bronze (raw + hashes) / silver (mentions) / gold (outcomes, forecasts)
docs/               acceptance criteria, architecture notes
research/           preregistration, experiment registry, benchmark cards
scripts/            bootstrap and operational entry points
src/pramaanx/       the package
tests/              unit / contracts / leakage / metamorphic / integration
```

`data/` contents are git-ignored: bronze is reproducible from connectors, and
licensed evidence must never be committed.

## Next milestone

Phase 1 — the point-in-time evidence ledger against real sources: ACLED,
ReliefWeb/HDX and data.gov.in connectors under their access terms, plus a
frozen English news corpus for leak-proof backtesting. Its gate is the same as
M0's: future-document injection must change no pre-cutoff snapshot, and every
record must carry provenance and a hash.

## Licence

Apache-2.0 for the code (`LICENSE`). Evidence acquired through the connectors
remains governed by each source's own terms. The licence choice is a
placeholder for the project sponsor to confirm.
