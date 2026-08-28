# Pramaan-X Analyst Console

A research-grade, district-level forecast console for India. It presents the
probabilistic forecasts, evidence, calibration and provenance produced by the
Python engine in this repository.

It does not forecast anything. Every probability, status and metric is computed
by `src/pramaanx/` and displayed here; the console has no model, no scoring and
no threshold logic of its own, because a second implementation that disagrees
with the first is worse than no console at all.

**It is not operational intelligence.** The engine's calibration is recorded as
`identity@uncalibrated` and its statuses come from a placeholder threshold
policy with no miss-rate guarantee. The console says so on every route, in every
export and on every printed page.

---

## Quick start

```bash
cd console
npm install
npm run dev            # http://localhost:5173
```

With no configuration it runs against a deterministic demo dataset and browser
storage — no engine, no database, no credentials. Sign in with any of:

| Email | Roles |
| --- | --- |
| `admin@demo.invalid` | administrator, analyst, reviewer, viewer |
| `analyst@demo.invalid` | analyst, viewer |
| `reviewer@demo.invalid` | reviewer, viewer |
| `peer@demo.invalid` | reviewer, viewer (the second opinion) |

Password `demo` for all four. Every record in this mode carries `is_demo: true`,
and the top bar shows a `SYNTHETIC` pill.

To point it at a real engine and a real database, see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Routes

| Route | What it is for |
| --- | --- |
| `/` | Ranked districts for the active cutoff: filters, summary, map, table |
| `/forecasts/:id` | One district-family: probability, trend, evidence, contribution, provenance |
| `/evidence` | Search the observation ledger, with span highlighting |
| `/review`, `/review/:taskId` | Blinded two-reviewer annotation |
| `/backtests` | Evaluation runs, comparison mode, reliability and budget-recall |
| `/data-health` | Source coverage, ingestion delay, outages |
| `/models` | Model artefacts, stated limitations, run lineage |
| `/scenarios`, `/scenarios/:id` | Hypothetical what-ifs, isolated from forecasts |
| `/audit` | Append-only action timeline with chain verification |
| `/admin` | Users and roles, disputes, exports, API configuration |
| `/auth` | Sign in / sign up (the only public route) |

## The decisions worth knowing about

**An empty chart is a claim.** Seven distinct state views — loading, empty,
unavailable, denied, malformed, stale, partial — exist because collapsing them
is how a console tells an analyst a district has no risk when the source feeding
it has been down for six days. "Unavailable" never renders as zero, and a denied
record is named rather than hidden, so its absence is not mistaken for its
non-existence.

**REST mode never falls back to mock data.** A dead engine quietly serving
fixtures behind a `LIVE` indicator is the worst failure this console could have,
so failures surface as errors instead.

**Every response is validated.** Probabilities outside `[0, 1]`, one-sided
intervals, blank snapshot hashes, `created_at` before `cutoff_at`, timestamps
with no timezone — all rejected before anything renders. The mock adapter
validates its own output against the same schemas, so the fixtures cannot drift
away from the contract.

**Blinding is enforced in Postgres.** A reviewer can read a peer's review only
once their own row exists, by RLS policy. Blinding that depends on the client is
not blinding. Submitted reviews have no `UPDATE` or `DELETE` policy at all:
corrections are appended as adjudications, never edits.

**Precision is an editorial decision.** `0.6231` renders as `62%`, not
`62.31%` — four significant figures would be a claim this model has not earned.
All timestamps are UTC with the zone in the string.

**Colour is never the only channel.** Probability uses `cividis`, which stays
monotonic under all three common colour-vision deficiencies, and every place it
appears also prints the number. Red is reserved for `alert` and hard failures;
amber means uncertainty and nothing else.

**Every chart ships its numbers.** A reliability diagram read off 300 pixels
cannot tell you the top bin holds nine samples, so every chart has a real data
table behind a toggle — the primary record, not an accessibility afterthought.

**Exports carry their context.** Cutoff, snapshot hash, data mode and the
research-use notice go inside the file, above the data. Cells beginning `=`,
`+`, `-` or `@` are escaped: an export that runs code when opened is not an
acceptable way to share a district table.

**Scenarios cannot become forecasts.** They live in their own tables with an
`is_hypothetical` column a check constraint will not let you set to false. The
isolation is structural because a filter is one forgotten `WHERE` clause from
failing.

## Layout

```
console/
├─ src/lib/api/          Zod schemas, the 15-method adapter, mock + REST, errors
├─ src/lib/mock/         Deterministic seeded dataset (every state reachable)
├─ src/lib/cloud/        Postgres and local backends behind one interface
├─ src/lib/format.ts     Probability, interval and UTC formatting rules
├─ src/lib/export.ts     CSV/JSON with watermarking and injection escaping
├─ src/components/       shell · filters · forecast · evidence · review · charts · states · ui
├─ src/routes/           One file per route
├─ src/test/             59 unit and integration tests
├─ e2e/                  24 Playwright specs
├─ supabase/migrations/  Schema, RLS, roles, audit chain
└─ supabase/tests/       Executable proof of the security model
```

## Checks

```bash
npm run typecheck
npm run lint
npm test                # 59 unit/integration tests
npm run build
npx playwright test     # 24 end-to-end specs (needs a browser)
```

The database policies are tested separately, against a real Postgres, by
`supabase/tests/01_rls_test.sql`. It performs thirteen escalation attempts — a
viewer promoting themselves, a reviewer reading a peer's answer early, an author
editing a submitted review, an audit row being deleted — and fails if any
succeeds. Writing it caught a genuine bug: the first blinding policy queried its
own table and died with `infinite recursion detected in policy`.

## Documentation

- [docs/API_INTEGRATION.md](docs/API_INTEGRATION.md) — the engine contract,
  endpoint by endpoint, and why nothing retries
- [docs/SECURITY_ROLES.md](docs/SECURITY_ROLES.md) — roles, policies, and what
  actually enforces them
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — build, configure, serve, and what
  deploying does not give you
