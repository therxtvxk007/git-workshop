# Schema changelog

Schemas are versioned and a field is never silently reinterpreted. Every record
stores the `schema_version` it was written under, so a migration can always tell
what a given value meant.

Adding a field bumps the version. Changing what an existing field *means* is not
permitted at all: add a new field and deprecate the old one.

## Version 2

**Added** `EventMention.observed_at` (required, timezone-aware UTC).

The availability time of the claim — the `first_observed_at` of the observation
the mention was extracted from.

*Why.* Recency filtering needs to answer "when was this said?", which is a
different question from `event_time_start`'s "when will it happen?". Version 1
had no way to ask the first question, so `pramaanx.generators.base_rate` fell
back on event time and got three cases wrong: undated claims were kept
regardless of age, a fresh warning about an event two months out was discarded
as outside the activity window, and a stale claim about an imminent event
counted as new activity.

*Migration.* Version 1 mentions cannot be validated as version 2. They live only
in `data/silver/`, which is derived and git-ignored, so the migration is to
re-run `pramaanx extract`. Bronze is unaffected — the field is recoverable from
the referenced observation.

## Version 1

Initial contracts: `Observation`, `EventMention`, `EventHypothesis`,
`ForecastRecord`, `OutcomeRecord`.
