# Part 2 — Data, From the Bits Up: Primitives, Wrappers, Casting, Autoboxing, Arrays, Strings, Vector

*The monologue continues. In Part 1 the bytecode kept saying `iload`, `iadd` —
`i` for int. Types are apparently baked into the machine itself. Time to
understand data the way the machine does.*

---

## 1. Why Scratch never made me think about this

In Scratch, a variable was a little orange pill that held… whatever. A number,
some text — the runtime figured it out as it went, re-checking "what is this
thing?" every single time a block touched it. Convenient, and slow, and the
reason weird things happened only at runtime.

Java's compiler wants to *prove* things about my program before it runs
(Part 1, stage 3). You can't prove anything about a box whose contents are a
surprise. So Java demands I declare, up front, what species of value each
variable holds:

```java
int age = 25;
double price = 19.99;
```

And the payoff is mechanical: if the compiler knows `age` is an `int`, it can
emit the exact `iadd` instruction, reserve exactly the right number of bytes,
and reject `age = "twenty-five"` at compile time. Declared types aren't
bureaucracy; they're what makes both the speed and the safety of Part 1
possible.

## 2. Deriving the primitive types instead of memorizing them

Eight primitive types. I could recite the list — or I could ask what the
*hardware* offers, and watch the list derive itself.

**Whole numbers.** Memory is finite, so an integer must occupy a fixed number
of bytes. Fixed size = hard limits, so Java offers a size menu:

| Type | Size | Range |
|------|------|-------|
| `byte` | 8 bits | −128 … 127 |
| `short` | 16 bits | −32,768 … 32,767 |
| `int` | 32 bits | about ±2.1 billion |
| `long` | 64 bits | about ±9.2 quintillion |

Where do those asymmetric ranges come from — why −128 to **127**, not 128?
This bugs me enough to work it out. With 8 bits I get 256 patterns. To encode
negatives, Java (like all modern hardware) uses **two's complement**: the top
bit carries weight −128 instead of +128. So `0111 1111` = 127, and
`1000 0000` = −128. One pattern must be zero (`0000 0000`), which eats a slot
from the positive side. Elegant side effect: the same physical adder circuit
works for signed and unsigned — no special cases.

But two's complement has a consequence Java does **not** protect me from, and
I'd rather learn it here than in production:

```java
int big = Integer.MAX_VALUE;   // 2_147_483_647
System.out.println(big + 1);   // -2147483648.  Silently.
```

Adding 1 to `0111…111` carries into the sign bit: `1000…000`, the most
negative value. The odometer rolls over. **No exception, no warning.** The
famous real-world casualty: video view-counters that went negative. Rule I'm
tattooing on my brain: *choose `long` when a quantity could plausibly exceed
two billion* — and `int` otherwise, since it's the natural word size CPUs
chew fastest.

**Fractional numbers.** How do you put 3.14159 in binary? The engineering
answer is scientific notation in base 2: store a sign, an exponent, and a
significand — the **IEEE 754** floating-point format. `float` is the 32-bit
version (1 sign + 8 exponent + 23 significand bits), `double` the 64-bit
version (1 + 11 + 52). "Double precision" — hence the name.

And here's the trap that catches every single programmer once:

```java
System.out.println(0.1 + 0.2);   // 0.30000000000000004
```

My first instinct is "bug!" — but let me think instead of react. In base 10,
1/3 has no finite decimal: 0.333… forever. In base **2**, it's 1/10 that has
no finite representation — 0.1 in binary is 0.000110011001100…, repeating
forever. The machine stores the nearest 64-bit approximation, and two rounded
inputs sum to a visibly-rounded output. Not a bug: an inherent property of
finite binary fractions. Consequences I accept now: **never compare doubles
with `==`** (compare `Math.abs(a - b) < epsilon`), and **never use
floating-point for money** (count cents in a `long`, or use `BigDecimal`).
Default to `double`; `float` is for when memory is desperately tight.

**Characters.** Text is just numbers wearing costumes — assign every character
a number (`'A'` = 65) and store the number. Java's `char` is 16 bits and
**unsigned** (0 … 65,535) because Java standardized on Unicode's 16-bit
encoding to hold the world's alphabets, and a negative character code means
nothing. A `char` really is a number in costume — `'A' + 1` is 66, and
`(char)('A' + 1)` is `'B'`. That's not a party trick; it's how you iterate
alphabets.

**Truth.** Decisions need a yes/no type: `boolean`, values `true` and `false`.
Java pointedly does *not* let 0 mean false and 1 mean true (C does, and a
whole family of C bugs comes from typing `if (x = 0)` when you meant `==`).
In Java that line doesn't even compile, because `x = 0` isn't a boolean. The
type system as guard rail, again.

So: `byte short int long` / `float double` / `char` / `boolean` — four sizes
of integer, two of floating point, one character, one truth value. Eight. Not
memorized — *derived* from what hardware can store.

## 3. Casting: conversions, and who bears the risk

Eight numeric-ish types means conversions between them, constantly. When is
conversion safe? That question alone predicts all the rules.

**Small into big — safe.** Every `int` fits in a `long`; every `int` fits in a
`double`. No information can be lost, so the compiler converts silently.
**Widening / implicit conversion:**

```java
int i = 100;
long l = i;      // fine, automatic
double d = i;    // fine, automatic
```

**Big into small — dangerous.** A `long` holding 5 fits in an `int`; a `long`
holding 10 billion does not. The compiler can't know at compile time which
case I'm in, so it refuses — *unless I sign the waiver*. That signature is the
**cast**, and now the syntax reads as what it is, an acceptance of liability:

```java
long l = 5;
int i = (int) l;        // "I accept the risk of truncation."

double pi = 3.99;
int chopped = (int) pi;  // 3 — truncates toward zero. Does NOT round!
```

Narrowing a too-big value doesn't error — it keeps the low bits, producing
two's-complement garbage. `(int) 10_000_000_000L` is `1410065408`. The cast
means *I* promised it fit.

One asymmetry worth catching because it violates the "widening is lossless"
slogan: `int` → `float` and `long` → `double` are classified as widening and
happen implicitly, **but can lose precision** — a `float` has only 24
significand bits, so `int` values above ~16 million don't all survive the
trip. Lossless in *range*, lossy in *precision*. Filed under "the spec chose
convenience; stay alert."

Also filed: integer division is its own quiet cast — `7 / 2` is `3`, because
`int` ÷ `int` produces `int`. If I want 3.5, someone must be a double *before*
the division: `7 / 2.0`. (Full operator treatment in Part 3.)

## 4. Wrapper types: when a primitive needs to be an object

Primitives are deliberately naked — an `int` is 32 raw bits, no baggage,
maximally fast, living happily in a stack slot. But Java's generic machinery
(collections and friends — coming in section 8) is built to handle **objects**:
things on the heap, addressed by reference, with methods. A raw `int` is not
that. So a `Vector` or `ArrayList` cannot hold `int`s. Genuinely cannot.

The workaround the language provides: every primitive has an official chaperone
class — a **wrapper type** — whose instances are real heap objects containing
one primitive value:

`byte→Byte, short→Short, int→Integer, long→Long, float→Float, double→Double,
char→Character, boolean→Boolean`

(Note the naming: primitives are lowercase keywords; classes are capitalized —
`int` vs `Integer`. The capitalization *is* the semantic signal. This
convention never breaks, and I'll lean on it constantly.)

Wrappers also serve as the natural home for type-related utilities and
constants, which is a tidy piece of design: `Integer.MAX_VALUE`,
`Integer.parseInt("42")` (string → int, essential for Part 4's command-line
arguments), `Character.isDigit(c)`, `Double.isNaN(x)`.

## 5. Autoboxing — and the two traps it hides

Writing `Integer.valueOf(5)` and `.intValue()` by hand everywhere would be
misery, so since Java 5 the compiler does the wrapping/unwrapping for me:

```java
Integer boxed = 5;       // autoboxing:  compiler inserts Integer.valueOf(5)
int raw = boxed;         // auto-unboxing: compiler inserts boxed.intValue()
```

Sugar. But sugar over a *real* mechanical difference — a heap allocation and a
pointer — and whenever syntax hides mechanics, there are traps. I want to find
them *now*, deliberately, rather than meet them in a 2 a.m. debugging session.

**Trap 1: `==` on wrappers compares identity, not value.**

```java
Integer a = 127, b = 127;
System.out.println(a == b);      // true
Integer c = 128, d = 128;
System.out.println(c == d);      // false ?!
```

Analysis: `==` between objects asks "same object on the heap?" (Part 5 will
formalize this). `Integer.valueOf` keeps a cache of −128…127 for efficiency,
so both 127s are literally the same cached object — while the 128s are two
separate allocations. The cache makes `==` *sometimes* work, which is far
crueler than never working: it passes every small-number test and detonates on
big inputs. Rule: **compare wrappers with `.equals()`, or unbox first.**

**Trap 2: unboxing `null` explodes.** A wrapper variable is a reference and
may be `null`. Unboxing is `.intValue()` on it → `NullPointerException`.
An `int` can never be null; an `Integer` can. The type says what can go wrong.

And a performance instinct: autoboxing in a hot loop
(`Integer sum = 0; sum += i;` a million times) allocates a fresh object per
iteration, since wrappers are immutable. Primitives in loops, wrappers at the
boundaries where objects are required.

## 6. Arrays: many values, one name, O(1) access

New problem, felt in the fingers: 100 sensor readings should not be 100
variables. In Scratch I had "lists." Java's rawest many-values tool is the
**array** — and its design falls out of one hardware fact: memory is a giant
numbered street of bytes.

If I store 100 `int`s *contiguously* — back to back — then finding element
`i` is pure arithmetic: `address = base + i × 4`. No searching. Element 0 and
element 99,999 cost identical time. That formula also explains, at last, why
indices start at **0**: the index isn't a rank, it's an *offset* — how far
from the start. First element, zero distance. (Scratch's 1-based lists were
hiding this from me.)

```java
int[] scores = new int[5];          // fixed size, zero-filled: [0,0,0,0,0]
scores[0] = 90;
int[] primes = {2, 3, 5, 7, 11};    // literal form
System.out.println(primes.length);  // 5 — a field, not a method: no ()
```

Three consequences worth reasoning through, not memorizing:

**Fixed size forever.** The array occupies a specific block of contiguous
memory; the block can't stretch, because the neighboring bytes are taken.
"Growing" an array means allocating a bigger one and copying. Remember this
pain — it's the entire reason section 8 exists.

**Arrays are objects; variables hold references.** `new` — so the array lives
on the heap, and `scores` is just an address pointing at it. Therefore:

```java
int[] a = {1, 2, 3};
int[] b = a;          // copies the ADDRESS, not the data
b[0] = 99;
System.out.println(a[0]);   // 99 — a and b are one array, two names
```

Aliasing. Not a bug — a direct consequence of "variable holds reference." A
real copy must be explicit: `int[] b = Arrays.copyOf(a, a.length);`.

**The JVM guards the borders.** `scores[10]` on a length-5 array throws
`ArrayIndexOutOfBoundsException` — the JVM checks every index at runtime. C
doesn't, and that single omission (reading/writing past the end of a buffer)
underlies decades of security exploits. The check costs a few cycles per
access; in character, Java pays it — and the JIT (Part 1) elides it inside
loops it can prove safe.

**2D arrays** aren't a grid in memory — they're an array *of references to
arrays*. `int[][] grid = new int[3][4]` builds one spine of 3 references, each
pointing to its own row of 4. Which means rows can be different lengths
(jagged arrays) — a possibility that only makes sense once you know the
representation. And the enhanced loop for walking any of it:

```java
for (int p : primes) { System.out.println(p); }   // "for each p in primes"
```

## 7. Strings: why text is immutable, and what that costs me

Text is a sequence of `char`s, so a string is "an array of char with
manners" — `String` wraps the storage and gives me methods:

```java
String name = "Ada Lovelace";
name.length();          // 12
name.charAt(0);         // 'A'
name.substring(0, 3);   // "Ada"
name.toUpperCase();     // "ADA LOVELACE"
name.indexOf("Love");   // 4
```

But `String` has one property so consequential that it explains three
otherwise-baffling behaviors, so let me lead with it: **strings are
immutable.** No method changes a string. `toUpperCase()` doesn't shout at the
original — it builds and returns a *new* string; the original is untouched.

Why would the designers do that? Reconstructing the reasoning:

1. **Sharing becomes safe.** If strings can't change, two variables can point
   at one string with zero risk (compare the array-aliasing scare above — for
   arrays, sharing is a footgun; for strings it's free). The JVM exploits this
   aggressively: identical string *literals* in code are stored once, in a
   **string pool**, and everyone points at the shared copy.
2. **Hashing becomes cacheable.** A string computes its hash code once and
   stores it forever — legal only because the content can't change. Strings
   are the most common map keys in existence; this matters.
3. **Security.** File paths, usernames, URLs get passed to sensitive code as
   strings. Immutability means no one can validate a string and have another
   thread mutate it *after* the check.

Now the famous traps, which stop being mysterious:

**Trap 1: `==` on strings.**

```java
String s1 = "hello";
String s2 = "hello";
String s3 = new String("hello");
s1 == s2         // true  — same pooled literal, same object!
s1 == s3         // false — `new` forced a fresh heap object
s1.equals(s3)    // true  — same CONTENT. This is the question I meant to ask.
```

Same cruelty as the Integer cache: the pool makes `==` *usually* work on
literals, so the bug hides until strings arrive from user input or files.
Rule, permanent: **`==` asks "same object?"; `.equals()` asks "same text?".
For strings, I virtually always mean `.equals()`.**

**Trap 2: concatenation in a loop.** `s = s + x` can't modify the immutable
`s` — it copies *all of s* plus `x` into a brand-new string, every iteration.
1 + 2 + 3 + … + n copying = **O(n²)**. Ten thousand concatenations, fifty
million character copies. The escape hatch is the mutable workbench class:

```java
StringBuilder sb = new StringBuilder();
for (int i = 0; i < 10_000; i++) sb.append(i);   // amortized O(n) total
String result = sb.toString();
```

Immutable product, mutable factory. A pattern I suspect I'll see again.

## 8. Vector: the growable array, and why it's a museum piece worth studying

Back to the pain from section 6: arrays are fixed-size, but the real world
sends me an unknown number of things. I can already sketch the solution
myself: keep an internal array, track how many slots are *used*, and when it
fills, allocate a bigger array and copy over. Java shipped exactly this in
version 1.0 (1996) as **`java.util.Vector`**.

```java
import java.util.Vector;

Vector<Integer> scores = new Vector<>();
scores.add(90);              // autoboxing at work: int → Integer (section 5!)
scores.add(85);
scores.get(0);               // 90 (auto-unboxed if assigned to int)
scores.size();               // 2 — how many elements I've stored
scores.remove(0);            // shifts everything left by one
scores.contains(85);         // true
```

The `<Integer>` is a **generic type parameter** — me telling the compiler
"this Vector holds Integers only," so it can type-check insertions and spare
me casts on the way out. And notice why it's `Integer`, not `int`: generics
work only with object types. Sections 4–5 weren't a detour; they were
load-bearing.

Details that reveal the mechanism:

- **`size()` vs `capacity()`** — elements stored vs. slots allocated in the
  hidden internal array. The gap between them is the growth strategy made
  visible.
- **Growth is doubling.** When full, Vector allocates double and copies. Why
  double, not +1? If it grew by one slot, *every* add would copy the whole
  array — O(n) per add. Doubling means copies happen rarely (at sizes 10, 20,
  40, 80…), and the total copying over n adds is O(n) — **amortized O(1)** per
  add. Exponential growth is the trick that makes growable arrays cheap.
- **Legacy fingerprints.** Vector predates the collections framework, so it
  drags around old method names (`addElement`, `elementAt`) alongside the
  modern ones (`add`, `get`) it gained when retrofitted into the `List`
  interface (a concept I'll properly meet in Part 5).

And the honest engineering note: modern code overwhelmingly uses **`ArrayList`**
instead — same idea, same API, one difference. Every Vector method is
`synchronized`: each call locks the object so concurrent threads can't corrupt
it. Sounds prudent; two problems. Single-threaded code (most code) pays the
locking tax for nothing. And multi-threaded code isn't actually saved, because
compound operations still interleave: my `if (!v.isEmpty()) v.remove(0)` can
be torn apart by another thread *between* the two calls — each call was
atomic, my *logic* wasn't. Per-method locking is the wrong granularity: too
coarse to be free, too fine to be safe. So Vector is a well-intentioned 1996
answer that modern Java superseded — but it taught me dynamic arrays,
amortized doubling, and generics in one object, so the museum visit paid.

---

**Where I stand:** I know what values *are* — bits with declared
interpretations — and where they live (stack slots for primitives and
references; heap for objects, arrays, strings, vectors). But I've been using
`+` and `<` and `==` on faith. Time to interrogate the operators themselves,
because at least one of them (`==`) has already shown me it doesn't mean what
it looks like it means. → [Part 3](03-operators-and-precedence.md)
