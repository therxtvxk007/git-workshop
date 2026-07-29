# Math visualization design system

A design system for figures whose job is to **teach a mathematical idea**, not to
report data.

---

## 1. How to select a design system (the actual decision)

The common mistake is to treat this as shopping — Material vs. Tailwind vs.
shadcn vs. Radix — and then to judge candidates on how they look. That question
is nearly irrelevant here, because a design system is really three separable
layers, and they have completely different economics:

| Layer | What it covers | How to source it |
|---|---|---|
| **L1 Perceptual** | color, contrast, colorblind separation | **Inherit + verify.** This layer is *computable*. Never choose by taste. |
| **L2 Structural** | type scale, spacing, surfaces, controls, dark mode | **Inherit wholesale.** Cheapest layer to adopt; almost any competent system will do. |
| **L3 Semantic** | what a color *means*, which figures exist, what order things appear in | **Author it yourself.** No general-purpose design system has this for mathematics. |

So the optimisation is:

> **Stop evaluating L1/L2 candidates. Inherit them from one validated system,
> then spend all your effort authoring L3.**

A figure fails to teach because its colors are arbitrary and its build order is
wrong — never because it used the wrong grid system. L3 is the entire game, and
it is the layer nobody ships for you.

This document inherits L1/L2 from the `dataviz` skill and authors L3 below.

---

## 2. What is inherited unchanged

From `dataviz`, taken as-is: the ramps, the surfaces, the chrome/ink roles, the
dark-mode discipline (dark steps are *selected*, never an automatic flip), the
texture channel, `tabular-nums` for aligned digits, and — most importantly — the
rule that **the palette is validated by script, not by eye**.

```
node scripts/validate_palette.js "#2a78d6,#eb6834,#1baf7a" --mode light --pairs all
node scripts/validate_palette.js "#3987e5,#d95926,#199e70" --mode dark  --pairs all
```

Both pass. Light mode returns one contrast WARN (aqua at 2.74:1), which invokes
the relief rule — visible direct labels required. Math figures label every
constructed object anyway, so the relief is satisfied by construction.

---

## 3. Where this system deliberately overrides `dataviz`

Three overrides. Each is a narrow, justified exception — not a general licence to
drift.

### 3.1 Serif notation is required

`dataviz` says: system sans everywhere, no serif face anywhere.

**Override:** mathematical notation is set in a math/serif face with italic
variables. This is not decoration — italic serif *is* the notation. Roman `d`
and italic *d* mean different things; a sans-serif `l`, `1`, and `I` collapse
into each other.

The override is scoped strictly to notation. Prose, labels, axes, controls, and
readouts stay in the system sans.

Use native **MathML** — every current browser renders it, it needs no external
font or library (which the artifact CSP would block anyway), and screen readers
announce it as mathematics rather than as scrambled punctuation.

```css
math { font-family: "Latin Modern Math", "STIX Two Math", "Cambria Math", Georgia, serif; }
```

### 3.2 Color encodes *role in the argument*, not identity

`dataviz` says: color follows the entity, never its rank.

**Override:** in a teaching figure, color follows the entity's **role in the
argument** — and roles change as the argument proceeds. When a secant line
becomes the tangent line, it *changes color*, because it has stopped being
scaffolding and become the conclusion. That colour change is the pedagogical
payload of the whole figure.

This is safe precisely because the `dataviz` rule exists to stop a filter from
repainting survivors *arbitrarily*. Here the repaint is the meaning.

### 3.3 Three colors, hard cap

Math figures are **all-pairs** forms: everything is on screen at once and
adjacent to everything else. Per the validator, only the first three slots clear
the all-pairs floors in both modes. So this system caps at three semantic hues —
and that cap is derived, not stylistic.

It is also sufficient. A figure needing a fourth color is a figure trying to
teach two ideas; split it.

---

## 4. The semantic palette (L3)

| Role | Meaning | Light | Dark |
|---|---|---|---|
| **Object** | the given — the thing under study | `#2a78d6` | `#3987e5` |
| **Construction** | scaffolding you add in order to reason | `#eb6834` | `#d95926` |
| **Result** | what the argument yields | `#1baf7a` | `#199e70` |

Everything else — axes, grid, gridlines, prose, the ambient plane — is ink and
neutral, drawn from the inherited chrome roles.

**The varying quantity gets no hue.** The parameter being pushed to a limit
(`h → 0`, `ε`, `n → ∞`) is expressed through **motion, position, and a readout** —
never a fourth color. This is the rule that keeps the three-color cap livable,
and it is also more honest: a limit is a *process*, and process is carried by
change over time, not by pigment.

```css
--math-object:       #2a78d6;
--math-construction: #eb6834;
--math-result:       #1baf7a;
```

---

## 5. The pedagogy layer

Rules `dataviz` has no opinion about, because data charts do not argue.

**One idea per figure.** If you cannot state the figure's claim in a single
sentence, it is two figures.

**Build, don't present.** A finished diagram with six labeled objects teaches
nothing — the reader cannot tell what depended on what. Reveal in the order the
argument runs: given → construction → limit → result. Every figure ships a step
control.

**Label directly, always.** No legend-hunting. The tangent line is labeled
*tangent*, on the line. This also discharges the light-mode contrast relief.

**Show the quantity, not just the picture.** A geometric claim gets a numeric
readout beside it, in `tabular-nums`, so the reader watches the number converge
while the picture moves. Picture and number must agree at every frame — that
agreement is what builds trust in the notation.

**Let them break it.** The reader must be able to drag the point to where the
claim is *interesting* — a corner, an inflection, a discontinuity. A figure that
only works at the author's chosen parameter is a figure the reader cannot test.

**Motion is explanation, so make it interruptible.** Animate only the varying
quantity. Honor `prefers-reduced-motion` by replacing continuous animation with
discrete steps the reader advances — never by removing the information.

---

## 6. Checklist

- [ ] Claim stated in one sentence
- [ ] ≤ 3 semantic hues; varying quantity carried by motion, not a 4th hue
- [ ] Palette re-validated by script after any color change, both modes
- [ ] Notation in MathML; prose and controls in system sans
- [ ] Every object direct-labeled
- [ ] Numeric readout agrees with the picture at every frame
- [ ] Step control present; build order is argument order
- [ ] Parameters draggable into the interesting cases
- [ ] Dark mode selected, not flipped
- [ ] `prefers-reduced-motion` gives steps, not stillness
