# Notice: commit `4fbb8b4` is not the completed coverage fix

`4fbb8b4` ("Measure evidence coverage, and abstain when the lookback was never
observed") is preserved in history and must **not** be treated as closing the
coverage defect. Its commit message overstates what it did. This notice records
the gap so nobody reads that message and concludes the problem is solved.

## What it actually did

Added a gate in front of the base-rate generator that abstains when a computed
coverage ratio falls below a threshold. That is all.

## Four defects

### 1. Coverage was record-timestamp spread, not acquisition coverage

`measure_coverage` computed `max(first_observed_at) - min(first_observed_at)`
over returned observations. That measures where records happen to sit in time.
It does not measure what was successfully fetched.

The consequence is not a rounding error. Two records — one at day −365, one at
day −1, with the intervening 300 days never collected — produce a span of 364
days, a coverage ratio of ~1.0, and a **forecast**. The gate passes on two
records as though a full year had been observed.

Nor can it separate cases that are not alike:

| Situation | Computed | Should be |
| --- | --- | --- |
| Query succeeded, returned nothing | span 0 → abstain | `queried_empty` — this source returned nothing, which is not evidence that nothing happened |
| Source never queried | span 0 → abstain | `not_acquired` — a different fact with a different remedy |
| Exactly one record | span 0 → abstain | one record is not zero records |
| Endpoints present, middle uncollected | span ≈ full → **forecast** | `UNCOVERED` |
| API silently truncated | undetectable | `INDETERMINATE` |

The last is live in this repository: `gdelt.py` breaks out of its row loop on
`max_rows_per_file` with no flag and no warning, so a capped file is
indistinguishable from a complete one. ReliefWeb and data.gov.in raise on
truncation; GDELT does not.

### 2. The denominator was never changed

The commit message says "So exposure becomes measured." It does not.
`estimate_rates` still reads:

```python
exposure = float(lookback_days)
```

`git show --stat 4fbb8b4` touches one file, `base_rate.py`, +27 lines: the
gate, an import and a constructor parameter. The estimator was not modified.
When coverage passes at 85%, the rate is still divided by 100% of the requested
lookback. `EvidenceCoverage.effective_exposure_days` exists, is tested, and is
called by no production code.

### 3. The original regression was deleted rather than pinned

The synthetic demo's 365-day request abstaining at 41% coverage was a real
finding. `4fbb8b4` removed it by changing the experiment configs and the shared
test fixture to request 90–120 days. No test pins the 365-day behaviour any
more. `test_the_generator_produces_nothing_under_thin_coverage` builds an
`EvidenceCoverage` by hand and never exercises the real pipeline path.

Both cases must exist as end-to-end regressions: the 365-day request must
deterministically abstain, and a sufficiently covered 90–120-day request must
remain eligible to forecast.

### 4. The counted units were never target outcomes

Separately from coverage, the numerator was wrong. The base-rate path counts
`EventMention` rows derived one-to-one from GDELT CAMEO codes
(`structured.py:144`) — article-derived mentions, undeduplicated, over a
`protest / demand / coerce / assault` ontology. Twenty articles about one
incident become twenty counted "events". None of it is terrorism, insurgency or
LWE.

## Status

The coverage defect is open. `first_observed_at` remains correct and necessary
for cutoff and leakage enforcement and keeps that role; it is simply not
acquisition coverage and must stop being used as such.

The fix is sequenced: freeze the prediction contract (it determines numerator,
denominator and geographic unit), then build the acquisition ledger, then
restore both regressions.
