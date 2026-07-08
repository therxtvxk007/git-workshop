# Part 3 — Operators and Precedence: The Algebra of the Language

*The monologue continues. I've been using `+` and `==` on faith, and `==` has
already betrayed me once (Part 2). Time to treat operators as what they are —
compact functions with rules — and derive the rules from the machine
underneath.*

---

## 0. The reframe that organizes everything

In Scratch, `(_ + _)` was a green oval — a block that takes two inputs and
reports one output. That framing is *exactly right* and I'm keeping it: **an
operator is a function in costume.** `a + b` is `plus(a, b)`. Every operator
has input types, an output type, and — because this is Java — the compiler
checks all of it. Two questions for every operator I meet: *what does it
compute?* and *what type comes out?* The second question is where the bugs
hide.

## 1. Arithmetic operators: `+  -  *  /  %`

Four of these are primary school. The interesting ones are division and
remainder, because types change their meaning.

**Integer division truncates.** `7 / 2` is `3`, not 3.5 — because both
operands are `int`, so the operator is *integer* division, and the result type
is `int`. There is nowhere for the .5 to live. It truncates toward zero
(`-7 / 2` is `-3`, not −4). If I want 3.5, one operand must be floating-point
*before* the divide: `7 / 2.0`, or `(double) a / b`. The classic bug is
averaging: `(a + b) / 2` on ints silently floors. This isn't an operator being
weird; it's the type system being consistent — `int op int → int`, always.

**`%` — remainder.** `13 % 5` is `3`. My workhorse for cyclic things: is `n`
even (`n % 2 == 0`), wrap an index around an array (`(i + 1) % length`),
extract digits (`n % 10`). One subtlety worth pinning down: in Java the result
takes the **sign of the dividend** — `-7 % 3` is `-1`, not 2. So "is odd"
written as `n % 2 == 1` fails for negative n; write `n % 2 != 0`.

**Division by zero — two different worlds.** Integer `10 / 0` throws
`ArithmeticException`: there is no int that can represent the answer, so the
machine refuses. But floating-point `10.0 / 0.0` is `Infinity`, and `0.0 / 0.0`
is `NaN` (Not a Number) — because IEEE 754 (Part 2) reserved bit patterns for
exactly these cases, letting long numeric pipelines keep flowing instead of
crashing. And NaN carries the strangest rule in the language: **`NaN != NaN`**.
NaN means "no meaningful value," and two meaningless results aren't equal to
each other. Test with `Double.isNaN(x)`, never `x == Double.NaN` (always
false — a perfect little trap).

**Increment/decrement, `++` and `--`.** `i++` is sugar for `i = i + 1`. The
prefix/postfix distinction only matters when I *use the value of the
expression itself*: `int a = ++i` increments then reads; `int a = i++` reads
then increments. My policy after two minutes of imagining debugging this:
`i++` alone on its own line, always; never embedded in a larger expression.
Cleverness here has negative value.

**And `+` is overloaded.** With a String on either side, `+` means
concatenation, and it converts the other operand to text. Useful, but it makes
`"Total: " + 1 + 2` print `Total: 12` — that's a precedence-and-associativity
story I'll nail in section 7.

## 2. Relational operators: `<  >  <=  >=  ==  !=`

Each takes two values and reports a `boolean` — these are the question-blocks
(the pointy hexagons from Scratch). Three landmines, all already foreshadowed:

1. **`==` on objects compares references** — "same object?", not "same
   content?" (the String pool and Integer cache betrayals from Part 2). For
   objects: `.equals()`. For primitives, `==` is honest and fine.
2. **`==` on doubles is a lie** because of accumulated rounding (Part 2):
   `0.1 + 0.2 == 0.3` is false. Compare with a tolerance.
3. **No chaining.** `0 <= x <= 10` doesn't compile — and I can see *why* by
   typing it out: `0 <= x` evaluates to a `boolean`, and then
   `boolean <= 10` is a type error. The compiler's strictness converts a
   subtle math-notation habit into a loud compile error. Write
   `0 <= x && x <= 10`.

## 3. Boolean logical operators: `&&  ||  !` — and why "short-circuit" matters

`&&` is AND, `||` is OR, `!` is NOT. The design decision worth understanding
is **short-circuit evaluation**: `&&` and `||` evaluate left-to-right and
*stop as soon as the answer is known*. `false && anything` is false without
evaluating `anything`; `true || anything` is true likewise.

At first this sounds like a micro-optimization. It isn't — it's a control-flow
tool, and idiomatic Java leans on it constantly:

```java
if (s != null && s.length() > 0) { ... }
```

If `s` is null, the right side **never runs** — which is the only thing saving
it from a `NullPointerException`. The guard works *because* of
short-circuiting; the order of the two conditions is load-bearing. Flip them
and the code crashes on exactly the case it was checking for. So in compound
conditions: cheap-and-guarding clauses first.

The corollary: never put side effects (like `i++` or a method that changes
state) on the right of `&&`/`||` — it will run *sometimes*, which is the worst
of all possible behaviors to debug.

(There also exist non-short-circuit `&` and `|` on booleans — both sides
always evaluate. Almost never what I want; if I see one in boolean context
it's either very deliberate or a typo. Their real job is the next section.)

## 4. Bitwise operators: `&  |  ^  ~  <<  >>  >>>`

Part 2 taught me an `int` is 32 bits. These operators work on those bits
directly — the same AND/OR/XOR/NOT, applied 32 times in parallel, one lane
per bit column:

```java
int a = 0b1100;          // 12
int b = 0b1010;          // 10
a & b;   // 0b1000 = 8    — 1 where BOTH are 1
a | b;   // 0b1110 = 14   — 1 where EITHER is 1
a ^ b;   // 0b0110 = 6    — 1 where they DIFFER (XOR)
~a;      // flips all 32 bits: ~12 == -13  (two's complement: ~x == -x-1)
```

Why would I ever want this? The killer use case is **flags**: one `int` can
store 32 independent yes/no switches, one per bit. Set a flag with `|`, test
with `&`, toggle with `^`, clear with `& ~mask`:

```java
static final int BOLD = 1, ITALIC = 2, UNDERLINE = 4;   // powers of two: one bit each
int style = BOLD | UNDERLINE;          // 0b101
boolean isBold = (style & BOLD) != 0;  // test one bit  (parens matter! §7)
```

File permissions (`rwx` = 421), network protocol headers, chess engines —
this is how compact systems represent sets.

**Shifts.** `x << n` slides bits left, filling with zeros — and since each
column is worth twice its neighbor, `x << n` is `x * 2ⁿ` for cheap. Right
shift comes in **two** flavors, and the reason is two's complement: the top
bit is the sign. `>>` (arithmetic shift) copies the sign bit in from the left,
preserving negativity: `-8 >> 1` is `-4` — division by two that works for
negatives. `>>>` (logical shift) shoves in zeros regardless: `-8 >>> 1` is a
huge positive number — right for raw bit patterns, wrong for arithmetic. Two
operators because there are two legitimate intentions. (No `<<<` exists —
shifting left, both intentions coincide, zeros are the only sensible fill.)

## 5. Assignment operators: `=` and its compound family

`=` is not equality; it's a *command*: evaluate the right side, store into the
left. And here's the subtle part — in Java, assignment is an **expression
that yields the assigned value**, not just a statement. That's what makes
`a = b = c = 0` legal (it evaluates right-to-left: `c = 0` yields 0, feeds
`b = 0`, …). It's also what makes `if (x = 5)` a classic C bug — Java mostly
saves me because `x = 5` yields an `int` and `if` demands a `boolean`… but
with booleans the trap survives: `if (flag = true)` compiles and always runs.
`==` asks; `=` overwrites. Respect the difference.

**Compound assignment**: `x += 5` for `x = x + 5`, likewise `-= *= /= %= &=
|= ^= <<= >>=`. Mostly convenience — with one hidden behavior worth knowing
because it's *inconsistent* with the longhand form:

```java
byte b = 10;
b = b + 1;    // COMPILE ERROR: b+1 is an int (arithmetic promotes to int),
              // and int → byte needs a cast (Part 2)
b += 1;       // compiles fine!
```

Why? The spec defines `b += 1` as `b = (byte)(b + 1)` — compound assignment
**smuggles in an implicit cast**. Convenient, and slightly dangerous: `b += 
300` compiles and silently truncates. The longhand form would have forced me
to acknowledge the risk. Noted: compound assignment is terser *and* less
honest.

## 6. The conditional (ternary) operator: `? :`

```java
int max = (a > b) ? a : b;
```

Read: "is a > b? then a, else b." Three operands — hence *ternary*, the only
one in the language. The insight that makes it click: `if` is a **statement**
(it *does*, returns nothing), while `?:` is an **expression** (it *is* a
value). I can't write `int x = if (...) ...` — but I can with `?:`, embed it
in arguments, in returns, in string concatenations.

It also short-circuits like `&&`: only the chosen branch evaluates. And its
result type is unified from both branches by the promotion rules, which hides
one exotic trap: `condition ? 1 : 2.0` has type `double` — the 1 becomes 1.0.
Mixed wrapper/primitive branches can even trigger surprise unboxing (and an
NPE if a null wrapper gets unboxed). Policy: keep both branches the same,
simple type; use it for choosing *values*, never for executing side effects;
never nest ternaries. `if` for doing, `?:` for choosing.

## 7. Operator precedence: grammar, not trivia

Now the question underneath all of the above: `2 + 3 * 4` — who goes first?
An expression is linear text, but its *meaning* is a tree (I saw this in the
parser, Part 1). Precedence is nothing but the tie-breaking rules the parser
uses to build one tree instead of another. Scratch never had this problem —
nesting ovals inside ovals *was* the tree, drawn explicitly. Java trades that
visual honesty for compact text and hands me a disambiguation rulebook.

I refuse to memorize a fifteen-row table, but I can *reconstruct* it, because
it mostly follows two principles: **math conventions hold** (unary before `*`
`/` before `+` `-`), and **compute values first, then compare them, then
combine the comparisons, then store the result**. That storyline gives:

```
HIGH  postfix           x++  x--
      unary             ++x  --x  +x  -x  ~  !   (and casts)
      multiplicative    *  /  %
      additive          +  -
      shift             <<  >>  >>>
      relational        <  >  <=  >=  instanceof
      equality          ==  !=
      bitwise AND       &
      bitwise XOR       ^
      bitwise OR        |
      logical AND       &&
      logical OR        ||
      ternary           ? :
LOW   assignment        =  +=  -=  ...
```

Arithmetic outranks relational (so `a + 1 < b * 2` parses as
`(a+1) < (b*2)` — what anyone would mean), relational outranks the boolean
combiners (so `a < b && c < d` needs no parens), `&&` outranks `||` (AND is
multiplication-like, OR is addition-like — the analogy runs deep, via 0/1
logic), and assignment sits at the very bottom because it consumes a fully
computed value. Almost everything is left-associative; assignment (and the
ternary) are right-associative — that's what `a = b = 0` relies on.

But derivation also exposes the **two places the table is genuinely
treacherous**, where I'll either parenthesize or get burned:

**Trap 1 — bitwise `&`/`|` rank *below* `==`.** Historical wart inherited
from C:

```java
if (flags & MASK == 0)      // parses as  flags & (MASK == 0)  → type error, if lucky
if ((flags & MASK) == 0)    // what I meant. Parens mandatory around bit-tests.
```

That's why section 4's example carried parentheses. Not style — survival.

**Trap 2 — `+` is left-associative and overloaded** (section 1):

```java
System.out.println("Total: " + 1 + 2);   // ("Total: " + 1) + 2 → "Total: 12"
System.out.println("Total: " + (1 + 2)); // "Total: 3"
System.out.println(1 + 2 + " done");     // (1+2) + " done" → "3 done" — ints met first
```

Same operator, same precedence, different results — purely from *what type
had been accumulated so far* when each `+` fired. Once I see it as
left-to-right tree building over changing types, it's not spooky, it's
mechanical.

My working policy, settled: internalize the storyline (values → comparisons →
boolean logic → assignment), trust math conventions, and **parenthesize
anything involving bitwise ops, ternaries, or mixed string arithmetic** — not
because I can't compute the parse, but because the next reader shouldn't have
to. Code is read far more often than it's written; parentheses are free
documentation of intent.

---

**Where I stand:** I can compute anything — but only in a straight line. No
decisions, no repetition. Every program I've written so far executes top to
bottom, once. The next problem is *flow*: how a program branches, loops, and
escapes — and what that looks like on a machine whose only real trick
(I peeked at the bytecode) is the conditional jump.
→ [Part 4](04-control-flow-functions-args.md)
