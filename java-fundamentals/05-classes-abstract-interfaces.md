# Part 5 — Classes, Abstract Classes, Interfaces — and the Naming Conventions Holding It All Together

*The monologue concludes. My data and my functions are strangers who keep
meeting inside `main`. Time to fix that — and it turns out I've known the
answer since Scratch.*

---

## 1. The problem, felt honestly

I'm sketching a bank program with what I have. Parallel arrays:

```java
String[] ownerNames = ...;
double[] balances = ...;

static void withdraw(String[] names, double[] balances, int index, double amount) {
    if (balances[index] >= amount) balances[index] -= amount;
}
```

I stare at this and enumerate what's wrong, because the wrongness is the
lesson:

1. **The data is shattered.** Account #7 is a *concept*, but here it's
   `ownerNames[7]` plus `balances[7]` — related only by my discipline in
   keeping indexes aligned. One sloppy delete and every account after it is
   corrupted.
2. **Nothing is protected.** Any code anywhere can write
   `balances[7] = -5000;` — bypassing my careful `withdraw` check entirely.
   My rule ("no overdrafts") is a suggestion, not a law.
3. **The functions float free.** `withdraw` clearly *belongs to* accounts,
   but nothing says so except its name.

Now — Scratch solved this and I didn't notice. A sprite *was* state (x, y,
costume, its "for this sprite only" variables) bundled with behavior (its
scripts), and other sprites couldn't reach in and scribble on its variables.
The sprite was the unit. Java's word for the blueprint is **class**; each
stamped-out copy is an **object** (or *instance*). What I called "the cat and
three copies of it" is precisely "one class, four instances."

## 2. Building the class

```java
public class BankAccount {                       // PascalCase: it's a TYPE
    private String ownerName;                    // fields: per-object state
    private double balance;                      //   ("for this sprite only")

    public BankAccount(String ownerName, double openingBalance) {   // constructor
        if (openingBalance < 0) {
            throw new IllegalArgumentException("Opening balance can't be negative");
        }
        this.ownerName = ownerName;              // this.field = parameter
        this.balance = openingBalance;
    }

    public boolean withdraw(double amount) {     // methods: behavior WITH the data
        if (amount <= 0 || amount > balance) return false;
        balance -= amount;                       // my own field — no index juggling
        return true;
    }

    public double getBalance() { return balance; }   // read allowed…
    // note: no setBalance(). Money enters/leaves ONLY via deposit/withdraw.
}
```

```java
BankAccount aliceAccount = new BankAccount("Alice", 100.0);
aliceAccount.withdraw(30.0);                     // "Alice's account, withdraw 30"
```

Let me narrate the load-bearing parts as decisions, not syntax:

**`new` and references.** `new` allocates the object on the heap (Part 1's
memory model) and hands back its address; `aliceAccount` is a reference —
same species of thing as an array variable (Part 2). So assignment aliases
(`b = aliceAccount` is one account, two names), `==` compares addresses not
contents (the `.equals()` lesson, third appearance), and a reference-typed
variable can be `null`. All old knowledge, now unified: *strings, arrays,
vectors, and my own objects are the same kind of thing.* The language just
let me join the club of type-authors.

**The constructor** is how an object is born valid. It runs exactly once, at
`new`, has no return type, is named after the class — and it's where I
enforce birth-rules (no negative opening balance). No default zombie state,
no "create then hopefully initialize" gap. Constructors overload like methods
(Part 4), so I can offer several legitimate ways to be born.

**`this`** is the answer to "which object's field?" — inside a method, `this`
is the object the method was called *on*. `aliceAccount.withdraw(30)`
secretly passes `aliceAccount` as `this`. That one fact demystifies method
call syntax entirely: `object.method(args)` is `method(object, args)` with
the first parameter promoted to the place of honor.

**`private` is problem #2 solved — and it's the whole point.** Fields are
`private`: no outside code can touch `balance` directly. Every mutation is
funneled through methods *I* wrote, so my invariant — "balance never goes
negative" — is now a **law enforced by the compiler**, not a hope. This is
**encapsulation**, and the getter-but-no-setter asymmetry is where design
lives: I expose *reads* of balance but force *writes* through the business
rules. If I later add transaction logging or thread-safety, I edit one class;
the outside world sees the same public surface. Public surface = contract;
private interior = mine to renovate.

**`static` vs instance — finally, properly.** A field like
`private static int totalAccountsCreated;` belongs to the *class*, one copy
shared by all instances (Scratch's "for all sprites" variable — the parallel
is exact). A static method (`Math.sqrt`, `Integer.parseInt`, `main`) needs no
instance, which is why the JVM can call `main` before any object exists
(Part 1's mystery, closed). Naming convention alert: call static things
through the class — `Math.sqrt(2)`, `BankAccount.getTotalAccounts()` — so a
reader can tell shared machinery from per-object behavior at a glance.

## 3. The naming conventions — a system, not etiquette

Worth pausing on, because I keep leaning on it: Java's conventions are
*camelCase-based semantic signaling*, and the compiler never checks them —
readers do.

| Thing | Convention | Example |
|---|---|---|
| Classes, interfaces (types) | `PascalCase`, nouns | `BankAccount`, `Comparable` |
| Methods | `camelCase`, verbs | `withdraw()`, `getBalance()` |
| Variables, fields, parameters | `camelCase`, nouns | `ownerName`, `openingBalance` |
| Constants (`static final`) | `SCREAMING_SNAKE_CASE` | `MAX_LOGIN_ATTEMPTS` |
| Packages | all lowercase | `java.util` |

The payoff is that code becomes *skimmable*: in `account.withdraw(MAX_DAILY)`
I can identify an instance (lowercase noun), a behavior (verb), and a
constant (screaming) without reading a single declaration. `Integer` vs
`int`, `String` vs `args` — every capitalization choice in these five parts
was this system talking. Breaking it doesn't break the program; it breaks the
*reader*, which is worse.

## 4. Abstract classes: blueprints with mandatory holes

New problem, one step up in altitude. I'm building shapes for a drawing app:
`Circle`, `Rectangle`, `Triangle`. Each has an area — computed completely
differently. And I want to sum areas over a *mixed* bag of shapes.

I reach for inheritance — a `Shape` parent class with `Circle extends Shape`
so shared stuff (a name, a color) lives once. But I hit an honest wall:
**what should `Shape.area()` return?** There is no generic-shape area
formula. Return 0.0? Then a subclass that *forgets* to write its own `area()`
silently inherits a wrong answer — a landmine that type-checks. What I
actually want to tell the compiler is: *"every Shape has an area; I cannot
say how; every concrete subclass MUST say how."* That sentence is exactly
what `abstract` encodes:

```java
public abstract class Shape {
    private final String name;                    // shared state lives here
    protected Shape(String name) { this.name = name; }

    public abstract double area();                // a hole: no body. Subclasses MUST fill it.

    public String describe() {                    // shared behavior lives here too —
        return name + " with area " + area();     // and it can CALL the hole!
    }
}

public class Circle extends Shape {
    private final double radius;
    public Circle(double radius) { super("circle"); this.radius = radius; }
    @Override public double area() { return Math.PI * radius * radius; }
}
```

Consequences, each one a former mystery dissolving:

- **`new Shape("blob")` is a compile error.** Of course — the class has a
  hole; instantiating it would create an object with a callable method that
  has no body. Abstract classes exist to be extended, never stamped.
- **A subclass missing `area()` is a compile error** unless it declares
  itself abstract too. The landmine from the naive design became a
  compile-time obligation. This is the recurring Java move — convert "I hope
  everyone remembers" into "the compiler refuses otherwise."
- **`describe()` calling `area()`** is the elegant bit: concrete shared code
  invoking the not-yet-written part, trusting the contract. The parent writes
  the skeleton; children supply the specifics. (The design-pattern people
  call this *template method*; I'd rather remember the reasoning than the name.)

And the payoff — **polymorphism**:

```java
Shape[] shapes = { new Circle(2), new Rectangle(3, 4) };
double total = 0;
for (Shape s : shapes) total += s.area();     // each element answers as ITSELF
```

`s` is declared `Shape`, but `s.area()` runs `Circle`'s code for the circle
and `Rectangle`'s for the rectangle. The decision happens **at runtime, by
the actual object's type** — this is *overriding*, the dynamic sibling I
parked in Part 4 next to compile-time overloading. The declared type answers
"what may I call?" (compile-time question); the actual object answers "whose
version runs?" (runtime question). The bytecode instruction is literally
`invokevirtual`, and the JIT (Part 1) optimizes the hot cases. One loop, open
to shape types not yet invented — I can add `Hexagon` next year and this loop
handles it, unmodified. That's the design win the whole apparatus buys.

(`@Override` is me telling the compiler "I intend to replace a parent
method — verify that I actually am." Without it, a typo like `aera()` would
silently *add a new method* instead of overriding. Same immune system,
another antibody.)

## 5. Interfaces: capabilities without ancestry

Different problem — and noticing it's different from the shapes problem is
the insight. Sorting: `Arrays.sort` wants to sort strings, accounts, shapes,
things that share **no common ancestor**. What sorting needs is not shared
state or shared machinery — it needs one promise: *"instances of me can be
compared to each other."*

Could I use an abstract class, `ComparableThing`, and extend it? Two reasons
no, and they're both structural: Java permits **one superclass only** (a
class can't extend both `Shape` and `ComparableThing` — multiple inheritance
of *state* creates genuine ambiguities, the classic "diamond problem," so
Java banned it), and anyway there is no state or code to share — the promise
is the entire content. What I want is a **pure contract**, and that's an
interface:

```java
public interface Comparable<T> {
    int compareTo(T other);          // implicitly public abstract — pure promise
}

public class BankAccount implements Comparable<BankAccount> {
    // ... everything from before, PLUS the promised method:
    @Override public int compareTo(BankAccount other) {
        return Double.compare(this.balance, other.balance);
    }
}
```

The key asymmetry that makes interfaces compose where classes can't: an
interface **holds no per-instance state** — no fields (only `public static
final` constants), classically no method bodies. Since nothing but promises
is inherited, promises can't *conflict*, so a class may implement **as many
interfaces as it likes** while still extending its one class:

```java
public class BankAccount extends Asset
        implements Comparable<BankAccount>, Auditable, Serializable { ... }
```

Read the two keywords as they deserve: `extends` = *"is a kind of"*
(ancestry, one parent); `implements` = *"can do"* (capabilities, unlimited).
An interface is also a full-fledged *type* for declarations —
`Comparable<BankAccount> x = aliceAccount;` — so I can write code that
depends only on the capability, accepting any object from any class
hierarchy that signed the contract. This is the loosest possible coupling:
caller and implementer share nothing but the promise. It's also exactly what
`Vector` did in Part 2 when it retrofitted `implements List` — old class,
newly signed contract, instantly usable by every method that says "give me
any List."

(Modern footnote: since Java 8, interfaces may carry `default` method bodies
— added so old interfaces could grow new methods without breaking every
implementer on Earth. It blurs the class/interface line, but the *stateless*
rule still holds, and the mental model survives: interfaces are contracts,
possibly with courtesy default clauses.)

## 6. Abstract class vs interface — the decision, compressed

Both can't be instantiated; both force implementations; both enable
polymorphism. After building one of each, the difference is no longer a
quiz answer but a design smell test:

- Related types sharing **state and machinery**, differing in specifics →
  **abstract class**. ("A Circle *is a* Shape" — and Shape owns fields and
  `describe()`.)
- Unrelated types sharing a **capability** → **interface**. ("Accounts,
  strings, and dates can all be *compared*" — no shared ancestry imaginable.)
- Need both? Common: `class Circle extends Shape implements Comparable<Circle>`.
  One ancestry, many capabilities.
- Genuinely torn and no state to share → prefer the interface; it costs the
  implementer nothing (their single-extends slot stays free) and couples the
  system more loosely.

---

## 7. Closing the loop

Looking back at the whole arc, it was never seventeen topics — it was one
argument unfolding:

Somebody must run my program (**JVM**), and running it well means checking it
first (**compiler**) and speeding it up later (**JIT**). Checking requires
knowing what data is (**primitives, types**), which forces rules for mixing
them (**casting, promotion**) and a bridge into the object world (**wrappers,
autoboxing**). Data comes in bulk (**arrays**), including text (**Strings**,
immutable for sharing's sake) and elastic collections (**Vector**, doubling
for amortized cheapness). Values combine via typed functions-in-costume
(**operators**) parsed by grammar rules (**precedence**), and flow through
disciplined jumps (**selection, iteration, jump statements**). Computation
gets named and stacked (**functions/methods**), fed from the world outside
(**command-line args**, **varargs**). And finally, state and behavior fuse
into the unit Scratch had shown me all along (**classes**), with contracts
that have holes (**abstract classes**) or are nothing *but* holes
(**interfaces**) — every capitalization along the way silently signaling
type-or-value, constant-or-variable (**naming conventions**).

Every rule was somebody's solved problem. That's the method, and it travels:
next time Java (or any language) does something baffling, the move isn't to
memorize — it's to ask *what problem was this the answer to?* and think my
way out.
