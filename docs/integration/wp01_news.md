# WP1 → WP9: wiring the news layer

WP1 owns the news data layer but not the surfaces that register it. This file
records everything WP9 has to add, and why WP1 deliberately did not add it.

Nothing here is a bug or an oversight. Every item is a shared integration
surface that a package running in parallel with WP4 and WP5 must not touch,
because two packages editing `config.py` is how the previous collision
happened.

## What WP1 built

| File | Contents |
|---|---|
| `src/pramaanx/ingest/article_content.py` | `ArticleRecord`, licence classes, retention, canonical URLs, syndication grouping, `latest_as_of`, immutable snapshots |
| `src/pramaanx/ingest/news_registry.py` | `NewsSourceEntry`, `NewsSourceRegistry`, effective dating, credential hygiene, `coverage_gaps` |
| `src/pramaanx/ingest/connectors/news.py` | `NewsAcquisition` protocol, `FeedAcquisition`, `JsonApiAcquisition`, `LicensedArchiveAcquisition`, `NewsConnector` |
| `src/pramaanx/ingest/source_health.py` | `SourceHealth`, `CoverageReport`, outage classification, `coverage_interpretable` |
| `configs/sources/news_india.yaml` | The shipped Indian source registry |

## 1. The connector is not registered

`NewsConnector` is **not** decorated with
`pramaanx.ingest.base.register_connector`, and `news.py` is **not** imported
from `src/pramaanx/ingest/connectors/__init__.py`.

Registration is refused today by construction: `register_connector` requires an
entry in `pramaanx.config.SOURCE_OPTION_MODELS`, and
`tests/contracts/test_source_contracts.py` requires an entry in
`pramaanx.ingest.contracts.SOURCE_CONTRACTS`. Both are shared files.

To wire it, WP9 needs to:

1. Add a `NewsSourceConfig(SourceOptions)` block to `config.py` and register it
   as `SOURCE_OPTION_MODELS["news"]`. `NewsConnector` already accepts the
   `options_model` contract; nothing in `news.py` needs to change.
2. Add a `SourceContract` for `news` to `contracts.py`. It must start at
   `VerificationState.DOCS_ONLY` or `UNVERIFIED` with a `blocker`, because **no
   live publisher feed has ever been called from this code** (see §5).
3. Import `NewsConnector` from `connectors/__init__.py`.
4. Extend the parametrised lists in `tests/contracts/test_source_config.py`
   (`consumed_options_are_declared`, `no_connector_reads_options_by_string_key`)
   to include `news.py`.

## 2. The registry ships under `extras`, not `sources`

`configs/sources/news_india.yaml` puts the registry at
`extras.news_registry`, read by `NewsSourceRegistry.from_extras(settings.extras)`.

This is not a workaround for validation. `sources` holds *connector options*
and is validated against `SOURCE_OPTION_MODELS`, which the news connector is
not yet in; `extras` is a first-class `Settings` field, so the registry is
validated as part of the config and — importantly — **travels in
`Settings.config_hash`**. A run performed under different licence terms is
therefore not mistakable for one performed under these, which is the property
that actually matters.

WP9 may promote it to a first-class `NewsConfig` block. If it does, keep it
inside the config hash, and keep `EXTRAS_KEY` working for one release so
existing snapshots stay loadable.

## 3. No CLI commands

WP1 added no CLI surface. `tests/contracts/test_cli_surface.py` pins the
command list, and that file is a shared integration surface.

The natural commands, and the functions behind them:

| Command | Backed by |
|---|---|
| `pramaanx news acquire` | `NewsConnector.acquire` / `.plan` (`--dry-run` already exists as `plan`) |
| `pramaanx news snapshot` | `article_content.write_snapshot` (dry-run, manifest, input/output hashes, overwrite refusal all implemented) |
| `pramaanx news health` | `source_health.build_coverage_report` |
| `pramaanx news group` | `article_content.group_syndication` |

Every write path already supports `--dry-run`, an explicit cutoff, an immutable
manifest, input and output hashes, deterministic ordering, and refusal to
overwrite. The CLI needs to pass those through, not re-implement them.

## 4. `first_resolvable_at` and the existing `Observation`

`ArticleRecord` is a separate model from `pramaanx.schemas.observation.Observation`.
It carries **four** timestamps where `Observation` carries three, because news
has a revision timestamp that humanitarian and event feeds do not.

`ArticleRecord.first_resolvable_at` corresponds to `Observation.first_observed_at`:
it is the only field cutoff filtering reads. When WP9 bridges news records into
the evidence ledger, map those two fields to each other and nothing else — in
particular, do **not** map `published_at` onto `first_observed_at`, which is the
exact substitution `tests/leakage/test_news_as_of.py` exists to catch.

## 5. What has **not** been validated

Stated plainly, because "implemented" and "validated" are different claims:

- **No live publisher feed has ever been called from this code.** Every adapter
  takes an injected byte reader; every test fills it from a recorded fixture.
  The RSS, Atom, publisher-API, GDELT-article and ReliefWeb-report shapes are
  parsed from fixtures written for these tests, not from captured responses.
- **No licensed news corpus exists.** `pti_wire`, `ani_wire`,
  `regional_ml_feed` and `regional_bn_feed` in the shipped registry are entries
  for sources nobody has an agreement with. The two regional feeds are
  `enabled: false`; the two wire entries are `licence_class: unknown`, which
  retains hashes only.
- **No HTTP client is wired in.** `FeedAcquisition` and `JsonApiAcquisition`
  take `reader: Callable[[], bytes]`. WP9 supplies
  `pramaanx.ingest.http`; WP1 deliberately did not, so that no test could reach
  a network by accident.
- **Pagination is not implemented.** A single reader call returns one payload.
  Real feeds page, and the reader abstraction is where that belongs — but a
  paging walk that has never met a real `nextPage` link is a guess, and the
  ReliefWeb connector's envelope-strictness tests show what it costs to guess
  wrong.
- **Expected volumes are estimates.** `expected_items_per_day` in the shipped
  registry drives `retrieval_completeness` and therefore every outage
  classification. The current values are plausible, not measured. Until they
  are measured against real delivery, an `OutageStatus.HEALTHY` from this layer
  means "delivered roughly what somebody guessed", and no operational decision
  should rest on it.
- **District coverage is unmeasured.** `compute_source_health` accepts an
  injected `district_resolver` and reports `districts_resolved=False` when none
  is supplied. WP0 owns district identity; WP1 does not import it, so district
  coverage is structurally available and currently empty.

## 6. Things that must not be "simplified" later

Three properties look redundant and are not:

- **`coverage_interpretable` travels with the counts.** `SourceHealth.as_feature_row`
  emits it alongside `retrieved_documents` on purpose, so a feature builder
  cannot consume the volume without the reason to distrust it. A zero from an
  out source is a missing value spelled with a digit.
- **`publisher_timestamp_disputed` is not optional bookkeeping.** When a
  publisher claims to have published after this project downloaded the article,
  the claim is kept and marked rather than corrected or dropped. A source whose
  clock drifts is a source whose delay statistics mean nothing, and that has to
  stay visible.
- **`UNKNOWN` and `PROHIBITED` licence classes store the same thing and are
  different states.** One is an action item, the other a settled fact.
  Collapsing them would lose the only signal that says which publishers are
  worth approaching.
