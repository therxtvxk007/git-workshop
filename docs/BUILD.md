# Building the machine

The software needs a machine that can do three things: move a pen in X, move it
in Y, and lift it off the paper. That's it. There is no fourth requirement, and
most of the cost of a pen plotter is in over-engineering those three.

Three routes, cheapest last.

---

## Route 1: you already own a 3D printer

This is by far the least work, and the accuracy is better than most purpose-built
pen plotters.

1. Zip-tie or clamp a pen to the hotend carriage, nib roughly where the nozzle
   was. A block of wood with a hole drilled through it, cable-tied to the fan
   shroud, is entirely adequate.
2. Let the pen slide vertically in its mount, resting on the paper under its own
   weight or a light spring. **Do not clamp it rigidly** — any bed unevenness
   then either lifts the nib off the paper or grinds it into the sheet.
3. Tape paper to the bed. Painter's tape at all four corners.
4. Use `machines/marlin-z-pen.toml`. Set `pen_down`'s Z to the height where the
   nib just touches with the spring lightly compressed, and `pen_up` about 2mm
   above it.

Pen lift is a Z move, so it is slower than a servo — expect roughly double the
plot time. It costs nothing and needs no wiring.

**Do not home Z into the bed with a pen fitted.** Delete `G28` from the profile
header, or home X and Y only (`G28 X Y`).

---

## Route 2: you already own a CNC router or laser

Same idea with more rigidity. Put a spring-loaded pen holder in the collet.
Start from `machines/a4-grbl-servo.toml`, and if you have no servo, switch the
pen commands to Z moves as in the Marlin profile.

**Disconnect the spindle** before doing anything else. A spindle that starts
because a stray `M3` reached it, while your hands are placing paper, is the one
genuinely dangerous failure mode in this whole project. `M3` is also what the
servo profile uses for pen-down.

---

## Route 3: build one

A two-axis Cartesian plotter. One evening of work, roughly £40–£70.

### Bill of materials

| Qty | Part | Notes | Approx |
|---:|---|---|---:|
| 1 | Arduino Uno (or clone) | Runs GRBL | £5–£20 |
| 1 | CNC shield v3 | Stepper drivers plug into it | £6 |
| 2 | A4988 or DRV8825 drivers | DRV8825 is quieter | £5 |
| 2 | NEMA 17 stepper, 40mm | 1.5A/phase or less | £16 |
| 1 | SG90 9g servo | The pen lifter | £2 |
| 2 | 2m GT2 belt + 4 pulleys (20T) | 6mm wide | £8 |
| 4 | 8mm smooth rod, 400mm | Or 2020 extrusion with V-wheels | £12 |
| 8 | LM8UU linear bearings | Skip if using V-wheels | £6 |
| 1 | 12V 2A power supply | Barrel jack to match the shield | £8 |
| — | M3 bolts, nuts, zip ties | | £4 |
| — | 3D-printed or laser-cut brackets | Many free designs; search "GRBL pen plotter" | — |

A moving-gantry design is the easiest to get square: Y moves the gantry,
X moves the pen carriage along it. Keep the writing area modest — A4 is plenty,
and a smaller machine is a stiffer machine.

### Wiring

```
 Arduino Uno + CNC shield v3
 ┌────────────────────────────────────┐
 │  X driver ──── X stepper (gantry)  │
 │  Y driver ──── Y stepper (carriage)│
 │                                    │
 │  Z+ / D11 ──── servo signal (pen)  │──▶ SG90
 │  5V       ──── servo red           │
 │  GND      ──── servo brown         │
 │                                    │
 │  X- / Y-  ──── limit switches (opt)│
 │  12V in   ──── power supply        │
 └────────────────────────────────────┘
```

- The servo signal goes on **D11**, which is the spindle PWM pin GRBL uses for
  `M3 S…`. That is what makes `pen_up = ["M3 S0"]` work.
- An SG90 draws little enough to run off the shield's 5V. A larger servo needs
  its own supply, with grounds tied together.
- Limit switches are optional. Without them you set the origin by jogging to the
  paper corner and zeroing there, every session.

### Firmware

Flash [GRBL 1.1](https://github.com/gnea/grbl) to the Uno, then set:

```gcode
$100=80      ; X steps/mm  (20T pulley, GT2 belt, 1/16 microstepping)
$101=80      ; Y steps/mm
$110=6000    ; X max rate mm/min
$111=6000    ; Y max rate
$120=300     ; X acceleration mm/s^2  — keep low, a pen is not a laser
$121=300     ; Y acceleration
$30=1000     ; max spindle value -> S0..S1000 maps to the servo range
$31=0        ; min spindle value
$32=0        ; laser mode OFF (must be off, or pen-up during moves misbehaves)
```

`$100`/`$101` of 80 assume 20-tooth pulleys on 2mm-pitch belt at 1/16
microstepping: `200 × 16 / (20 × 2) = 80`. Adjust for your own pulleys, then
verify with the calibration square in [CALIBRATION.md](CALIBRATION.md).

`$32=0` matters. In laser mode GRBL defers spindle changes until the next
motion, which desynchronises every pen lift.

### The pen lifter

The simplest mechanism that works: mount the servo beside the pen, with a
short arm that pushes the pen holder up when it rotates. The pen falls back
under gravity or light spring pressure.

Make sure the pen **falls** to write rather than being pushed down. A driven-down
pen transfers every bit of servo jitter into the paper, and tears it when the
angle is slightly off.

Find your two S values by hand:

```gcode
M3 S0      ; note where the arm sits
M3 S180    ; adjust until the nib just kisses the paper
```

Put those numbers in your machine profile's `pen_up` and `pen_down`.

---

## Once it moves

```bash
hwm calibrate -m machines/a4-grbl-servo.toml -o cal.gcode
hwm send cal.gcode --port /dev/ttyUSB0
```

You should get a closed square with matching diagonals and twelve evenly-inked
dashes. If you don't, [CALIBRATION.md](CALIBRATION.md) explains what each
failure means.

## Choosing a pen

| Pen | Verdict |
|---|---|
| Fineliner (Micron, Staedtler) | Best results. Consistent line, no pressure needed |
| Gel pen | Good. Watch for blobbing at the start of strokes |
| Ballpoint | Needs real pressure; skips on fast travel. Slow `feed_draw` down |
| Fountain pen | Beautiful, but bleeds when the pen pauses. Raise `feed_draw` |
| Sharpie | Bleeds badly at small sizes. Fine above `--size 12` |

Start with a 0.3–0.5mm fineliner. Cap it between plots — a nib left uncapped
under a servo arm dries out in about twenty minutes.
