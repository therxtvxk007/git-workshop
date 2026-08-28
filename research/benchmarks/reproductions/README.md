# Reproduction run manifests

One immutable JSON file per run, named `<run_id>.run.json`.

Run identifiers are derived from the contract hash, the official commit, the
dataset and split hashes, the environment hash, the command and the seed — never
from a clock. The same plan on another machine produces the same identifier.

Manifests are never overwritten. A second attempt at the same run is recorded as
a **rerun**, with `is_rerun_of` pointing at the first; it does not replace it.
Failed runs stay here, because a directory that keeps only the successful runs
turns a reported score into the maximum over attempts.

**Empty.** No reproduction has been run. Every benchmark in the registry is
`contract_incomplete`, and `python -m pramaanx.benchmarks reproduce <id>` refuses
with the specific blockers rather than producing a manifest.
