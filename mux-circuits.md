# Multiplexer Circuit Diagrams

Gate-level and block-level circuits for the 2 × 1, 4 × 1 and 8 × 1 MUXes.
(Mermaid diagrams render directly on GitHub; ASCII versions are included for
copying into lab notebooks.)

---

## 1. 2 × 1 MUX — gate level

`Y = S'·I0 + S·I1`

```mermaid
flowchart LR
    S(("S")) --> N["NOT"]
    N -- "S'" --> A0["AND<br/>G0"]
    I0(("I0")) --> A0
    S --> A1["AND<br/>G1"]
    I1(("I1")) --> A1
    A0 --> OR["OR"]
    A1 --> OR
    OR --> Y(("Y"))
```

```
                ┌─────┐
   S ───┬──────►│ NOT ├───► S'
        │       └─────┘
        │
   I0 ──────────────┐
                    │   ┌───────┐
   S' ──────────────┴──►│ AND0  ├───┐
                        └───────┘   │   ┌──────┐
                                    ├──►│  OR  ├───► Y
   I1 ──────────────┐   ┌───────┐   │   └──────┘
                    ├──►│ AND1  ├───┘
   S  ──────────────┘   └───────┘
```

Gates: 1 NOT, 2 AND (2-input), 1 OR (2-input).

---

## 2. 4 × 1 MUX — gate level

`Y = S1'S0'·I0 + S1'S0·I1 + S1S0'·I2 + S1S0·I3`

```mermaid
flowchart LR
    S1(("S1")) --> NS1["NOT"]
    S0(("S0")) --> NS0["NOT"]

    I0(("I0")) --> G0["AND G0"]
    NS1 -- "S1'" --> G0
    NS0 -- "S0'" --> G0

    I1(("I1")) --> G1["AND G1"]
    NS1 -- "S1'" --> G1
    S0 --> G1

    I2(("I2")) --> G2["AND G2"]
    S1 --> G2
    NS0 -- "S0'" --> G2

    I3(("I3")) --> G3["AND G3"]
    S1 --> G3
    S0 --> G3

    G0 --> OR["OR<br/>4-input"]
    G1 --> OR
    G2 --> OR
    G3 --> OR
    OR --> Y(("Y"))
```

```
          ┌─────┐                 ┌─────┐
 S1 ──┬──►│ NOT ├─► S1'    S0 ─┬─►│ NOT ├─► S0'
      │   └─────┘              │  └─────┘
      │                        │

   I0 ──┐
   S1' ─┼──┐  ┌────────┐
   S0' ─┴──┴─►│  AND0  ├──────────┐
              └────────┘          │
   I1 ──┐                         │
   S1' ─┼──┐  ┌────────┐          │
   S0  ─┴──┴─►│  AND1  ├──────────┤    ┌──────────┐
              └────────┘          ├───►│    OR    ├──► Y
   I2 ──┐                         │    │ 4-input  │
   S1 ──┼──┐  ┌────────┐          │    └──────────┘
   S0' ─┴──┴─►│  AND2  ├──────────┤
              └────────┘          │
   I3 ──┐                         │
   S1 ──┼──┐  ┌────────┐          │
   S0 ──┴──┴─►│  AND3  ├──────────┘
              └────────┘
```

Gate input map:

| Gate | Inputs          | Active when |
|------|-----------------|-------------|
| AND0 | S1', S0', I0    | S1 S0 = 00  |
| AND1 | S1', S0 , I1    | S1 S0 = 01  |
| AND2 | S1 , S0', I2    | S1 S0 = 10  |
| AND3 | S1 , S0 , I3    | S1 S0 = 11  |

Gates: 2 NOT, 4 AND (3-input), 1 OR (4-input).
The four AND gates are exactly the four outputs of a 2-to-4 decoder, each
gated by its data input — so a 4 × 1 MUX = 2-to-4 decoder + 4 AND + 1 OR.

With an enable `E`, every AND gate takes `E` as a fourth input; `E = 0` forces
`Y = 0`.

---

## 3. 8 × 1 MUX — block level, from three 4 × 1 blocks

```mermaid
flowchart LR
    I0(("I0")) --> A
    I1(("I1")) --> A
    I2(("I2")) --> A
    I3(("I3")) --> A
    A["MUX A<br/>4 × 1<br/>sel = S1,S0"] -- "YA → in0" --> C

    I4(("I4")) --> B
    I5(("I5")) --> B
    I6(("I6")) --> B
    I7(("I7")) --> B
    B["MUX B<br/>4 × 1<br/>sel = S1,S0"] -- "YB → in1" --> C

    Z(("0")) -- "in2, in3" --> C
    C["MUX C<br/>4 × 1<br/>S1 = 0, S0 = S2"] --> Y(("Y"))
```

```
   I0 ─►┐                                MUX C  (4 × 1 used as 2 × 1)
   I1 ─►│  MUX A  │── YA ───────────────► in0 ┐
   I2 ─►│  4 × 1  │                           │
   I3 ─►┘                                     ├──► Y
         ▲   ▲                                │
        S1   S0        YB ──────────────► in1 ┘
                        ▲                0 ─► in2
   I4 ─►┐               │                0 ─► in3
   I5 ─►│  MUX B  │─────┘                     ▲    ▲
   I6 ─►│  4 × 1  │                          S1   S0
   I7 ─►┘                                     │    │
         ▲   ▲                                0    S2
        S1   S0
```

`S1 S0` select the position inside each group of four; `S2` selects the group.
MUX C has its own `S1` tied to 0, so it only ever picks `in0` (= YA, when
S2 = 0) or `in1` (= YB, when S2 = 1). `in2`/`in3` are grounded.

**Cost: 3 × 4 × 1 MUX, no extra gates.**

### Enable variant — two blocks + OR

```mermaid
flowchart LR
    S2(("S2")) --> N["NOT"]
    N -- "S2' → E" --> A["MUX A<br/>I0..I3<br/>sel = S1,S0"]
    S2 -- "E" --> B["MUX B<br/>I4..I7<br/>sel = S1,S0"]
    A -- "YA" --> OR["OR"]
    B -- "YB" --> OR
    OR --> Y(("Y"))
```

Exactly one block is enabled at a time, so the disabled one drives 0 and
`Y = YA + YB`.

**Cost: 2 × 4 × 1 MUX + 1 NOT + 1 OR.**
