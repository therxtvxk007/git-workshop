# WP2 — Deterministic multilingual NLP: integration notes

What WP2 built, what it deliberately did not build, and what a later package has
to do to wire it in. Written for whoever picks up WP3, WP4 or WP9, so that none
of them has to re-derive the boundaries from the code.

Base: `origin/claude/wp01-news-data-layer` @ `42daa4d`, tree `c6f4d519`.

---

## 1. What this package is for

`pramaanx.nlp` turns a WP1 `ArticleRecord` into a `DeterministicNlpResult`: a
set of typed mentions, each carrying a span that slices the **original** article
text exactly.

It exists to make the LLM stage checkable. A model asked to extract events can
invent a location, an actor, a date or a quotation, and the output is
well-formed either way. The only defence is to require every claim to cite a
span and to verify that span against text the model did not produce — which is
worth exactly as much as the offsets are exact.

**It assigns no probability and ranks nothing.** A deterministic preprocessor
that scored articles would be an unevaluated model sitting upstream of the
evaluated one, and its influence would never appear in any metric.
`tests/unit/test_nlp_pipeline.py::test_no_probability_is_produced` enforces this
on the schema.

---

## 2. Integration seams

Three things are injected, never imported. All defaults are inert, so a
pipeline run without them produces *visibly* incomplete output rather than
plausible wrong output.

### 2.1 Geography — for WP0

```python
class DistrictResolver(Protocol):
    name: str
    version: str
    def resolve(self, query: LocationQuery) -> LocationResolution: ...
```

`LocationQuery` carries `place_text`, `state_context`, `as_of`, `language` and
`widened`. `LocationResolution` returns `status` (`resolved` / `ambiguous` /
`unresolved`) plus `candidate_district_ids`.

- **No second district registry was built.** `NullDistrictResolver` is the
  default and resolves nothing. WP0's registry plugs in here.
- `as_of` is **required**, not optional. A district that split in 2022 has two
  correct answers depending on the date; a signature that let callers omit the
  date would guarantee half of them did.
- `search_widened` is set whenever no state context was found. Searching all of
  India is permitted; doing it silently is not.
- `pramaanx.nlp.locations.STATES` holds the 28 states + UTs. This is a small,
  closed, slow-changing set used only to *disambiguate* districts. If WP0 wants
  to own it, delete it here and inject it — nothing else depends on it.

**WP0 action:** implement `DistrictResolver` over the effective-dated registry
and pass it as `NlpOptions(resolver=...)`.

### 2.2 Actors

`ActorAliasRegistry` is effective-dated on half-open intervals, same discipline
as WP1's news source registry. Overlapping intervals *are* allowed (an actor has
several current aliases); a shared alias surfaces as `AMBIGUOUS` with every
candidate, never as a choice.

`EMPTY_REGISTRY` is the default: no actors found, rather than actors guessed
from ideology or location. The alias table itself is **not** shipped by WP2 —
populating it is a data task requiring sourcing decisions, and inventing one
here would have meant inventing proscribed-organisation lists.

**Open action:** whoever owns the actor table supplies `ActorAlias` entries with
real `effective_from` / `effective_to` dates and a provenance note per entry.

### 2.3 Language detection

```python
class LanguageDetector(Protocol):
    name: str
    version: str
    def detect(self, text: str) -> LanguageAssessment: ...
```

`ScriptHeuristicDetector` is the deterministic fallback. It never downloads a
model, and it hedges where script does not determine language.

---

## 3. The GLiNER / LLM boundary

WP2 does **not** reimplement the Codex GLiNER stage or the Gemini verification
stage. It produces the input they consume.

`DeterministicNlpResult.candidate_spans` holds **whole sentences** containing at
least one extracted signal (temporal, location, actor, target-family term, or
quotation). Whole sentences rather than matched fragments: a model asked to
confirm "Kishtwar" in isolation cannot tell an incident from a weather report;
one given the sentence can.

Suggested cascade position:

```
PatternStage → MultilingualNlpStage (WP2) → GLiNERStage → GeminiVerificationStage
```

For a verification stage, the useful contract is:

| WP2 provides | Verifier uses it to |
| --- | --- |
| `candidate_spans` | bound what gets sent, and what may be cited |
| `original_text_hash` | prove it reasoned about the same characters |
| `verify_spans(text)` | reject any returned span that does not slice the source |
| `temporal_mentions[].anchor_time` | check a date claim against the article's own clock |
| `location_mentions[].status` | refuse a resolved district the deterministic layer left ambiguous |
| `ordinary_crime_assessment` | skip articles already screened out, cheaply |

**Independence note for WP4:** a verifier that only confirms WP2's candidates
shares WP2's lineage. Agreement between the two is not independent
corroboration, and must not be counted as a second source.

---

## 4. Dependency requests

**None. WP2 adds no dependency**, and `pyproject.toml` / `uv.lock` are
untouched. Everything is stdlib plus Pydantic, which the project already has.

Two places where a dependency was considered and declined:

| Candidate | Purpose | Why not |
| --- | --- | --- |
| `fasttext` / `lingua` | statistical language ID | Would need a model file at import or first call. The `LanguageDetector` seam means a caller can add one later without touching this package. |
| `indic-transliteration` | romanisation | The nine Indic blocks share an ISCII-derived layout, so one offset table covers all of them in ~80 lines. A dependency would add install weight and a second version to pin for no accuracy gain at this scope. |
| `regex` (PyPI) | Unicode property classes | `unicodedata` + `re` covers what is needed. |
| a grapheme-cluster library | cluster boundaries | `unicodedata.combining` + category check is sufficient and has no data file. See §6. |

If a statistical detector is later wanted, add it as an **optional extra**
(`[project.optional-dependencies] nlp`), constructed by the caller and passed
through `NlpOptions.language_detector`. Do not construct it inside this package.

---

## 5. Language support — the honest version

**Represented (13):** Assamese, Bengali, English, Gujarati, Hindi, Kannada,
Malayalam, Marathi, Odia, Punjabi, Tamil, Telugu, Urdu.

"Represented" means, and only means: the script is detected correctly, text is
normalised without damage, sentences segment on the right terminators
(including danda, double danda and the Urdu full stop), the text survives the
pipeline intact, and every span slices the original exactly. All thirteen are
covered by fixtures and asserted per language.

**Not claimed — extraction quality.** These are English-first and have been
measured on no Indian-language corpus:

| Component | Coverage today |
| --- | --- |
| Temporal extraction | English patterns and month names only. A Hindi date expression is not extracted. |
| Location candidates | Relies on Latin-script capitalisation, which Indic scripts do not have. Effectively English-only. |
| Actor matching | Script-agnostic (literal alias match), but only finds aliases somebody entered. |
| Quotations | Quotation marks are script-agnostic; reporting verbs are English. |
| Retrospective cues | English only. |
| Ordinary-crime screen | English only — and this is deliberately *safe*, because unmatched text returns `INSUFFICIENT_EVIDENCE` and is **retained**. |

The ordinary-crime screen fails in the harmless direction for unsupported
languages. The others simply return less. **Nobody should describe WP2 as
working equally across thirteen languages until per-language extraction is
measured**, and that measurement needs an annotated multilingual set that does
not exist yet.

**Transliteration** covers the nine Indic scripts. Urdu is deliberately
excluded: it omits short vowels, so romanisation needs a lexicon rather than a
character map, and a mechanical attempt would produce consonant skeletons that
collide with unrelated words — worse than nothing, because it would match
aliases it should not.

---

## 6. Two findings worth carrying forward

**`PramaanModel` sets `str_strip_whitespace=True`.** That is right for names and
identifiers and catastrophic for spans: a span ending in a space silently loses
it, and the text then disagrees with the offsets by one character while still
looking like a citation. `TextSpan` and `AlignedTextView` override it. **Any
future model holding raw text or an offset-indexed string must do the same.**

**Indic vowel signs have canonical combining class 0.** Malayalam `ോ`
decomposes to `േ` + `ാ`, and both pieces report `combining() == 0`
while being spacing marks (category `Mc`). A cluster-boundary rule based on
combining class alone splits them, NFC cannot recompose across the split, and
decomposed Malayalam, Tamil, Kannada, Bengali and Assamese silently fail to
reach canonical form — so the same sentence from two feeds would hash
differently and count as two stories. `combining_clusters` therefore tests
category as well. Any future Unicode handling in this repo should do likewise.

---

## 7. Wiring required later (WP9)

WP2 registered nothing globally, by design. To wire it in:

1. **CLI** — add `pramaanx nlp run` (or fold into `extract`) taking
   `--cutoff`, `--snapshot`, `--dry-run`, writing a manifest with
   `pipeline_version`, `alias_version`, input and output hashes.
   `batch_hash()` already provides the output hash.
2. **Config** — an `NlpConfig` block for `transliterate_enabled`, the language
   detector backend name, and the alias-table path. WP2 reads none of these from
   config today; everything arrives through `NlpOptions`.
3. **Cascade** — register a `MultilingualNlpStage` implementing the existing
   `ExtractionStage` protocol. WP2 does not touch `ExtractionCascade`.
4. **Storage** — `DeterministicNlpResult` is a `VersionedModel` and can go
   straight into a `RecordTable`; it has no table spec yet.

None of this was done here because `config.py`, `cli/`, `pyproject.toml` and the
cascade registration are shared integration surfaces that WP2 does not own.

---

## 8. Test map

| Requirement | Where |
| --- | --- |
| 1 Spans slice original | `test_nlp_sentences.py`, `test_nlp_pipeline.py::TestSpansAreGrounded` |
| 2 Normalisation keeps alignment | `test_nlp_normalization.py::TestAlignmentSurvivesNormalisation` |
| 3 Repeated substrings | `test_nlp_normalization.py::test_repeated_substrings_do_not_confuse_the_mapping` |
| 4 Zero-width characters | same file + `test_nlp_determinism.py::TestInvisibleCharacters` |
| 5 Reordering is byte-identical | `test_nlp_determinism.py::TestOrderInvariance` |
| 6 Post-cutoff rejected | `test_nlp_as_of.py::TestPostCutoffArticles` |
| 7 Later revision inert | `test_nlp_as_of.py::TestRevisions` |
| 8 Devanagari ≠ Hindi | `test_nlp_language_script.py::TestLanguageIsNotScript` |
| 9 Mixed script preserved | `test_nlp_sentences.py::test_mixed_script_is_segmented_without_damage` |
| 10 Unknown language explicit | `test_nlp_language_script.py::TestEnglishVersusRomanised` |
| 11 Publication anchor | `test_nlp_temporal.py::TestRelativeExpressions` |
| 12 First-resolvable controls admissibility | `test_nlp_as_of.py::TestAnchorVersusCutoff` |
| 13 Ambiguous dates stay ambiguous | `test_nlp_temporal.py::TestAmbiguityIsPreserved` |
| 14 Place ambiguity preserved | `test_nlp_locations.py::TestResolutionIsDelegated` |
| 15 Unknown state does not widen silently | `test_nlp_locations.py::TestSearchWidening` |
| 16 Aliases effective-dated | `test_nlp_actors.py::TestEffectiveDating` |
| 17 No invented speakers | `test_nlp_quotes.py::TestNoInventedSpeakers` |
| 18 Retrospective marked | `test_nlp_retrospective.py` |
| 19 Target indicator never discarded | `test_nlp_ordinary_crime.py::TestRecallProtection` |
| 20 Original never replaced | `test_nlp_transliteration.py::TestOriginalIsUntouched` |
| 21 No model download at import | `test_nlp_pipeline.py::TestNoModelsAndNoNetwork` |
| 22 No network | same class, `socket` monkeypatched |
| 23 Alias order irrelevant | `test_nlp_actors.py::TestDeterminism`, `test_nlp_determinism.py` |
| 24 Deterministic ids and hashes | `test_nlp_determinism.py::TestRepeatability` |
| 25 Naive timestamps rejected | `test_nlp_temporal.py`, `test_nlp_pipeline.py`, `test_nlp_locations.py` |

---

## 9. Known limitations

- Extraction is English-first (§5). Not measured per language.
- Location candidate detection depends on capitalisation and so barely fires on
  Indic scripts. WP3 should not read an empty `location_mentions` on a Hindi
  article as "no places mentioned".
- Weekday expressions resolve to `AMBIGUOUS` with both readings. Correct, but a
  consumer wanting a single date needs discourse context WP2 does not have.
- The ordinary-crime lexicons are hand-written and unmeasured. They are
  recall-protective by construction, so the failure mode is cost, not missed
  events — but the precision is unknown.
- `SNIPPET_MAX_CHARS` from WP1 bounds what any span can quote from a
  snippet-licensed source. Not a bug; worth knowing when evidence looks short.
