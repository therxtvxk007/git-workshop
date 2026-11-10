# Full Adder and Full Subtractor with 74HC08 (AND) + 74HC86 (XOR)

Chips used (from the photos):

| Chip | Function | Gates |
|------|----------|-------|
| **SN74HC08N** | Quad 2-input **AND** | 4 |
| **CD74HCT86** | Quad 2-input **XOR** | 4 |

> The marking on the second chip was blurry. It is read here as **CD74HCT86 (XOR)**.
> If it is actually a 74xx32 (OR), these circuits will not work as drawn.

No OR or NOT chip is needed:

* **OR → XOR.** When two terms can never both be 1, `P + Q = P ⊕ Q`.
  This is true for the carry and borrow terms below.
* **NOT → XOR with 1.** `X ⊕ 1 = X'`. Tie one input of the XOR gate to +5 V.

---

## Pinout (same for 74HC08 and 74HC86)

```
            +---\/---+
   1A  1 |        | 14  VCC (+5V)
   1B  2 |        | 13  4B
   1Y  3 |        | 12  4A
   2A  4 |        | 11  4Y
   2B  5 |        | 10  3B
   2Y  6 |        |  9  3A
  GND  7 |        |  8  3Y
            +--------+
```

Gate 1: pins 1,2 → 3  Gate 2: pins 4,5 → 6  Gate 3: pins 9,10 → 8  Gate 4: pins 12,13 → 11

**Power both chips:** pin 14 → +5 V, pin 7 → GND.
Pin 1 is at the notch or dot end of the chip.

---

## 1. Full Adder

### Equations

```
Sum  = A ⊕ B ⊕ Cin
Cout = A·B + Cin·(A ⊕ B)
     = A·B ⊕ Cin·(A ⊕ B)      (the two terms are never 1 together)
```

### Truth table

| A | B | Cin | Sum | Cout |
|---|---|-----|-----|------|
| 0 | 0 | 0 | 0 | 0 |
| 0 | 0 | 1 | 1 | 0 |
| 0 | 1 | 0 | 1 | 0 |
| 0 | 1 | 1 | 0 | 1 |
| 1 | 0 | 0 | 1 | 0 |
| 1 | 0 | 1 | 0 | 1 |
| 1 | 1 | 0 | 0 | 1 |
| 1 | 1 | 1 | 1 | 1 |

### Logic diagram

```
A ──┬──────────┐
    │        ┌─┴──┐  X = A⊕B
    │        │XOR1├──────┬──────────────┐
B ──┼──┬─────┤    │      │            ┌─┴──┐
    │  │     └────┘      │            │XOR2├──────────────► SUM
    │  │                 │   Cin ──┬──┤    │
    │  │                 │         │  └────┘
    │  │                 │         │
    │  │                 │       ┌─┴──┐  Cin·X
    │  │                 └───────┤AND2├──────┐
    │  │                         └────┘    ┌─┴──┐
    │  │       ┌────┐  A·B                 │XOR3├───────► COUT
    └──┼───────┤AND1├──────────────────────┤ (OR)│
       └───────┤    │                      └────┘
               └────┘
```

### Breadboard connections (3 XOR + 2 AND)

| Gate | Inputs | Output | Signal |
|------|--------|--------|--------|
| 74HC86 Gate 1 | pin 1 = **A**, pin 2 = **B** | pin 3 | X = A⊕B |
| 74HC86 Gate 2 | pin 4 = X (from 86-pin 3), pin 5 = **Cin** | pin 6 | **SUM** → LED |
| 74HC08 Gate 1 | pin 1 = **A**, pin 2 = **B** | pin 3 | A·B |
| 74HC08 Gate 2 | pin 4 = X (from 86-pin 3), pin 5 = **Cin** | pin 6 | Cin·X |
| 74HC86 Gate 3 | pin 9 = 08-pin 3, pin 10 = 08-pin 6 | pin 8 | **COUT** → LED |

Spare: 74HC86 gate 4 and 74HC08 gates 3 and 4.

---

## 2. Full Subtractor (A − B − Bin)

### Equations

```
Diff = A ⊕ B ⊕ Bin
Bout = A'·B + Bin·(A ⊕ B)'
```

To build this with only AND and XOR gates, let `X = A ⊕ B`:

* `A'·B = X·B`. If X = 1 and B = 1, then A must be 0.
* `(A ⊕ B)' = X ⊕ 1`. This is NOT built from an XOR gate.
* The two terms are never 1 together, so `+` becomes `⊕`.

```
Bout = (X·B) ⊕ (X'·Bin)
```

### Truth table

| A | B | Bin | Diff | Bout |
|---|---|-----|------|------|
| 0 | 0 | 0 | 0 | 0 |
| 0 | 0 | 1 | 1 | 1 |
| 0 | 1 | 0 | 1 | 1 |
| 0 | 1 | 1 | 0 | 1 |
| 1 | 0 | 0 | 1 | 0 |
| 1 | 0 | 1 | 0 | 0 |
| 1 | 1 | 0 | 0 | 0 |
| 1 | 1 | 1 | 1 | 1 |

### Logic diagram

```
A ─────────┐
         ┌─┴──┐  X = A⊕B
B ──┬────┤XOR1├────┬─────────┬─────────────┐
    │    └────┘    │         │           ┌─┴──┐
    │              │         │           │XOR2├────────────► DIFF
    │              │         │  Bin ──┬──┤    │
    │              │         │        │  └────┘
    │              │       ┌─┴──┐     │
    │              │ +5V ──┤XOR3├─┐   │       (XOR3 = NOT gate)
    │              │       └────┘ │X' │
    │              │            ┌─┴───┴┐  X'·Bin
    │              │            │ AND2 ├──────┐
    │              │            └──────┘    ┌─┴──┐
    │            ┌─┴──┐  X·B (= A'B)        │XOR4├──────► BOUT
    └────────────┤AND1├─────────────────────┤ (OR)│
                 └────┘                     └────┘
```

### Breadboard connections (4 XOR + 2 AND)

| Gate | Inputs | Output | Signal |
|------|--------|--------|--------|
| 74HC86 Gate 1 | pin 1 = **A**, pin 2 = **B** | pin 3 | X = A⊕B |
| 74HC86 Gate 2 | pin 4 = X (86-pin 3), pin 5 = **Bin** | pin 6 | **DIFF** → LED |
| 74HC86 Gate 3 | pin 9 = X (86-pin 3), pin 10 = **+5 V** | pin 8 | X' (NOT X) |
| 74HC08 Gate 1 | pin 1 = X (86-pin 3), pin 2 = **B** | pin 3 | X·B = A'B |
| 74HC08 Gate 2 | pin 4 = X' (86-pin 8), pin 5 = **Bin** | pin 6 | X'·Bin |
| 74HC86 Gate 4 | pin 12 = 08-pin 3, pin 13 = 08-pin 6 | pin 11 | **BOUT** → LED |

Spare: 74HC08 gates 3 and 4.

---

## General wiring notes

1. **Inputs (A, B, Cin/Bin):** connect each one through a switch to +5 V,
   with a 10 kΩ pull-down resistor to GND. CMOS inputs must never be left floating.
2. **Outputs:** output pin → 330 Ω resistor → LED anode, LED cathode → GND.
3. **Unused gate inputs:** tie them to GND. On the 08 these are pins 9, 10, 12 and 13.
   For the adder, also tie pins 12 and 13 of the 86 to GND.
4. A 0.1 µF capacitor between pin 14 and pin 7 of each chip is recommended.
5. Building **both** circuits at once takes 7 XOR gates and 4 AND gates,
   so you would need a second 74HC86. With one of each chip, build them one at a time.
