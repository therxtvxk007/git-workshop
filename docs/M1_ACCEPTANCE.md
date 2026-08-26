# Phase 1A acceptance: the ReliefWeb evidence connector

Phase 1A adds one real Tier-0 source to the point-in-time ledger, preserving
every M0 guarantee: availability-based admission, append-only content-addressed
bronze, strict configuration, and the future-injection gate.

Run everything: `make check` — ruff, mypy, and 380 tests behind an enforced
coverage floor.

| Suite | Tests | Phase 1A additions |
| --- | ---: | --- |
| `tests/unit` | 195 | Connector logic, availability rule, pagination, contract failures, rate limiting |
| `tests/contracts` | 86 | `ReliefWebSourceConfig` strictness and typo rejection |
| `tests/leakage` | 24 | (unchanged; M0 guarantees) |
| `tests/metamorphic` | 8 | (unchanged; M0 guarantees) |
| `tests/integration` | 67 | Dry-run purity, ledger provenance, cutoff safety, CLI surface |
| `tests/network` | 3 | Opt-in live verification (2 ReliefWeb, 1 GDELT) |

---

## Read this first: what has and has not been verified

This distinction matters more than any test count below.

| | Status |
| --- | --- |
| Connector **logic** — pagination, ordering, deduplication, availability rule, contract failure handling | **Fixture-verified.** Hand-written synthetic records, `tests/unit` + `tests/integration`. |
| Connector **request path** — URL construction, appname resolution, proxy/TLS negotiation, egress error handling | **Executed against the network.** The live test builds the real URL and opens a real TLS tunnel; it reaches ReliefWeb's edge and receives a policy denial from this environment's egress proxy. |
| **The API contract itself** — that ReliefWeb returns the field names, envelope and pagination this connector assumes | **NOT VERIFIED.** Asserted from prior knowledge, not read from the official documentation, because the development environment had no route to `reliefweb.int` or `apidoc.reliefweb.int`. |

The assumptions are collected in one place — `API_CONTRACT` in
`src/pramaanx/ingest/connectors/reliefweb.py` — which carries
`verified_against_official_docs: False`, and a test asserts that it says so.
`tests/network/test_reliefweb_live.py` checks every entry against the live
service and is what converts the assertion into a fact.

**A skipped live test is not a verification.** The live test skips when it is
not enabled, when no appname is set, or when egress is blocked, and it fails
loudly — never passes quietly — if the API shape does not match.

---

## 1. Strictly typed configuration

**Implementation** — `ReliefWebSourceConfig` in `src/pramaanx/config.py`,
registered in `SOURCE_OPTION_MODELS`.

Covers identity (`appname`), endpoint, pagination (`page_size`, `max_items`,
`max_pages`), filters (`languages`, `countries`, `disaster_types`, `formats`),
and egress (`cache`, `timeout_seconds`, `max_attempts`, `backoff_seconds`,
`min_interval_seconds`, `proxy`, `trust_env`, `ca_bundle`, `verify`).

**Accepted when** — `tests/contracts/test_source_config.py`:

- `appnmae`, `page_siz`, `countires` are rejected, with the source named in the
  error;
- strictness extends to meaning, not only spelling: `countries: ["IN"]` is
  rejected as not ISO-3166 alpha-3, `languages: ["eng"]` as not ISO-639-1, and
  `endpoint: disasters` as out of Phase 1A scope;
- `page_size: 5000` is rejected against the API's own ceiling;
- every option the connector reads is declared, checked by parsing the module
  (`TestEveryConsumedOptionIsDeclared`), and no option is read by string key;
- ReliefWeb options are inside `config_hash`, so a run with a different page
  size is a different experiment.

## 2. Temporal semantics

**The rule**, implemented in `availability_of` and pinned by
`tests/unit/test_reliefweb_connector.py::TestAvailabilityRule`:

```
first_observed_at = max(date.created, date.changed)
```

Four instants are kept distinct:

| Instant | Source | Where it goes |
| --- | --- | --- |
| Availability | `max(created, changed)` | `first_observed_at` — the only field admission uses |
| Publication | `date.original` if present, else `date.created` | `published_at` |
| Modification | `date.changed` | `metadata.date_changed`, `revised_after_publication` |
| Retrieval | the ledger's clock | `retrieved_at`, never used for admission |
| Claimed event time | — | **left unset**: report metadata carries publication dates, not the date of the situation described. Deriving one would be inventing it. |

**Why the maximum.** The API serves only the current revision; there is no
version-history endpoint. The body in hand is the revised body, so the earliest
moment this project can honestly claim to have had *this text* is when it was
last revised. A report created in 2020 and edited in 2026 enters a 2026
snapshot, not a 2020 one.

This is deliberately conservative in a specific direction: it withholds evidence
from early cutoffs that a contemporaneous reader might really have had, rather
than risk attributing to an early cutoff a sentence written later. For a system
whose entire claim rests on not seeing the future, that is the right way to err.
Recovering the earlier text would need an external archive; until one exists,
this is the honest bound, and it is stated in the connector docstring, the
`SourceRecord.notes`, and the README.

**Accepted when** —

- a revised report is available only from its revision
  (`test_revised_report_is_available_only_from_its_revision`);
- `date.original` never sets availability
  (`test_original_publication_date_never_sets_availability`);
- naive timestamps are refused rather than assumed UTC
  (`test_naive_timestamps_are_refused`) — an assumed offset is an hour of
  leakage;
- a report revised after a cutoff cannot enter a snapshot at that cutoff
  (`test_a_report_revised_after_the_cutoff_cannot_enter_an_earlier_snapshot`);
- future records do not change a pre-cutoff snapshot hash, with a negative
  control proving the injection was real
  (`TestCutoffSafety`).

## 3. Pagination, ordering, deduplication

**Accepted when** — `tests/unit/test_reliefweb_connector.py::TestPagination`:

- offset pagination walks until `totalCount` is reached, or an empty page, or
  `max_pages` — a mis-specified window cannot walk the archive indefinitely;
- ordering is total (`date.changed:asc`, then `id:asc`), because a date-only
  sort repeats or drops records where timestamps collide at a page boundary;
- a record appearing on two pages is ingested once
  (`test_duplicate_records_across_pages_are_ingested_once`);
- `max_items` bounds a first run;
- `FetchWindow` is half-open while the API's range bounds are inclusive, so the
  window is re-applied client-side — a record exactly at the end bound is
  dropped, one at the start bound is kept (`TestWindowBoundaries`).

## 4. Failing loudly

A response shape the connector does not understand raises
`ReliefWebContractError`. It is never skipped, and never returned as an empty
page: a silent gap in an append-only ledger later reads as a quiet news week.

**Accepted when** — `TestContractFailures` covers a missing `data` list, an API
error envelope, a record with no date object, a naive timestamp, a non-JSON
body, and a record with no id.

## 5. Egress

Reuses M0's `HttpClient` unchanged in behaviour, with one addition: HTTP 429 is
now retried honouring the server's own `Retry-After` (delta-seconds or HTTP
date), and a persistent 429 raises an actionable `RateLimitError` naming the
knobs to turn. ReliefWeb rate-limits, and guessing a backoff against a service
that has just told you the answer is both rude and slower.

**Accepted when** — `tests/unit/test_http_client.py::TestRateLimiting`, and
`TestEgressConfiguration` in the connector tests proves `proxy`, `ca_bundle`,
`trust_env`, timeouts, attempts and pacing all reach the client.

## 6. `--dry-run` purity

**Accepted when** — `TestDryRunPurity`: the planner is handed a fetcher that
raises on any call, and no request is made; no bronze directory is created; the
caller identity is redacted from the emitted plan; and a missing appname fails
*during* the dry run rather than on the first real request.

## 7. Credentials and licensed content

- The appname is resolved from `PRAMAANX_RELIEFWEB_APPNAME`, or from
  configuration when an experiment should record the identity it called under.
  Absent both, the connector raises — calling an API anonymously that asks you
  not to is not a default anyone should get by omission.
- The identity is redacted from every persisted payload and from plan output
  (`test_payload_never_carries_the_caller_identity`).
- A contract test fails if any committed config sets an appname.
- Fixtures are hand-written and synthetic; `tests/fixtures/reliefweb/README.md`
  explains why no real corpus is committed. `data/` remains git-ignored.

## 8. M0 remains intact

The M0 acceptance gate (`tests/leakage`, `tests/metamorphic`,
`tests/contracts`, then `make demo`) is unchanged and still passes. `make demo`
does not touch ReliefWeb: it runs on the synthetic world, offline.

---

## What Phase 1A does not do

- **No extraction.** ReliefWeb observations reach bronze; nothing turns them
  into `EventMention`s. Humanitarian prose needs the Phase 2 extraction
  cascade, so `pramaanx extract` skips them and logs that it did. They are
  evidence in the ledger, not yet features.
- **No `/disasters`, `/jobs` or `/training`.** Different date semantics; the
  config rejects those endpoints rather than pretending.
- **No historical reconstruction.** Revised reports are timestamped at their
  revision, so deep-history backtests over ReliefWeb will under-represent
  early cutoffs. Quantifying that needs an external archive.
- **No ACLED, no data.gov.in, no frozen news corpus.** Phase 1B.

## Human actions still required

1. **Allowlist `api.reliefweb.int`** for whatever network runs the ingest. This
   environment's egress proxy denies it (`403` on CONNECT), which is why the
   API contract is unverified.
2. **Run the live test** once egress exists, and read its result:
   ```bash
   PRAMAANX_LIVE_RELIEFWEB=1 PRAMAANX_RELIEFWEB_APPNAME=your-app \
     uv run pytest tests/network -m network -v
   ```
   If it fails, the contract has drifted from reality and both `API_CONTRACT`
   and the parsing need correcting against <https://apidoc.reliefweb.int/>.
   Then flip `verified_against_official_docs` to `True` and update the test
   that asserts it.
3. **Choose an appname** identifying your deployment.
4. **Review ReliefWeb's terms** for your intended use. The connector records
   the licence and marks the source non-redistributable, but whether a
   particular use is permitted is not a decision code can make.
5. **Decide whether the conservative availability rule is acceptable** for your
   backtests, or whether recovering pre-revision text from an archive is worth
   building.
