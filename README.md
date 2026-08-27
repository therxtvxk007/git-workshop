# PRAMAAN-X Zero-Base — M0 + Phase 1 evidence connectors

A cutoff-safe, open-world future-event forecasting system. **This branch
contains the immutable M0 temporal foundation plus the four Phase 1 evidence
connectors — GDELT, ReliefWeb, data.gov.in and ACLED — integrated onto one
shared ingestion surface.** It
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
| 5 | Synthetic, GDELT, and credentialed ACLED connectors | `src/pramaanx/ingest/connectors/` |
| 6 | Base-rate generator (G0) | `src/pramaanx/generators/base_rate.py` |
| 7 | Rolling-backtest skeleton | `src/pramaanx/evaluation/` |
| 8 | Future-leakage tests | `tests/leakage/`, `tests/metamorphic/` |
| 9 | Ruff, mypy, pytest, coverage floor, GitHub Actions | `Makefile`, `.github/workflows/ci.yaml` |
| 10 | Setup and architecture documentation | this file, `docs/` |

Acceptance criteria and the test that proves each one: **[docs/M0_ACCEPTANCE.md](docs/M0_ACCEPTANCE.md)**.

Phase 1C adds one strict data.gov.in resource connector. It is evidence
acquisition infrastructure, not a forecasting model or a real-data performance
result. See **[docs/M1C_ACCEPTANCE.md](docs/M1C_ACCEPTANCE.md)**.

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
- **ReliefWeb evidence is ingested but not extracted.** Phase 1A adds the
  connector; turning humanitarian prose into `EventMention`s needs the Phase 2
  extraction cascade, so `pramaanx extract` skips ReliefWeb observations and
  says so.
- **No dashboard, API or containers.** Phase 10. A polished interface must not
  hide an unvalidated forecasting core.
- **No real-world accuracy claim.** The demo runs on a synthetic world with a
  machine-derived, unadjudicated outcome registry. Those numbers measure
  agreement with automated resolution, not with reality.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13 or 3.14. CI runs the
full suite on both — see **[docs/python_versions.md](docs/python_versions.md)**.

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
# GDELT: machine-coded event records, no credential required.
uv run pramaanx ingest --source gdelt \
  --config configs/sources/gdelt_india_unrest.yaml \
  --from 2026-01-01T00:00:00Z --until 2026-01-01T06:00:00Z

# ReliefWeb: curated humanitarian reporting. No key, but every caller must
# identify itself with an appname ReliefWeb has APPROVED IN ADVANCE (mandatory
# since 2025-11-01 -- request one via https://apidoc.reliefweb.int/parameters).
export PRAMAANX_RELIEFWEB_APPNAME=your-approved-appname
uv run pramaanx ingest --source reliefweb \
  --config configs/sources/reliefweb_india.yaml \
  --from 2026-03-01 --until 2026-03-02 --dry-run   # plan first; makes no request
```

Neither needs an account, though ReliefWeb needs an approved appname. Its terms
restrict use to personal/non-commercial purposes and prohibit resale and
redistribution unless specific permission or a particular document's own terms
provide otherwise; the connector marks the source non-redistributable as a
conservative machine-enforced default, which is not a substitute for reading
the terms for your use. The remaining Tier-0 sources require registration and licence review —
see `.env.example`. **No licensed data may be committed to this repository.**

#### ReliefWeb caller identity

The `appname` is **mandatory**, it travels in the request URL, and since
**1 November 2025 it must be pre-approved by ReliefWeb**. It is not a string you
pick: request one through the process linked from
<https://apidoc.reliefweb.int/parameters>. An unapproved or misspelled name is
refused at the origin with an HTTP 403 — which this client reports as a
permanent error naming the appname, never as a blocked-egress skip.

Keep it in the environment. It is redacted from every persisted payload, every
log line, every exception message and from `--dry-run` output, and a contract
test fails if any tracked config commits one.

#### ReliefWeb availability semantics

ReliefWeb serves only the *current* revision of a report, with no
version-history endpoint. So a report's `first_observed_at` is
**`max(date.created, date.changed)`** — never `date.created` alone, and never
the document's own `date.original`. A report posted in 2020 and revised in 2026
enters a 2026 snapshot, because the body in hand is the 2026 body.

That is deliberately conservative: it withholds evidence from early cutoffs that
a contemporaneous reader might really have had, rather than risk attributing to
an early cutoff a sentence written later. `claimed_event_time` is left unset,
because report metadata carries publication dates and not the date of the
situation described.

All three raw instants survive into `metadata` under their own names —
`date_created`, `date_changed` (null when the API omits it, never back-filled)
and `date_original` — alongside the derived `date_availability`. `published_at`
is `date.original` when present, otherwise `date.created`. Details in
[docs/M1_ACCEPTANCE.md](docs/M1_ACCEPTANCE.md).

Acquisition queries the union of reports whose `date.created` **or**
`date.changed` intersects the window, then applies the exact derived maximum
client-side. A changed-only query would silently lose records whose modification
instant is absent or earlier than creation.

#### ReliefWeb pagination: overlap your windows

Paging walks `offset` under a total sort (`date.changed:asc`, then `id:asc`).
The total order stops records with identical timestamps reshuffling across a
page boundary. It does **not** stop an index that mutates mid-walk from omitting
a record entirely, and no client-side check can detect that — the response is
well-formed either way. Deduplication handles repeats, which are visible;
nothing handles drops, which are not.

So treat one pass as a sample, not a proof: re-ingest with overlapping windows.
Bronze is content-addressed and append-only, so re-ingesting is idempotent.
Detectable truncation is not treated as a sample: an unexpectedly empty page or
an exhausted `max_pages` bound raises and commits no partial bronze records.

#### data.gov.in: contextual evidence only

The data.gov.in profile is deliberately contextual only:

```bash
export PRAMAANX_DATA_GOV_IN_API_KEY='<user-issued-key>'
uv run pramaanx ingest --source data_gov_in \
  --config configs/sources/data_gov_in_extremism_context.yaml \
  --from 2026-02-13T00:00:00Z --until 2026-02-15T00:00:00Z --dry-run
```

Remove `--dry-run` only after reviewing the resource terms and running the
opt-in live contract test described in `docs/M1C_ACCEPTANCE.md`. The table is an
annual retrospective aggregate published in 2026 about 2023. It can support
context/base rates; it is not pre-incident evidence and is never back-dated to
2023.

#### ACLED caller identity and availability

ACLED programmatic access uses OAuth, not the retired email/API-key query
parameters. Create a myACLED account, accept the applicable terms, then inject
either a short-lived bearer token or the username/password used for ACLED's
documented OAuth password grant:

```bash
export PRAMAANX_ACLED_ACCESS_TOKEN='short-lived-token'
uv run pramaanx ingest --source acled \
  --config configs/sources/acled_india.yaml \
  --from 2026-01-01T00:00:00Z --until 2026-02-01T00:00:00Z
```

The connector uses cursor pagination, requires stable totals and query
restrictions, and writes nothing if a traversal is incomplete. ACLED's
``timestamp`` controls availability; ``event_date`` remains the claimed event
date. Because ACLED is a living dataset, a revised row receives the later
timestamp. Deep-history cutoffs are therefore conservative unless an external
versioned archive is available. Raw ACLED data are marked non-redistributable
by default; review the EULA, Content Usage Terms, and Attribution Policy for the
actual deployment.

Behind a proxy, the standard environment is honoured (`HTTPS_PROXY`,
`ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`), and every part of it is overridable
per source — `proxy`, `trust_env`, `ca_bundle`, `verify` — including SOCKS.
Egress failures are classified rather than lumped together: an HTTP 407, or a
CONNECT the proxy refuses, is a **policy denial** reported immediately and
naming the blocked host; an HTTP 401/403 *from the destination* is a
**permanent origin refusal**, because a request that was answered is not a
request that was blocked. Neither is retried. HTTP 429 is retried honouring the
server's own `Retry-After`, bounded by `max_retry_after_seconds` so a header of
86400 cannot park an ingest for a day. To check egress end to end:

```bash
PRAMAANX_LIVE_GDELT=1 uv run pytest tests/network -m network -v
PRAMAANX_LIVE_RELIEFWEB=1 PRAMAANX_RELIEFWEB_APPNAME=your-app \
  uv run pytest tests/network -m network -v
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

Configuration is strict throughout, including per-source options: an unknown
source name or a misspelled connector option (`publication_lag_minuts`) raises
when settings load, rather than being ignored in favour of a default nobody
chose.

## Next milestone

All four connectors are now integrated on one shared ingestion surface, so a
change to retry, redaction or cutoff handling applies to every source at once
rather than being fixed four times. Each connector keeps its own acceptance
document, and those documents do not currently agree on verification status:

| Source | Docs-verified | Fixture-tested | Live-verified |
| --- | --- | --- | --- |
| GDELT | yes | yes | opt-in, reachable |
| data.gov.in | yes (2026-08-26) | yes | **yes** (2026-08-27) |
| ReliefWeb | yes (2026-08-26) | yes | **no** |
| ACLED | yes | yes | **no** |

None of these connectors improves forecasting accuracy, and none claims to.
They add trustworthy bronze evidence sources. ReliefWeb is response-driven
humanitarian reporting, data.gov.in is retrospective administrative aggregate,
and ACLED is hand-coded after the fact — so by construction none of them alone
supplies the pre-event signal coverage a 26/11, Pahalgam or Kandahar
retrospective would need.

Still outstanding in Phase 1: a legally frozen English news corpus for
leak-proof backtesting. The gate stays the same as M0's: future-document
injection must change no pre-cutoff snapshot, and every admitted record must
carry provenance and a hash.

## Licence

Apache-2.0 for the code (`LICENSE`). Evidence acquired through the connectors
remains governed by each source's own terms. The licence choice is a
placeholder for the project sponsor to confirm.
