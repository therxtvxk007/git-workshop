# 2 × 1 Multiplexer

A 2-to-1 multiplexer routes **one of two data inputs** (`I0`, `I1`) to the
output `Y`, based on a **single select line** `S`.

```
        I0 ──►┐  2 × 1  │
              │   MUX   ├──► Y
        I1 ──►┘
               ▲
               S
```

Number of select lines = log2(2) = 1.

## Truth table (compact form)

| S | I1 | I0 | Y |
|---|----|----|---|
| 0 | x  | 0  | 0 |
| 0 | x  | 1  | 1 |
| 1 | 0  | x  | 0 |
| 1 | 1  | x  | 1 |

## Truth table (function form)

| S | Y  |
|---|----|
| 0 | I0 |
| 1 | I1 |

## Full truth table (all 8 input combinations)

| S | I1 | I0 | Y |
|---|----|----|---|
| 0 | 0  | 0  | 0 |
| 0 | 0  | 1  | 1 |
| 0 | 1  | 0  | 0 |
| 0 | 1  | 1  | 1 |
| 1 | 0  | 0  | 0 |
| 1 | 0  | 1  | 0 |
| 1 | 1  | 0  | 1 |
| 1 | 1  | 1  | 1 |

## Boolean expression

```
Y = S' · I0  +  S · I1
```

## Gate count

- 1 NOT gate (to generate `S'`)
- 2 two-input AND gates
- 1 two-input OR gate

## Verilog

```verilog
module mux2x1 (
    input  wire I0,
    input  wire I1,
    input  wire S,
    output wire Y
);
    assign Y = S ? I1 : I0;

    // Equivalent boolean form:
    // assign Y = (~S & I0) | (S & I1);
endmodule
```

## Relation to the 4 × 1 MUX

A 4 × 1 MUX can be built from three 2 × 1 MUXes: two in the first stage
selected by `S0` (choosing between `I0`/`I1` and between `I2`/`I3`), and one in
the second stage selected by `S1` that picks between the two first-stage
outputs. See [`4x1-mux-truth-table.md`](4x1-mux-truth-table.md).
