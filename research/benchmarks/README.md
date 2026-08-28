# Benchmark registry

Machine-readable contracts for every benchmark this project has committed to,
including the ones it is blocked on.

- `registry.yaml` — the index: one entry per benchmark, pointing at its contract.
- `contracts/` — one YAML file per benchmark. This is the source of truth.
- `reproductions/` — immutable run manifests, one JSON file per run. Empty until
  a reproduction actually runs.

Read it with:

```
python -m pramaanx.benchmarks list
python -m pramaanx.benchmarks show <benchmark_id>
python -m pramaanx.benchmarks validate
```

## What a contract is for

A benchmark claim is an assertion about someone else's published number. The
only way to make one checkable is to write down, before running anything, which
artefacts it depends on: which commit, which dataset version, which split, which
metric implementation, which seeds, which statistical test.

The registry is fail-closed. A contract is invalid until it proves otherwise,
and no model may be described as **reproduced**, **challenged** or **exceeded**
unless its complete contract and its run artefacts satisfy every rule in
`pramaanx.benchmarks.verification`.

## Unknown is a value

A field nobody has verified is `null` and carries a blocker naming it. It is
never a plausible-looking guess. A guessed commit or an invented dataset version
does not fail loudly — it produces a run that looks reproduced and is not.

Every blocker names the contract field it applies to and why, so a report can
say precisely what would have to be learned to unblock the benchmark.

## Status is computed, not declared

`status:` in a contract file is a claim, and `validate` checks it against the
evidence. A record that says `reproduced` with no successful control run inside
tolerance fails validation. "Code exists" is `not_started`; eleven states
separate it from `reproduced`.

## The registry keeps its failures

Blocked benchmarks stay listed. Failed runs stay in `reproductions/`. A registry
that records only what went well is a marketing document — the same argument
that governs `research/experiment_registry.yaml` governs this one.

## Current state

All thirteen contracts are `contract_incomplete`. Nothing has been reproduced,
and no published score in this registry has been verified against its primary
source: `arxiv.org`, `aclanthology.org` and `journals.sagepub.com` were all
refused by the network egress proxy of the environment the registry was built
in. Where a score is recorded, it is recorded as a claim awaiting verification,
with `verified_against_primary: false` and a blocker on `published_score`.

What *was* verified, directly from the official repositories: repository URLs,
licences where declared, default branches, tags, environment files, entrypoint
commands and dataset names. See `docs/integration/wpb0_benchmarks.md` for the
per-benchmark record of what was checked and what was not.
