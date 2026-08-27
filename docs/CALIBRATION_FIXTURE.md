# The calibration fixture

Phase 2's downstream half records two open dependencies. One of them —
"the frozen snapshot plus outcome registry fixture does not exist yet, so the
calibration fitters have no realistic sample" — is closed by this document.
It did not need new evidence. The M0 demo already produces the sample; nothing
had named it, pinned it or proved it reproduces.

## Verification status

| Claim | Status | Evidence |
| --- | --- | --- |
| `sample_exists` | `true` | 2,086 rows, 684 positives, base rate 0.3279, across 9 folds. |
| `regenerates_offline` | `true` | No network, no credentials. `make demo` builds it in about twenty seconds. |
| `reproduces_on_a_clean_workspace` | `true` | `tests/integration/test_calibration_fixture.py` bootstraps a scratch world under a different data root and requires the pinned manifest to verify. |
| `drawn_from_real_prose` | **`false`** | The world is synthetic. See the caveat below — it is the row that limits every use of this fixture. |
| `outcomes_adjudicated` | **`false`** | The registry is machine-derived; all 785 outcomes are `PENDING`. |

## What it is

`pramaanx.fixtures.load_calibration_sample` returns a `CalibrationSample`:
pooled `(probability, label)` pairs plus the fold structure that produced them.
The pairs come from `ScoringResult`, the one place where the persisted
forecasts and their match results are both in hand, so the fixture's labels
are the backtest's labels by construction rather than by a second
implementation that could drift from it.

The sample is worth fitting against because it is *badly calibrated*:
calibration slope 0.036, expected calibration error 0.133, Brier 0.237 against
a base rate of 0.328. There is real miscalibration for a calibrator to correct
and ~684 positives to support a Hoeffding bound, so a fitter that does nothing
and a fitter that works produce visibly different numbers.

## Why it is a recipe, not committed data

The generated world is 46 MB of bronze. Committing it would put derived bytes
under review and invite someone to edit the fixture rather than the generator
behind it. The synthetic world is seeded, so the fixture ships instead as a
regeneration recipe plus `research/fixtures/calibration_v1.json`, a manifest
of what regenerating must produce.

```bash
make demo                                          # or scripts/bootstrap_data.py
python scripts/build_calibration_fixture.py        # verify against the manifest
python scripts/build_calibration_fixture.py --write  # re-pin, deliberately
```

Verification failing is the point: a fixture that can move silently takes
every number fitted against it with it.

## The portability problem, and what it means beyond this fixture

The first version of this manifest pinned `config_hash` and the per-fold
snapshot hashes. It failed immediately on a clean workspace, and the cause is
worth recording because it is **not** specific to fixtures.

`Settings.config_hash` is `hash_object(self.model_dump(mode="json"))` — the
whole resolved settings model, including `storage.data_root`. Change the data
directory and the config hash changes:

```
data_root=/a  ->  sha256:4d292c61412e4360...
data_root=/b  ->  sha256:163cb846f234bb7f...
```

Snapshot hashes fold in `config_hash`; forecast identifiers derive from
snapshot hashes; the scoring pass reads forecasts sorted by identifier. So the
*order* of the pooled rows depends on where the data directory lives. The
content does not — the per-fold multiset of `(probability, label)` pairs is
byte-identical across data roots, which is what made a portable fixture
possible at all.

Two consequences reach past this file:

1. **Snapshot identifiers, forecast identifiers and report hashes are
   machine-local.** CI's `make demo` produces different snapshot IDs than a
   developer's laptop over identical evidence. Any acceptance criterion that
   compares these across machines is comparing path strings.
2. **"The M0 acceptance hashes should not move" holds only per machine.**
   Phase 2's calibration work is right that its injectable defaults are
   behaviour-preserving, but that claim has to be checked on one box, not by
   comparing a CI hash to a local one.

Neither is this fixture's to fix. Making `config_hash` cover configuration
rather than filesystem layout is a change to `config.py`, which is contested
by three unmerged branches; it is recorded here so the decision is taken
deliberately rather than discovered again.

## Using it

```python
from pramaanx.fixtures import load_calibration_sample

sample = load_calibration_sample("configs/experiments/e2e_v1.yaml")
fit, validate = sample.split_at_fold(6)   # folds 0-5 fit, folds 6-8 validate
```

`split_at_fold` is the only split offered. Conformal coverage assumes
exchangeability, temporal data violates it, and a random split would hide the
violation instead of exposing it — so the fixture makes the temporal split the
easy path and the random split absent.

## The caveat that travels with every number

> This sample comes from the seeded synthetic world with a machine-derived,
> unadjudicated outcome registry. It measures agreement with automated
> resolution, not with reality, and establishes nothing about real prose.

`SYNTHETIC_CAVEAT` is a field on `CalibrationSample` and on the manifest, so it
is carried rather than remembered. This fixture can exercise a fitter, expose a
numerical bug and anchor a regression test. It cannot support a claim that a
calibrator works. That needs the prose connectors — Phase 1A ReliefWeb and 1B
ACLED — merged, and a real corpus that this environment's egress policy
currently blocks.
