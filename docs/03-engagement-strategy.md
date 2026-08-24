# Engagement Strategy: Taking This Project to C-DAC

## Part A — Verification: has C-DAC closed the gap? (as of 24 Aug 2026)

**Finding: no, not in the public record.** Confidence: high on the public record, zero claim about internal work.

What was checked, and what turned up:

| Check | Result |
|---|---|
| Follow-up implementation of the promised system ("a new approach is being developed… predicting events from unstructured text with substantial supportive evidence") | **Not found.** Open loop since 2020. |
| Any C-DAC event-forecasting dataset, benchmark or corpus | **None found.** |
| Any C-DAC entry on ForecastBench / FutureX / MIRAI / VIEWS challenge / CASE shared tasks | **None found.** |
| Any C-DAC public code repository for event prediction | **None found.** |
| Continued output by the same authors | **Yes — but same mode.** Comparative/survey papers in Springer conference proceedings: *A Novel Approach of Deduplication on Indian Demographic Variation* (WorldS4 2021); *Object Detection in Computer Vision: A Comparative Analysis of Advanced Computer Vision Models* (IC3T 2024, pub. 2025). |
| Any sign the group moved into the modern stack | **Yes.** Recent work by ShivaKarthik et al. on robust multilingual language identification with **romanised script detection using LLMs and RAG**. They are in the LLM+RAG era and working on romanised/code-mixed Indic text. |

**Two honest caveats.**
1. Absence in public indices is not absence of work. A MeitY lab serving security-adjacent users can have a running system that never appears in any index. Nothing here contradicts that; nothing here supports it either.
2. Indian conference and journal venues are unevenly indexed, and Scholar/dblp/Academia were not directly reachable from this session. A paper in a poorly-indexed proceedings could have been missed. The probability that a *system with a public evaluation* was missed is low — that kind of artifact leaves traces (GitHub, dataset DOI, leaderboard entry) and none exist.

**What this means strategically:** the loop their own paper opened is still open, and they now have adjacent competence (LLM + RAG + romanised Indic) but no closed forecasting loop. That is the exact shape of an opening.

---

## Part B — How to gain the most

### B0. Decide what "gain" means, because the plays differ

Three currencies, and only one of them erodes if you're careless:

- **Standing inside C-DAC** — selection, an internship converted, a Joint Director who remembers your name.
- **Portable credentials** — a public artifact with your name on it that works outside that building: a repo, a benchmark, a preprint, a co-authored paper.
- **Capability** — what you actually learn to build.

Standing and capability accrue regardless. **Portable credentials are the ones you can lose by default**, because government project deliverables become internal artifacts. Everything in B5 exists to protect that one.

### B1. The single highest-leverage move: complete them, don't compete with them

Their 2020 paper ends, in print, with a promise of a system that never publicly appeared. That is an unclosed loop with their names on it.

**Walk in with the closed loop.** The frame is:

> "Your gap analysis specified what was missing. I built a system against that specification and measured it. Here's the evidence."

This makes them the origin of the work and you the person who executed it. Maximum credit transfer, zero threat.

**Never** present it as a critique. Do not say "your paper had no baselines." Do not show them a table where they lose. The competitive analysis in `01-competitive-analysis.md` is *your* private map for deciding what to build — it is not a document you hand to them, and no slide should be derived from it in a way that reads as an audit of their work.

### B2. Bring the thing they structurally cannot produce: evidence

They have data access, deployment channels, mandate, and compute. They do not have — by incentive, not by ability — benchmarks, baselines, prospective evaluation, or calibration.

So the complement you bring is **the evaluation apparatus**, not another model.

This matters more than it sounds. A model is easy to dismiss, easy to replace, easy to absorb. A scoreboard makes you the referee, and referees are much harder to replace than players. If the group ends up using your evaluation harness to judge their own work, you are structurally embedded in a way that no model contribution achieves.

### B3. Scope: one narrow vertical, fully closed, 6–10 weeks

Not a platform. Not a framework. One vertical, end to end:

> District-level (admin-2) forecasting of one event class — protest / strike / bandh — for 2–3 Indian states, 1–4 week horizon, from Indian news in English + Hindi (+ one regional language), with a **live weekly scoreboard** and a beaten **no-change baseline**.

A fully working narrow tool beats a half-built platform in every review room that has ever existed. And the no-change baseline is the point: VIEWS' own flagship challenge showed most academic teams cannot beat it. If yours does, with calibrated intervals, that is a real result — and it is legible to a government reviewer in one sentence.

### B4. Deployability constraints are a feature, not a tax

If your demo calls an external API at inference time, it is dead on arrival in that building. Build for it from day one:

- **Open weights only** at inference (Sarvam / Qwen / Llama class), quantised, runs on PARAM/AIRAWAT-class hardware
- **Air-gappable** — no external dependency at run time
- **Data stays in-country** — say this explicitly, it will be asked
- **Audit trail per alert** — every forecast traces to the articles and features that produced it

Western SOTA systems never have to satisfy these. You do, and that is a differentiator you can state out loud.

### B5. Protect your leverage *before* you hand anything over

Do these in this order, and do them early:

1. **Build on public data.** GDELT, ACLED, POLECAT, public news RSS. Work built on public data before or outside a formal engagement stays portable. Work built on their internal data does not.
2. **Timestamp publicly.** A GitHub repo under a permissive licence (MIT/Apache-2.0) and a dated Zenodo or arXiv preprint, *before* you hand over code. This costs an afternoon and permanently fixes provenance.
3. **Split the artifact.** Two things, two homes:
   - the **system** — hand it over, integrate it, let it be theirs;
   - the **benchmark and corpus** — keep it public, under your name, separately licensed.
   Give away the player, keep the referee.
4. **Ask about authorship before, not after.** One light question early — *"if this works out, is it something we'd publish jointly, and who'd be on it?"* — is normal, professional, and settles the thing while it costs nothing. Asking after the work is done is a negotiation; asking before is a clarification.

### B6. The pitch, six slides

1. **Their own gap table from the 2020 paper, verbatim, with your checkmarks against it.** This is the slide that does the work. It says: I read your paper carefully, I took it as a specification, here is the specification met.
2. **Live demo.** Working, on real current news, not curated examples.
3. **Scoreboard.** vs no-change and recurrency baselines, stratified novel vs recurring, with calibration.
4. **The Indic result.** Performance on Hindi / code-mixed / romanised text — the thing no foreign system does, and the thing they *already care about* given their language-ID work.
5. **Deployment + governance.** Runs on their infra, air-gappable, audit trail, stated misuse limits.
6. **The ask.** Data access, compute, a mentor, a scope for phase 2. Always end with an ask — it converts a presentation into a project.

### B7. Governance posture, stated up front

This is unrest forecasting handed to a government body. Have an explicit boundary before anyone asks:

- aggregate and geographic level only, never person-level targeting
- no individual social-media profiling
- audit trail on every alert
- documented failure modes and a published miss log

Two reasons. It is right. And in a review room it reads as maturity rather than naivety — there is a published CSCW critique of exactly this class of product, and showing that you have read it and designed against it puts you above the median applicant instantly.

### B8. Your asymmetric advantage — use it as a leave-behind

You now hold a current map of a field that a Joint Director does not have time to track weekly. A **short, neutral field brief** — what the state of the art is in 2026, what the open problems are, what it would cost to be competitive — is genuinely valuable to them, and it positions you as someone who *reduces* their uncertainty rather than someone who adds work.

Write it as a forward-looking landscape, not as a comparison against their output. Same facts, entirely different document.

### B9. What not to do

- Don't lead with Western leaderboard numbers. Nobody in that room is scored on ICEWS MRR.
- Don't build a chatbot wrapper.
- Don't demo anything that only works on hand-picked examples.
- Don't critique the 2020 paper, at all, in any register.
- Don't over-scope.
- Don't hand over the only copy of anything.

---

## Expected-value summary

Maximise `P(accepted) × value(outcome) × P(you keep something portable)`.

- `P(accepted)` rises with: their-gap-table framing, a working demo, Indic results, deployability.
- `value(outcome)` rises with: owning the evaluation layer rather than the model, and ending with an ask.
- `P(portable)` rises with: public data, early timestamping, split licensing, and asking about authorship before the work rather than after.

The three move together almost everywhere. The only real tension is B5 vs. speed — protecting provenance costs you an afternoon up front. Spend it.
