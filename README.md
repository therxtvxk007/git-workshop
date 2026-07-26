# handwriting-machine

A machine that writes on paper with a real pen, in **your** handwriting.

You write each letter once in a browser. The software learns the strokes, then
replays them — with fresh, natural variation every time — as G-code for a pen
plotter. The result is ink on paper from a real pen, not a printed image of
handwriting.

```
 your hand          software                        machine
┌──────────┐   ┌──────────────────────┐   ┌────────────────────────┐
│ capture  │──▶│ font ▸ layout ▸ paths│──▶│ G-code ▸ plotter ▸ pen │
│ a-z once │   │  variation, wrapping │   │  X/Y motion, pen lift  │
└──────────┘   └──────────────────────┘   └────────────────────────┘
```

- **Two parts**: the software in this repo, and a two-axis plotter to hold the
  pen. If you already have a 3D printer or a CNC router, you have the machine —
  see [docs/BUILD.md](docs/BUILD.md).
- **No dependencies.** Pure Python standard library. `pyserial` is optional and
  only needed to drive the machine directly.

---

## Quick start

```bash
git clone <this repo> && cd git-workshop
pip install -e .              # or just use: PYTHONPATH=. python3 -m handwriting.cli

hwm preview "Hello, world" -o hello.svg     # try it with the built-in font
```

That uses a built-in reference font so you can see the pipeline work. It is
nobody's handwriting. Next, capture your own.

### 1. Capture your handwriting

```bash
hwm capture
```

This opens a page in your browser with four guide lines. (The page is
self-contained — you can also just open `capture/index.html` from disk, no
server or Python needed.) Write each prompted character between them — three samples of each by default, because repeating
the *same* stroke data is what makes output look like a font instead of a hand.

- Use a stylus or trackpad if you have one; a mouse works but is slower.
- **Rest every letter on the baseline.** Consistency with the baseline matters
  far more than neatness — the machine adds its own wobble later.
- Work is saved in your browser as you go, so you can stop and come back.
- Click **Save font JSON** when done.

Lowercase alone is enough to start. About 15 minutes gets you a full set.

```bash
hwm font info -f my-hand.json     # coverage, variants per character
hwm font clean my-hand.json       # thin out digitiser noise (recommended)
```

Captured in several sittings? Combine them — more variants is strictly better:

```bash
hwm font merge session1.json session2.json -o my-hand.json
```

### 2. Preview before you commit paper to it

```bash
hwm preview -i letter.txt -f my-hand.json -o preview.svg --show-margins
```

Open the SVG in any browser. Tune until you like it:

```bash
hwm preview "the same words, a different hand" -f my-hand.json --seed 7
```

### 3. Plot it

```bash
hwm gcode -i letter.txt -f my-hand.json -m machines/a4-grbl-servo.toml -o letter.gcode
hwm send letter.gcode --port /dev/ttyUSB0
```

`send` streams to GRBL directly. Any other sender (UGS, bCNC, Candle,
OctoPrint) works too — the G-code is ordinary.

---

## Commands

| Command | What it does |
|---|---|
| `hwm capture` | Serve the browser tool that records your handwriting |
| `hwm font info` | Coverage, variant counts, and what's missing |
| `hwm font clean` | Simplify and smooth captured strokes |
| `hwm font merge` | Combine capture sessions into one font |
| `hwm font export-demo` | Write the built-in reference font to a file |
| `hwm preview` | Render to SVG without plotting |
| `hwm gcode` | Render to G-code for the machine |
| `hwm send` | Stream G-code to a GRBL controller |
| `hwm ports` | List serial ports |
| `hwm calibrate` | Plot a test pattern for pen height and squareness |

Text comes from an argument, `-i FILE`, or stdin — so `fortune | hwm preview`
works.

## Style

Everything below is per-run; nothing is baked into the font.

| Option | Effect |
|---|---|
| `--size 6` | Writing size in mm, ascender to descender |
| `--line-spacing 1.9` | Line pitch, as a multiple of size |
| `--slant 12` | Degrees of rightward lean |
| `--letter-spacing`, `--word-spacing` | Tighten or loosen |
| `--align left\|center\|right` | Line alignment |
| `--neatness 0.5` | Scales *all* irregularity at once |
| `--seed 7` | Same seed, same page — every time |
| `--join` | Draw connecting strokes within words |
| `--paper a4\|a5\|a3\|letter\|legal`, `--landscape`, `--margin` | Page setup |

`--neatness` is the one to reach for first: `0` is mechanical and identical
every time, `1` is natural, `2` is scruffy.

Long text paginates automatically — `-o out.gcode` becomes `out-01.gcode`,
`out-02.gcode`, and so on. Line breaking is decided once for the whole text, so
page breaks never change how a line wraps.

### What makes it look handwritten

A font repeats itself perfectly; a hand never does. The layout engine varies:

- **which sample** of a letter gets used, each time it appears;
- **per letter** — size, rotation, vertical offset, and advance width;
- **per word** — slant and size, because a hand doesn't reset between words;
- **per line** — a baseline that wanders smoothly, as on unruled paper;
- **per stroke** — low-frequency tremor, so no line is perfectly straight.

All of it is driven by seeded noise, so a given `(text, seed)` always produces
exactly the page you previewed.

---

## The machine

Any two-axis machine that can hold a pen and lift it will do. Full build
instructions, bill of materials and wiring: **[docs/BUILD.md](docs/BUILD.md)**.
Setting it up and squaring it: **[docs/CALIBRATION.md](docs/CALIBRATION.md)**.

Already own something suitable?

| You have | What to do |
|---|---|
| 3D printer | Clamp a pen where the hotend is. Use `machines/marlin-z-pen.toml` |
| CNC router | Spring-loaded pen in the collet. Start from `machines/a4-grbl-servo.toml` |
| Neither | Build one — roughly £40–£70 in parts, one evening |

Machine profiles are TOML and carry the literal G-code for pen up and pen down,
so any controller can be described without touching the code:

```toml
[machine]
bed_width = 210.0
bed_height = 297.0
pen_up = ["M3 S0"]        # or ["G1 Z2 F1200"] for a Z-axis lift
pen_down = ["M3 S180"]
pen_up_dwell = 0.15       # servos need time to arrive
```

Copy one of the files in `machines/` and edit the copy.

---

## Using it as a library

```python
from handwriting import Font, Style, PageSetup, layout_text, render, generate_gcode
from handwriting.machine import MachineProfile

font = Font.load("my-hand.json")
page = layout_text("Hello", font, Style(size=7, slant=8), PageSetup(), seed=42)

open("out.svg", "w").write(render(page))

profile = MachineProfile.load("machines/a4-grbl-servo.toml")
gcode, stats = generate_gcode(page.polylines, profile, page_height=page.page.height)
print(stats.describe(profile))       # 113 strokes, 475mm drawn, ~1.0 min
```

### Font file format

Plain JSON, easy to edit or generate. Glyph coordinates are millimetres,
y-up, baseline at 0:

```json
{
  "format": "handwriting-machine/font",
  "metrics": { "em": 10.0, "x_height": 5.0, "ascender": 7.5, "descender": -2.5 },
  "glyphs": {
    "l": [
      { "strokes": [[[0.8, 7.5], [0.8, 0.8], [1.9, 0.0]]], "advance": 3.0 }
    ]
  }
}
```

Each character maps to a list of variants; each variant is a list of strokes;
each stroke is a list of points. Add more variants to make a letter livelier.

---

## Safety and limits

- **Bounds are checked before any file is written.** If the layout would run
  off the bed, `hwm gcode` refuses and tells you by how much, rather than
  letting the machine drive into a rail. `--no-bounds-check` overrides it.
- Plot time estimates ignore acceleration, so treat them as a floor. Real time
  on a small machine is often 1.5–2× the estimate.
- Keep a hand near the reset. First plot of a session, watch the whole thing.
- The pen is a consumable: fineliners dry out if left down, and ballpoints skip
  if the pen-down pressure is too light. See
  [docs/CALIBRATION.md](docs/CALIBRATION.md).

## Tests

```bash
python3 -m unittest discover -s tests -t . -q
```

95 tests, no dependencies. They cover the geometry, font round-tripping,
layout and wrapping, travel optimisation, and G-code correctness — including
that the pen is never dragged during a rapid move.

`tests/fixtures/captured-abc.json` is a real export from the capture tool, and
`test_capture_format.py` pins the format against it. The capture tool is the
only JavaScript in the project, so what it writes is a contract: every font
already recorded is in that format.

## Licence

MIT.
