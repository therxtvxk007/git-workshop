# India incident registry

`india_incidents.csv` — 42 mass-casualty attacks in India, 1993–2025, compiled
from public reporting for methodological evaluation.

## What it is for

It exists to make two questions answerable with a number rather than an
anecdote: *how did the region and target class of the next attack rank, given
only what was public beforehand?* and *how much better than chance is that?*

It is **not** an authoritative incident database. GTD, ACLED and SATP are, and
each is licensed. If this work goes further, one of those replaces this file and
the numbers should be recomputed against it.

## Why a retrospective dataset can be backtested on here

Most retrospective event datasets cannot support honest backtesting, because
their rows are *coded* long after the fact — attribution, casualty revisions and
investigative findings that no contemporaneous observer had. The project's own
source table records exactly this limitation for ACLED and data.gov.in.

The exception exploited here is narrow and worth stating precisely. For attacks
of this scale, four facts are public within hours through ordinary news
reporting:

- that an attack occurred,
- its date,
- its city,
- its broad target class.

Those four are the only fields the model reads. Availability time is therefore
computable from event time as `event_date + reporting_lag` (default one day),
which is what `admissible_at()` enforces — the registry is not exempt from
cutoff discipline, it is a case where the discipline is cheap to satisfy.

Everything a database like this usually carries is deliberately **absent**,
because it would not have been available on the day: no perpetrator attribution,
no claimed responsibility, no investigative findings. `fatalities` is retained
for description only and is **never a model input**, because early counts are
revised for weeks.

## Columns

| Column | Meaning |
| --- | --- |
| `date` | Date of the attack, `YYYY-MM-DD` |
| `state` | Indian state or union territory |
| `city` | City or locality |
| `target_class` | One of the six-class taxonomy below |
| `fatalities` | Approximate deaths, public reporting. Description only. |
| `note` | Short free-text descriptor |

Taxonomy, fixed a priori in `pramaanx.india.registry.TARGET_CLASS_TAXONOMY`:
`government`, `hospitality`, `market`, `religious`, `security`, `transit`.

The taxonomy is declared rather than inferred from the data. This matters: if
the class vocabulary were read off history, the first hospitality attack in the
country would be *unrankable* rather than merely unlikely, and the model would
record a discovery failure as though it were a probability failure. Fixing the
vocabulary is what lets an unprecedented pairing hold a rank at the prior.

## Known limitations

- **Selection.** Compiled from prominent public reporting, so it over-represents
  attacks in large cities and under-represents sustained low-intensity violence
  in the north-east and the Maoist belt. Any rate estimated from it inherits
  that bias, and the ranking will understate regions whose violence is chronic
  rather than spectacular.
- **Fatality figures are approximate** and vary across sources. They are carried
  for description only, and no result depends on them.
- **Coarse geography.** State-level. A state is not a threat geography; J&K and
  Maharashtra are not comparable units.
- **Sparse.** 42 events across 14 states and 6 classes. Almost every cell is
  zero or one, which is why estimates are shrunk hard toward a pooled prior and
  the credible intervals are wide.

## Sources

Compiled from public reporting and reference summaries, including Britannica's
timeline of major terror attacks in Delhi and Mumbai, Wikipedia articles for the
individual incidents, and Al Jazeera's India attack timelines. Individual rows
were cross-checked for date and location; fatality counts follow the most
commonly reported figure where sources differ.
