# Finite Automata, Derived From Nothing

*A monologue. No prerequisites assumed — not even the idea of a "machine". Every definition
below is derived rather than announced: I will only write down a definition once the argument
has forced it. Where I make a claim, I prove it or say plainly that I am not proving it.*

*Last section is the state of the field as of July 2026.*

---

## Table of contents

**Book I — Forcing the definitions**
0. [Absolute nothing](#0-absolute-nothing)
1. [Why anything at all must have state](#1-why-anything-at-all-must-have-state)
2. [The DFA, forced](#2-the-dfa-forced)
3. [The first real theorem: finiteness is a *bound*](#3-the-first-real-theorem-finiteness-is-a-bound)

**Book II — The structure of the class**
4. [Nondeterminism: a lie that costs nothing](#4-nondeterminism-a-lie-that-costs-nothing)
5. [Why the exponential is real](#5-why-the-exponential-is-real)
6. [Closure: an algebra of machines](#6-closure-an-algebra-of-machines)
7. [Regular expressions, and Kleene's theorem](#7-regular-expressions-and-kleenes-theorem)
8. [Derivatives: Brzozowski's reframing](#8-derivatives-brzozowskis-reframing)

**Book III — The canonical object**
9. [Myhill–Nerode: the machine was there all along](#9-myhillnerode-the-machine-was-there-all-along)
10. [Minimization algorithms](#10-minimization-algorithms)
11. [Pumping, and how to prove a limit](#11-pumping-and-how-to-prove-a-limit)
12. [Deciding things about automata](#12-deciding-things-about-automata)

**Book IV — Three other faces of the same class**
13. [Algebra: the transition monoid](#13-algebra-the-transition-monoid)
14. [Logic: Büchi–Elgot–Trakhtenbrot](#14-logic-büchielgottrakhtenbrot)
15. [Star-free, aperiodic, first-order, temporal](#15-star-free-aperiodic-first-order-temporal)

**Book V — Changing the rules**
16. [Two-way, alternating, and the succinctness lattice](#16-two-way-alternating-and-the-succinctness-lattice)
17. [Transducers: machines that write](#17-transducers-machines-that-write)
18. [Weights, probabilities, quantum](#18-weights-probabilities-quantum)
19. [Infinite words: ω-automata](#19-infinite-words-ω-automata)
20. [Trees, and the strongest decidability results we have](#20-trees-and-the-strongest-decidability-results-we-have)
21. [Infinite alphabets: register, symbolic, nominal](#21-infinite-alphabets-register-symbolic-nominal)

**Book VI — Learning and inference**
22. [Learning an automaton from examples](#22-learning-an-automaton-from-examples)
23. [Angluin's L\*, and what replaced it](#23-angluins-l-and-what-replaced-it)

**Book VII — The machine in the world**
24. [Where finite automata actually run in 2026](#24-where-finite-automata-actually-run-in-2026)
25. [The 2026 frontier](#25-the-2026-frontier)
26. [What is still open](#26-what-is-still-open)
27. [Reading path](#27-reading-path)

A companion file, [`automata.py`](automata.py), implements every construction in Books I–III
and Book VI from scratch, with tests. Nothing in it is imported from a library.

---

# Book I — Forcing the definitions

## 0. Absolute nothing

Start with nothing. I will not assume machines, computers, states, or even numbers beyond
counting. I need to invent the subject, so let me find the smallest possible starting point
and see what it forces.

The one thing I cannot do without is **distinction**. If I cannot tell two things apart, I
cannot say anything at all. So posit a finite, nonempty collection of distinguishable marks.
Call it Σ, the *alphabet*; call its elements *symbols*. Finiteness is not a technicality —
it is the claim that my capacity to perceive distinctions is bounded. Everything downstream
inherits that.

Next: things happen in order. One mark, then another. A finite ordered list of symbols is a
**string** (or word). Write it by juxtaposition: `abba`. The list of length zero exists and
matters — call it ε. Let |w| denote length.

Two strings can be joined: `u · v`, concatenation, usually written `uv`. Note immediately what
kind of object I have built:

- concatenation is associative: `(uv)w = u(vw)`, since both are "just the marks in order";
- ε is a two-sided identity: `εw = wε = w`;
- there are no inverses — you cannot un-append.

An associative operation with an identity and no promised inverses is a **monoid**. So the
very first structure that appears, before any machine, is the free monoid Σ\*: all finite
strings over Σ. "Free" means it satisfies no equations beyond the ones forced by the axioms —
`ab` and `ba` are different because nothing said they should be equal. This is not decoration.
Book IV will show that the entire theory of finite automata is the theory of *finite* monoids,
and that the free monoid is where all the questions live.

Now: what is a *problem*? The most primitive thing I can ask about a string is a yes/no
question. A yes/no question about strings is exactly a subset L ⊆ Σ\* — the set of strings
where the answer is yes. Call it a **language**. Not "language" in the human sense; it is just
"a property of strings", identified with its extension.

So the object of study is fixed before any machinery exists:

> **Given a property of finite strings, can it be decided by something with bounded
> resources — and if so, how cheaply?**

One fact worth internalizing before we go on, because it sets the scale of the problem. Σ\* is
countably infinite (enumerate by length, then alphabetically). The set of *languages* is
therefore the powerset of a countably infinite set, which by Cantor's diagonal argument is
uncountable. Any notion of "machine" I invent will be a finite text over some finite alphabet,
so there are only countably many machines. Therefore:

> **Almost every language is not decidable by any finite description whatsoever.**

Not "hard to decide" — undescribable. This is true before we say anything about computation.
The interesting question is never "can everything be done" (no) but "what exactly can be done
under this budget, and what does the boundary look like".

Let me now pick the smallest possible budget.

## 1. Why anything at all must have state

I want to answer "is w ∈ L?" by reading w. Impose the harshest constraints I can think of and
see whether anything survives:

1. I read the string once, left to right, one symbol at a time.
2. I cannot go back.
3. I cannot store the string.
4. I have a bounded amount of memory, fixed in advance, independent of |w|.
5. I must be ready to answer at any moment.

Constraint 4 is the whole game. Let me take it seriously and ask what "memory" even means
here, since I refuse to assume it.

Suppose I have already read a prefix `u`. The rest of the string, `v`, is still coming. My
eventual answer is determined by `uv`. But I have thrown `u` away — all that remains is
whatever is left in my bounded memory. So the memory contents after reading `u` must be
*sufficient* to determine, for every possible continuation `v`, whether `uv ∈ L`.

That sentence is the seed of everything. Turn it around: define, for a prefix u,

    F(u) = { v ∈ Σ* : uv ∈ L }        the "future" of u, also written u⁻¹L

Claim: if `F(u₁) = F(u₂)`, then no continuation can ever distinguish u₁ from u₂ — they are
interchangeable forever, and my memory is *permitted* to forget the difference. Conversely if
`F(u₁) ≠ F(u₂)`, some continuation `v` has (say) `u₁v ∈ L` but `u₂v ∉ L`; if my memory were in
the same configuration after both prefixes, it would behave identically on `v` and be wrong on
one of them. So my memory is *required* to distinguish them.

Therefore, with no assumptions at all about what memory is made of:

> The number of distinct memory configurations I need is exactly the number of distinct sets
> F(u), over all prefixes u ∈ Σ\*.

Two things fall out at once, and they are the two halves of the subject.

**(a)** If that number is finite, a bounded-memory device is *possible*, because I can just
let the memory be "which of the finitely many futures am I in". Call each such configuration
a **state**. State was not assumed; it was derived. A state is an equivalence class of pasts
that agree on all futures.

**(b)** If that number is infinite, a bounded-memory device is *impossible*, no matter how
clever. Not "hard" — impossible, by the pigeonhole argument above. This is already the deepest
theorem in the subject and I have not defined an automaton yet. Everything in Book III is
bookkeeping around it.

Let me sanity-check (b) on the classic example. L = { aⁿbⁿ : n ≥ 0 }. Take prefixes `a`, `aa`,
`aaa`, …. Then F(aⁱ) contains `bⁱ` and no other pure-b string, so all these futures are
pairwise distinct — infinitely many. Hence *no* bounded-memory left-to-right device decides
`aⁿbⁿ`. Done, in three lines, with no pumping lemma, no machine model, nothing. Remember this;
in §11 I will argue that the pumping lemma is the *weaker* tool that everyone teaches first
for historical reasons.

And check the positive direction too. L = strings over {a,b} containing `aa`. Futures: from a
prefix that already contains `aa`, the future is everything, Σ\*. From a prefix ending in `a`
without `aa` yet, the future is "starts with a, or eventually gets `aa`". From a prefix ending
in `b` (or empty) without `aa` yet, another future. That is three futures total. Three states.
Finite. So the device exists — and I derived not just its existence but its *exact minimum
size*, without designing it.

There is one more forced consequence. How does memory update? After prefix u, reading symbol
a, my prefix is ua, and

    F(ua) = { v : uav ∈ L } = { v : av ∈ F(u) } = a⁻¹F(u)

The new future depends only on the old future and the symbol read. **The update is a function
of (state, symbol) alone.** I did not choose this design; it is a theorem about the definition
of F. Similarly "should I answer yes right now?" after prefix u is "is ε ∈ F(u)?", which
depends only on the state.

Every ingredient of the definition I am about to write has now been forced.

## 2. The DFA, forced

**Definition.** A *deterministic finite automaton* is a 5-tuple

    A = (Q, Σ, δ, q₀, F)

- `Q` — a finite nonempty set of **states** (the possible memory configurations),
- `Σ` — the finite alphabet,
- `δ : Q × Σ → Q` — the **transition function** (the forced update rule),
- `q₀ ∈ Q` — the **initial state** (the configuration before reading anything),
- `F ⊆ Q` — the **accepting states** (those whose future contains ε).

Extend δ to strings by the only definition that composes:

    δ*(q, ε)  = q
    δ*(q, wa) = δ( δ*(q, w), a )

and define the **language recognized**:

    L(A) = { w ∈ Σ* : δ*(q₀, w) ∈ F }

A language is **regular** iff some DFA recognizes it. (The word "regular" is Kleene's, and is
historically arbitrary; read it as "finite-state".)

Some observations that cost nothing but pay later:

- δ is *total* and *single-valued*. Totality means the machine never gets stuck; if a natural
  design wants to get stuck, add a **sink** state with δ(sink, a) = sink, sink ∉ F.
- A run on w of length n visits exactly n+1 states. Time is Θ(n), with the constant being one
  table lookup. This is why lexers are fast: a DFA step is `state = table[state][byte]`, which
  a modern CPU does in a couple of cycles, branch-free.
- Space is Θ(1) in the input. That is the entire point.
- The machine is a *labelled directed graph* with out-degree exactly |Σ|. Automata theory and
  graph theory are the same subject viewed at different angles, and several later algorithms
  (reachability, SCC decomposition, bisimulation) are graph algorithms wearing a hat.

Worked example, built by the method of §1 rather than by inspiration. L = binary strings that,
read as a big-endian number, are ≡ 0 mod 3. What is F(u)? Whether `uv ∈ L` depends on `u` only
through `value(u) mod 3`, because appending v does `value(uv) = value(u)·2^|v| + value(v)`, and
mod 3 that needs only `value(u) mod 3`. And all three residues are genuinely distinguishable
(ε distinguishes 0 from 1 and 2; `1` maps 1↦3≡0 but 2↦5≡2, so 1 and 2 differ). So exactly three
states, named 0, 1, 2:

    δ(r, 0) = 2r mod 3        δ(r, 1) = (2r+1) mod 3       q₀ = 0,  F = {0}

That is a complete divisibility tester in nine table entries, and the derivation shows it is
optimal. This generalizes: divisibility by m needs exactly m states (the futures are the m
residues, all distinguishable), and "is the k-th symbol from the *start* an a" needs k+2 while
"the k-th from the *end*" will turn out to need 2^k — a gap we will explain in §5.

## 3. The first real theorem: finiteness is a *bound*

Before building more machinery, let me extract the pigeonhole consequence in the form used
constantly later.

**Lemma (state repetition).** If A has n states and w ∈ L(A) with |w| ≥ n, then the run on w
visits some state twice.

*Proof.* The run visits |w|+1 ≥ n+1 states from a set of size n. □

**Corollary (nonemptiness and finiteness).** L(A) ≠ ∅ iff A accepts some word of length < n.
L(A) is infinite iff A accepts some word of length ≥ n and < 2n.

*Proof sketch.* If a shortest accepted word had length ≥ n, a repeated state would let us
excise the loop and get a shorter accepted word — contradiction. For infiniteness, a loop
reachable from q₀ and co-reachable to F can be pumped; conversely, an accepted word of length
≥ n contains such a loop, and lengths in [n, 2n) suffice because a longer witness can be
shortened by cutting one loop at a time. □

So questions that look like they quantify over infinitely many strings are decidable by
*finite search* — indeed by graph reachability, in linear time. Contrast Turing machines,
where the analogous question is undecidable. The whole value of the finite-state restriction
is that it converts semantic questions into graph questions.

---

# Book II — The structure of the class

## 4. Nondeterminism: a lie that costs nothing

Designing DFAs by hand is painful because δ is a *function*: at every point I must commit.
Consider "strings over {a,b} whose 3rd-from-last symbol is a". The honest DFA has to remember
the last three symbols — 8 states — because it cannot know where the end is. But the *natural*
description is: "at some point, guess that you are 3 from the end, check the symbol is a, and
verify exactly three symbols remain."

That word "guess" is not implementable, but it is a legitimate *specification*. Let me define
a mathematical object that permits it and then ask what it costs.

**Definition.** A *nondeterministic finite automaton* is `N = (Q, Σ, Δ, I, F)` with
`Δ ⊆ Q × Σ × Q` (equivalently `Δ : Q × Σ → 2^Q`) and a set of initial states `I ⊆ Q`. A word w
is accepted iff **there exists** at least one path labelled w from some state in I to some
state in F.

Note the asymmetry that makes nondeterminism subtle: acceptance is existential. One good path
suffices; a thousand bad paths do not hurt. This is why complementing an NFA is not "swap F"
(that is flatly wrong) while complementing a DFA is.

The 3rd-from-last NFA is four states in a line: q₀ loops on a,b; `q₀ --a--> q₁ --a,b--> q₂
--a,b--> q₃`, F = {q₃}. Immediately readable. Now, is it more *powerful*?

**Theorem (Rabin–Scott 1959, subset construction).** Every NFA has an equivalent DFA.

*Derivation, not just proof.* I return to §1. The only thing that determines the future
behaviour of an NFA after reading prefix u is **the set of states reachable on u** — nothing
finer is needed (any two prefixes with the same reachable set have identical futures), and
nothing coarser will do in general. So take the states of the DFA to be those sets:

    Q_D = 2^Q            q₀_D = I
    δ_D(S, a) = ⋃_{q∈S} Δ(q, a)
    F_D = { S : S ∩ F ≠ ∅ }        ← the existential, made explicit

An induction on |w| gives δ*_D(I, w) = { q : some path from I on w ends in q }, and acceptance
matches. □

Notice what happened: the "guess" was implemented by *tracking all guesses at once*. That is
the actual content of nondeterminism — not magic, but breadth-first parallelism whose cost is
the number of distinct reachable subsets.

Practically one never materializes 2^Q. You do reachable-subset exploration from I, which
often yields far fewer than 2^n states (for the 3rd-from-last NFA it yields exactly the 8 you
would have written by hand). This "on-the-fly determinization", memoized in a cache with
eviction, is precisely what production regex engines call a *lazy DFA*.

**ε-transitions.** One more convenience: allow `Δ ⊆ Q × (Σ ∪ {ε}) × Q`, so the machine may
move without consuming input. This makes the constructions of §6–§7 trivial to state. Cost:
nothing. Define the ε-closure `E(S)` = states reachable from S by ε-edges only (a graph
reachability, computable once per state set), and run the subset construction with
`δ_D(S,a) = E(⋃_{q∈S} Δ(q,a))`, `q₀_D = E(I)`. Everything else is unchanged.

So DFA, NFA, and ε-NFA all recognize **exactly the same class of languages**. Expressiveness:
identical. Succinctness: not identical at all, which is the subject of the next section.

## 5. Why the exponential is real

The subset construction gives an upper bound of 2ⁿ (and, being slightly careful, 2ⁿ − 1 for
NFAs with a single initial state, since ∅ is only reachable if the NFA can die). Is the
exponent an artifact of a lazy proof? No.

**Theorem.** For each n, the language `Lₙ = { w ∈ {a,b}* : the n-th symbol from the end is a }`
is recognized by an NFA with n+1 states, but every DFA for it needs at least 2ⁿ states.

*Proof of the lower bound — and note that I need no automaton to do it, only §1.* Consider the
2ⁿ prefixes of length exactly n. Take two distinct ones, u ≠ u′; they differ at some position
i (1-indexed from the left), so one has a at position i and the other b. Let v be any string of
length i−1. Then in `uv` the n-th-from-last symbol is exactly u's i-th symbol, and likewise for
`u′v`. Hence exactly one of `uv`, `u′v` is in Lₙ: the futures differ. So all 2ⁿ prefixes have
pairwise distinct futures, and by §1 any bounded-memory device needs ≥ 2ⁿ states. □

This is the standard shape of every state-complexity lower bound: exhibit a **fooling set** of
pairwise-inequivalent prefixes. It is elementary and it is tight.

The gap is not pathological, it is the normal case, and it is why the practical world cares:

- **ReDoS.** A backtracking engine explores nondeterministic paths one at a time by DFS. On
  `(a+)+b` against `aaaa…a`, the number of paths is exponential in the input length, so
  matching takes exponential *time* (not space). Real outages have come from this — the July
  2019 Cloudflare global outage was a regex whose backtracking blew up. The fix is not "write
  better regexes" but "use an engine with a different algorithm": simulate the NFA as a *set*
  of states (Thompson's algorithm, 1968), which is O(|w|·|N|) worst case, or lazily determinize
  with a bounded cache. RE2, Go's `regexp`, and Rust's `regex` do this by construction and
  therefore have no ReDoS class at all — the price is dropping backreferences and (in some
  engines) lookaround.
- **State explosion in verification.** Composing k components multiplies state counts. Every
  technique in model checking (symbolic BDD representation, partial-order reduction,
  abstraction, bounded model checking via SAT) exists to fight this exact exponential.
- **The determinization is sometimes worth it.** For an intrusion-detection ruleset run at line
  rate, a big precomputed DFA table gives you one memory access per byte. The engineering
  question is always "does the DFA fit in cache", which is why §10's minimization matters
  commercially and why hybrid/lazy schemes dominate.

## 6. Closure: an algebra of machines

Regular languages are not just a class; they form an algebra. Each closure property is a
construction, and each construction is the *only* natural one.

**Complement.** Take a DFA (must be a DFA, and must be complete), swap F and Q∖F. Correct
because the run is unique and total: exactly one of A, Ā accepts. Cost: 0 extra states.
On an NFA, you must determinize first — cost 2ⁿ, and that exponential is unavoidable.

**Intersection and union (product construction).** Run both machines simultaneously, in
lockstep, on the same input. States `Q₁ × Q₂`, transitions componentwise, initial `(q₀¹,q₀²)`.
For ∩ take `F₁ × F₂`; for ∪ take `(F₁×Q₂) ∪ (Q₁×F₂)`. Cost: n₁·n₂, which is tight in general.
This construction is one of the most reused ideas in all of computer science — it is how you
check "does the system satisfy the property" (product of system and negated property automaton,
then test emptiness), and it is the core loop of automata-theoretic model checking.

**Concatenation `L₁L₂`.** With ε-NFAs: put the two machines side by side and add ε-edges from
every accepting state of N₁ to every initial state of N₂; new accepting set is F₂. The
nondeterminism handles "where do I split w" — exactly the guess we are now allowed to make.

**Kleene star `L*`.** Add a fresh initial-and-accepting state s with an ε-edge into N's initial
state, plus ε-edges from each state of F back to N's initial state. The fresh state is what
gets you ε ∈ L\* without accidentally accepting ε in the middle of things. (The classic bug is
making N's own initial state accepting; that can wrongly accept strings by "restarting" from a
state that was not really a boundary.)

**Reversal.** Reverse every edge, swap I and F. Yields an NFA for `L^R`. Determinizing that is
exponential in general — but see Brzozowski in §10, where the exponential blowup accidentally
becomes a minimization algorithm.

**Homomorphism and inverse homomorphism.** For `h : Σ* → Γ*` a monoid morphism (determined by
its values on letters), `h(L)` and `h⁻¹(L)` are regular. Inverse images are the easy direction:
relabel each transition. This is the seed of the *variety* theory in §13, where closure under
inverse morphisms is one of the defining axioms.

**Quotients.** `u⁻¹L` is regular (move the start state); `L/u` likewise. §1 already used these.

Two consequences worth stating as slogans, because they organize the whole subject:

> Regular languages form a **Boolean algebra** (closed under ∪, ∩, complement) and a **Kleene
> algebra** (closed under ·, \*, with ∅ and ε). Everything decidable about them ultimately
> reduces to emptiness, via these closures.

For example: is `L₁ ⊆ L₂`? Equivalently `L₁ ∩ L̄₂ = ∅`. Complement is available, product is
available, emptiness is reachability. So inclusion is decidable — mechanically, without a new
idea. Hold onto that pattern; it is the reason the class is so useful and the reason richer
classes (context-free and up) lose their utility the moment they lose complementation.

## 7. Regular expressions, and Kleene's theorem

I now have an algebra of *machines*. Let me ask the dual question: what is the algebra of
*notations*? Take the smallest syntax closed under the operations of §6 that I could plausibly
call primitive:

    r ::= ∅ | ε | a (a ∈ Σ) | r₁ + r₂ | r₁ · r₂ | r*

with the obvious semantics (`+` union, `·` concatenation, `*` = ⋃ₙ Lⁿ, and L⁰ = {ε}). These are
**regular expressions** — the mathematical kind, not the POSIX/PCRE kind, which added a great
deal of non-regular machinery we will get to in §24.

**Theorem (Kleene 1956).** A language is regular (DFA-recognizable) iff it is denoted by a
regular expression.

*Direction 1: expression → automaton (Thompson 1968).* Structural induction, using exactly the
constructions of §6. Base cases are one- or two-state machines. Each operator adds O(1) states
and ε-edges. Result: an ε-NFA with **at most 2m states for an expression of size m**, linear
and with a very regular shape (every state has out-degree ≤ 2), which is why Thompson's
construction is what real engines compile to.

*Direction 2: automaton → expression.* Two classic routes; I prefer the second.

*(a) Kleene/Floyd–Warshall style.* Let `R(i,j,k)` denote the set of words labelling paths from
i to j whose intermediate states are all < k. Then

    R(i,j,k+1) = R(i,j,k) + R(i,k,k) · R(k,k,k)* · R(k,j,k)

which is exactly Floyd–Warshall with (+, ·, \*) in place of (min, +) — the same algorithm over
a different semiring. The answer is `Σ_{f∈F} R(q₀,f,n)`. Clean, obviously correct, and produces
gigantic expressions (2^Θ(n)).

*(b) State elimination.* Draw the automaton with regular expressions on the edges. Repeatedly
delete a non-initial, non-final state k: for every surviving pair (i,j) with edges through k,
add the edge `R(i,k) · R(k,k)* · R(k,j)`. When only start and end remain, read off the answer.
Same content as (a), far more usable by hand, and the order of elimination changes the size of
the result dramatically (choosing a good order is itself NP-hard-ish in practice; heuristics
eliminate low-degree states first). □

An important asymmetry, often glossed over: expression → NFA is linear, but NFA → expression is
**necessarily** exponential. There are n-state DFAs whose smallest equivalent regular expression
has size 2^Ω(n) (Ehrenfeucht–Zeiger 1976 for a specific family; sharpened by Gelade–Neven and
Gruber–Holzer in the 2000s–2010s). So the two formalisms are equal in power and wildly unequal
in economy — a recurring theme: *every* reformulation in this subject preserves the class and
changes the costs.

## 8. Derivatives: Brzozowski's reframing

§1 said: the state after prefix u is the future `u⁻¹L`. §7 gave me a syntax for languages. Put
them together — can I compute the future *symbolically*, on the expression itself, and never
build a machine at all?

**Definition (Brzozowski 1964).** For an expression r and symbol a, define the *derivative*
`∂ₐ r`, intended to denote `a⁻¹L(r)`, and the nullability predicate `ν(r) = ε ∈ L(r)`:

    ν(∅) = ν(a) = false        ν(ε) = true
    ν(r+s) = ν(r) ∨ ν(s)       ν(rs) = ν(r) ∧ ν(s)      ν(r*) = true

    ∂ₐ ∅  = ∅        ∂ₐ ε = ∅        ∂ₐ b = (ε if b = a else ∅)
    ∂ₐ (r + s) = ∂ₐ r + ∂ₐ s
    ∂ₐ (r · s) = (∂ₐ r) · s   +   (ν(r) ? ∂ₐ s : ∅)
    ∂ₐ (r*)    = (∂ₐ r) · r*

The concatenation rule is the only one requiring thought, and it is forced: a word in `rs`
starting with a either has its a consumed inside the r-part, or r matched ε and the a is
consumed inside s.

Then `w ∈ L(r)` iff `ν(∂_w r)` where `∂_w` is derivative iterated over w's symbols. **This is a
complete matcher with no automaton construction.** And it is a DFA in disguise: take states to
be derivative-expressions, `q₀ = r`, transition `∂ₐ`, accepting iff ν.

Why does that terminate? Brzozowski's theorem: modulo the ACI laws (associativity, commutativity,
idempotence of `+`), the set of distinct derivatives of any expression is **finite**. Without
quotienting by ACI it is not finite, which is a good lesson in how much of "the algorithm" lives
in the normalization.

Three reasons this reframing matters far beyond elegance:

1. **The construction is antiderivative-friendly and extends to complement and intersection for
   free.** Add `∂ₐ(r ∩ s) = ∂ₐr ∩ ∂ₐs` and `∂ₐ(¬r) = ¬∂ₐr`, with `ν(¬r) = ¬ν(r)`. Thompson's
   construction cannot do this (complement needs determinization first); derivatives get
   *extended* regular expressions — with ∩ and ¬ — at no structural cost. This is exactly why
   .NET's non-backtracking regex engine (shipped in .NET 7, built on Veanes et al.'s symbolic
   derivative work) is derivative-based.
2. **It is lazy.** You only compute the states you visit. Combined with a memo table it *is* the
   lazy DFA.
3. **It is the bridge to symbolic automata** (§21): if instead of single symbols a you take
   *predicates* over a huge or infinite alphabet, the derivative rules survive verbatim, and you
   get Unicode-scale matching without 1.1M-entry transition tables.

Antimirov (1996) gave the nondeterministic cousin — *partial derivatives*, returning a **set**
of expressions — which yields an NFA with at most one state per syntactic position, essentially
the Glushkov automaton. Glushkov/position automata (ε-free, |r|+1 states) are the other standard
compilation target and matter for engines that want ε-free NFAs.

---

# Book III — The canonical object

## 9. Myhill–Nerode: the machine was there all along

Book I derived states as equivalence classes of prefixes. Let me now make that a theorem, because
it is *the* theorem: it says the minimal automaton is not a construction but a discovery.

**Definition.** For L ⊆ Σ\*, define the *Myhill–Nerode relation*:

    u ≡_L v   ⟺   ∀w ∈ Σ*.  (uw ∈ L  ⟺  vw ∈ L)

This is an equivalence relation, and it is a **right congruence**: `u ≡_L v ⟹ ua ≡_L va` for
every a. (Immediate from the definition.) Let `index(L)` be its number of classes.

**Theorem (Myhill 1957, Nerode 1958).** L is regular **iff** index(L) is finite. Moreover, if it
is finite, there is a DFA with exactly index(L) states recognizing L, and it is the unique
minimal one up to renaming of states.

*Proof.*

(⇐) Suppose index(L) = k < ∞. Build `A_L`: states = the classes `[u]`, initial `[ε]`, transition
`δ([u], a) = [ua]` — well defined precisely because ≡_L is a right congruence — and accepting
iff `[u] ⊆ L` (also well defined: taking w = ε in the definition shows all members of a class
agree on membership). Induction gives `δ*([ε], w) = [w]`, so `w` is accepted iff `w ∈ L`. Hence
L is regular with k states.

(⇒) Suppose a DFA A with n states recognizes L. Define `u ~_A v` iff `δ*(q₀,u) = δ*(q₀,v)`. This
has at most n classes. And `u ~_A v ⟹ u ≡_L v`, because the machine's future behaviour depends
only on the current state. So ≡_L is *coarser* than ~_A, hence index(L) ≤ n < ∞.

(Minimality and uniqueness) The last line also proves that **every** DFA for L has at least
index(L) states, so A_L is minimal. For uniqueness: given any minimal DFA A (all states reachable
and pairwise inequivalent), the map `δ*(q₀,u) ↦ [u]` is a well-defined bijection commuting with
transitions and preserving acceptance — an isomorphism. □

Let me say plainly why this is the center of the subject.

- **It gives a canonical form.** Two DFAs are equivalent iff their minimizations are isomorphic.
  Equivalence testing becomes a graph isomorphism on a canonical object — and since both sides
  are determinized and minimized starting from the same initial state, it is decidable in near
  linear time (§12), not the hard general graph-isomorphism problem.
- **It is a machine-independent characterization.** It mentions no automaton. That makes it the
  tool of choice for lower bounds (§5's fooling set is exactly "these prefixes are pairwise
  ≢_L") and the definition that generalizes: change "future" to "future with weights", "future
  over infinite words", "future over trees", and you get the canonical objects for weighted,
  ω-, and tree automata. The Hankel matrix of a weighted automaton (§18) is the same idea in
  linear algebra: rank replaces index.
- **It is the semantics behind learning.** In §23, Angluin's L\* algorithm is literally an
  algorithm for discovering the classes of ≡_L by experiment: the rows of its observation table
  are approximations of futures, and the algorithm terminates when the approximation becomes a
  right congruence of finite index.

A worked instance, to keep this concrete. L = { w ∈ {a,b}\* : |w|_a is even and |w|_b is odd }.
Futures depend only on (parity of a's so far, parity of b's so far) — four classes — and all
four are distinguishable (from (0,0) the word `b` is accepted; from (0,1) `ε` is accepted; and
so on). So the minimal DFA has exactly 4 states, no cleverness required. Contrast with §5's Lₙ:
there the class count was 2ⁿ, and the *same theorem* delivered the lower bound. One theorem,
both directions.

## 10. Minimization algorithms

Myhill–Nerode says the minimum exists. Now compute it. Assume a DFA with all states reachable
(one BFS to discard the rest; unreachable states are invisible to the language but do inflate
the state count).

Define state equivalence: `p ≈ q` iff for all w, `δ*(p,w) ∈ F ⟺ δ*(q,w) ∈ F`. Minimization =
quotient by ≈. Three algorithms, each teaching something different.

**(1) Moore / table-filling — refinement from above, O(n²|Σ|).**
Start with the partition {F, Q∖F}: distinguishable by ε. Repeat: split any block containing p,q
with `δ(p,a)` and `δ(q,a)` in different blocks, for some a. Stop at a fixed point.
Correctness: by induction, after round k the partition separates exactly the states
distinguishable by words of length ≤ k; the process stabilizes in ≤ n rounds because each round
that changes anything increases the block count. This is *partition refinement*, and it is the
same algorithm as coarsest-stable-partition / bisimulation on labelled graphs.

**(2) Hopcroft 1971 — O(n log n |Σ|).**
Same refinement, but choose splitters cleverly: when a block B splits into B₁ and B₂, you only
need to enqueue the **smaller** of the two as a future splitter. The "process the smaller half"
argument means each state participates in O(log n) splits. This is the same accounting trick as
in union-find by size and in small-to-large merging. Hopcroft's algorithm is still, in 2026, the
practical default; its precise worst case and the analysis of variants (Gries, Knuutila, Valmari)
have been picked over for fifty years, and no o(n log n) general algorithm is known — nor is a
matching lower bound, which is a small, real open problem.

**(3) Brzozowski 1963 — determinize(reverse(determinize(reverse(A)))).**
Astonishing claim: reverse the automaton, determinize (subset construction, keeping only
reachable subsets), reverse again, determinize again. The result is minimal.
*Why it works, in one paragraph:* if N is any NFA whose reverse is deterministic-and-reachable
("co-deterministic"), then the accessible subset construction applied to N yields a DFA all of
whose states are pairwise distinguishable. Reason: the subset-states arising are exactly the
sets of N-states co-reachable to a given word-set, and two distinct such subsets must be
separated by some word. Applying that lemma to the intermediate automaton gives minimality.
The cost is potentially exponential — but on *many* practical inputs it is competitive, it is
two lines of code, and it composes beautifully with symbolic representations (you can do it with
BDDs, and in derivative-based settings you effectively get it for free). It also generalizes: the
"reverse-determinize" duality is an instance of a categorical duality between reachability and
observability that has been formalized in coalgebra (Bonchi, Bonsangue, Rutten, Silva, 2010s) —
the same duality as controllability/observability in linear systems theory.

**On minimizing NFAs.** Everything above is about DFAs, and that is not an accident. Minimal
NFAs are *not unique*, and finding one is **PSPACE-complete** (Jiang–Ravikumar 1993); even
approximating the minimum number of NFA states within a good factor is hard (Gruber–Holzer).
This is the sharpest possible statement of why determinism is mathematically special: it is the
setting in which "the best machine" is a well-defined object.

## 11. Pumping, and how to prove a limit

Everyone learns the pumping lemma first. I have deliberately postponed it, because it is a
*corollary* of §3 and is strictly weaker than §9. Here it is, properly placed.

**Pumping lemma.** If L is regular, there is p ≥ 1 such that every w ∈ L with |w| ≥ p factors as
`w = xyz` with |xy| ≤ p, |y| ≥ 1, and `xyⁱz ∈ L` for all i ≥ 0.

*Proof.* Let p = number of states. On the first p symbols the run repeats a state (§3); let y be
the loop. Traversing the loop i times stays in the automaton's language. □

Use: to show L is *not* regular, assume it is, take the adversary's p, choose a clever w, and
show every legal factorization breaks. For `aⁿbⁿ`: |xy| ≤ p forces y ⊆ a's, so pumping unbalances.

Now the honest caveats, which are usually taught late or not at all:

- **The lemma is necessary, not sufficient.** There are non-regular languages that pump. The
  standard witness is `L = { aⁱbʲcᵏ : i = 1 ⟹ j = k }` (Hopcroft–Ullman): it satisfies the
  pumping condition but is not regular. So a "proof of regularity by pumping" is not a thing.
- **Myhill–Nerode is exactly right, not merely sufficient** — it is an iff. So it is the better
  tool in every case, and it is usually *shorter*: for `aⁿbⁿ`, three lines in §1 versus a page
  of factorization analysis.
- If you want a pumping-style characterization that *is* an iff, the Jaffe pumping lemma and
  Ehrenfeucht–Parikh–Rozenberg's block pumping property exist, but they are essentially
  Myhill–Nerode in disguise and nobody uses them.

Teach pumping as a convenient hammer; teach Myhill–Nerode as the truth.

## 12. Deciding things about automata

Collect what is decidable, with costs, because this table is what makes the class *engineerable*.
Below, n is the state count and the alphabet is fixed.

| Question | DFA | NFA |
|---|---|---|
| `w ∈ L?` | O(\|w\|) | O(\|w\|·n²) (Thompson simulation) or lazily determinized |
| `L = ∅?` | O(n) reachability | O(n) reachability |
| `L` infinite? | O(n) (cycle on a useful path) | O(n) |
| `L = Σ*?` | O(n) (complement + reachability) | **PSPACE-complete** |
| `L₁ ⊆ L₂?` | O(n₁n₂) product + reachability | **PSPACE-complete** |
| `L₁ = L₂?` | near-linear (Hopcroft–Karp) | **PSPACE-complete** |
| minimize | O(n log n) | **PSPACE-complete** |

Two comments.

*The near-linear DFA equivalence* is Hopcroft–Karp's union-find algorithm: merge q₀¹ with q₀²,
then propagate merges through matching transitions; report inequivalent if an accepting state is
ever merged with a rejecting one. Complexity is O(n α(n)) — inverse-Ackermann, effectively
linear. It is also the algorithm that generalizes to *bisimulation up-to congruence* (Bonchi–Pous,
POPL 2013), which checks NFA equivalence with dramatic practical speedups despite the PSPACE
worst case. That paper is a good model of the modern style: the worst case is immovable, so
attack the typical case with better invariants.

*The PSPACE-completeness of NFA universality* (Meyer–Stockmeyer 1972) is the source of nearly all
hardness in this area, by reduction. It also explains the shape of practical tools: they either
determinize (paying space) or work with under/over-approximations.

---

# Book IV — Three other faces of the same class

The class of regular languages keeps reappearing under definitions that share no vocabulary.
That is the strongest evidence that it is a natural object and not an accident of one definition.

## 13. Algebra: the transition monoid

Return to the free monoid of §0. Each word w of a DFA induces a function `Q → Q`, namely
`q ↦ δ*(q,w)`. Composition of these functions matches concatenation of words. So the map

    w  ↦  (the function δ*(·, w))

is a **monoid morphism** from Σ\* into the (finite!) monoid of functions Q → Q under composition.
Call its image the **transition monoid** M(A), of size ≤ n^n.

Acceptance is now: `w ∈ L` iff the function of w maps q₀ into F. That is, membership is decided
by looking at the *image* of w under a morphism to a finite monoid, and asking whether it lands
in a designated subset P ⊆ M.

**Definition.** L is *recognized by a finite monoid* M if there is a morphism `h : Σ* → M` and
`P ⊆ M` with `L = h⁻¹(P)`.

**Theorem.** L is regular iff L is recognized by a finite monoid.
(⇒ is the transition monoid above. ⇐: build a DFA whose states are elements of M, δ(m,a) =
m·h(a), q₀ = 1, F = P.)

Exactly as in §9, there is a *minimal* such monoid, the **syntactic monoid** M(L) = Σ\*/≈_L where

    u ≈_L v   ⟺   ∀x,y ∈ Σ*.  (xuy ∈ L ⟺ xvy ∈ L)

Note the two-sided context, versus Myhill–Nerode's one-sided (suffix-only) context. ≈_L is a
*congruence* (both-sided), refines ≡_L, and every monoid recognizing L has M(L) as a quotient of
a submonoid. So: **Myhill–Nerode gives the minimal automaton; the syntactic congruence gives the
minimal algebra.** Both are computable from a DFA — M(L) is the transition monoid of the minimal
DFA.

Why bother? Because the algebraic invariants of M(L) turn out to characterize *subclasses* of the
regular languages in a decidable way, and this is knowledge you cannot see from the automaton.
That is the content of the next two sections, and it is the deepest classical mathematics in the
subject.

The general statement is **Eilenberg's variety theorem** (1976): there is a bijective
correspondence between *varieties of regular languages* (classes closed under Boolean operations,
quotients, and inverse morphisms) and *pseudovarieties of finite monoids* (classes closed under
submonoids, quotients, finite products). Deciding whether a given regular language belongs to a
variety becomes deciding whether its syntactic monoid satisfies a profinite equation. This turned
a family of ad-hoc questions into a single research program, still active — the study of
pseudovarieties, profinite topology, and Straubing–Thérien / dot-depth hierarchies. As of 2026,
the **decidability of the dot-depth hierarchy** at each level remains only partially resolved:
levels 1, 3/2, 2, 5/2 and a few more are known decidable through work of Place and Zeitoun in the
2010s–2020s, and the general question is open.

## 14. Logic: Büchi–Elgot–Trakhtenbrot

Third face. Forget machines and algebra. Describe a string as a **logical structure**: the
domain is the set of positions {1,…,|w|}, there is a linear order `<`, and unary predicates
`Pₐ(x)` meaning "position x carries the letter a".

Now write properties in **monadic second-order logic (MSO)**: first-order quantifiers over
positions, plus second-order quantifiers over *sets* of positions, plus <, Pₐ, Boolean
connectives.

Example: "the number of a's is even" is
`∃X. (∀x. (x ∈ X ⟺ (x is a-labelled and the number of a's before x is odd)))` — more cleanly,
guess the set X of positions where the running parity is 1, assert its consistency conditions
locally, and assert the last position's parity. That guessing-a-set-and-checking-locally shape
is the whole idea.

**Theorem (Büchi 1960, Elgot 1961, Trakhtenbrot 1962).** L ⊆ Σ\* is regular **iff** L is
definable in MSO over words.

*Proof idea.* (Automaton → MSO) Guess the run: existentially quantify sets X_q, one per state,
partitioning the positions ("position i is where the machine is in state q"), then write
first-order constraints saying the guess is a legal run and ends accepting. The second-order
quantifier is exactly "there exists a run" — nondeterminism is existential set quantification.
(MSO → automaton) Induction on formula structure: atomic formulas get small automata over an
extended alphabet that carries the valuation of free variables in extra tracks; ∨ is union, ¬ is
**complement** (this is where you must determinize), ∃X is projection (erase a track), which
introduces nondeterminism. □

Two things to take from this.

1. **Complementation is the load-bearing step**, and it costs an exponential each time. Since
   negations can nest, the translation from MSO to automata is *non-elementary*: a tower of
   exponentials of height proportional to the quantifier alternation depth. That is not slack in
   the proof — Stockmeyer proved a matching non-elementary lower bound. MSO on words is
   decidable and hopelessly infeasible in the worst case, which is a useful thing to know before
   promising anyone a tool.
2. **This is a decision procedure for an entire logical theory.** Since MSO over (ℕ, <) — "S1S",
   the monadic second-order theory of one successor — reduces to ω-automata (§19), Büchi's
   theorem gives decidability of S1S. Rabin extended it to two successors (S2S, §20), which is
   one of the most powerful decidability results known: a great many logics are decidable
   *because* they interpret into S2S.

So: **automata = algebra = logic**. Three definitions, one class. Pick whichever is convenient
for the question at hand — that fungibility is the practical payoff of the theory.

## 15. Star-free, aperiodic, first-order, temporal

Now the jewel. Ask a natural question: what if I remove Kleene star, but allow complement?

**Definition.** The *star-free* languages are the smallest class containing ∅, {ε}, and each {a},
closed under ∪, concatenation, and complement. (No star. Note `Σ* = ¬∅`, so you can still write
"anything", just not "arbitrarily many repetitions of a nontrivial pattern".)

Example: "contains `ab`" is star-free: `¬∅ · ab · ¬∅`. Example: "even number of a's" — is it?
Intuitively no; you cannot count modulo anything without a loop. How would one *prove* that?

**Theorem (Schützenberger 1965).** L is star-free **iff** its syntactic monoid is **aperiodic**
(i.e. contains no nontrivial group; equivalently ∃n ∀x. xⁿ = xⁿ⁺¹).

"Even number of a's" has syntactic monoid ℤ/2, a nontrivial group, so not star-free. Proof
complete, and the criterion is *decidable*: compute the syntactic monoid from the minimal DFA and
test the identity. This is the archetype of the algebraic method — a semantic question ("is there
a star-free expression?") reduced to a finite algebraic check.

**Theorem (McNaughton–Papert 1971).** Star-free = definable in **first-order** logic FO[<] over
words.

**Theorem (Kamp 1968).** FO[<] over linear orders = **linear temporal logic** (LTL) with Until.

Chain them:

> **star-free = aperiodic = FO[<] = LTL**

Four definitions from four fields — combinatorics on words, finite semigroup theory, model
theory, and modal logic — that pick out exactly the same set of languages. When that happens, the
object is real. And this one is *load-bearing in industry*: LTL is the specification language of
hardware and protocol verification, so "what can LTL express" is answered by Schützenberger's
theorem, and "what needs full ω-regularity" (like "p holds at every even step") tells you when
you must leave LTL for automata-based or μ-calculus specifications.

The hierarchy above star-free is also mapped: adding modular counting to FO gives FO+MOD =
solvable monoids; the quantifier-alternation hierarchy inside FO[<] corresponds to the
Straubing–Thérien hierarchy of monoid pseudovarieties, and — as noted in §13 — its decidability
is a live research question in 2026, with Place and Zeitoun's *separation* technique the main
weapon.

---

# Book V — Changing the rules

Everything so far kept one setting fixed: finite words, one-way reading, yes/no output, single
run. Relax each knob in turn. In each case ask the same three questions: *does the class change,
does the size change, does decidability survive?*

## 16. Two-way, alternating, and the succinctness lattice

**Two-way (2DFA).** Let the head move left as well as right. Surely this is stronger — you can
re-read. **It is not.** (Rabin–Scott 1959; Shepherdson 1959.) The proof is a lovely application
of §1's principle: summarize what the machine can do on a prefix by a *crossing function* — for
each state in which the head enters the prefix from the right, which state does it exit in (or
does it loop forever)? There are finitely many such functions, so a one-way machine can track
them. Class unchanged; **cost**: converting a 2DFA with n states to a DFA can need 2^Θ(n log n)
states, and the exact bound is known tightly.

**The Sakoda–Sipser problem (1978).** Can every n-state 2NFA be converted to a polynomial-size
one-way NFA? **Open since 1978, still open in 2026.** It is not a curiosity: the question is
tightly related to whether L = NL (nondeterministic logspace collapse), and partial results are
known for restricted machine classes (e.g. sweeping automata, unary alphabets — Geffert et al.).
This is the most conspicuous open problem in classical automata succinctness.

**Alternating automata (AFA).** Allow states to be labelled ∃ or ∀. Acceptance is defined by a
game: at ∃-states one successor must accept, at ∀-states all must. Equivalently, transitions
map to *positive Boolean formulas* over states. Class unchanged (still regular). Cost:
**doubly exponential** to DFA — AFA → NFA is 2ⁿ, NFA → DFA is another 2ⁿ. In return, complement
is trivial (dualize ∧/∨ and swap acceptance), which is exactly why alternating automata are the
standard intermediate representation when translating LTL to automata: you get a linear-size
alternating automaton from the formula, then pay for de-alternation once.

The succinctness picture, then, with each arrow labelled by worst-case blowup:

    AFA  --2^n-->  NFA  --2^n-->  DFA
    2DFA --2^(n log n)--> DFA
    regex --O(n)--> εNFA --O(n)--> NFA        NFA --2^Ω(n)--> regex

Same class throughout. Different economics by huge factors. **Expressiveness and succinctness are
orthogonal axes, and almost all engineering questions live on the second one.**

## 17. Transducers: machines that write

Change the output from a bit to a string. A **finite-state transducer** has transitions labelled
`a/u` (read a, emit u). Two important sub-cases:

- **Mealy machine**: output on transitions, one symbol per input symbol. **Moore machine**:
  output on states. They are interconvertible with O(n) states and are the standard model for
  synchronous digital circuits — every FSM you write in Verilog is one of these.
- **Rational transductions**: general nondeterministic transducers, computing relations rather
  than functions. Closed under composition (Elgot–Mezei), and images of regular languages are
  regular — a workhorse fact in NLP and compiler pipelines.

Determinism matters even more here. A **sequential** (deterministic) transducer produces output
online. Not every functional transducer is sequential (e.g. "if the input ends with a, replace
every b with c" requires unbounded lookahead), but Choffrut's theorem gives a decidable
characterization (the *twinning property*) of exactly which are, and there is a determinization
algorithm plus a canonical minimal form for subsequential transducers (Mohri 1997). Mohri's work
underpinned the weighted-FST toolchains (AT&T FSM, OpenFst) that powered speech recognition and
machine translation from the late 1990s until neural systems displaced them — and FSTs are
*still* the standard for morphological analysis, text normalization, grapheme-to-phoneme, and
the pronunciation lexicons inside modern speech stacks.

A modern strengthening worth knowing: **streaming string transducers** (Alur–Černý 2010) add a
finite set of string-valued registers updated by copyless assignments, and capture exactly the
MSO-definable transductions — the transducer analogue of Büchi's theorem, and the basis of
decidable verification for string-processing programs.

## 18. Weights, probabilities, quantum

Change the output from a bit to a *number*. Fix a semiring (K, ⊕, ⊗, 0, 1). A **weighted
automaton** assigns each transition a weight; the weight of a path is the ⊗-product; the value of
a word is the ⊕-sum over all accepting paths. Instantiate:

- Boolean semiring ({0,1}, ∨, ∧) → ordinary NFA.
- Tropical semiring (ℝ ∪ {∞}, min, +) → shortest path / Viterbi decoding. This is what an HMM
  decoder or a CTC beam search is doing structurally.
- (ℝ, +, ×) → counting/probabilistic automata. Probabilistic automata (Rabin 1963) with a
  strict cutoff can recognize non-regular languages, and — importantly — the **emptiness problem
  for probabilistic automata is undecidable** (Paz), as is the value-1 problem. Losing
  decidability the moment you leave the Boolean world is the recurring price.
- Formal power series view: the value function is a rational series; **Schützenberger's theorem**
  characterizes those recognized by weighted automata, and the **Hankel matrix** rank plays the
  role of Myhill–Nerode index. Over a *field*, equivalence of weighted automata is decidable in
  polynomial time by linear algebra (Schützenberger; Tzeng), and there is a minimal canonical
  form. Over the tropical semiring, equivalence is **undecidable** (Krob 1994). Same syntax,
  different arithmetic, completely different theory.
- **Spectral learning** of weighted automata (Hsu–Kakade–Zhang, Balle–Mohri) does Myhill–Nerode
  numerically: build an empirical Hankel matrix, take an SVD, read off a minimal WFA. This is the
  method-of-moments alternative to EM for HMMs, with actual consistency guarantees.

**Quantum finite automata.** Replace stochastic matrices with unitaries and add measurement.
Measure-once QFAs (Moore–Crutchfield) are strictly *weaker* than DFAs — they recognize only
group languages — which surprises people. Measure-many QFAs (Kondacs–Watrous) with bounded error
recognize a proper subclass of the regular languages too, but can be **exponentially smaller**:
the classic result is that for the language "length ≡ 0 mod p", a QFA uses O(log p) states where
any DFA needs p (Ambainis–Freivalds 1998). So the quantum advantage here is in *state
complexity*, not expressiveness. Worth knowing precisely, because the topic attracts loose
claims.

## 19. Infinite words: ω-automata

Now change the *input*. A reactive system — an OS kernel, a controller, a protocol — does not
terminate; its behaviour is an infinite word. Acceptance must be redefined, since there is no
last state. Let `inf(ρ)` be the set of states visited infinitely often in a run ρ.

- **Büchi** (1960): accept iff `inf(ρ) ∩ F ≠ ∅` — "something good happens infinitely often".
- **co-Büchi**: `inf(ρ) ∩ F = ∅` — "eventually always safe".
- **Rabin, Streett, Muller, parity**: richer conditions. **Parity**: each state has a priority;
  accept iff the least priority seen infinitely often is even. Parity is the sweet spot — closed
  under complement by shifting priorities, and parity *games* are the algorithmic engine of
  synthesis.

The one structural fact that shapes everything: **nondeterministic Büchi automata (NBW) are
strictly more expressive than deterministic ones (DBW).** Witness: "finitely many a's" — a DBW
cannot recognize it (an easy argument: pump a's past any putative accepting behaviour), an NBW
can (guess when the last a occurs). So the DFA↔NFA collapse of §4 **fails** for infinite words.
That single failure is why the ω-world is so much harder.

The repairs:

- **McNaughton's theorem (1966):** NBW = deterministic Muller = deterministic Rabin = deterministic
  parity. So determinization *is* possible, just not into Büchi.
- **Safra's construction (1988):** determinize an n-state NBW into a Rabin automaton with
  2^O(n log n) states, using trees of subsets ("Safra trees"). Piterman (2006) refined this to
  parity with better constants, and Schewe (2009) gave matching bounds. The n log n in the
  exponent is *optimal* (Michel; Löding) — this is genuinely harder than the subset construction,
  and the difficulty is intrinsic, not a proof artifact.
- **Complementation** of NBW: also 2^Θ(n log n). Historically the hardest basic operation in the
  field; Kupferman–Vardi's rank-based and Schewe's slice-based constructions are the modern
  approaches.

**Why anyone endures this: model checking and synthesis.** Vardi–Wolper's automata-theoretic
approach says: to check that system S satisfies LTL property φ, build an NBW for ¬φ (linear-ish
via alternating automata), take the product with S, and test **emptiness** — which for Büchi is
"is there a reachable accepting cycle", i.e. nested DFS or SCC computation, linear time. That is
SPIN, and its descendants; and the LTL→NBW step is what Spot, ltl3ba, and friends implement.
**Synthesis** (Pnueli–Rosner) is harder: you need a *deterministic* automaton to turn the problem
into a two-player game, which forces you through Safra — hence decades of work on "Safraless"
approaches (Kupferman–Vardi 2005; bounded-synthesis) and on cheaper canonical forms.

**History-deterministic (a.k.a. good-for-games) automata** are the modern resolution of that
tension: automata that are nondeterministic but whose choices can be resolved on-the-fly by a
strategy depending only on the prefix. They are good enough to compose with games (so synthesis
works) while being exponentially more succinct than deterministic ones. This is one of the most
active areas in 2026 — see §25.

## 20. Trees, and the strongest decidability results we have

Change the input again: from a word (a linear order) to a **tree**. A finite tree automaton
reads bottom-up (leaves to root, states propagate upward) or top-down. Bottom-up deterministic =
nondeterministic; **top-down deterministic is strictly weaker** (it cannot express "one child is
a and the other is b, in either order"). Regular tree languages have their own Myhill–Nerode,
minimization, and closure properties, and they are the theory behind XML schema validation
(DTD/XSD/RelaxNG are essentially tree-automaton formalisms), typed-term rewriting, and
higher-order model checking.

For **infinite trees**, Rabin's theorem (1969) is the summit of the classical theory:

> **Rabin:** MSO over the infinite binary tree (S2S) is decidable, via nondeterministic tree
> automata with Rabin acceptance, which are closed under complementation.

Complementation of tree automata is the hard part; the modern proof goes through **parity games**
and their positional determinacy (Emerson–Jutla, Mostowski), which is much cleaner than Rabin's
original argument. The payoff is enormous: decidability of S2S implies decidability of the modal
μ-calculus, CTL\*, and a long list of logics that interpret into it. Whenever you read "this logic
is decidable", there is a decent chance the proof ends in Rabin's theorem.

Two facts to keep the picture honest: the complexity is non-elementary, and Rabin's theorem does
not extend to arbitrary structures — the boundary of decidable MSO theories is charted by
Seese's conjecture and the theory of clique-width/twin-width, itself an active area in 2026.

Also worth flagging: **parity game solving** is one of the great algorithmic stories of the last
decade. The problem sits in NP ∩ coNP (and UP ∩ coUP), and in 2017 Calude, Jain, Khoussainov, Li
and Stephan gave the first **quasi-polynomial** algorithm, n^O(log n), triggering a wave of
alternative quasi-polynomial approaches (Jurdziński–Lazić's succinct progress measures,
Zielonka-style recursive variants, and the *universal trees* framework that unifies them and
provides matching lower bounds for that whole family). Whether parity games are in P is **open in
2026**, and the universal-tree lower bounds tell us any P algorithm must avoid the entire known
family of techniques.

## 21. Infinite alphabets: register, symbolic, nominal

The last knob: Σ finite was assumption number one in §0. Drop it.

- **Symbolic automata** (Veanes, D'Antoni, et al.). Transitions are labelled with *predicates*
  from a decidable Boolean algebra over the alphabet, not individual symbols. Determinization,
  minimization, product, and emptiness all lift, with the alphabet operations delegated to an SMT
  solver. This is how you handle Unicode (a 21-bit alphabet where a full table is absurd) or
  alphabets like "all 64-bit integers". It is not a theoretical curiosity — it is the architecture
  of the .NET non-backtracking regex engine and of many string-constraint solvers.
- **Register automata / data words** (Kaminski–Francez 1994). A finite control plus a fixed number
  of registers holding data values, comparable only by equality. Models "the same session ID
  appears again". Emptiness is decidable (NP-complete for the basic model) but the class loses
  closure under complement and determinization, and the theory is much more delicate.
- **Nominal automata** (Bojańczyk, Klin, Lasota). The same phenomena, done properly with sets
  that carry a group action of the symmetry of the data domain; you recover a Myhill–Nerode
  theorem and minimization *in the category of nominal sets*. A satisfying case of "the right
  abstraction makes the anomalies disappear".
- **Timed automata** (Alur–Dill 1994). Real-valued clocks with resets and comparisons to
  constants. Reachability is decidable via the **region construction** — quotient the uncountable
  clock space by a finite equivalence — and is PSPACE-complete. This underlies UPPAAL and the
  entire field of real-time verification. Timed automata are *not* determinizable and *not*
  complementable in general, so the toolchains are built around reachability rather than around
  language operations.

The lesson repeats: each generalization keeps *some* of the finite-state package and loses the
rest, and knowing exactly which piece you lost is the difference between a usable tool and a
research project.

---

# Book VI — Learning and inference

## 22. Learning an automaton from examples

Flip the problem. Instead of "given L, build a machine", ask "given *data* about L, find the
machine". This is where automata theory meets machine learning, and it is where a lot of 2026
activity is.

**Passive learning: from a finite labelled sample.**
Given sets S⁺ and S⁻, find a smallest DFA consistent with them.

- **Gold (1978):** this is **NP-hard**.
- **Pitt–Warmuth (1993):** it is NP-hard even to *approximate* the minimum size within any
  polynomial factor. So there is no efficient algorithm, and none is coming.
- Practical algorithms therefore give up optimality: **RPNI** (Oncina–García 1992) builds the
  prefix-tree acceptor and greedily merges states in a fixed order whenever merging does not
  create an inconsistency; **EDSM** (Lang, Pearlmutter, Price — the Abbadingo competition, 1998)
  scores merges by evidence and does the highest-scoring first. Both are still competitive
  baselines. The modern alternative is to encode "is there a consistent DFA with k states" as a
  **SAT/SMT/ILP instance** and hand it to a solver (Heule–Verwer 2010 is the standard reference);
  solvers are good enough that this is often the best exact method.
- **Gold's identification in the limit (1967):** with only positive examples, no superfinite class
  is learnable — you can never rule out overgeneralization. This is a genuinely deep negative
  result, and it is the reason every practical system either uses negative examples, uses queries
  (next section), or imposes a strong prior.

## 23. Angluin's L\*, and what replaced it

**Active learning** changes the setting: the learner may ask an oracle (a "teacher"), which is
exactly right when the target is a black-box *system* you can run — a protocol implementation, a
legacy binary, an API, a neural network.

Two query types (Angluin 1987, the **MAT** model — Minimally Adequate Teacher):

- **Membership query:** is w ∈ L? (Run the system on w.)
- **Equivalence query:** is my hypothesis H equal to L? If not, return a counterexample.
  (In practice: replaced by *conformance testing* — W-method, Wp-method, or random walks —
  which makes the whole thing a heuristic with a coverage guarantee rather than a proof.)

**L\* in one paragraph, derived from §9.** Maintain an *observation table*: rows indexed by a
prefix-closed set S ∪ S·Σ, columns by a suffix-closed set E of "experiments", cells filled by
membership queries `row(u)[e] = [ue ∈ L]`. A row is an approximation of the future `u⁻¹L`,
restricted to the experiments tried so far. Enforce two conditions: *closed* (every row of S·Σ
equals some row of S) and *consistent* (equal rows in S stay equal after appending any letter —
this is the right-congruence property of §9). When both hold, the table defines a DFA: states are
distinct rows, transitions follow row(ua). Ask an equivalence query; a counterexample gives a new
distinguishing experiment (add suffixes of it to E), which splits a state. Since every split
increases the number of distinct rows, and that is bounded by index(L) = n, the loop terminates
after at most n splits.

Complexity: O(|Σ|n² + n log m) membership queries, where m is the longest counterexample, and at
most n equivalence queries. **The termination argument is literally Myhill–Nerode**: L\* is a
procedure for discovering the finitely many classes of ≡_L, one experiment at a time.

Since 1987:

- **Rivest–Schapire (1993):** binary search on the counterexample to extract *one* good suffix —
  removes the O(m) factor.
- **Kearns–Vazirani:** replace the table with a *discrimination tree*, avoiding the redundancy of
  filling a full matrix.
- **TTT (Isberner, Howar, Steffen 2014):** three redundancy-free tree structures; the current
  practical champion, and what **LearnLib** implements.
- **Beyond DFAs:** L\*-style algorithms now exist for Mealy machines (the workhorse for protocol
  inference), register automata (SL\*), symbolic automata, nominal automata, weighted automata
  (via Hankel matrices), NFAs (NL\* — using residual automata, which have a canonical form
  unlike general NFAs), and ω-automata.

**What this is actually used for.** Model learning has found real bugs in real systems by
inferring a state machine and then model-checking it: TCP implementations (Fiterău-Broştean et
al. found divergences from the RFC in Linux/Windows/FreeBSD stacks), TLS implementations
(de Ruiter–Poll's state-machine fuzzing found several protocol-state bugs, including in OpenSSL),
SSH, MQTT, bank card protocols (EMV), and legacy industrial controllers. The pitch is precise:
*you cannot review a state machine that nobody wrote down; learn it, then look at it.*

---

# Book VII — The machine in the world

## 24. Where finite automata actually run in 2026

A DFA is not a museum piece. Concretely, today:

**1. Lexical analysis.** Every compiler front end. `lex`/`flex`/`re2c` compile token regexes into a
DFA table. The "maximal munch" rule needs one extra trick — remember the last accepting position
and back up — but the core is §2 verbatim.

**2. Regex engines, split into two lineages.**
- *Backtracking* (PCRE, Perl, Python `re`, JS, Java): implements a search over the NFA's paths,
  supports backreferences and lookaround (which push it beyond regular — `(a*)\1` is not regular,
  and matching with backreferences is NP-hard), and is vulnerable to ReDoS.
- *Automata-based* (RE2, Go, Rust `regex`, .NET's non-backtracking mode): Thompson simulation +
  lazy DFA + Aho–Corasick/memchr prefilters + SIMD literal scanning, giving linear-time worst
  case. Rust's `regex` in particular is a good object lesson: a hybrid engine that picks among a
  one-pass DFA, a lazy DFA, a bounded-backtracker, and a "pike VM" depending on the pattern and
  input size. .NET 7+ ships a derivative-based symbolic engine (§8, §21).

**3. Network and storage at line rate.** Deep packet inspection (Snort/Suricata rulesets),
intrusion detection, and log scanning are DFA/NFA problems at 100 Gbps+. Hyperscan (Intel,
open-sourced 2015, and its ARM port Vectorscan) decomposes regexes into literal factors matched
with SIMD plus small NFA/DFA engines with bit-parallel (Glushkov) simulation. On GPUs, NFA
processing continues to be pushed — e.g. *ANG: Accelerating NFA processing on GPUs via exploring
multi-level fine-grained parallelism* (PACT 2025) — and FPGA-based DPI pipelines remain an active
engineering line. Micron's Automata Processor (a DRAM-array NFA engine) is the famous dedicated
silicon attempt; it did not survive commercially, but its benchmark suite (ANMLZoo) still shapes
the field.

**4. Protocol and controller implementation.** Every TCP stack, every USB device, every traffic
light, every `enum State` + `switch` in embedded C, every Verilog FSM. Statecharts (Harel) and
tools like SCXML, Xstate, and the state machines inside UI frameworks are all finite automata
with syntactic sugar for hierarchy and orthogonality (the latter being the product construction
of §6 with a nicer notation).

**5. Text and speech.** Finite-state transducers for morphology (Xerox/Foma, HFST), text
normalization, and pronunciation lexicons; OpenFst under the hood of many pipelines. Even in a
2026 neural stack, the "inverse text normalization" step that turns *"twenty twenty six"* into
*"2026"* is very often an FST, because it must be auditable and correctable by a human.

**6. Constrained decoding of language models — the big new one.** When you ask an LLM for JSON
that conforms to a schema, or for a call to a specific tool, the production technique is to
compile the grammar into an automaton and, at every decoding step, **mask the logits** of tokens
that cannot extend a valid prefix. For regular constraints this is exactly a DFA; for JSON/CFG
constraints it is a pushdown automaton with a DFA over the tokenizer vocabulary at each state.
The key engineering insight (Willard & Louf's *Outlines*, 2023) is to precompute, per DFA state,
the set of vocabulary tokens that are legal — turning per-step constraint checking into an O(1)
table lookup rather than a per-token grammar walk. XGrammar (2024–25) and similar systems push
this further with context-independent/dependent token splitting, persistent stacks, and overlap
with GPU execution, reaching effectively zero-overhead structured generation; equivalents now
ship in vLLM, TensorRT-LLM, llama.cpp (GBNF grammars), and the major inference APIs.
So: **every structured-output LLM call in production in 2026 is running a finite automaton over
the token vocabulary, in lockstep with the sampler.** Kleene's 1956 class, in the hottest part of
the stack.

**7. Verification.** As in §19: SPIN, NuSMV/nuXmv, TLA+'s TLC, Spot for ω-automata manipulation,
UPPAAL for timed systems. Automata are the intermediate language of model checking.

**8. Bioinformatics, tokenizers, data validation, indexing.** Profile HMMs (weighted automata) for
sequence homology; Aho–Corasick for multi-pattern search everywhere from antivirus to grep;
Levenshtein automata for fuzzy dictionary lookup (Lucene builds one per query term); finite-state
transducers as the on-disk term index in Lucene/Tantivy.

## 25. The 2026 frontier

Where the research edge actually is, right now. I have grouped by theme and cited concrete recent
work; publication venues are given where I am confident of them.

**(a) Automata and neural sequence models — the most active interface.**
The question "what finite-state computation can a transformer do" now has sharp answers, and they
are all automata-theoretic.
- Constant-depth transformers with hard/saturated attention sit inside **TC⁰**, so under standard
  complexity assumptions they cannot recognize even simple regular languages like PARITY, nor do
  general **NC¹**-hard state tracking (word problems of non-solvable groups such as S₅ —
  "composition of 5-element permutations"). This is the Hahn / Merrill–Sabharwal line of work,
  and it is a *lower bound on architectures*, not on training.
- Liu et al.'s "Transformers learn shortcuts to automata" showed the positive side: a transformer
  of depth O(log T) can simulate T steps of any finite automaton, via a parallel-prefix
  (associative scan) over transition functions — the Myhill–Nerode/transition-monoid composition
  of §13, implemented in attention. Solvable groups get depth-O(1) shortcuts; non-solvable ones
  do not.
- **Chain-of-thought is the escape hatch**, and it has been made mechanistic: *Finite State
  Automata Inside Transformers with Chain-of-Thought* (arXiv 2502.20129, 2025) locates an
  implicit FSA implemented largely in late-layer MLP neurons, and shows CoT-trained models learn
  robust state-tracking algorithms rather than shortcuts. Work through 2026 continues to sharpen
  what low-precision softmax transformers with (summarized) chain-of-thought can express.
- The same lens applies to **state-space models**: Mamba-style linear-recurrent models were shown
  (Merrill, Petty, Sabharwal, "The Illusion of State in State-Space Models") to also live in TC⁰
  and to be unable to do genuine unbounded state tracking, despite the recurrent framing. The
  2024–2026 response has been architectures deliberately designed to recover non-solvable state
  tracking (input-dependent negative eigenvalues in linear RNNs, DeltaNet-style products of
  Householder matrices, and related "expressive recurrence" work). *Automata theory is now a
  design constraint for sequence architectures* — this is the single biggest change in the
  subject's relevance in a decade.
- Conversely, automata are being extracted *from* models: DFA/WFA extraction as interpretability
  (Weiss–Goldberg–Yahav's L\*-based RNN extraction being the seed), and 2026 work on **learning
  automata that characterize the support of a language model** (ICLR 2026), i.e. inferring the
  regular over-approximation of what a model can output — directly useful for safety and for
  constrained decoding.

**(b) History-determinism / good-for-games automata.** The liveliest classical topic. Highlights:
the **2-token theorem** (Lehtinen & Prakash, STOC 2025) gives an efficient characterization for
recognizing history-deterministic parity automata; *Checking History Determinism for Parity
Automata Is in NP* (LICS 2026) lowers the complexity further; **minimal history-deterministic
co-Büchi automata** admit congruence-based canonical forms and *passive learning* algorithms
(Löding & Walukiewicz, LICS 2025); and succinctness results (HD Büchi automata are succinct,
2026) quantify what you gain over determinism. The practical stake: synthesis pipelines that
avoid Safra entirely.

**(c) New canonical forms for ω-regular languages.** **COCOA** — chains of co-Büchi automata —
is a recent canonical representation in which each ω-word gets its "natural color", the component
automata are minimizable in **polynomial time** (unlike minimal deterministic parity automata,
which are NP-hard to compute), and everything is good-for-games. A LICS 2026 paper gives a
*naturally-colored* translation from LTL directly to parity and COCOA, bypassing the
Safra-style detour. If this line succeeds, it changes the standard LTL→automaton toolchain.

**(d) Symbolic automata, modulo theories.** *Symbolic Automata: ω-Regularity Modulo Theories*
(POPL 2025) lifts alternating and nondeterministic Büchi automata to work over arbitrary
decidable alphabet theories, with alternation elimination and a symbolic RLTL, unifying classical
automata and SMT-based model checking. Adjacent: certified symbolic finite transducers formalized
in a proof assistant (2025), and continued work on symbolic derivatives.

**(e) Regex engineering.** Still moving: **register set automata** for backreferences (PLDI 2026)
give a non-backtracking route to a feature everyone assumed required backtracking; **sparse
counting-sets** (2026) attack the counting/bounded-repetition blowup `a{1,1000}` that has caused
both ReDoS incidents and memory explosions; and lookaround handling in derivative-based engines
continues to mature. The general direction: recover PCRE's *features* without PCRE's *complexity
class*.

**(f) Automata learning.** Active learning has moved past L\*: **SMT-based active learning of
weighted automata** over arbitrary semirings (2026) as an alternative to Hankel/L\*, guaranteed
minimal on termination; **unsupervised automata learning** via discrete optimization (2026),
showing DFA learning from *unlabeled* data is hard and giving constraint-optimization algorithms
with regularizers that keep the result interpretable; **DFA inference via Q-learning**
(arXiv 2510.17386); and database-assisted and tree-automata learning variants. Meanwhile,
LearnLib/AutomataLib remain the practical infrastructure, and model learning of protocol
implementations continues to find real CVE-worthy bugs.

**(g) Quantitative and hybrid.** Weighted/quantitative automata for resource analysis and for
specifying "how well" rather than "whether"; token games and history-determinism for quantitative
automata (Boker–Lehtinen); automata over infinite alphabets for data-aware process mining. And
the parity-game/universal-tree program continues, with quasi-polynomial being the current
frontier and P still out of reach.

**(h) Formalization.** Increasing amounts of this theory now exist machine-checked — regular
language theory, Myhill–Nerode, Kleene's theorem, and symbolic transducers in Coq/Rocq, Isabelle
(the CAVA verified model checker), and Lean's Mathlib. For a subject whose constructions are
fiddly and whose papers historically contained real errors (Safra-style determinization proofs
being the notorious case), this matters more than it sounds.

## 26. What is still open

Short list, all genuinely unresolved as of July 2026:

1. **Sakoda–Sipser (1978):** is 2NFA → NFA polynomial? Tied to L vs NL.
2. **Černý conjecture (1964):** every n-state synchronizing DFA has a reset word of length
   ≤ (n−1)². The classic cubic bound (n³−n)/6 stood from the 1980s; Szykuła broke it in 2018 to
   ≈ 0.1654 n³, with subsequent small improvements. The quadratic conjecture remains open, and it
   is embarrassing that we cannot close a gap between n² and 0.16n³ for such an elementary
   statement.
3. **Generalized star height:** is every regular language of generalized star height ≤ 1? Open
   since Eggan (1963) — we do not even know a single language proven to have generalized star
   height 2. (Ordinary star height *is* decidable, by Hashiguchi 1988 / Kirsten 2005.)
4. **Dot-depth / quantifier-alternation hierarchy:** decidability of membership at every level.
   Place–Zeitoun's separation machinery has cracked the low levels; the general case is open.
5. **Parity games in P?** Quasi-polynomial since 2017, and the universal-tree lower bounds say
   the known family of algorithms cannot do better.
6. **Minimization lower bound:** is O(n log n) optimal for DFA minimization? No matching lower
   bound is known in a general model.
7. **Tight state complexity for many combined operations** — a cottage industry with real gaps.
8. On the applied side: **what neural architectures can do genuinely unbounded state tracking at
   constant depth, without chain-of-thought?** Currently we have impossibility results and
   architectural workarounds, but no clean positive theory. This is an automata question wearing
   a machine-learning coat, and it is where I would expect the next surprise.

## 27. Reading path

If you want to go deeper, in this order:

- **Sipser, *Introduction to the Theory of Computation*** — the cleanest first exposure; Chapter 1
  is Books I–III above.
- **Hopcroft, Motwani, Ullman** — more encyclopedic, good on minimization and closure.
- **Kozen, *Automata and Computability*** — lecture-per-chapter, excellent on Myhill–Nerode.
- **Pin, *Mathematical Foundations of Automata Theory*** (free online, continuously updated) —
  the algebraic view of Book IV, done properly. Then Straubing for varieties and circuit
  complexity connections.
- **Grädel, Thomas, Wilke (eds.), *Automata, Logics, and Infinite Games*** — the standard entry to
  Book V's ω-world.
- **Baier & Katoen, *Principles of Model Checking*** — for the verification application.
- **Vaandrager, "Model Learning" (CACM 2017)** and the **LearnLib** codebase — for Book VI.
- For the 2026 frontier, follow **POPL / LICS / CAV / STOC / ICALP / TACAS** and, for the neural
  interface, **the formal-languages-and-neural-networks track at ICLR / NeurIPS / ACL**.

---

## Coda

The through-line, stated once more: I assumed only that distinctions are finite and that input
arrives in order. That forced the notion of a *future*, `u⁻¹L`. Finiteness of the set of futures
turned out to be simultaneously

- the definition of what a bounded-memory device can decide,
- the exact state count of the optimal device,
- the termination argument for learning one from experiments,
- the reason the class is closed under everything and decidable for everything,
- and, in its algebraic and logical disguises, the reason the same class keeps reappearing in
  fields that were not looking for it.

Everything after §1 is consequence and engineering. That is what it means for a definition to be
right.
