#!/usr/bin/env python3
"""Check every machine in generate_automata.py against the language it claims to accept.

The transition tables were transcribed from the paper by hand, so each one is run over
every string up to a fixed length and compared with a direct predicate.  Machines whose
language the paper leaves open (Q4, which has no accepting set) are skipped.

Usage: python3 tools/verify_automata.py
"""

import itertools
import re
import sys

from generate_automata import (MACHINES, Q2, Q5A, Q5B, Q5C, Q5D_DFA, Q5D_NFA, Q6A, Q6B,
                               Q6C_DFA, Q6C_NFA, Q7A_MIN, Q7A_ORIG, Q7B_DIFF, Q7B_INT,
                               Q7B_UNION, Q8A_DFA, Q8A_NFA, Q8B, Q1)

MAX_LEN = 9


def words(alphabet, max_len):
    for n in range(max_len + 1):
        for w in itertools.product(alphabet, repeat=n):
            yield "".join(w)


def closure(m, states):
    """ε-closure of a set of states."""
    out, stack = set(states), list(states)
    while stack:
        for nxt in m.targets(stack.pop(), "ε"):
            if nxt not in out:
                out.add(nxt)
                stack.append(nxt)
    return out


def accepts(m, word):
    cur = closure(m, {m.start})
    for sym in word:
        cur = closure(m, {t for s in cur for t in m.targets(s, sym)})
        if not cur:
            return False
    return bool(cur & m.accept)


def value_mod(word, k):
    return int(word, 2) % k if word else None


def product_mod7(word):
    prod = 1
    for ch in word:
        prod *= int(ch)
    return prod % 7 == 2


CASES = [
    (Q1, product_mod7),
    (Q2, lambda w: w == "" or w[0] == w[-1]),
    (Q5A, lambda w: w != "" and value_mod(w, 4) == 0),
    (Q5B, lambda w: w.count("1") % 4 == 0 and w.count("0") % 2 == 1),
    (Q5C, lambda w: "aa" not in w),
    (Q5D_NFA, lambda w: w != "" and w[0] == w[-1]),
    (Q5D_DFA, lambda w: w != "" and w[0] == w[-1]),
    (Q6A, lambda w: w.endswith("01")),
    (Q6B, lambda w: w.count("a") == 2),
    (Q7B_INT, lambda w: False),
    (Q7B_UNION, lambda w: w.endswith("00") or w.endswith("11")),
    (Q7B_DIFF, lambda w: w.endswith("00")),
    (Q8A_NFA, lambda w: len(w) >= 3 and w[-3] == "1"),
    (Q8A_DFA, lambda w: len(w) >= 3 and w[-3] == "1"),
    (Q8B, lambda w: all(w[i:i + 3].count("a") >= 2 for i in range(len(w) - 2))),
]

BLOCKS = re.compile(r"^a*b*c*d*$")


def blocks_ok(w):
    if not BLOCKS.match(w):
        return False
    n, m, p, q = (w.count(c) for c in "abcd")
    return (n + m) % 2 == 0 and (p + q) % 2 == 1


CASES += [(Q6C_NFA, blocks_ok), (Q6C_DFA, blocks_ok)]


def main():
    failures = 0
    for m, want in CASES:
        limit = MAX_LEN if len(m.alphabet) < 4 else 6
        bad = None
        checked = 0
        for w in words(m.alphabet, limit):
            checked += 1
            if accepts(m, w) != want(w):
                bad = w
                break
        if bad is None:
            print(f"ok    {m.key:34s} {checked:6d} words up to length {limit}")
        else:
            failures += 1
            print(f"FAIL  {m.key:34s} disagrees on {bad!r} "
                  f"(machine={accepts(m, bad)}, expected={want(bad)})")

    # Q7(a): the minimised machine must accept exactly what the original accepts
    for w in words(Q7A_ORIG.alphabet, MAX_LEN):
        if accepts(Q7A_ORIG, w) != accepts(Q7A_MIN, w):
            failures += 1
            print(f"FAIL  q7a minimisation changes the language at {w!r}")
            break
    else:
        print(f"ok    {'q7a-minimisation':34s} original ≡ minimised up to length {MAX_LEN}")

    # every DFA must be complete: one target per state and symbol
    for m in MACHINES:
        if m.nondet:
            continue
        for state in m.delta:
            for sym in m.alphabet:
                if len(m.targets(state, sym)) != 1:
                    failures += 1
                    print(f"FAIL  {m.key}: δ({state}, {sym}) is not a single state")

    # every state must be reachable from the start state
    for m in MACHINES:
        seen, stack = {m.start}, [m.start]
        while stack:
            state = stack.pop()
            for sym in m.columns:
                for t in m.targets(state, sym):
                    if t not in seen:
                        seen.add(t)
                        stack.append(t)
        missing = set(m.delta) - seen
        if missing:
            failures += 1
            print(f"FAIL  {m.key}: unreachable states {sorted(missing)}")

    print("\n" + ("all checks passed" if not failures else f"{failures} failure(s)"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
