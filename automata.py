#!/usr/bin/env python3
"""
Finite automata, implemented from nothing.

Companion to FINITE_AUTOMATA.md. Every construction discussed in Books I-III and
Book VI of that document is implemented here directly from its definition, with
no library beyond the standard one. Section numbers in docstrings refer to the
document.

Run it:  python3 automata.py
It builds the objects, checks them against each other, and prints a short report.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import count
from typing import Callable, Dict, FrozenSet, Iterable, Optional, Sequence, Set, Tuple

State = object
Sym = str


# ---------------------------------------------------------------------------
# Section 2. The DFA.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DFA:
    """A complete deterministic finite automaton (Q, Sigma, delta, q0, F)."""

    states: FrozenSet[State]
    alphabet: FrozenSet[Sym]
    delta: Dict[Tuple[State, Sym], State]
    start: State
    accepting: FrozenSet[State]

    def __post_init__(self) -> None:
        missing = [
            (q, a)
            for q in self.states
            for a in self.alphabet
            if (q, a) not in self.delta
        ]
        if missing:
            raise ValueError(f"delta is partial; missing {missing[:3]}")

    def step(self, q: State, a: Sym) -> State:
        return self.delta[(q, a)]

    def run(self, w: Sequence[Sym]) -> State:
        """delta*(q0, w), the state after reading w."""
        q = self.start
        for a in w:
            q = self.delta[(q, a)]
        return q

    def accepts(self, w: Sequence[Sym]) -> bool:
        return self.run(w) in self.accepting

    def reachable(self) -> FrozenSet[State]:
        seen, work = {self.start}, deque([self.start])
        while work:
            q = work.popleft()
            for a in self.alphabet:
                r = self.delta[(q, a)]
                if r not in seen:
                    seen.add(r)
                    work.append(r)
        return frozenset(seen)

    def trim(self) -> "DFA":
        """Drop unreachable states. Language-preserving; shrinks the state count."""
        keep = self.reachable()
        return DFA(
            states=keep,
            alphabet=self.alphabet,
            delta={k: v for k, v in self.delta.items() if k[0] in keep},
            start=self.start,
            accepting=frozenset(self.accepting & keep),
        )

    def rename(self) -> "DFA":
        """Canonically renumber states 0..n-1 by BFS order from the start state."""
        order: Dict[State, int] = {}
        work = deque([self.start])
        order[self.start] = 0
        ids = count(1)
        while work:
            q = work.popleft()
            for a in sorted(self.alphabet):
                r = self.delta[(q, a)]
                if r not in order:
                    order[r] = next(ids)
                    work.append(r)
        return DFA(
            states=frozenset(order.values()),
            alphabet=self.alphabet,
            delta={
                (order[q], a): order[self.delta[(q, a)]]
                for q in order
                for a in self.alphabet
            },
            start=0,
            accepting=frozenset(order[q] for q in self.accepting if q in order),
        )

    # -- Section 6. Closure properties. -------------------------------------

    def complement(self) -> "DFA":
        """Swap accepting and non-accepting. Correct only because delta is total."""
        return DFA(
            self.states,
            self.alphabet,
            self.delta,
            self.start,
            frozenset(self.states - self.accepting),
        )

    def product(self, other: "DFA", accept: Callable[[bool, bool], bool]) -> "DFA":
        """Run both machines in lockstep; `accept` combines the two verdicts.

        intersection: lambda x, y: x and y      union: lambda x, y: x or y
        difference:   lambda x, y: x and not y  xor:   lambda x, y: x != y
        """
        if self.alphabet != other.alphabet:
            raise ValueError("product needs a common alphabet")
        alphabet = self.alphabet
        start = (self.start, other.start)
        states: Set[State] = {start}
        delta: Dict[Tuple[State, Sym], State] = {}
        work = deque([start])
        while work:
            p, q = work.popleft()
            for a in alphabet:
                r = (self.delta[(p, a)], other.delta[(q, a)])
                delta[((p, q), a)] = r
                if r not in states:
                    states.add(r)
                    work.append(r)
        acc = frozenset(
            s for s in states if accept(s[0] in self.accepting, s[1] in other.accepting)
        )
        return DFA(frozenset(states), alphabet, delta, start, acc)

    def reverse(self) -> "NFA":
        """Reverse every edge, swap the roles of start and accepting (Section 6)."""
        trans: Dict[Tuple[State, Optional[Sym]], Set[State]] = {}
        for (q, a), r in self.delta.items():
            trans.setdefault((r, a), set()).add(q)
        return NFA(
            states=self.states,
            alphabet=self.alphabet,
            trans={k: frozenset(v) for k, v in trans.items()},
            starts=self.accepting,
            accepting=frozenset({self.start}),
        )

    # -- Section 12. Decision procedures. -----------------------------------

    def is_empty(self) -> bool:
        return not (self.reachable() & self.accepting)

    def shortest_word(self) -> Optional[str]:
        """A shortest accepted word, or None. Plain BFS -- Section 3."""
        prev: Dict[State, Tuple[State, Sym]] = {}
        seen, work = {self.start}, deque([self.start])
        target = None
        if self.start in self.accepting:
            return ""
        while work and target is None:
            q = work.popleft()
            for a in sorted(self.alphabet):
                r = self.delta[(q, a)]
                if r not in seen:
                    seen.add(r)
                    prev[r] = (q, a)
                    if r in self.accepting:
                        target = r
                        break
                    work.append(r)
        if target is None:
            return None
        out = []
        while target != self.start:
            target, a = prev[target]
            out.append(a)
        return "".join(reversed(out))

    def equivalent(self, other: "DFA") -> bool:
        """Hopcroft-Karp: merge start states, propagate, fail on a mixed class.

        Near-linear (union-find with path compression), Section 12.
        """
        if self.alphabet != other.alphabet:
            raise ValueError("equivalence needs a common alphabet")
        parent: Dict[State, State] = {}

        def find(x: State) -> State:
            root = x
            while parent.get(root, root) != root:
                root = parent[root]
            while parent.get(x, x) != x:
                parent[x], x = root, parent[x]
            return root

        def union(x: State, y: State) -> None:
            parent.setdefault(x, x)
            parent.setdefault(y, y)
            parent[find(x)] = find(y)

        a0, b0 = ("A", self.start), ("B", other.start)
        union(a0, b0)
        work = deque([(a0, b0)])
        while work:
            (_, p), (_, q) = work.popleft()
            if (p in self.accepting) != (q in other.accepting):
                return False
            for a in self.alphabet:
                x, y = ("A", self.delta[(p, a)]), ("B", other.delta[(q, a)])
                if find(x) != find(y):
                    union(x, y)
                    work.append((x, y))
        return True

    # -- Section 10. Minimization. ------------------------------------------

    def minimize(self) -> "DFA":
        """Hopcroft's algorithm: partition refinement, always splitting on the
        smaller half so each state is touched O(log n) times."""
        d = self.trim()
        acc = frozenset(d.accepting)
        rej = frozenset(d.states - acc)
        blocks: Set[FrozenSet[State]] = {b for b in (acc, rej) if b}
        if len(blocks) <= 1:
            # Constant machine: one state suffices.
            return _single_state_dfa(d.alphabet, bool(acc)).rename()

        # Predecessor map, so a splitter can be applied backwards.
        pre: Dict[Tuple[State, Sym], Set[State]] = {}
        for (q, a), r in d.delta.items():
            pre.setdefault((r, a), set()).add(q)

        def preimage(block: FrozenSet[State], a: Sym) -> Set[State]:
            out: Set[State] = set()
            for r in block:
                out |= pre.get((r, a), set())
            return out

        waiting: Set[Tuple[FrozenSet[State], Sym]] = {
            (min(blocks, key=len), a) for a in d.alphabet
        }
        while waiting:
            splitter, a = waiting.pop()
            x = preimage(splitter, a)
            if not x:
                continue
            for block in list(blocks):
                inter = block & x
                diff = block - x
                if not inter or not diff:
                    continue
                blocks.discard(block)
                blocks.add(frozenset(inter))
                blocks.add(frozenset(diff))
                for b in d.alphabet:
                    if (block, b) in waiting:
                        waiting.discard((block, b))
                        waiting.add((frozenset(inter), b))
                        waiting.add((frozenset(diff), b))
                    else:
                        smaller = inter if len(inter) <= len(diff) else diff
                        waiting.add((frozenset(smaller), b))

        rep: Dict[State, FrozenSet[State]] = {q: b for b in blocks for q in b}
        delta = {
            (rep[q], a): rep[d.delta[(q, a)]] for q in d.states for a in d.alphabet
        }
        return DFA(
            states=frozenset(blocks),
            alphabet=d.alphabet,
            delta=delta,
            start=rep[d.start],
            accepting=frozenset(b for b in blocks if b & d.accepting),
        ).rename()

    def minimize_brzozowski(self) -> "DFA":
        """determinize(reverse(determinize(reverse(A)))). Two lines, Section 10."""
        return self.reverse().determinize().reverse().determinize().rename()

    # -- Section 9. Myhill-Nerode. ------------------------------------------

    def nerode_classes(self, max_len: int = 6) -> Dict[State, str]:
        """Map each reachable state to a shortest prefix reaching it.

        By Section 9 the states of a *minimal* DFA are exactly the Myhill-Nerode
        classes, so this enumerates representatives of the classes of ~=_L.
        """
        rep: Dict[State, str] = {self.start: ""}
        work = deque([("", self.start)])
        while work:
            w, q = work.popleft()
            if len(w) >= max_len:
                continue
            for a in sorted(self.alphabet):
                r = self.delta[(q, a)]
                if r not in rep:
                    rep[r] = w + a
                    work.append((w + a, r))
        return rep


def _single_state_dfa(alphabet: FrozenSet[Sym], accepting: bool) -> DFA:
    return DFA(
        states=frozenset({0}),
        alphabet=alphabet,
        delta={(0, a): 0 for a in alphabet},
        start=0,
        accepting=frozenset({0}) if accepting else frozenset(),
    )


# ---------------------------------------------------------------------------
# Section 4. The NFA, with epsilon transitions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NFA:
    """Nondeterministic automaton. `trans[(q, a)]` is a set; a == None is epsilon.

    Acceptance is existential: one accepting path suffices.
    """

    states: FrozenSet[State]
    alphabet: FrozenSet[Sym]
    trans: Dict[Tuple[State, Optional[Sym]], FrozenSet[State]]
    starts: FrozenSet[State]
    accepting: FrozenSet[State]

    def move(self, qs: Iterable[State], a: Optional[Sym]) -> FrozenSet[State]:
        out: Set[State] = set()
        for q in qs:
            out |= self.trans.get((q, a), frozenset())
        return frozenset(out)

    def eclose(self, qs: Iterable[State]) -> FrozenSet[State]:
        """States reachable using epsilon edges only (Section 4)."""
        seen = set(qs)
        work = deque(seen)
        while work:
            q = work.popleft()
            for r in self.trans.get((q, None), frozenset()):
                if r not in seen:
                    seen.add(r)
                    work.append(r)
        return frozenset(seen)

    def accepts(self, w: Sequence[Sym]) -> bool:
        """Thompson simulation: track the whole set of live states. O(|w| * n^2)."""
        cur = self.eclose(self.starts)
        for a in w:
            cur = self.eclose(self.move(cur, a))
            if not cur:
                return False
        return bool(cur & self.accepting)

    def determinize(self) -> DFA:
        """Rabin-Scott subset construction, exploring reachable subsets only.

        The DFA state after prefix u is the set of NFA states reachable on u --
        which is exactly the information Section 1 proved to be necessary and
        sufficient.
        """
        start = self.eclose(self.starts)
        states: Set[FrozenSet[State]] = {start}
        delta: Dict[Tuple[State, Sym], State] = {}
        work = deque([start])
        while work:
            s = work.popleft()
            for a in self.alphabet:
                t = self.eclose(self.move(s, a))
                delta[(s, a)] = t
                if t not in states:
                    states.add(t)
                    work.append(t)
        return DFA(
            states=frozenset(states),
            alphabet=self.alphabet,
            delta=delta,
            start=start,
            accepting=frozenset(s for s in states if s & self.accepting),
        )

    def reverse(self) -> "NFA":
        trans: Dict[Tuple[State, Optional[Sym]], Set[State]] = {}
        for (q, a), rs in self.trans.items():
            for r in rs:
                trans.setdefault((r, a), set()).add(q)
        return NFA(
            states=self.states,
            alphabet=self.alphabet,
            trans={k: frozenset(v) for k, v in trans.items()},
            starts=self.accepting,
            accepting=self.starts,
        )


# ---------------------------------------------------------------------------
# Section 7. Regular expressions: syntax, parser, Thompson construction.
# ---------------------------------------------------------------------------
#
# The AST is a plain tuple so that it is hashable and can serve as a DFA state
# in the derivative construction of Section 8. Smart constructors normalise
# modulo the ACI laws (associativity, commutativity, idempotence of +), which is
# exactly what makes Brzozowski's derivative set finite.

EMPTY = ("empty",)  # the empty language, no words at all
EPS = ("eps",)  # the language {epsilon}


def sym(c: Sym):
    return ("sym", c)


def alt(*rs):
    parts: Set[tuple] = set()
    for r in rs:
        if r == EMPTY:
            continue
        if r[0] == "alt":
            parts |= set(r[1])
        else:
            parts.add(r)
    if not parts:
        return EMPTY
    if len(parts) == 1:
        return next(iter(parts))
    return ("alt", frozenset(parts))


def cat(*rs):
    parts = []
    for r in rs:
        if r == EMPTY:
            return EMPTY
        if r == EPS:
            continue
        if r[0] == "cat":
            parts.extend(r[1])
        else:
            parts.append(r)
    if not parts:
        return EPS
    if len(parts) == 1:
        return parts[0]
    return ("cat", tuple(parts))


def star(r):
    if r in (EMPTY, EPS):
        return EPS
    if r[0] == "star":
        return r
    return ("star", r)


def show(r) -> str:
    kind = r[0]
    if kind == "empty":
        return "0"
    if kind == "eps":
        return "e"
    if kind == "sym":
        return r[1]
    if kind == "alt":
        return "(" + "|".join(sorted(show(x) for x in r[1])) + ")"
    if kind == "cat":
        return "".join(show(x) for x in r[1])
    return show(r[1]) + "*"


class Parser:
    """expr := term ('|' term)* ; term := factor* ; factor := atom ('*'|'+'|'?')*"""

    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0

    def peek(self) -> Optional[str]:
        return self.s[self.i] if self.i < len(self.s) else None

    def parse(self):
        r = self.expr()
        if self.i != len(self.s):
            raise ValueError(f"trailing input at {self.i}: {self.s[self.i:]!r}")
        return r

    def expr(self):
        r = self.term()
        while self.peek() == "|":
            self.i += 1
            r = alt(r, self.term())
        return r

    def term(self):
        parts = []
        while self.peek() is not None and self.peek() not in "|)":
            parts.append(self.factor())
        return cat(*parts) if parts else EPS

    def factor(self):
        r = self.atom()
        while self.peek() in ("*", "+", "?"):
            op = self.s[self.i]
            self.i += 1
            if op == "*":
                r = star(r)
            elif op == "+":
                r = cat(r, star(r))
            else:
                r = alt(r, EPS)
        return r

    def atom(self):
        c = self.peek()
        if c == "(":
            self.i += 1
            r = self.expr()
            if self.peek() != ")":
                raise ValueError("unbalanced parenthesis")
            self.i += 1
            return r
        if c is None or c in "|)*+?":
            raise ValueError(f"unexpected {c!r} at {self.i}")
        self.i += 1
        return sym(c)


def parse(text: str):
    return Parser(text).parse()


def thompson(r, alphabet: FrozenSet[Sym]) -> NFA:
    """Regex -> epsilon-NFA, O(size of r) states (Section 7)."""
    ids = count()
    trans: Dict[Tuple[State, Optional[Sym]], Set[State]] = {}
    states: Set[State] = set()

    def new() -> int:
        q = next(ids)
        states.add(q)
        return q

    def edge(p: State, a: Optional[Sym], q: State) -> None:
        trans.setdefault((p, a), set()).add(q)

    def build(r) -> Tuple[int, int]:
        kind = r[0]
        if kind == "empty":
            return new(), new()  # no path between them
        if kind == "eps":
            s, t = new(), new()
            edge(s, None, t)
            return s, t
        if kind == "sym":
            s, t = new(), new()
            edge(s, r[1], t)
            return s, t
        if kind == "alt":
            s, t = new(), new()
            for x in r[1]:
                xs, xt = build(x)
                edge(s, None, xs)
                edge(xt, None, t)
            return s, t
        if kind == "cat":
            first_s = None
            prev_t = None
            for x in r[1]:
                xs, xt = build(x)
                if first_s is None:
                    first_s = xs
                else:
                    edge(prev_t, None, xs)
                prev_t = xt
            return first_s, prev_t
        # star
        s, t = new(), new()
        xs, xt = build(r[1])
        edge(s, None, xs)
        edge(s, None, t)  # zero repetitions
        edge(xt, None, xs)  # loop back
        edge(xt, None, t)
        return s, t

    s, t = build(r)
    return NFA(
        states=frozenset(states),
        alphabet=alphabet,
        trans={k: frozenset(v) for k, v in trans.items()},
        starts=frozenset({s}),
        accepting=frozenset({t}),
    )


# ---------------------------------------------------------------------------
# Section 8. Brzozowski derivatives: a DFA straight out of the syntax.
# ---------------------------------------------------------------------------


def nullable(r) -> bool:
    kind = r[0]
    if kind in ("empty", "sym"):
        return False
    if kind in ("eps", "star"):
        return True
    if kind == "alt":
        return any(nullable(x) for x in r[1])
    return all(nullable(x) for x in r[1])  # cat


def deriv(r, a: Sym):
    """d_a r, denoting a^-1 L(r). The concatenation case is the only subtle one."""
    kind = r[0]
    if kind in ("empty", "eps"):
        return EMPTY
    if kind == "sym":
        return EPS if r[1] == a else EMPTY
    if kind == "alt":
        return alt(*[deriv(x, a) for x in r[1]])
    if kind == "star":
        return cat(deriv(r[1], a), r)
    # cat: r = x1 x2 ... xn
    parts = r[1]
    head, tail = parts[0], cat(*parts[1:])
    d = cat(deriv(head, a), tail)
    return alt(d, deriv(tail, a)) if nullable(head) else d


def derivative_dfa(r, alphabet: FrozenSet[Sym]) -> DFA:
    """States are derivative expressions; the ACI normalisation keeps them finite."""
    states: Set[tuple] = {r}
    delta: Dict[Tuple[State, Sym], State] = {}
    work = deque([r])
    while work:
        e = work.popleft()
        for a in alphabet:
            d = deriv(e, a)
            delta[(e, a)] = d
            if d not in states:
                states.add(d)
                work.append(d)
    return DFA(
        states=frozenset(states),
        alphabet=alphabet,
        delta=delta,
        start=r,
        accepting=frozenset(e for e in states if nullable(e)),
    )


# ---------------------------------------------------------------------------
# Handy constructions used by the demos.
# ---------------------------------------------------------------------------


def nth_from_end_nfa(n: int, letter: Sym = "a", alphabet: str = "ab") -> NFA:
    """n+1 states, nondeterministically guessing where the end is (Section 4)."""
    sigma = frozenset(alphabet)
    trans: Dict[Tuple[State, Optional[Sym]], Set[State]] = {}
    for a in sigma:
        trans.setdefault((0, a), set()).add(0)  # stay and keep guessing
    trans.setdefault((0, letter), set()).add(1)  # guess: this is the n-th from end
    for i in range(1, n):
        for a in sigma:
            trans.setdefault((i, a), set()).add(i + 1)
    return NFA(
        states=frozenset(range(n + 1)),
        alphabet=sigma,
        trans={k: frozenset(v) for k, v in trans.items()},
        starts=frozenset({0}),
        accepting=frozenset({n}),
    )


def mod_dfa(m: int) -> DFA:
    """Big-endian binary numbers divisible by m -- exactly m states (Section 2)."""
    sigma = frozenset("01")
    delta = {}
    for r in range(m):
        delta[(r, "0")] = (2 * r) % m
        delta[(r, "1")] = (2 * r + 1) % m
    return DFA(frozenset(range(m)), sigma, delta, 0, frozenset({0}))


def words_up_to(alphabet: Iterable[Sym], n: int):
    alpha = sorted(alphabet)
    yield ""
    cur = [""]
    for _ in range(n):
        nxt = [w + a for w in cur for a in alpha]
        yield from nxt
        cur = nxt


def agree(m1, m2, alphabet: Iterable[Sym], n: int = 9) -> bool:
    """Brute-force agreement check on all words up to length n."""
    return all(m1.accepts(w) == m2.accepts(w) for w in words_up_to(alphabet, n))


# ---------------------------------------------------------------------------
# Section 23. Angluin's L*.
# ---------------------------------------------------------------------------


class Teacher:
    """A minimally adequate teacher backed by a known DFA.

    Membership queries just run the machine. Equivalence queries do what a real
    teacher cannot: compute an exact counterexample by a product search. In
    practice this slot is filled by conformance testing.
    """

    def __init__(self, target: DFA) -> None:
        self.target = target
        self.membership_queries = 0
        self.equivalence_queries = 0

    def member(self, w: str) -> bool:
        self.membership_queries += 1
        return self.target.accepts(w)

    def equivalent(self, hyp: DFA) -> Optional[str]:
        """None if equal, else a shortest distinguishing word."""
        self.equivalence_queries += 1
        diff = self.target.product(hyp, lambda x, y: x != y)
        return diff.shortest_word()


class LStar:
    """Angluin 1987, with the Rivest-Schapire binary search on counterexamples.

    The observation table's rows approximate the futures u^-1 L of Section 1;
    the algorithm terminates because each counterexample splits a state, and the
    number of splits is bounded by the Myhill-Nerode index (Section 9).
    """

    def __init__(self, alphabet: Iterable[Sym], teacher: Teacher) -> None:
        self.sigma = sorted(alphabet)
        self.teacher = teacher
        self.S = [""]  # access strings, prefix-closed
        self.E = [""]  # experiments, suffix-closed
        self.T: Dict[str, bool] = {}

    def obs(self, u: str, e: str) -> bool:
        key = u + "\0" + e
        if key not in self.T:
            self.T[key] = self.teacher.member(u + e)
        return self.T[key]

    def row(self, u: str) -> Tuple[bool, ...]:
        return tuple(self.obs(u, e) for e in self.E)

    def close_and_make_consistent(self) -> None:
        changed = True
        while changed:
            changed = False
            rows = {self.row(u): u for u in self.S}
            # Closed: every one-letter extension must match some row in S.
            for u in list(self.S):
                for a in self.sigma:
                    if self.row(u + a) not in rows:
                        self.S.append(u + a)
                        rows[self.row(u + a)] = u + a
                        changed = True
            if changed:
                continue
            # Consistent: equal rows must stay equal after one letter.
            for i, u1 in enumerate(self.S):
                for u2 in self.S[i + 1 :]:
                    if self.row(u1) != self.row(u2):
                        continue
                    for a in self.sigma:
                        r1, r2 = self.row(u1 + a), self.row(u2 + a)
                        if r1 != r2:
                            k = next(j for j in range(len(self.E)) if r1[j] != r2[j])
                            self.E.append(a + self.E[k])
                            changed = True
                            break
                    if changed:
                        break
                if changed:
                    break

    def hypothesis(self) -> DFA:
        rows: Dict[Tuple[bool, ...], str] = {}
        for u in self.S:
            rows.setdefault(self.row(u), u)
        states = frozenset(rows.values())
        delta = {}
        for u in states:
            for a in self.sigma:
                delta[(u, a)] = rows[self.row(u + a)]
        return DFA(
            states=states,
            alphabet=frozenset(self.sigma),
            delta=delta,
            start=rows[self.row("")],
            accepting=frozenset(u for u in states if self.obs(u, "")),
        )

    def refine(self, ce: str) -> None:
        """Rivest-Schapire: binary search for the index where the hypothesis'
        state and the target's future diverge; add that one suffix."""
        hyp = self.hypothesis()
        rows: Dict[Tuple[bool, ...], str] = {}
        for u in self.S:
            rows.setdefault(self.row(u), u)

        def access(prefix: str) -> str:
            return hyp.run(prefix)

        lo, hi = 0, len(ce)
        base = self.teacher.member(ce)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            # Replace the first `mid` symbols by their access string and see
            # whether the answer still matches the true one.
            candidate = access(ce[:mid]) + ce[mid:]
            if self.teacher.member(candidate) == base:
                lo = mid
            else:
                hi = mid
        suffix = ce[hi:]
        if suffix not in self.E:
            self.E.append(suffix)
        else:  # fall back: add every suffix (still terminates)
            for i in range(len(ce)):
                if ce[i:] not in self.E:
                    self.E.append(ce[i:])
                    break

    def learn(self, max_rounds: int = 100) -> DFA:
        for _ in range(max_rounds):
            self.close_and_make_consistent()
            hyp = self.hypothesis()
            ce = self.teacher.equivalent(hyp)
            if ce is None:
                return hyp
            self.refine(ce)
        raise RuntimeError("L* did not converge")


# ---------------------------------------------------------------------------
# Demonstrations. Each one checks a claim made in the document.
# ---------------------------------------------------------------------------


def demo_derived_dfa() -> None:
    print("== Section 2: a DFA derived, not designed ==")
    d = mod_dfa(3)
    for w in ["", "0", "11", "110", "1001", "1010"]:
        n = int(w, 2) if w else 0
        assert d.accepts(w) == (n % 3 == 0), w
    print("   divisibility by 3 over big-endian binary: 3 states, verified")
    assert len(mod_dfa(7).minimize().states) == 7
    print("   divisibility by 7: minimal size is 7, as the futures argument predicts")


def demo_subset_and_blowup() -> None:
    print("\n== Sections 4-5: subset construction, and the exponential is real ==")
    for n in range(1, 6):
        nfa = nth_from_end_nfa(n)
        det = nfa.determinize()
        minimal = det.minimize()
        assert agree(nfa, minimal, "ab", 8)
        print(
            f"   n={n}: NFA {len(nfa.states):2d} states"
            f" -> DFA {len(det.states):3d} -> minimal {len(minimal.states):3d}"
            f"   (2^n = {2 ** n})"
        )
        assert len(minimal.states) == 2**n, "fooling-set lower bound must be attained"
    print("   the minimal DFA is exactly 2^n: the lower bound of Section 5 is tight")


def demo_closure() -> None:
    print("\n== Section 6: closure by product and complement ==")
    even_a = DFA(
        frozenset({0, 1}),
        frozenset("ab"),
        {(0, "a"): 1, (1, "a"): 0, (0, "b"): 0, (1, "b"): 1},
        0,
        frozenset({0}),
    )
    odd_b = DFA(
        frozenset({0, 1}),
        frozenset("ab"),
        {(0, "b"): 1, (1, "b"): 0, (0, "a"): 0, (1, "a"): 1},
        0,
        frozenset({1}),
    )
    both = even_a.product(odd_b, lambda x, y: x and y).minimize()
    for w in words_up_to("ab", 6):
        assert both.accepts(w) == (w.count("a") % 2 == 0 and w.count("b") % 2 == 1)
    print(f"   (even #a) and (odd #b): {len(both.states)} states, matches Section 9")
    assert len(both.states) == 4
    comp = both.complement()
    assert all(comp.accepts(w) != both.accepts(w) for w in words_up_to("ab", 5))
    print("   complement verified on all words up to length 5")


def demo_regex() -> None:
    print("\n== Sections 7-8: Kleene's theorem, two compilations, one language ==")
    sigma = frozenset("ab")
    cases = [
        ("(a|b)*abb", lambda w: w.endswith("abb")),
        ("a*", lambda w: set(w) <= {"a"}),
        ("(ab)*", lambda w: w == "ab" * (len(w) // 2)),
        ("(a|b)*a(a|b)(a|b)", lambda w: len(w) >= 3 and w[-3] == "a"),
    ]
    for pattern, oracle in cases:
        r = parse(pattern)
        via_thompson = thompson(r, sigma).determinize().minimize()
        via_derivatives = derivative_dfa(r, sigma).minimize()
        assert via_thompson.equivalent(via_derivatives), pattern
        for w in words_up_to("ab", 7):
            assert via_thompson.accepts(w) == oracle(w), (pattern, w)
        print(
            f"   {pattern:18s} Thompson->subset->min = {len(via_thompson.states)} states,"
            f" derivatives->min = {len(via_derivatives.states)} states, equivalent"
        )
    print("   derivative states are literally the futures u^-1 L, e.g. for (a|b)*abb:")
    d = derivative_dfa(parse("(a|b)*abb"), sigma)
    for u in ["", "a", "ab", "abb"]:
        e = parse("(a|b)*abb")
        for ch in u:
            e = deriv(e, ch)
        print(f"      d_{u or 'e':4s} = {show(e)}")


def demo_minimization() -> None:
    print("\n== Section 10: Hopcroft and Brzozowski agree ==")
    r = parse("(a|b)*a(a|b)(a|b)(a|b)")
    d = thompson(r, frozenset("ab")).determinize()
    h = d.minimize()
    b = d.minimize_brzozowski()
    assert h.equivalent(b) and len(h.states) == len(b.states)
    print(
        f"   raw subset DFA {len(d.states)} states"
        f" -> Hopcroft {len(h.states)} -> Brzozowski {len(b.states)} (equal, as they must be)"
    )
    print("   Myhill-Nerode class representatives of the minimal machine:")
    reps = h.nerode_classes()
    shown = sorted(reps.values(), key=lambda s: (len(s), s))[:8]
    print("      " + ", ".join(repr(x) for x in shown) + ", ...")


def demo_decisions() -> None:
    print("\n== Section 12: decision procedures ==")
    sigma = frozenset("ab")
    a = thompson(parse("(a|b)*abb(a|b)*"), sigma).determinize().minimize()
    b = thompson(parse("(a|b)*ab(a|b)*"), sigma).determinize().minimize()
    # a subset b  <=>  a intersect complement(b) is empty
    not_b = b.complement()
    witness = a.product(not_b, lambda x, y: x and y).shortest_word()
    print(f"   L(.*abb.*) subseteq L(.*ab.*)? {'yes' if witness is None else 'no'}")
    assert witness is None
    witness2 = b.product(a.complement(), lambda x, y: x and y).shortest_word()
    print(f"   the converse? no -- shortest counterexample {witness2!r}")
    assert witness2 is not None and "ab" in witness2 and "abb" not in witness2
    empty = a.product(a.complement(), lambda x, y: x and y)
    assert empty.is_empty()
    print("   L intersect complement(L) is empty, by reachability")


def demo_learning() -> None:
    print("\n== Section 23: L* learns the machine by asking questions ==")
    targets = [
        ("(a|b)*abb", "ab"),
        ("(a|b)*a(a|b)(a|b)", "ab"),
        ("(aa)*(bb)*", "ab"),
    ]
    for pattern, alpha in targets:
        target = thompson(parse(pattern), frozenset(alpha)).determinize().minimize()
        teacher = Teacher(target)
        learned = LStar(alpha, teacher).learn()
        assert learned.equivalent(target)
        assert len(learned.minimize().states) == len(target.states)
        print(
            f"   {pattern:20s} learned exactly:"
            f" {len(target.states)} states,"
            f" {teacher.membership_queries:4d} membership +"
            f" {teacher.equivalence_queries} equivalence queries"
        )
    print("   in each case the learned machine is the minimal one -- Myhill-Nerode again")


def demo_nonregular() -> None:
    print("\n== Sections 1 and 11: showing a limit, without a pumping lemma ==")
    # L = { a^n b^n }. Compute each prefix's future, restricted to the finitely
    # many suffixes b^0..b^k -- enough to separate the prefixes pairwise.
    k = 8
    in_L = lambda w: w == "a" * (len(w) // 2) + "b" * (len(w) // 2) and len(w) % 2 == 0
    futures = {
        "a" * i: tuple(in_L("a" * i + "b" * j) for j in range(k + 1)) for i in range(k)
    }
    assert len(set(futures.values())) == len(futures), "must be pairwise distinct"
    print(
        f"   prefixes a^0..a^{k - 1} have {len(set(futures.values()))} pairwise"
        " distinct futures (b^i separates a^i)"
    )
    print("   the pattern continues for every i, so index(L) is infinite")
    print("   => no bounded-memory device decides a^n b^n. No machine model needed.")


def main() -> None:
    print("Finite automata, built from nothing. See FINITE_AUTOMATA.md.\n")
    demo_derived_dfa()
    demo_subset_and_blowup()
    demo_closure()
    demo_regex()
    demo_minimization()
    demo_decisions()
    demo_learning()
    demo_nonregular()
    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()
