# Phase 1A acceptance: the ReliefWeb evidence connector

Phase 1A adds one real Tier-0 source to the point-in-time ledger, preserving
every M0 guarantee: availability-based admission, append-only content-addressed
bronze, strict configuration, and the future-injection gate.

Run everything: `make check` — ruff, mypy, and 469 offline tests behind an
enforced coverage floor.

| Suite | Tests | Phase 1A additions |
| --- | ---: | --- |
| `tests/unit` | 278 | Connector logic, temporal fidelity, envelope strictness, item-id contract, query semantics, plan redaction, HTTP classification and retry bounds |
| `tests/contracts` | 92 | `ReliefWebSourceConfig` strictness, single-sourced API version, retry ceiling |
| `tests/leakage` | 24 | (unchanged; M0 guarantees) |
| `tests/metamorphic` | 8 | (unchanged; M0 guarantees) |
| `tests/integration` | 67 | Dry-run purity, ledger provenance, cutoff safety, CLI surface |
| `tests/network` | 7 | Opt-in live verification (6 ReliefWeb, 1 GDELT) |

---

## Read this first: three statuses, and they are not the same thing

This distinction matters more than any test count above. Collapsing any two of
these is how a verification claim becomes a false one.

| Status | Value | What it rests on |
| --- | --- | --- |
| **Verified against current official documentation** | **YES** — 2026-08-26 | The v2 contract below was read from ReliefWeb's official documentation by external review on that date. The exact pages are listed under "Official documentation consulted". |
| **Fixture / integration tested** | **YES** | Hand-written synthetic records drive `tests/unit` and `tests/integration` through the real ingest path, ledger and snapshot builder. This proves the connector's *logic*. It is not evidence about the wire format. |
| **Genuinely live API verified** | **NO** | No response from `api.reliefweb.int` has ever been fetched or parsed in this environment. Its egress policy answers `403` to `CONNECT api.reliefweb.int:443`. |

Machine-readable, in `API_CONTRACT` (`src/pramaanx/ingest/connectors/reliefweb.py`):

```python
"official_docs_verified": True,
"official_docs_verified_on": "2026-08-26",
"fixture_tested": True,
"live_api_verified": False,
```

**Fixture tests do not replace a live request.** They can only show that the
connector handles a shape someone wrote down; they cannot show ReliefWeb sends
it.

**None of these is a live verification:** a skipped test, an established TLS
tunnel, an HTTP 403, a successfully constructed URL, or an empty response.
`tests/network/test_reliefweb_live.py` now *fails* on an origin 403 rather than
skipping — see §6 — and nothing in the repository flips `live_api_verified`
automatically. That is a deliberate human edit after reading a passing run.

---

## 1. The v2 contract, from one constant

The official list endpoint is `https://api.reliefweb.int/v2/reports`. Every
version-bearing string is derived from a single definition,
`RELIEFWEB_API_VERSION` in `src/pramaanx/config.py`:

| Where | Value |
| --- | --- |
| `ReliefWebSourceConfig.base_url` | `https://api.reliefweb.int/v2` |
| `configs/base.yaml` | `https://api.reliefweb.int/v2` |
| payload `api_version` | `v2` |
| `RawItem.source_version` / `SourceRecord.source_version` | `reliefweb-v2-reports` |

**Accepted when** — `TestApiVersionIsSingleSourced`: the URL, payload and both
source-version strings agree; `API_VERSION is RELIEFWEB_API_VERSION` (an alias,
not a second literal); and a tree scan proves no `reliefweb-v1-` or
`api.reliefweb.int/v1` literal survives in `src/` or `configs/`.

## 2. Caller identity: mandatory and pre-approved

The `appname` is required, travels in the request URL, and since **1 November
2025 must be approved by ReliefWeb in advance**. It is not a name an operator
chooses. `.env.example`, `README.md`, `configs/base.yaml` and the connector's
own error message all say so and point at
<https://apidoc.reliefweb.int/parameters>.

No appname is committed anywhere: `.env.example` ships the key empty, and a
contract test fails if any tracked config sets `sources.reliefweb.appname`.

Whether a given name is *approved* is knowable only to ReliefWeb — an
unapproved name is well-formed locally and refused at the origin with an HTTP
403. That is why §6's classification change matters.

## 3. Temporal fidelity: nothing is substituted

| Instant | Source | Where it goes |
| --- | --- | --- |
| Created | raw `date.created` | `metadata.date_created` |
| Changed | raw `date.changed`, or **null** | `metadata.date_changed` |
| Original | raw `date.original`, or **null** | `metadata.date_original` |
| Availability | `max(created, changed)`, else `created` | `first_observed_at`, `metadata.date_availability` |
| Publication | `date.original` if present, else `date.created` | `published_at` |
| Retrieval | the ledger's clock | `retrieved_at`, never used for admission |
| Claimed event time | — | **left unset** |

Three corrections against the previous implementation:

- `published_at` is `date.original` when present, **not** `min(original,
  created)`. The two agree only while `original` is the earlier of the pair;
  where it is not, the old code published ReliefWeb's posting date instead of
  the document's own.
- `metadata.date_changed` carries the **raw** `date.changed`, or null. It used
  to carry the computed availability, so a record the API never said was
  modified looked as though it had been.
- `revised_after_creation` (renamed from `revised_after_publication`) is
  `changed > created`, and `False` when `changed` is absent. The absence of a
  modification timestamp is not evidence of a modification.

An `original` that postdates availability raises `ReliefWebContractError` naming
the report. Clamping `published_at` down would rewrite what the record says
about itself; raising availability would import the document's own date into the
field admission depends on. Both are worse than failing.

**Why the maximum.** The API serves only the current revision; there is no
version-history endpoint. The body in hand is the revised body, so the earliest
moment this project can honestly claim to have had *this text* is when it was
last revised. A report created in 2020 and edited in 2026 enters a 2026
snapshot. That withholds evidence from early cutoffs a contemporaneous reader
might really have had, rather than risk attributing to an early cutoff a
sentence written later.

**Accepted when** — `TestTemporalFidelity` and `TestAvailabilityRule` cover
`original` earlier than `created`; `original` later than `created` but before
availability; `original` postdating availability (raises); `changed` absent;
`changed` earlier than `created`; and all three instants written in different
timezone offsets. Plus the M0 gate tests in `TestCutoffSafety`.

## 4. The envelope is strict

The official successful list response carries `totalCount`, `count` and `data`.
All three are now required, and this fallback is gone:

```python
document.get("totalCount", document.get("count", len(data)))   # removed
```

It was the most dangerous line in the connector. The pagination loop terminates
on `offset >= total`, so an envelope missing `totalCount` reported the first
page's size as the total, stopped after one page, and wrote a truncated window
into an append-only ledger with no error anywhere.

`parse_envelope` now requires: `totalCount` and `count` both present,
non-negative integers, and **not** `bool` (which is an `int` subclass in Python
and would otherwise sail through `isinstance`); `count == len(data)`;
`totalCount >= count`; and every item in `data` a JSON object.

**Accepted when** — `TestEnvelopeStrictness` covers `totalCount` absent with
`count` present, both absent, `count` absent, boolean totals, negative totals,
non-integer totals, count/data disagreement, `totalCount` below `count`, and a
non-object item — plus a regression proving the walk aborts on the first bad
page instead of continuing.

## 5. The item contract and the query

**Items.** A top-level integer `id` is required, with no fallback to
`fields.id`. When `fields.id` is present it must be an integer and must equal
the top-level id. Fixtures model ids as integers, as the official fields table
specifies.

**Query.** Both operators are stated, never left to a default:

- `filter[operator]=AND` — always emitted, even when the date condition stands
  alone, so adding a filter later cannot change the query's meaning;
- `filter[conditions][N][operator]=OR` — whenever a condition carries several
  values. "Any of these countries" is a union; an implicit AND would ask for a
  report filed under every listed country at once and quietly return nothing.

Date ranges use `value[from]` / `value[to]`. The API's bounds are inclusive
while a `FetchWindow` is half-open, so the window is re-applied client-side.
Sort is the total order `date.changed:asc`, `id:asc` — both documented sort
keys. `limit` is bounded by the config at 1–1000. `profile=list` supplies the
list profile's own fields and `fields[include][]` adds the rest, every one of
them confirmed in the official fields table.

**Accepted when** — `TestFilterQuerySemantics` asserts on `parse_qs` output, not
substrings. A substring check passes on malformed nesting; an exact parse does
not.

## 6. Egress failures are classified, not lumped together

`HttpClient` used to raise `ProxyPolicyError` for every 403. That was unsafe the
moment appnames became approval-gated:

- an unapproved appname causes an **origin** 403;
- the live test skips on `ProxyPolicyError`;
- so invalid API access was reported as blocked egress and never failed
  verification.

Now:

| Condition | Class | Retried |
| --- | --- | --- |
| HTTP 407 response | `ProxyPolicyError` | no |
| CONNECT-time `httpx.ProxyError` with a denial marker | `ProxyPolicyError` | no |
| HTTP 401 / 403 response from the destination | `PermanentHttpError` | no |

The 403 message names the appname and its approval requirement. The live test
fails on an origin 403 and skips **only** on a genuine proxy/CONNECT denial.

**Accepted when** — `TestOriginRefusalIsNotAProxyDenial` proves all three cases
are distinguishable by type and that a permanent refusal is not retried. GDELT's
behaviour is unchanged.

## 7. Redaction and bounded retries

**Redaction.** The request URL contains the appname, so `redact_url` /
`redact_proxy` in `pramaanx.ingest.http` are the single display path for every
log line, exception message and persisted payload. They redact sensitive query
values and URL/proxy userinfo, and they never touch the URL actually requested
or the string the cache is keyed on — redacting those would break the request or
make two callers collide in one cache entry.

**Accepted when** — `TestRedaction` covers retry logs, rate-limit logs,
`RateLimitError`, `PermanentHttpError`, `NotFoundError`, `ProxyPolicyError`, the
final `HttpFetchError`, configured-proxy logging, that the real request URL is
unaltered, and that two appnames still get distinct cache entries.

**Retries.** `max_retry_after_seconds` (default 60, configurable per source)
clamps both the delta-seconds and HTTP-date forms of `Retry-After` *and* the
exponential fallback. A header of 86400 cannot park an ingest for a day inside a
retry loop nobody is watching.

**Accepted when** — `TestRetryAfterIsBounded` covers an ordinary header honoured,
an excessive one capped (both forms), negative/past values becoming zero,
malformed values falling back to bounded backoff, non-finite values capped, and
a persistent 429 still raising `RateLimitError`. No test sleeps for real: the
loop is exercised with a stubbed clock.

## 8. Pagination: what the total sort does and does not buy

The total order (`date.changed:asc`, then `id:asc`) stops records with identical
timestamps reshuffling across a page boundary. It does **not** stop an index
that mutates mid-walk from omitting a record entirely, and no client-side check
can detect that — the response is well-formed either way. Deduplication handles
repeats, which are visible; nothing handles drops, which are not.

No keyset-filter syntax has been invented to work around this. The limitation is
documented instead, in the connector docstring, `SourceRecord.notes`, the README
and `API_CONTRACT["pagination"]["residual_limitation"]`, together with the
operational answer: **overlapping ingestion windows**, which are cheap because
bronze is content-addressed and re-ingesting is idempotent.

**Accepted when** — `TestPaginationLimitationIsStated` pins the admission in the
source record a modeller will actually read.

## 9. `--dry-run` purity

The planner is handed a fetcher that raises on any call, and no request is made;
no bronze directory is created; and a missing appname fails *during* the dry run
rather than on the first real request.

The plan no longer emits the appname. It emits `appname_configured`,
`appname_source` (`config` or the environment variable name), and the constant
marker `<redacted>`. The identity is still resolved, so a missing one still
fails the dry run.

**Accepted when** — `TestPlanWithholdsTheCallerIdentity` serialises the entire
plan to JSON and proves the appname appears nowhere in it, for both the
environment and config paths; the CLI integration test does the same against
`--dry-run` stdout.

## 10. Licence and terms

`redistributable=False` stays, as a conservative machine-enforced default.

The recorded licence text describes the terms without over-reading them: use is
subject to personal/non-commercial and no-resale/no-redistribution limitations
**unless specific permission or material-specific terms provide otherwise**, with
attribution to the contributing organisation. Which of those applies to a given
use is a question for a human, and the connector says so rather than converting
an engineering default into a legal conclusion.

Fixtures are hand-written and synthetic; no real ReliefWeb corpus is committed.
`data/` remains git-ignored.

## 11. M0 remains intact

The M0 acceptance gate (`tests/leakage`, `tests/metamorphic`,
`tests/contracts`, then `make demo`) is unchanged and still passes. `make demo`
does not touch ReliefWeb: it runs on the synthetic world, offline.

---

## Official documentation consulted

Accessed **2026-08-26** by external review:

- <https://apidoc.reliefweb.int/endpoints>
- <https://apidoc.reliefweb.int/parameters>
- <https://apidoc.reliefweb.int/result-structure>
- <https://apidoc.reliefweb.int/fields-tables>
- <https://apidoc.reliefweb.int/faq>
- <https://reliefweb.int/terms-conditions>

Recorded in `API_CONTRACT["official_docs"]` and pinned by a test.

## What Phase 1A does not do

- **It does not improve forecasting accuracy, and does not claim to.** It
  creates one trustworthy bronze evidence source. Nothing more follows from it.
- **ReliefWeb alone cannot support the intended retrospectives.** It is
  *response-driven* humanitarian reporting: coverage follows operational
  response, not severity, and a report exists because something is already being
  responded to. That is structurally the wrong side of the event for the
  pre-event signal coverage a 26/11, Pahalgam or Kandahar retrospective
  evaluation would need. Those need sources that emit before a response exists.
- **No extraction.** ReliefWeb observations reach bronze; nothing turns them
  into `EventMention`s. Humanitarian prose needs the Phase 2 extraction cascade,
  so `pramaanx extract` skips them and logs that it did.
- **No `/disasters`, `/jobs` or `/training`.** Different date semantics; the
  config rejects those endpoints rather than pretending.
- **No historical reconstruction.** Revised reports are timestamped at their
  revision, so deep-history backtests over ReliefWeb will under-represent early
  cutoffs. Quantifying that needs an external archive.
- **No ACLED, no data.gov.in, no frozen news corpus.** Phase 1B.

## Human actions still required

1. **Obtain a pre-approved appname** from ReliefWeb. Mandatory since
   2025-11-01, and not something to choose locally — request one through the
   process linked from <https://apidoc.reliefweb.int/parameters>, then set
   `PRAMAANX_RELIEFWEB_APPNAME`. Until then no live call can succeed, and an
   unapproved name returns an origin 403.
2. **Allowlist `api.reliefweb.int`** for whatever network runs the ingest. This
   environment's egress proxy denies it (`403` on CONNECT), which is why
   `live_api_verified` is false.
3. **Run the live test** once both exist, and read its result:
   ```bash
   PRAMAANX_LIVE_RELIEFWEB=1 PRAMAANX_RELIEFWEB_APPNAME=your-approved-app \
     uv run pytest tests/network -m network -v
   ```
   A pass is the only thing that justifies setting `live_api_verified: True`,
   and that edit is deliberate and human. A skip, a 403, or an empty result is
   not a pass. If it fails, the contract has drifted from reality and both
   `API_CONTRACT` and the parsing need correcting against
   <https://apidoc.reliefweb.int/>.
4. **Review ReliefWeb's terms** for your intended use. The connector records the
   licence and marks the source non-redistributable, but whether a particular
   use is permitted is not a decision code can make.
5. **Decide the ingestion overlap.** Offset pagination can omit records under
   concurrent mutation (§8); choose a window overlap that suits your tolerance,
   or build the reconciliation Phase 1A deliberately does not.
6. **Decide whether the conservative availability rule is acceptable** for your
   backtests, or whether recovering pre-revision text from an archive is worth
   building.
