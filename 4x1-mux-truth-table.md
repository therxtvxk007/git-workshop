# 4 × 1 Multiplexer

A 4-to-1 multiplexer routes **one of four data inputs** (`I0`–`I3`) to a single
output `Y`, based on **two select lines** (`S1`, `S0`).

```
        I0 ──►┐
        I1 ──►│  4 × 1  │
        I2 ──►│   MUX   ├──► Y
        I3 ──►┘
               ▲    ▲
              S1    S0
```

Number of select lines = log2(4) = 2.

## Truth table (compact form)

The data inputs that are not selected are *don't-cares* (`x`), so the behaviour
is fully described by the four select combinations:

| S1 | S0 | I3 | I2 | I1 | I0 | Y  |
|----|----|----|----|----|----|----|
| 0  | 0  | x  | x  | x  | 0  | 0  |
| 0  | 0  | x  | x  | x  | 1  | 1  |
| 0  | 1  | x  | x  | 0  | x  | 0  |
| 0  | 1  | x  | x  | 1  | x  | 1  |
| 1  | 0  | x  | 0  | x  | x  | 0  |
| 1  | 0  | x  | 1  | x  | x  | 1  |
| 1  | 1  | 0  | x  | x  | x  | 0  |
| 1  | 1  | 1  | x  | x  | x  | 1  |

## Truth table (function form)

| S1 | S0 | Y  |
|----|----|----|
| 0  | 0  | I0 |
| 0  | 1  | I1 |
| 1  | 0  | I2 |
| 1  | 1  | I3 |

## Boolean expression

```
Y = S1' · S0' · I0  +  S1' · S0 · I1  +  S1 · S0' · I2  +  S1 · S0 · I3
```

Each product term is one output of a 2-to-4 decoder (`S1'S0'`, `S1'S0`,
`S1S0'`, `S1S0`) ANDed with its data input; the four AND outputs are ORed
together. With an enable input `E`, every term is additionally ANDed with `E`,
so `E = 0` forces `Y = 0`.

## Gate count

- 2 NOT gates (to generate `S1'` and `S0'`)
- 4 three-input AND gates (four-input if an enable is used)
- 1 four-input OR gate

## Verilog

```verilog
module mux4x1 (
    input  wire [3:0] I,   // I[3]..I[0]
    input  wire [1:0] S,   // S[1] = S1, S[0] = S0
    output wire       Y
);
    assign Y = I[S];

    // Equivalent structural/boolean form:
    // assign Y = (~S[1] & ~S[0] & I[0])
    //          | (~S[1] &  S[0] & I[1])
    //          | ( S[1] & ~S[0] & I[2])
    //          | ( S[1] &  S[0] & I[3]);
endmodule
```
