# git-workshop

## Math visualizations

When producing any figure, diagram, or interactive whose purpose is to **teach a
mathematical idea**, follow `design-system/math-viz.md`. Read it before writing
the first line of markup.

Summary of the parts that are most often gotten wrong:

- Exactly **three** semantic colors — object `#2a78d6`, construction `#eb6834`,
  result `#1baf7a` (dark: `#3987e5` / `#d95926` / `#199e70`). The varying
  quantity in a limit gets **motion, not a fourth color**.
- Color tracks an object's **role in the argument**, so an object changes color
  when its role changes (secant → tangent).
- Notation is **MathML** in a serif math face. Prose, controls, and readouts stay
  in the system sans. No external font or library — the artifact CSP blocks them.
- Figures **build in argument order** and ship a step control. Never present a
  finished six-object diagram.
- Re-run the `dataviz` palette validator (`--pairs all`, both modes) after any
  color change.
