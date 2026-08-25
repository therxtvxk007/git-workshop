# Architecture notes

Companion to the README. This file explains *why* the pieces are shaped the way
they are, and which decisions are load-bearing for later phases.

## The decomposition

```
candidate discovery -> candidate adjudication -> calibration -> risk-controlled alerting
```

The decomposition is not an implementation detail. A model cannot score a future
event that never entered the candidate pool, so discovery gets its own
interface, its own metrics and its own failure mode. Conflating discovery with
scoring makes a recall failure look like a probability failure, and the two have
completely different remedies.

M0 implements stage one and the scaffolding around it. Stages two to four are
named in every forecast record (`calibration: identity@uncalibrated`,
`alert_policy: fixed_threshold@placeholder`) so that no downstream consumer can
mistake their absence for their presence.

## Load-bearing decisions

### Availability time, not event time

`Observation.first_observed_at` answers one question: when could this project
legitimately have seen this? Not when the event happened, not when a publisher
claims to have published.

This is the single field cutoff filtering runs on, and getting it wrong is the
only bug that silently defeats every guarantee downstream. It is why the GDELT
connector uses the export slot rather than `SQLDATE`, and why
`Connector.guarded_fetch` treats an out-of-window item as a hard error rather
than a rounding issue.

### Append-only bronze

A story edited after the cutoff cannot overwrite its earlier self. It becomes a
new observation with a later `first_observed_at`, which the guard excludes.

This turns "detect updated bodies" from an unsolvable text-forensics problem
into a structural property. The remaining hole — evidence that lies about its
own observation time — is not closable by the ledger, which is why
`leakage_audit` screens for identical content appearing under distant dates, and
why the metamorphic suite has an explicit negative control demonstrating that
back-dated evidence *does* get in.

### Content-only snapshot hashes

The snapshot hash covers sorted observation hashes, source versions, code hash
and config hash. It does not cover creation time or file layout.

Without this, the M0 gate would be untestable: "the forecast is unchanged" could
only ever mean "roughly similar", because every rebuild would produce different
bytes. With it, the assertion is literal equality.

Snapshot identity deliberately includes the code hash, so a snapshot pins the
evidence *and* the logic that selected it. Editing the guard produces a new
snapshot id even over identical evidence, which is the intended behaviour: the
old id still refers to what the old code admitted.

### Determinism as a testable property

No `uuid4`, no `datetime.now()` outside an injectable `Clock`, no Python
built-in `hash()` anywhere its value escapes the process (it is salted per
process). Identifiers derive from content. Sorting is explicit at every
aggregation boundary.

This is not tidiness. A pipeline that cannot be shown deterministic cannot be
shown leak-free, because "the output changed" stops being evidence of anything.

### Ground truth is derived, never injected

The synthetic world does not hand the pipeline its latent events. It publishes
reports *after* they happen, and the outcome registry is built from those
reports — the same path a real deployment would use. `ground_truth()` exists for
test assertions only and is never called by the pipeline.

The alternative — injecting known answers — would make the whole loop untestable
in the one respect that matters, because the system would be scored against
information it could in principle have reached.

### Uncertainty is not one number

`epistemic_uncertainty` on an M0 forecast means exactly one thing: the width of
the credible interval on the occurrence probability, from the Gamma-Poisson
posterior. It is recorded under that narrower meaning.

Generator disagreement, evidence insufficiency, candidate instability and
distribution shift are different quantities that Phase 8 will have to combine
deliberately. Collapsing them into one float now would make the later work
harder and the current number dishonest.

## Where later phases attach

| Phase | Attaches at | Interface it uses |
| --- | --- | --- |
| 1 — more Tier-0 sources | `ingest/connectors/` | `Connector` + `register_connector` |
| 2 — learned extraction | `extraction/` | replaces `structured.py`, same `EventMention` output |
| 5–6 — G1–G7 generators | `generators/` | `CandidateGenerator` + `register_generator` |
| 7 — BLF adjudication | between `merge_proposals` and probability in `pipeline.py` | consumes `CandidateProposal`, emits a probability |
| 8 — calibration and risk | between probability and `status` in `pipeline.py` | replaces `IDENTITY_CALIBRATION` and `assign_status` |
| 10 — API and operations | around `ledger/forecasts.py` | reads the immutable forecast ledger |

Adding a generator is a registration plus a config line; nothing upstream or
downstream of it changes. That is the main thing M0 was shaped to buy.

## Deliberate omissions

`merge_proposals` already preserves per-generator traces and the union of
`generated_by`, even though M0 has one generator and therefore nothing to merge.
This is not speculative generality: the rule that the union stage may merge
candidates but may never erase which branch proposed them is what makes the
candidate-oracle diagnostic possible, and retrofitting provenance after the fact
is how that diagnostic quietly becomes unavailable.

Everything else with no M0 consumer was left out.
