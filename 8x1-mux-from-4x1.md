# 8 × 1 Multiplexer Built From 4 × 1 Multiplexers

An 8-to-1 multiplexer routes **one of eight data inputs** (`I0`–`I7`) to the
output `Y`, using **three select lines** (`S2`, `S1`, `S0`).

Number of select lines = log2(8) = 3.

## Truth table

| S2 | S1 | S0 | Y  |
|----|----|----|----|
| 0  | 0  | 0  | I0 |
| 0  | 0  | 1  | I1 |
| 0  | 1  | 0  | I2 |
| 0  | 1  | 1  | I3 |
| 1  | 0  | 0  | I4 |
| 1  | 0  | 1  | I5 |
| 1  | 1  | 0  | I6 |
| 1  | 1  | 1  | I7 |

Boolean expression:

```
Y = S2'S1'S0'·I0 + S2'S1'S0·I1 + S2'S1S0'·I2 + S2'S1S0·I3
  + S2 S1'S0'·I4 + S2 S1'S0·I5 + S2 S1S0'·I6 + S2 S1S0·I7
```

## Construction: three 4 × 1 MUXes (4 × 1 only)

The low two select bits `S1 S0` pick a position *within* each group of four; the
high bit `S2` picks *which group*. So two 4 × 1 MUXes form the first stage and a
third 4 × 1 — wired to behave as a 2 × 1 — forms the second stage.

```
   I0 ─►┐                              MUX C (used as 2 × 1)
   I1 ─►│ MUX A │──── YA ────────────►┐ (in0)
   I2 ─►│ 4 × 1 │                     │
   I3 ─►┘                             │ 4 × 1 ├──► Y
         ▲ ▲                YB ──────►┘ (in1)
        S1 S0                ▲          in2 ─► 0 (unused)
                             │          in3 ─► 0 (unused)
   I4 ─►┐                    │             ▲   ▲
   I5 ─►│ MUX B │────────────┘            S1   S0
   I6 ─►│ 4 × 1 │                          │    │
   I7 ─►┘                                  0   S2
         ▲ ▲
        S1 S0
```

Wiring summary:

| Block | Data inputs (in0…in3) | Select S1 | Select S0 | Output |
|-------|-----------------------|-----------|-----------|--------|
| MUX A | I0, I1, I2, I3        | S1        | S0        | YA     |
| MUX B | I4, I5, I6, I7        | S1        | S0        | YB     |
| MUX C | YA, YB, 0, 0          | 0 (tied)  | S2        | Y      |

Because MUX C's own `S1` is tied to logic 0, it only ever selects `in0` or
`in1`, i.e. `Y = YA` when `S2 = 0` and `Y = YB` when `S2 = 1`. Its `in2` and
`in3` are don't-cares and can be grounded.

**Cost: 3 × (4 × 1 MUX), no extra gates.**

Trace check — `S2 S1 S0 = 101`: MUX A outputs `I1`, MUX B outputs `I5`,
MUX C selects `in1 = YB = I5`. ✔ Matches the truth table.

## Alternative: two 4 × 1 MUXes with enable

If the 4 × 1 MUX has an active-high enable (`E = 0` forces its output to 0),
the second stage collapses into a single OR gate:

| Block | Data inputs    | Selects | Enable | Output |
|-------|----------------|---------|--------|--------|
| MUX A | I0, I1, I2, I3 | S1, S0  | S2'    | YA     |
| MUX B | I4, I5, I6, I7 | S1, S0  | S2     | YB     |

`Y = YA + YB`. Exactly one MUX is enabled at a time, so the disabled one
contributes 0.

**Cost: 2 × (4 × 1 MUX) + 1 NOT + 1 two-input OR.**

## Verilog

```verilog
// Structural 8x1 from three 4x1 blocks
module mux8x1_from_4x1 (
    input  wire [7:0] I,
    input  wire [2:0] S,   // S[2] = S2, S[1] = S1, S[0] = S0
    output wire       Y
);
    wire ya, yb;

    mux4x1 A (.I(I[3:0]), .S(S[1:0]),      .Y(ya));
    mux4x1 B (.I(I[7:4]), .S(S[1:0]),      .Y(yb));
    mux4x1 C (.I({2'b00, yb, ya}),         // in3, in2, in1, in0
              .S({1'b0, S[2]}),            // S1 tied low, S0 = S2
              .Y(Y));
endmodule
```

(`mux4x1` is the module from [`4x1-mux-truth-table.md`](4x1-mux-truth-table.md).)

## General rule

To build a `2^n × 1` MUX from `4 × 1` blocks, each stage consumes 2 select bits
and reduces the input count by 4×. A 16 × 1 needs 4 + 1 = 5 blocks in two
stages; a 64 × 1 needs 16 + 4 + 1 = 21 blocks in three stages. An 8 × 1 is the
awkward case — 3 select bits is not a multiple of 2 — which is why its second
stage is a 4 × 1 running at half capacity.
