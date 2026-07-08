# Part 4 — Control Flow, Functions, and Talking to the Outside: Selection, Iteration, Jumps, Methods, Command-Line Arguments, Varargs

*The monologue continues. I can compute, but only in a straight line. Time to
make programs that decide, repeat, and organize themselves.*

---

## 0. The secret underneath all control flow

Before learning the statements, I want to know what they compile *down to*,
because that will make every rule self-explanatory. I disassemble an `if` with
`javap -c` (my flashlight from Part 1) and find… no `if`. The bytecode has
essentially two tricks: **`goto`** (jump to instruction N) and **conditional
jumps** (`if_icmpge` — "if the top two stack ints compare ≥, jump to N").

That's the whole secret. The CPU only knows "jump." `if`, `while`, `for`,
`switch`, `break` — every one of them is a *disciplined pattern of jumps* that
the compiler weaves for me. Raw `goto` was expressive enough to build anything
and unstructured enough to build unmaintainable spaghetti (this is literally
what Dijkstra's famous "Go To Considered Harmful" letter was about). Java's
control statements are jumps wearing safety equipment. Everything below is
"which jump pattern, and what discipline does it enforce."

## 1. Selection statements: `if`, `if-else`, `switch`

### if / else — the fork

```java
if (score >= 90) {
    grade = 'A';
} else if (score >= 80) {      // just an if nested in the else — chained forks
    grade = 'B';
} else {
    grade = 'C';
}
```

The condition must be a genuine `boolean` (Part 3 explained how this kills
the `if (x = 5)` bug at compile time). Compiles to: evaluate condition,
conditional-jump over the block if false. Notes from thinking ahead about my
own failure modes:

- **Order matters in a chain** — conditions are tested top-down and the first
  hit wins, so `score >= 80` must come *after* `score >= 90`, or every A
  student gets a B. Chains encode priority; I should order from most to least
  specific.
- **Always braces**, even for one-liners. The language allows `if (x) doIt();`
  without braces, but then the *indentation* and the *structure* can disagree
  — the "dangling else" (an `else` binds to the *nearest* unbraced `if`, not
  the one my indentation suggests) and Apple's infamous `goto fail` bug both
  live in that gap. Braces make the tree visible. Cheap insurance.

### switch — the multi-way jump table

A 12-way `if-else if` chain on one value is doable but tests conditions one by
one — and reads as noise. `switch` says what I actually mean, "jump directly
to the case matching this value":

```java
switch (dayNumber) {
    case 1:  dayName = "Monday";  break;
    case 2:  dayName = "Tuesday"; break;
    // ...
    default: dayName = "Unknown";
}
```

For dense int cases the compiler can emit an actual **jump table** — compute
index, one jump, O(1) instead of a cascade of comparisons. That's the origin
story, and it explains switch's two idiosyncrasies:

- Cases must be **compile-time constants** (the table is built at compile
  time). Since Java 7, `String` works too — compiled via `hashCode` then an
  `equals` check, a lovely example of sugar over mechanics.
- **Fall-through**: cases are labels *in* a jump table, not rooms with walls.
  Execution entering `case 1` keeps flowing into `case 2` unless a `break`
  jumps out. Forgetting `break` is a legendary bug source. Fall-through is
  occasionally exactly right (grouping cases: `case 6: case 7:` for weekend)
  — but accidental fall-through is so common that modern Java added arrow
  syntax (`case 1 -> "Monday";`, no fall-through, and it's an expression
  yielding a value — the `?:` lesson from Part 3 recurring). If I have the
  choice, arrows; if reading old code, hunt for missing `break`s.

Decision rule: `if` for *conditions* (ranges, compound predicates), `switch`
for *one value against a set of constants*.

## 2. Iteration statements: `while`, `do-while`, `for`, for-each

### while — the primordial loop

```java
while (attempts < 3) {
    // ...
    attempts++;
}
```

Compiles to: label, test condition, conditional-jump past the block if false,
block, `goto` label. Everything else in this section is this pattern with
different upholstery. Two ways I can hurt myself, worth pre-visualizing: the
**infinite loop** (I forget `attempts++` — the condition never changes; in
Scratch "forever" was a feature, here it's usually a hang), and the
**off-by-one** (does `<` vs `<=` run 3 or 4 times? I trace tiny cases by hand
until boundary instincts form).

### do-while — test at the bottom

`while` tests *before* the first iteration, so the body may run zero times.
Sometimes zero is impossible by design — a menu must display at least once, a
password prompt must ask at least once:

```java
do {
    input = promptUser();
} while (!isValid(input));
```

Body first, then test, jump back if true. Runs ≥ 1 time. Rare, but when it
fits, it says "at least once" more honestly than a `while` with a duplicated
first prompt above it.

### for — the counting loop, with the bookkeeping gathered in one place

Counting with `while` scatters the counter's *birth*, *test*, and *update*
across three lines, and in real code they drift apart. `for` collects all
three where I can audit them at a glance:

```java
for (int i = 0; i < 10; i++) {
    System.out.println(i);
}
//   ^init      ^test   ^update — the loop's entire lifecycle in one line
```

It's *exactly* a `while` in a costume — same jumps — plus one genuine
improvement: `i` is **scoped to the loop**. It doesn't exist afterward, so I
can reuse `i` in the next loop without stale-state bugs. The idiom
`for (int i = 0; i < n; i++)` — start at 0, strict `<`, increment — is burned
into every Java programmer's fingers precisely because it visits `0…n-1`,
which is exactly the legal index range of an array of length n (Part 2's
zero-as-offset insight paying rent again).

### for-each — when I don't care about the index

Most array/collection loops never use `i` except as `arr[i]`. The enhanced
for says just that:

```java
for (int score : scores) {      // "for each score in scores"
    total += score;
}
```

Less to write, and *nothing to get wrong* — no bounds, no off-by-one
possible. Its honest limits, which fall out of what it hides: no index
available, can't walk two arrays in lockstep, can't modify the collection's
structure mid-walk, and assigning to `score` changes only the local copy, not
the array. When I need those powers, the classic `for` is right there.
Default to for-each; escalate when needed.

## 3. Jump statements: `break`, `continue`, labeled break, `return`

The structured loops sometimes need an emergency exit — a controlled dose of
the underlying `goto`:

- **`break`** — leave the enclosing loop (or switch) immediately. The classic
  use is search: found it, stop scanning. Without `break` I'd contort the
  loop condition with flag variables; `break` says "done" at the exact moment
  I know it.
- **`continue`** — abandon *this iteration*, jump to the next test/update.
  It's a skip, not an exit. Great for filtering: `if (line.isEmpty())
  continue;` at the top of a loop body reads as "skip blanks," and keeps the
  main logic un-indented.
- **Labeled break** — the one Java kept from goto-land for a real problem:
  `break` only exits *one* level, so how do I escape a nested search?

  ```java
  search:
  for (int row = 0; row < grid.length; row++) {
      for (int col = 0; col < grid[row].length; col++) {
          if (grid[row][col] == target) {
              break search;        // exits BOTH loops
          }
      }
  }
  ```

  A plain `break` inside would only end the inner loop and the outer would
  grind on. `break search` names which structure dies. Used rarely, but the
  alternative (boolean flags checked in every loop condition) is worse.
- **`return`** — exits the whole *method*, which is the cleanest jump of all
  and the perfect segue…

## 4. Functions (methods): naming a computation

The problem announces itself the first time I copy-paste a block of code and
then fix a bug in one copy but not the other. In Scratch the answer was "Make
a Block"; in Java it's a **method**:

```java
static double average(int a, int b) {
    return (a + b) / 2.0;               // 2.0! Integer-division scar, Part 3
}
//  ^return type  ^name  ^parameters

int result = average(10, 15);   // COMPILE ERROR: double → int needs a cast
double avg = average(10, 15);   // 12.5
```

The **signature** (name + parameter types) plus return type is a *contract*,
and the compiler enforces both sides of it: callers must send the right
types, and my method body *must* return a `double` on every path — the
compiler literally analyzes all branches and rejects a method where some
`if`-path falls off the end without returning. (`void` = returns nothing;
`return;` bare just exits. And `static` means "belongs to the class, callable
without an object" — the full story is Part 5's; until then my methods live
in `main`'s world, so they're static.)

Two deep mechanics, both of which I can now explain with pictures I already
own:

**Every call pushes a stack frame** (Part 1's memory model): a fresh workspace
holding that call's parameters and locals. Return pops it. This is why local
variables don't collide across calls, why recursion *just works* — each
recursive call gets its own frame, so `factorial(5)` stacks five independent
`n`s — and why infinite recursion dies with `StackOverflowError`: frames pile
up until the stack region is full. The error message *is* the memory model.

**Java passes everything by value — including references.** This one deserves
slow thinking, because half the internet is confused about it:

```java
static void reassign(int[] arr) { arr = new int[] {9, 9}; }   // caller unaffected
static void mutate(int[] arr)   { arr[0] = 99; }              // caller SEES this
```

The parameter `arr` is a *copy of the reference* (the address, Part 2).
`mutate` follows the copied address to the one shared array and writes — the
caller sees it, because there is only one array. `reassign` overwrites its
local copy of the address to point elsewhere — the caller's variable still
holds the old address, unmoved. One rule covers every case: **the copy is of
the variable's contents; for objects, the variable's contents are an
address.** Corollary: the classic `swap(a, b)` function is impossible for
primitives in Java — it swaps copies. If I can predict both behaviors above
without running them, I own this concept.

**Overloading.** Several methods may share a name with different parameter
types — `println(int)`, `println(String)`, `println(double)` — that's why one
"function" seems to print anything. The compiler picks the version by the
*compile-time types of the arguments*. Same name, statically chosen. (Park
that phrase; Part 5's overriding is the dynamic sibling, and the contrast is
the whole story of polymorphism.)

## 5. Command-line arguments: `String[] args` finally explained

That mysterious `String[] args` in `main` since day one — it's the program's
front door. Text after the program name on the command line arrives, split on
spaces, as this array:

```
java Greeter Alice 3
```

```java
public class Greeter {
    public static void main(String[] args) {
        if (args.length < 2) {                              // guard first!
            System.out.println("Usage: java Greeter <name> <count>");
            return;                                          // jump statement, §3
        }
        String name = args[0];                   // "Alice" — args[0] is the
        int count = Integer.parseInt(args[1]);   // FIRST argument, not the
        for (int i = 0; i < count; i++) {        // program name (unlike C!)
            System.out.println("Hello, " + name);
        }
    }
}
```

Everything I know converges here, which is satisfying: it's an ordinary
`String[]` (Part 2), so `args.length` guards against
`ArrayIndexOutOfBoundsException` when the user forgets arguments; everything
arrives *as text*, so numbers need `Integer.parseInt` (the wrapper classes
earning their keep — and it throws `NumberFormatException` on garbage like
`"three"`, so real tools validate). Why so primitive an interface? Because
it's a *universal* one — every OS, shell script, and build tool knows how to
pass strings to a program. Simple interfaces are the ones everything can
speak. This is also how programs become scriptable components rather than
interactive toys.

## 6. Variable-length arguments (varargs): the last parameter relaxes

New irritation: I want `sum(1, 2)` and `sum(1, 2, 3, 4, 5)` without writing
an overload per arity, and without forcing every caller to build an array by
hand. Java's answer:

```java
static int sum(int... numbers) {        // "zero or more ints"
    int total = 0;
    for (int n : numbers) total += n;   // inside, numbers IS an int[]
    return total;
}

sum();               // 0    (empty array arrives — decide if that's valid!)
sum(1, 2, 3);        // 6    compiler packs {1,2,3} into an array for me
sum(myIntArray);     // also legal — pass an existing array straight through
```

Once I know it's **compiler sugar for an array parameter**, the rules stop
being rules and become consequences:

- **Only the last parameter** may be varargs, and only one per method — the
  compiler assigns arguments to parameters left-to-right, and the greedy
  "everything else" bucket is only unambiguous at the end.
  `format(String template, Object... values)` — hello, `printf`, whose
  signature suddenly makes sense.
- **Exact overloads win over varargs**: given `sum(int, int)` and
  `sum(int...)`, the call `sum(1, 2)` picks the exact one; varargs is the
  fallback. (The compiler prefers the most specific match — same principle
  as overloading generally.)
- The zero-argument call is legal, so my method body must decide whether an
  empty pile is meaningful or an error. The syntax can't decide that for me.

---

**Where I stand:** I can decide, repeat, escape, decompose into named
functions, and accept input from the world. What I can't yet do is keep *data
and the functions that manage it* together — my scores array and my
`average` method are strangers who happen to meet inside `main`. Every real
program I imagine (a game with sprites, a bank with accounts) wants bundles
of state + behavior. Scratch had these all along — they were called
*sprites*. Java calls them objects, and building their blueprints is the
final and biggest idea. → [Part 5](05-classes-abstract-interfaces.md)
