# Replay acceptance

Two operations share one module, `src/pramaanx/ingest/replay.py`, and one
verification pass. Conflating them is the mistake this page exists to prevent.

| Operation | Question it answers | Entry point |
| --- | --- | --- |
| **Verify** | Is the bronze in this data root intact, and what does it contain? | `pramaanx replay verify` |
| **Restore** | Can this archived bronze be put somewhere else and still be the same evidence? | `pramaanx replay restore --source <root>` |

Neither answers the other's question. Verify never writes evidence; restore
never asks a connector for any.

## Why replay is a verification pass, not a read

Bronze is append-only and content-addressed, which makes replay possible. It
does not make it verified. Between an ingestion and a replay a payload can be
deleted, its bytes can change underneath a reference that still resolves, a
source record can go missing, or an acquisition can have died halfway.

Every one of those reads, to naive code, as a **smaller corpus** — and a smaller
corpus does not raise. It quietly produces a forecast from less evidence than
the run it claims to reproduce, and its output is indistinguishable from a
legitimate one.

## The eight defects

| Defect | What it means |
| --- | --- |
| `missing_payload` | The payload reference does not resolve. The evidence is gone. |
| `payload_hash_mismatch` | It resolves, but the bytes no longer hash to what was recorded. |
| `unknown_source` | An observation cites a source with no record — licence, tier and version unknown. |
| `id_collision` | Two observations share an id but not their content. |
| `non_reproducible_id` | An id does not derive from its own record's content. Strictly stronger than a collision check, which needs two records before it fires. |
| `orphaned_payload` | A stored payload no observation refers to. Bronze is written observations-last, so this is the signature of a partial ingestion. |
| `duplicate_source_record` | Two source records claim one `source_id`. |
| `impossible_timeline` | `first_observed_at` is after `retrieved_at`. |

`verify()` reports all of them and never raises. `replay()` refuses a corpus
with any of them. The split is deliberate: finding out what is wrong with a
ledger should not require doing it through an exception.

## Restore preconditions

Checked before the destination is touched, and every one raises
`ReplayArchiveError` rather than degrading:

- source and destination must not be the same root;
- the dependency lock must exist — a restore that cannot pin the dependency set
  cannot claim the restored evidence parses the same way;
- the archive must have a `bronze/` directory and **no symbolic links**, because
  a symlink makes hashing the tree and copying it two different operations;
- the archive must match `--expect-hash` when one is given;
- the destination must be empty, or already contain this exact archive. A ledger
  assembled from two archives has provenance belonging to neither.

The copy goes to a staging directory, is re-hashed after copying to catch a
mid-copy change, and is committed with a single rename — so the destination is
either the whole archive or absent, never a half-copy that looks complete.
Restoring the identical archive twice is a no-op, which is what makes the
operation safe to retry.

## What is pinned

Source versions, source contracts, config hash, code hash, and the dependency
lock hash. A missing `uv.lock` records the literal `"absent"` rather than
`None`: an environment without it genuinely has different provenance, and
saying so is what stops two incomparable replays comparing equal.

`created_at` and `replay_id` are excluded from the replay hash, so two replays
of the same bronze under the same pins agree a week apart.

## Provenance of this design

Two implementations were built in parallel and merged rather than one being
discarded — Track A's in-place verification, and a Codex implementation of
archive restore (`codex/pramaan-x-deterministic-replay`, commit `7cd8c8e`).

Three checks came from the Codex side and are strictly stronger than what was
here: `non_reproducible_id`, `orphaned_payload` and `duplicate_source_record`.
The first caught a real defect in this repository's own test fixtures, which
were minting observation ids from `datetime.isoformat()` while
`EvidenceLedger.observation_from_item` uses `utc_isoformat` — ids production
could never produce, in tests that passed.

The whole restore path, its symlink and staging discipline, and the CI gate are
also from that implementation.
