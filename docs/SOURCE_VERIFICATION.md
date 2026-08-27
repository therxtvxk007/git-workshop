# Source verification status

The machine-readable version of this page is `SOURCE_CONTRACTS` in
`src/pramaanx/ingest/contracts.py`. That registry is authoritative; this page
explains it and says what a person has to do to move a source down the table.

## Why a source needs a state at all

A connector written from current official documentation, with fixtures that
pass, is a well-researched hypothesis about a service nobody has called. Every
Phase 1 connector was in that position at some point, and each recorded it in
its own vocabulary — `live_api_verified`, `genuinely_live_api_verified`,
`verified_against_current_official_docs` — so the cross-source question, *which
of my evidence sources has ever been answered by the real thing?*, took reading
three modules in three dialects and produced no artefact.

`VerificationState` is that one question, asked the same way of every source,
and written into every ingestion manifest and every snapshot.

| State | Means |
| --- | --- |
| `synthetic` | No external service exists. A generated world, not a feed. |
| `unverified` | Neither docs nor service checked. Never a state to leave a source in. |
| `docs_only` | Contract read from current official docs on a recorded date, fixtures pass. **No response from the real service has ever been parsed.** |
| `live_verified` | A real response was fetched and satisfied the contract, on a recorded date, with evidence naming where. |

A `live_verified` contract that cannot produce a date, a scope and an address
for its evidence is rejected at construction. So is a `docs_only` contract that
names no blocker: an unverified source must say what is missing, or nobody can
act on it.

## Current state — 2026-08-27

| Source | State | Detail |
| --- | --- | --- |
| `gdelt` | **live_verified** | One 15-minute export file fetched, unzipped and parsed. [Actions run 33086345335](https://github.com/therxtvxk007/git-workshop/actions/runs/33086345335). Scope: the export archive's schema, not every GDELT product. |
| `data_gov_in` | **live_verified** | Raw first-page envelope plus a forced multi-page terminal traversal, against the selected resource only. Recorded in `docs/M1C_ACCEPTANCE.md`. |
| `reliefweb` | `docs_only` | Blocked on an approved `appname`. Approval-gated since 2025-11-01; this environment's egress additionally refuses `CONNECT` to `api.reliefweb.int`. |
| `acled` | `docs_only` | Blocked on a myACLED credential, which requires accepting the EULA under a declared institutional use. |
| `synthetic` | `synthetic` | Nothing to verify. |

## What is pinned, and what is not

`data_gov_in` pins its **resource identifier** so that a withdrawn resource
fails a test rather than ingesting nothing. It does **not** pin the resource's
field names, because no live response's field names have ever been recorded
here — the 2026-08-27 run recorded that the envelope contract held and the
traversal terminated, and the repository's only data.gov.in records are openly
synthetic fixtures. `PinnedResource.drift_against` raises rather than compare
against an empty pin, since "every field is new" is drift noise, not a finding.

Capturing it needs one live probe that writes down what came back. Until then
the schema pin is honestly absent rather than dishonestly present.

## Moving a source to `live_verified`

1. **Obtain the credential.** This is the part code cannot do.
   - ReliefWeb: request a pre-approved `appname` through the process linked from
     <https://apidoc.reliefweb.int/parameters>.
   - ACLED: create a myACLED account, review the EULA, decide between a
     short-lived bearer token and the documented password grant.
   - data.gov.in: a user-issued key from <https://www.data.gov.in/help>. Never
     the portal's sample key.
2. **Add it as a repository secret** under the name in `.env.example`
   (`PRAMAANX_RELIEFWEB_APPNAME`, `PRAMAANX_ACLED_ACCESS_TOKEN` or
   `PRAMAANX_ACLED_USERNAME`/`_PASSWORD`, `PRAMAANX_DATA_GOV_IN_API_KEY`).
   Adding the secret is the only step: `live-sources.yaml` starts *enforcing*
   that source on its next run, because it treats "credential configured" as
   "this source is attempted", and an attempted source that does not pass is a
   failure.
3. **Run the workflow** — Actions → *live source verification* → pick the source.
4. **Read the result, then update the contract** in `contracts.py`: set the
   state, the date, the scope of what was actually checked, and the run URL.
   Bump `contract_version` and update `PINNED_CONTRACTS` in
   `tests/contracts/test_source_contracts.py` in the same commit.

## Why a skip is not a pass

`pytest` exits 0 when every test skips. The previous live workflow ran the whole
`tests/network` directory and reported success while ten of eleven tests skipped
for want of credentials — a green tick that verified one source and looked like
it verified four.

`live-sources.yaml` judges each source separately and fails an attempted source
whose suite produced no passing test. The opt-in live tests themselves are built
the same way: they fail on an origin 403 rather than skipping, so an incomplete
verification cannot quietly become a green one. Only a CONNECT-time egress
refusal skips, and it names the host.
