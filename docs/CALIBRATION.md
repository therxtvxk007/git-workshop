# Calibration and troubleshooting

Run the test pattern first, every time you change something mechanical:

```bash
hwm calibrate -m machines/your-machine.toml -o cal.gcode
hwm send cal.gcode --port /dev/ttyUSB0
```

It plots a 60mm square, both diagonals, and twelve short dashes. Those three
things between them expose almost every problem a pen plotter has.

---

## Reading the pattern

### The square doesn't close

The finish point misses the start.

- **Missing by a lot, one axis** — steps/mm is wrong on that axis. Measure the
  side you actually got and scale: `new = old × (wanted / measured)`. So a 60mm
  side that came out 57mm with `$100=80` becomes `80 × 60/57 = 84.2`.
- **Missing by a little, randomly** — the machine is losing steps. Lower
  acceleration (`$120`/`$121`) and `feed_travel` before anything else. A pen
  plotter has no reason to accelerate hard.
- **Missing only after a long plot** — belt tension. It should be tight enough
  to twang, not tight enough to bow the rails.

### The square isn't square

Measure both diagonals. Equal diagonals mean square corners.

- **Diagonals differ** — the gantry is not perpendicular to the rails.
  Loosen the frame, push it against a known-square edge, retighten diagonally
  opposite bolts a little at a time.
- **Sides bow outward or inward** — a rail is bent, or a bearing is binding.
  Move the carriage by hand with the power off; it should slide freely with no
  tight spot.

### The dashes are uneven

Twelve dashes should all be the same weight.

| Symptom | Cause | Fix |
|---|---|---|
| First dash faint, rest fine | Pen drops too slowly | Increase `pen_down_dwell` |
| All faint or skipping | Pen too high | Raise the `pen_down` S value (or lower Z) |
| Paper dented, ink blobbing | Pen too low | Lower `pen_down` |
| Fading left to right | Bed not level, or paper not flat | Re-tape the paper; shim the bed |
| Tails trailing off each dash | Pen lifts while still moving | Increase `pen_up_dwell` |

### The pen drags between letters

You'll see faint lines connecting characters. The pen is still down during
rapid moves.

1. Increase `pen_up_dwell` to 0.2–0.3s.
2. Check `$32=0` on GRBL. In laser mode, spindle (and therefore servo) changes
   are deferred until the next move — which is exactly the pen-up you need
   to happen *first*.
3. If it only happens on tiny strokes such as the dot on an `i`, the servo is
   too slow to complete a full lift/drop cycle. Increase both dwells.

---

## Setting the paper origin

Without limit switches, the origin is wherever the machine was when you
powered it on. So:

1. Tape the paper down. All four corners.
2. Jog the pen to the **top-left corner of the paper**, just touching.
3. Zero there: send `G92 X0 Y0`, or use your sender's "set origin" button.
4. Leave `origin_x` and `origin_y` at `0.0` in the profile.

If you'd rather keep the machine origin and place the paper elsewhere on the
bed, measure from the machine origin to the paper's top-left corner and put
those numbers in `origin_x` / `origin_y` instead.

Check before committing to a full page:

```bash
hwm gcode "|" -f my-hand.json -m machines/your-machine.toml -o corner.gcode
```

That writes a single mark at the top-left of the text area. If it lands where
you expect, the whole page will.

---

## Y comes out mirrored

The text is upside down or flipped top-to-bottom. Flip `flip_y` in the profile.

Page coordinates put y=0 at the *top* of the paper; most machines put Y=0 at
the front and grow away from the operator. `flip_y = true` reconciles the two,
and is right for nearly every GRBL machine. It is wrong if your machine's Y
grows toward the operator.

---

## Handwriting-specific tuning

Once the machine is mechanically sound, the remaining problems are in the
handwriting itself.

### The letters look like a font

Not enough variants. A character captured once is drawn identically every time
it appears, and the eye catches that immediately in common letters — `e`, `a`,
`t`, `o`, `n`.

```bash
hwm font info -f my-hand.json    # tells you which characters have only one
```

Recapture the common letters with 3–5 samples each and merge:

```bash
hwm font merge my-hand.json extra-samples.json -o my-hand.json
```

### The letters look furry or wobbly at small sizes

Digitiser noise, magnified. Clean the font:

```bash
hwm font clean my-hand.json --tolerance 0.08 --smooth 2
```

Then reduce the synthetic tremor, which is additive on top of it:

```bash
hwm preview ... --tremor 0.02
```

### The writing wanders off the line

`--neatness` scales the baseline drift along with everything else. Halve it:

```bash
hwm preview ... --neatness 0.5
```

For fully mechanical output — useful for checking the machine rather than the
handwriting — use `--neatness 0`.

### Letters collide or float apart

Advance widths come from the bounding box of what you drew, so a letter written
with a long lead-in stroke reserves too much space. Either recapture it more
tightly, or fix the advance directly in the JSON:

```json
"r": [ { "strokes": [...], "advance": 3.9 } ]
```

Global adjustments are easier: `--letter-spacing -0.2` tightens everything.

### It takes forever to plot

```bash
hwm gcode ... --preview      # writes an SVG beside the G-code
```

Check the reported travel distance. If travel dwarfs the drawn distance, the
optimiser could not help much — usually because the text is very sparse. Otherwise
raise `feed_travel`, which only affects pen-up moves and so cannot hurt line
quality.

Plot time estimates ignore acceleration. On a small machine with low
acceleration, expect 1.5–2× the estimate.
