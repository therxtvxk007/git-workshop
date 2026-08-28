# Integrating the console with a live engine

The console displays what the Pramaan-X engine produces. It does not forecast,
calibrate, score outcomes or assign statuses, and it must never start: a second
implementation of the pipeline that disagrees with the first is worse than no
console at all.

This document is the contract a serving API has to satisfy.

## Switching modes

```bash
VITE_PRAMAANX_API_MODE=rest
VITE_PRAMAANX_API_BASE_URL=https://engine.example.internal
```

Both are required. In REST mode the app refuses to start without a base URL
rather than falling back to the demo dataset — a dead engine quietly serving
fixtures behind a `LIVE` pill is the single worst failure this console could
have.

The active mode is shown in the top bar on every route and is not hideable.

## Endpoints

Fifteen methods, all read-only except the last. Paths are relative to the base
URL. Schemas are in `src/lib/api/types.ts`; that file is the normative
definition and this table is a map to it.

| Method | Endpoint | Returns |
| --- | --- | --- |
| `getSnapshot` | `GET /v1/snapshot` | `SnapshotInfo` |
| `listDistricts` | `GET /v1/districts` | `District[]` |
| `listForecasts` | `GET /v1/forecasts` | `ForecastSummary[]` |
| `getForecast` | `GET /v1/forecasts/{id}` | `ForecastDetail` |
| `getForecastHistory` | `GET /v1/forecasts/history?district_id&event_family` | `HistoryPoint[]` |
| `getContributions` | `GET /v1/forecasts/{id}/contributions` | `ContributionReport` |
| `listEvidence` | `GET /v1/evidence` | `EvidencePage` |
| `getEvidenceItem` | `GET /v1/evidence/{id}` | `EvidenceItem` |
| `listReviewTasks` | `GET /v1/review/tasks` | `ReviewTaskSummary[]` |
| `getReviewTask` | `GET /v1/review/tasks/{id}` | `BlindedTask` |
| `listBacktestRuns` | `GET /v1/backtests` | `BacktestRunSummary[]` |
| `getBacktestRun` | `GET /v1/backtests/{id}` | `BacktestRun` |
| `getDataHealth` | `GET /v1/data-health` | `DataHealth` |
| `listModelArtifacts` | `GET /v1/models` | `ModelArtifact[]` |
| `getRunLineage` | `GET /v1/runs/{id}/lineage` | `RunLineage` |
| `evaluateScenario` | `POST /v1/scenarios/evaluate` | `ScenarioResult` |

## Relationship to the engine's own schemas

Field names mirror `src/pramaanx/schemas/` exactly, so the two can be diffed by
eye. `ForecastSummary` carries `forecast_id`, `cutoff_at`, `created_at`,
`raw_probability`, `calibrated_probability`, `epistemic_uncertainty`, `status`
and `snapshot_hash` with the same meanings as `ForecastRecord`; `EvidenceRef`
matches `pramaanx.schemas.evidence.EvidenceRef`; `Hypothesis` matches
`EventHypothesis`.

Four fields are **console-layer**: they are part of the serving API, not of the
persisted record, and are marked as such in `types.ts`.

- `district_id` / `district_name` / `state` — the district projection of
  `hypothesis.location_cells`. The engine stores a distribution over location
  cells; the console needs one district per row.
- `interval` — a two-sided probability interval. `ForecastRecord` has no
  interval field, so a serving layer computing one must say how
  (`interval.method`), or return `null`.
- `base_rate` — what the probability should be read against. Without it, a 12%
  forecast is unreadable.
- `horizon_days` — the horizon the experiment config fixed.

## Validation is not optional

Every response is parsed against its schema before anything is rendered. A `200`
carrying a malformed body is a `MalformedResponseError`, and the console shows
the list of violations instead of the data. The rules that will reject a
response:

- a probability outside `[0, 1]`;
- a one-sided interval, or one whose lower bound exceeds its upper;
- a blank `snapshot_hash` — a forecast that cannot be audited for leakage is
  not a forecast;
- `created_at` earlier than `cutoff_at`;
- `independent_cluster_count` greater than `evidence_count`;
- a timestamp with no timezone offset — a guessed timezone is a cutoff bug;
- a status outside the five the engine defines;
- a non-empty categorical distribution that does not sum to 1;
- restricted evidence that still ships a body.

This is deliberately strict. Rendering a probability the console cannot vouch
for is the one thing it must never do.

## Error semantics

| Condition | Class | What the analyst sees |
| --- | --- | --- |
| Network failure, `5xx` | `ApiUnavailableError` | "Unavailable", with the endpoint |
| `404`, `501` | `ApiUnavailableError` | "The engine has not implemented this" |
| `401`, `403` | `AccessDeniedError` | "Not permitted", naming the resource |
| `200` failing validation | `MalformedResponseError` | The list of violations |

Nothing is retried. All three are conditions a retry cannot fix, and a spinner
that never resolves is less informative than an error.

An empty list is **not** an error. `[]` means "we asked, and the answer is
none", and the console says exactly that.

## Authentication and keys

The browser sends the signed-in user's session bearer token and nothing else.
There is no engine API key in the client, in an environment variable, or in the
bundle — a key shipped to the browser is a key published.

If the engine requires a credential of its own, put a server function in front
of it:

```
browser ──(user session JWT)──▶ proxy function ──(engine key)──▶ engine
```

The proxy validates the session, applies whatever per-role filtering the
deployment requires, attaches the engine credential server-side, and returns the
engine's response unchanged so the console's validation still applies.

## Caching

`public.api_response_cache` (migration `0006`) is keyed by
`(endpoint, request_hash, snapshot_hash)`. Including the snapshot is the whole
point: a response computed against one snapshot must never be served for
another, or the console will show numbers from one cutoff under the label of a
different one. The table is readable by the workspace and writable only by the
service role that fronts the engine — a browser that can write the cache can
poison every other analyst's view.

## Restricted and post-cutoff evidence

Two behaviours the serving layer must preserve:

- **Withheld items are counted.** `EvidencePage.withheld` reports how many
  matches the caller may not see. A silently shortened list reads as "there is
  nothing more", which is the wrong belief to install. Restricted items must
  return `body: null` — the schema rejects a restricted item that ships one.
- **Post-cutoff items are labelled, not hidden.** `post_cutoff: true` marks
  evidence observed after the cutoff. The console shows it only on request and
  always labelled, so an analyst can see what the model was missing without
  mistaking it for something the model used.

## Blinding

`GET /v1/review/tasks/{id}` must not include the model's probability, status,
or which generator proposed the candidate. Not filtered in the response —
absent from it. The console asserts this in `src/test/blinding.test.ts`, and
blinding that depends on the client is not blinding.
