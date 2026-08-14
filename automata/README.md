# Series Exam 1 automata (PCCST302 · Theory of Computation)

State diagrams for every automaton in the fully solved previous-year paper — 20 machines
across Q1–Q8, both OR branches included. Q3 asks for a shortest excluded string, so it has
no automaton.

Each SVG is standalone and theme aware: it carries its own palette and follows the
viewer's light or dark system setting. `index.html` collects all 20 with their transition
tables and an answer map.

| File | Question | Machine |
| --- | --- | --- |
| `q1-product-mod-7.svg` | Q1 | product of symbols ≡ 2 (mod 7) — minimal DFA, 6 states |
| `q2-equal-01-10.svg` | Q2 | #01 = #10 — minimal DFA, 5 states |
| `q4-epsilon-nfa.svg` | Q4 | the ε-NFA used for δ̂(q2, aaaabbbaaab) |
| `q5a-divisible-by-4.svg` | Q5(a) | binary value divisible by 4 — 3 states |
| `q5b-ones-mod4-zeros-odd.svg` | Q5(b) | #1 ≡ 0 (mod 4) and #0 odd — 8 states |
| `q5c-avoid-aa.svg` | Q5(c) | strings avoiding `aa` — 3 states |
| `q5d-same-first-last-nfa.svg` | Q5(d) | starts and ends with the same symbol — NFA, 4 states |
| `q5d-same-first-last-dfa.svg` | Q5(d) | same language — minimal DFA, 5 states |
| `q6a-ends-with-01.svg` | Q6(a) | strings ending with `01` — 3 states |
| `q6b-exactly-two-a.svg` | Q6(b) | exactly two `a` symbols — 4 states |
| `q6c-blocks-enfa.svg` | Q6(c) | aⁿbᵐcᵖd^q, n+m even, p+q odd — ε-NFA, 8 states |
| `q6c-blocks-dfa.svg` | Q6(c) | same language — DFA, 9 states with the trap |
| `q7a-original-dfa.svg` | Q7(a) | the photographed 8-state DFA |
| `q7a-minimised-dfa.svg` | Q7(a) | its minimisation — 6 equivalence classes |
| `q7b-intersection.svg` | Q7(b) | L(M1) ∩ L(M2) = ∅ — 1 state |
| `q7b-union.svg` | Q7(b) | ends in `00` or `11` — 5 states |
| `q7b-difference.svg` | Q7(b) | L(M1) − L(M2) = L(M1) — 3 states |
| `q8a-third-from-right-enfa.svg` | Q8(a) | third symbol from the right is 1 — ε-NFA, 5 states |
| `q8a-third-from-right-dfa.svg` | Q8(a) | same language — minimal DFA, 8 states |
| `q8b-window-two-a.svg` | Q8(b) | every length-3 window has ≥ two `a` — 7 states |

## Regenerating

Everything here is generated; edit the machine definitions, not the SVGs.

```sh
python3 tools/generate_automata.py   # rewrites the SVGs and index.html
cd tools && python3 verify_automata.py   # checks each table against its language
```

`verify_automata.py` runs every machine over all strings up to length 9 (length 6 for the
four-symbol alphabets) and compares the result with a direct predicate, so a mistyped
transition fails loudly. It also checks that each DFA is complete and that no state is
unreachable.

## Reading the diagrams

- `→` marks the initial state; a double ring marks an accepting state.
- `D` or `X` is a dead/trap state.
- `ε` labels a transition that consumes no input.
- State captions below a circle give the memory that state stands for.
