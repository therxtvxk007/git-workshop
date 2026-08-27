# Phase 1C acceptance — data.gov.in

Phase 1C adds a strict resource-profile connector to the M0 temporal
foundation. It is production-oriented acquisition code within the tested
boundaries below; it is not a complete forecasting product and has not yet been
validated against a genuine live API response.

## Verification status

| Claim | Status | Checked | Evidence / blocker |
| --- | --- | --- | --- |
| `verified_against_current_official_docs` | `true` | 2026-08-26 UTC | Current resource API panel, portal help, terms and Government Open Data License pages were inspected. |
| `fixture_and_integration_tested` | `true` | 2026-08-26 UTC | Hand-written synthetic pages exercise strict parsing, pagination, ledger writes, cutoff exclusion, deterministic hashing and failure containment. |
| `genuinely_live_api_verified` | `false` | 2026-08-27 UTC | A credentialed Windows probe now reached the origin and received a JSON success envelope without exposing the replacement key. Parsing established that all required fields exist, `status` is `ok`, and `total`/`count` are JSON integers; it then found the live `limit` echo encoded as the canonical decimal string `"10"`. The parser now normalizes canonical decimal strings only for `limit`/`offset`, while authoritative counts remain strict integers. A complete live pass is still required before this flag changes. |

These booleans are independent. A green offline suite or documentation check
does not change `genuinely_live_api_verified`.

## Official sources checked

- Resource-specific API contract and selected resource:
  <https://www.data.gov.in/resource/attacker-wise-incidents-violence-extremists-insurgents-terrorists-during-2023>
- API catalogue entry point: <https://www.data.gov.in/apis>
- Registration and API-key help: <https://www.data.gov.in/help>
- Terms of use: <https://www.data.gov.in/terms-of-use>
- Government Open Data License - India:
  <https://www.data.gov.in/government-open-data-license-india>

The older standalone `https://data.gov.in/ogpl_api/api-doc.html` returned the
portal's not-found page when checked. The resource-specific API panel is the
current official contract surface used here.

## Selected resource and permitted role

The profile uses resource UUID
`869c674d-59a4-4de3-8b09-f2b709983f51`, “Attacker-wise Incidents of Violence
by Extremists/Insurgents/Terrorists during 2023,” from the Crime in India 2023
catalog. The portal displayed annual granularity and publication/update date
2026-02-13 when checked.

This is a retrospective aggregate, published years after the measured period.
It is appropriate only for contextual exposure, base-rate research and
retrospective validation. It is not an event feed, does not enter silver via a
fabricated deterministic event mapping, and must not be cited as early-warning
evidence for a 2023 event. The profile records the portal dates at their native
date precision and uses 2026-02-14T00:00:00Z as a conservative operator-defined
availability boundary—the start of the next UTC day—not as a claimed portal
timestamp.

## API contract implemented

| Property | Phase 1C contract |
| --- | --- |
| Endpoint | `GET https://api.data.gov.in/resource/{resource_id}` |
| Version | No versioned path was advertised in the inspected resource API panel; the code stamps its checked contract date. |
| Authentication | Required query parameter `api-key`, sourced only from `PRAMAANX_DATA_GOV_IN_API_KEY`. |
| Format | Required `format=json`; production fetch accepts `application/json`. |
| Pagination | `offset` + `limit`; response must echo both and prove completion with stable `total`. |
| Required envelope | `status`, `total`, `count`, `limit`, `offset`, `records`; status must be `ok`. |
| Strict numeric policy | Authoritative `total`/`count` must be non-negative JSON integers. Request echoes `limit`/`offset` accept either non-negative JSON integers or canonical ASCII decimal strings (`0` or a non-zero digit followed by digits), then must exactly match the request. Booleans, signs, whitespace, leading zeros, floats, exponents, null and Unicode digits fail. |
| Row identity | Configured scalar stable fields where a resource has them; otherwise canonical resource-ID + row-content hash. Any duplicate fails. |
| Ordering | Complete traversal is buffered and sorted by stable row ID before emission. |
| Safety bounds | Page size 1–1000, pages 1–10000 and items 1–1,000,000 are project safety bounds, not claims about undocumented portal maxima. The shipped profile uses page size 10 because the portal labels its public sample key as limited to 10 records. |

The inspected official panel documented JSON/XML/CSV, offset/limit, and HTTP
200/400/403, but did not publish a general user-key quota, rate limit,
transactional snapshot token, durable row ID, or universal maximum page size.
The connector does not invent those properties. The first successful origin
response showed that `limit` is a JSON string, a representation the official
panel did not specify. That observation is recorded without treating a partial
parse as complete verification. Unknown live response types fail the opt-in
contract test with field names and type names only—never record values, URLs or
credentials—and must be reconciled before the live flag changes.

Offset pagination over a mutating resource is not transactionally complete.
Stable totals and duplicate detection catch several failure modes, but cannot
prove that a row was not omitted after an insertion/deletion shifted offsets.
Operational mitigation is to ingest only published resource versions, retain
immutable hashes, and overlap/reconcile later acquisitions. This is mitigation,
not a snapshot guarantee.

## Four instants

- `published_at`: `null` for the selected profile because the portal exposes a
  date, not a timezone-aware instant. The raw date remains in the canonical
  payload.
- `first_observed_at`: the explicit profile `available_at`; this alone controls
  window acquisition and cutoff admission.
- `claimed_event_time`: `null` for this annual aggregate. A year is not silently
  converted to midnight. Other profiles may configure a field only when every
  row contains an unambiguous timezone-aware instant.
- `retrieved_at`: assigned by the evidence ledger's clock at ingestion.

Retrieving an old table today never makes it available to an earlier cutoff.
Tests inject post-cutoff data and prove an earlier snapshot is unchanged, with
a later-cutoff negative control proving the injected row was genuinely stored.

## Credential and failure safety

The API key is absent from Pydantic config, YAML, examples, fixtures, plans,
source records and canonical payloads. Request query names are parsed
case-insensitively and redacted before cache hashing, project logging or error
conversion. Repeated/encoded parameters and malicious newline values are
covered. HTTPX/HTTPCore request logging is held above INFO because their native
request line contains the raw query string. Inline proxy credentials are
rejected for this source.

Dry-run validates that a key and operational resource profile exist, reports
only `configured: true` and the environment-variable name, and performs no
network or filesystem access. Missing identity fails before side effects.

Origin 400/401/403 responses are permanent API/auth failures. Only proxy 407 or
a CONNECT-time proxy refusal is classified as egress policy. HTTP 429 and
transient failures retry within configured attempts; delta-seconds and HTTP-date
`Retry-After` values are clamped to `max_retry_after_seconds`. Contract and
authentication failures are never retried. Those shared HTTP exception classes
remain intact across the production connector boundary, so operator handling
cannot accidentally turn an origin rejection or a proxy-policy refusal into an
undifferentiated connector failure.

## License and redistribution boundary

Portal terms say dataset accuracy/currency is not guaranteed and users should
verify with the publishing department. The Government Open Data License is the
general portal license, but resource metadata and third-party exclusions remain
controlling. The source record is therefore conservatively
`redistributable: false`; no real corpus is committed. A human must confirm the
resource-level license, attribution wording, automated-use terms and any
third-party material before raw redistribution or operational use.

## Running

Acquire a user-issued key through the portal account flow. Do not use the
public sample key as deployment proof.

```bash
export PRAMAANX_DATA_GOV_IN_API_KEY='<user-issued-key>'
uv run pramaanx ingest --source data_gov_in \
  --config configs/sources/data_gov_in_extremism_context.yaml \
  --from 2026-02-13T00:00:00Z --until 2026-02-15T00:00:00Z --dry-run

PRAMAANX_LIVE_DATA_GOV_IN=1 \
PRAMAANX_DATA_GOV_IN_API_KEY='<user-issued-key>' \
uv run pytest tests/network/test_data_gov_in_live.py -m network -v
```

```powershell
$env:PRAMAANX_DATA_GOV_IN_API_KEY = "<user-issued-key>"
uv run pramaanx ingest --source data_gov_in `
  --config configs/sources/data_gov_in_extremism_context.yaml `
  --from 2026-02-13T00:00:00Z --until 2026-02-15T00:00:00Z --dry-run

$env:PRAMAANX_LIVE_DATA_GOV_IN = "1"
uv run pytest tests/network/test_data_gov_in_live.py -m network -v
```

The live tests skip before network only when opt-in or the credential is
missing. The first probe validates the raw first-page envelope. The second
forces page size 1 and walks every page through the production connector,
requires a positive total and more than one page, reconciles emitted items
exactly to that total, and verifies strictly increasing unique offsets. A CONNECT/proxy policy refusal may skip with the host named.
Origin authentication, authorization, rate, content-type, schema, pagination
or terminal-reconciliation failures fail without rendering credentials.

## Scope boundary and human actions

Evidence reaches bronze only. Phase 1C adds no retrieval, graph, learned
extraction, adjudication, calibration, conformal risk control, service,
dashboard, container or deployment work. Phase 1D was not started.

Before calling the source live-ready, a human must obtain a user-issued key,
approve the selected resource and its role, review license/attribution terms,
allowlist `api.data.gov.in` if needed, execute the live test, and record a real
passing response. Before any release, all isolated source branches must be
integrated deliberately and real-data rolling backtests must beat preregistered
baselines without leakage.
