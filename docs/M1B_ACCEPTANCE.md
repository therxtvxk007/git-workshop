# Phase 1B acceptance — ACLED

Phase 1B adds one source only: the credentialed ACLED event API. It does not
merge Phase 1A, change the forecasting model, or make a real-world accuracy
claim.

## Verification status

| Claim | Status | Evidence |
| --- | --- | --- |
| Current official documentation inspected | **Verified 2026-08-26** | Links below and `API_CONTRACT` |
| OAuth, envelope, item and cursor behaviour | **Fixture/integration tested** | Synthetic fixtures and offline tests |
| Genuine ACLED API response observed | **Not verified** | No ACLED credential is available in this environment |
| Terms acceptable for the intended deployment | **Human decision required** | ACLED EULA and organization/license status |

Fixture success is not live verification. `API_CONTRACT` deliberately keeps
`genuinely_live_api_verified: False`; a successful opt-in run must be reviewed
before a human changes it.

## Official contract consulted

- [Getting started](https://acleddata.com/api-documentation/getting-started) —
  OAuth password grant, 24-hour bearer token, refresh flow and base endpoint.
- [Elements of ACLED's API](https://acleddata.com/api-documentation/elements-acleds-api) —
  query operators, totals, cursor pagination and the 2026-10-01 page-pagination
  deprecation.
- [ACLED endpoint](https://acleddata.com/api-documentation/acled-endpoint) —
  filters, returned fields and JSON envelope.
- [ACLED codebook](https://acleddata.com/methodology/acled-codebook) — event
  identifier, event date, API timestamp, taxonomy and living-dataset warning.
- [ACLED EULA](https://acleddata.com/eula) — license classes, credential
  restrictions, attribution and non-reconstructable derivative requirements.

The old `email`/`key` query authentication is intentionally absent. ACLED's
myACLED transition ended legacy key access on 15 September 2025.

## Temporal contract

Four instants remain separate:

| Instant | ACLED/PRAMAAN-X field | Meaning |
| --- | --- | --- |
| Claimed event date | `event_date` → `claimed_event_time` | Day the coded event is said to have occurred |
| API publication/revision | `timestamp` → `published_at` | Current body uploaded to ACLED API |
| Cutoff admission | `timestamp` → `first_observed_at` | Earliest conservative instant the current body is usable |
| Retrieval | ledger clock → `retrieved_at` | When this deployment fetched the body |

`event_date` never controls cutoff admission. ACLED is a living dataset and
does not release formal versions: if a row is revised, its current timestamp is
later. Without a separately licensed versioned archive, old cutoffs omit that
current body instead of back-dating it.

## Fail-closed acquisition

The connector requests JSON dyadic rows using cursor pagination from cursor
`0`, `with_total=true`, an explicit field list and a timestamp range. It refuses
to yield any row until all pages pass these checks:

- required envelope fields exist and have documented types;
- `status == 200`, `success is true`, `count == len(data)`;
- `total_count` and `data_query_restrictions` stay stable;
- every data entry is an object with required identifiers and instants;
- event ids do not repeat across pages;
- cursors are non-empty, advance without cycles, and terminate at null;
- terminal received rows exactly equal `total_count`;
- empty non-terminal pages, total overshoot and `max_pages` exhaustion fail.

`EvidenceLedger.ingest` completes the connector walk before writing source,
payload or observation records, so a late pagination failure cannot leave a
plausible partial bronze ingest.

## Credential and egress contract

Credential values are read only from environment variables. Configuration
contains their names, so secrets never enter configuration hashes.

Preferred:

```bash
PRAMAANX_ACLED_ACCESS_TOKEN='short-lived-token' \
  uv run pramaanx ingest --source acled \
  --config configs/sources/acled_india.yaml \
  --from 2026-01-01T00:00:00Z --until 2026-02-01T00:00:00Z
```

Alternatively set `PRAMAANX_ACLED_USERNAME` and
`PRAMAANX_ACLED_PASSWORD`; the connector executes the OAuth password grant.
Passwords and bearer tokens are sent in a form body/header, never a URL, log or
cache key. `--dry-run` resolves only which credential mode is configured and
prints `<redacted>` without network or filesystem effects.

Origin 400/401/403 responses fail as permanent HTTP errors. Only an HTTP 407 or
a CONNECT-time proxy refusal is classified as egress policy. HTTP 429 obeys a
bounded `Retry-After` and fails distinctly when attempts are exhausted.

## Offline acceptance

```bash
uv sync --frozen --extra dev --managed-python
make check
uv run pytest tests/unit/test_acled_connector.py \
  tests/integration/test_acled_integration.py -v
uv run pytest tests/leakage tests/metamorphic tests/contracts -v
make demo
git diff --check
```

The ACLED tests cover OAuth modes and redaction, envelope drift, item types,
cursor completion, total/restriction stability, cycles, duplicates,
`max_pages`, deterministic hashing, real ledger writes, zero writes on
incomplete traversal, structured extraction, dry-run purity and a future-item
injection with a negative control.

## Genuine live verification

After accepting the applicable terms and configuring credentials:

```bash
PRAMAANX_LIVE_ACLED=1 \
  uv run pytest tests/network/test_acled_live.py -m network -v
```

After opt-in, only a CONNECT-time egress refusal skips. Bad credentials, origin
authorization failures, rate limits, schema drift, malformed events and cursor
failures fail the test. A skip does not verify ACLED.

## Human actions remaining

1. Create/confirm the myACLED account used by the deployment.
2. Decide whether a short-lived managed token or the documented password grant
   is acceptable for the deployment's secret-management policy.
3. Review the EULA, Content Usage Terms and Attribution Policy. Government,
   quasi-government, multilateral and commercial uses may require separate
   licensing.
4. Run and review the live tests; correct the isolated contract if ACLED's real
   response differs, then manually update the live-verification flag.
5. Decide whether conservative deep-history coverage is sufficient or obtain a
   permitted versioned archive.
