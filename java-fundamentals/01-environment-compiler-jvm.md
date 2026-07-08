# Part 1 — The Environment, the Compiler, and the Java Virtual Machine

*The monologue of someone who has only ever snapped blocks together in Scratch,
now staring at a blinking terminal cursor.*

---

## 1. Who was running my Scratch programs?

Let me start with a question I never asked myself: when I clicked the green
flag in Scratch, *what actually happened?*

I snapped blocks together. Blocks aren't electricity. My laptop's CPU is a slab
of silicon that understands exactly one language — machine code, a stream of
numbers like `B8 01 00 00 00` that mean "put 1 into this register." My colorful
`move 10 steps` block is not that. So something must have been sitting between
my blocks and the CPU, reading my blocks one by one and *doing them on my
behalf*.

That something was the Scratch runtime — a program, written by other people,
whose whole job is to walk through my program and perform it. There was a
machine inside the machine. I was never programming the CPU. I was programming
a simulated, friendlier computer that somebody built for me.

Hold that thought, because Java is going to do the exact same trick — just
openly, and industrially.

## 2. The problem Java was built to solve

Suppose I want to write a real program and hand it to a friend. I have options,
and each one has a problem. Let me actually think through them instead of
accepting the textbook answer.

**Option A: write machine code for the CPU directly** (or use a compiler like
C's that translates my source into machine code). Result: blisteringly fast,
the CPU eats it natively. Problem: machine code is CPU-specific and
OS-specific. The program I build on my x86 Windows laptop is gibberish to my
friend's ARM MacBook. I'd have to rebuild — and often re-test, and sometimes
re-write — for every platform. In the 1990s, with a dozen competing systems,
this was misery.

**Option B: ship my source code and let everyone run it through an
interpreter**, the way Scratch does, the way early Python and JavaScript did.
Result: perfectly portable — anyone with the interpreter can run it. Problems:
it's slow (someone is re-reading and re-deciphering my text at runtime, every
time, forever), and my mistakes are discovered *late*. If line 500 has a typo,
nobody finds out until execution reaches line 500. Possibly in production.
Possibly on the friend's machine.

Now, thinking about it, these two options fail for *opposite* reasons. A is
fast but chained to one machine. B is portable but slow and fragile. Which
means the fix is probably a hybrid. What would a hybrid even look like?

Here's the insight, and it's genuinely beautiful: **compile — but not for a
real CPU. Compile for an imaginary one.**

Design a fictional, idealized processor on paper. Give it a clean, simple
instruction set. Then:

1. Compile Java source into instructions for that fictional processor. This
   is called **bytecode**. It's a real, binary, compact, checkable format —
   all the benefits of compiling — but it belongs to no physical chip.
2. For every *real* platform — Windows/x86, macOS/ARM, Linux, your fridge —
   write a program that *pretends to be* the fictional processor. That
   impersonator is the **Java Virtual Machine (JVM)**.

Now I compile once, and the result runs anywhere someone has installed the
impersonator. "Write once, run anywhere" isn't a slogan; it's a direct logical
consequence of splitting the work this way. The bytecode is portable because
the imaginary CPU is standardized; the speed problem gets solved inside the JVM
(section 5 — it's cleverer than you'd guess).

And notice: this is Scratch's architecture, matured. The Scratch runtime was
my VM all along. Java just formalizes the contract and publishes the spec.

## 3. The programming environment: what do I actually need installed?

So what software does this workflow require? Let me derive the shopping list
from the workflow itself:

- To **run** a Java program, I need the impersonator (the JVM) plus the big
  library of prebuilt classes every program leans on (printing, math,
  collections — the standard "blocks palette", if you like). JVM + standard
  class library = the **JRE, Java Runtime Environment**. That's all a *user*
  of my program needs.
- To **write** Java, I additionally need the translator that turns my source
  text into bytecode — the compiler, `javac` — plus developer tools: `jar`
  (bundles many compiled classes into one shippable file), `javadoc`
  (generates documentation), `jdb` (a debugger), `javap` (a disassembler —
  we'll use it, it's a flashlight). All of that, bundled *with* a JRE, is the
  **JDK, Java Development Kit**.

So the nesting is: **JDK ⊃ JRE ⊃ JVM.** Developer kit contains runtime
contains virtual machine. I install the JDK; my users only strictly need a
JRE. One sentence, and the three acronyms stop being trivia.

## 4. Command line first — because I want to see the machinery

I could open a giant IDE right away, but then buttons would do things I don't
understand, and I refuse to build on mystery. Let me do one full cycle by hand.

I create a file. Not with Word — word processors embed formatting bytes into
the file; the compiler wants *plain text*. A plain editor, then, and I save
this as `HelloWorld.java`:

```java
public class HelloWorld {
    public static void main(String[] args) {
        System.out.println("Hello, world");
    }
}
```

I'll dissect every keyword in later parts. For now the shape: Java insists all
code lives inside a **class** (Part 5 explains why), and `main` is the agreed
entry point — Java's green flag. When I ask the JVM to run this class, it looks
for exactly this signature: `public static void main(String[] args)`. Public so
the JVM may call it from outside; static so it can be called *before any object
exists* (nothing has been created yet at time zero — something must be callable
on the class itself, or we have a chicken-and-egg problem); `void` because it
returns nothing; `String[] args` — hold that until Part 4, it's the command
line talking to me.

One rule that surprises me until I see the reason: the file *must* be named
`HelloWorld.java`, matching the public class inside, case and all. Why so
strict? Because later, when the JVM hunts for a class named `HelloWorld`, it
needs to know which file to look in *without opening every file on disk*. The
naming rule turns a search problem into a lookup. Convention as an index.

Now, in the terminal:

```
javac HelloWorld.java
```

Silence. In command-line culture, silence is applause. A new file has appeared:
`HelloWorld.class`. If I open it, it's binary noise — that's the bytecode, the
program for the imaginary CPU. Then:

```
java HelloWorld
```

```
Hello, world
```

Note the asymmetry, because it trips everyone once: `javac` takes a **file
name** (`HelloWorld.java` — it's a file-processing tool), but `java` takes a
**class name** (`HelloWorld`, no extension — I'm naming the class whose `main`
I want; the JVM does the class-to-file mapping itself). Typing
`java HelloWorld.class` fails, and now I know exactly why: the JVM would go
looking for a class called `class` in a package called `HelloWorld`.

Two commands, two tools, one handoff. That's the entire environment. Everything
else is convenience layered on top of this.

## 5. What is `javac` actually doing? (More than translating.)

Naively: "the compiler converts my code so the machine can run it." True but
it undersells the most useful thing the compiler does. Let me walk through the
pipeline like an engineer, because each stage explains a category of error
message I'm going to see for the rest of my life.

**Stage 1 — Lexing.** The compiler reads my file as a stream of characters and
groups them into tokens: `public`, `class`, `HelloWorld`, `{`, `"Hello, world"`.
Like turning letters into words. Errors here are rare and low-level (an
unterminated string, a stray character).

**Stage 2 — Parsing.** The token stream gets checked against Java's grammar
and built into a tree — this class contains this method contains this
statement. Here's where a missing `}` or `;` explodes. And now I understand a
phenomenon that used to baffle me: *one* missing brace produces *fifty* error
messages. The parser isn't being dramatic — after the missing brace, its model
of the tree is wrong, so every subsequent line genuinely looks illegal *to it*.
Lesson learned by reasoning, not by rote: **fix the first error, recompile,
ignore the rest.** They're usually echoes.

**Stage 3 — Semantic analysis.** This is the stage Scratch never had, and it
changes my relationship with mistakes. The compiler now checks *meaning*:
every variable I use is declared; every method I call exists; and — the big
one — the **types** line up. In Scratch I could join the word "apple" to a
number and multiply the result by a sprite's direction; nothing complained
until runtime did something weird. Java's compiler is a proof-checker: it
verifies, *before the program ever runs*, that I never hand a `String` to
something demanding an `int`. A whole galaxy of bugs — the kind that lurk on
line 500 waiting for an unlucky user — die here instead, at my desk, seconds
after I write them.

This reframes compiler errors emotionally, which matters more than it sounds:
an error message isn't the compiler rejecting me. It's a colleague catching my
bug *before anyone else could see it*. The compiler is the cheapest QA I will
ever employ.

**Stage 4 — Code generation.** The verified tree is lowered into bytecode and
written to `.class` files. Not machine code — bytecode. Which raises the
question I can now actually investigate…

## 6. Looking at bytecode with my own eyes

The JDK ships a disassembler. Let me point it at something real:

```java
public class Sum {
    public static void main(String[] args) {
        int a = 3;
        int b = 4;
        int c = a + b;
        System.out.println(c);
    }
}
```

```
javac Sum.java
javap -c Sum
```

Among the output:

```
   iconst_3        // push the constant 3
   istore_1        // store it into local variable slot 1  (a)
   iconst_4
   istore_2        //                                      (b)
   iload_1         // push a
   iload_2         // push b
   iadd            // pop both, add, push the sum
   istore_3        //                                      (c)
```

Fascinating — the imaginary CPU is a **stack machine**. No registers: values
get pushed onto a little stack, operations pop their operands and push their
result. `a + b` becomes push-push-add. It reads like reverse Polish notation,
and it's this simple *on purpose*: a dead-simple instruction set is easy to
implement correctly on every real platform, easy to verify for safety, and
easy to translate further (section 8). The `i` prefix on everything means
*integer* — foreshadowing Part 2: types are so central that they're baked into
the instruction names themselves.

I no longer have to take "compiles to bytecode" on faith. I've read some.

## 7. The JVM at runtime: loading, verifying, and memory

I type `java Sum`. Walk through what happens, in order.

**Loading.** The JVM finds `Sum.class` and loads it — and here's a subtlety
worth knowing: classes load **lazily**, on first use, not all upfront. A big
program doesn't pay for the parts it never touches.

**Verification.** Before executing a single instruction, the JVM *audits* the
bytecode: does every jump land on a real instruction? does the stack stay
consistent? does anything forge access it shouldn't have? My first reaction —
"why? `javac` already checked everything!" — dissolves after two seconds of
thought: *the JVM has no idea this bytecode came from `javac`.* Bytecode can
arrive from the network, from another language's compiler, from an attacker's
hex editor. The JVM trusts no one. Java was born in the era of code downloaded
into browsers; paranoia was a design requirement, and it stuck.

**Memory.** The JVM organizes memory into two regions I'll be picturing
constantly from Part 2 onward, so let me fix the image now:

- **The stack** (one per thread): every method call pushes a *frame* holding
  that call's local variables and its little operand stack; when the method
  returns, the frame pops and everything in it evaporates. Cheap, automatic,
  perfectly ordered. (Those `istore_1` slots above live here.)
- **The heap**: the open field where *objects* live — anything created with
  `new`. Objects on the heap outlive the method that made them, which is the
  point, but it means someone must eventually clean them up. In C, that
  someone is the programmer, and forgetting is the infamous *memory leak*. In
  Java, a background service — the **garbage collector** — watches the heap
  and reclaims any object nothing points to anymore. I trade a sliver of
  performance for the elimination of an entire genus of catastrophic bugs.
  Given what I now know about Java's design temperament (see: verification),
  this trade is exactly in character.

**Execution.** The JVM starts interpreting the bytecode, instruction by
instruction. Which brings back the unresolved problem from section 2 —
interpretation is *slow*. Wasn't that half the reason we rejected Option B?

## 8. The JIT: the trick that makes the hybrid actually fast

Here's how the JVM squares the circle, and it's my favorite idea in this whole
part. The JVM doesn't *only* interpret. While interpreting, it **profiles** —
it counts. And program execution time is wildly lopsided: nearly all time is
spent in a few hot loops and hot methods, while most code runs once or twice.

So: when the JVM notices a method getting hammered, its **Just-In-Time (JIT)
compiler** translates *that method's bytecode into genuine native machine code
for the actual CPU it's standing on* — and from then on, calls jump straight
to the native version. Full hardware speed, for exactly the code that matters.

Savor what just happened: we compiled *on the user's machine, at runtime*,
which means portability was never sacrificed — and the JIT can even optimize
using facts only observable at runtime ("this branch is never taken *in this
run*", "this method only ever receives one type here"), optimizations a
compile-everything-upfront compiler can't safely make because it can't see the
future. The consequence is observable: Java programs start a touch slowly
(interpreting, profiling, warming up) and then get *fast*. People call it
"warm-up," and now I know it's the sound of the JIT doing its job.

So the full picture, end to end:

```
Me → HelloWorld.java → [javac: lex, parse, TYPE-CHECK, emit] → HelloWorld.class
      → [JVM: load lazily → verify → interpret + profile → JIT the hot parts]
      → my CPU, running native code → "Hello, world"
```

Compile-time checks catch my errors early (Option A's virtue). Bytecode + a
JVM per platform gives portability (Option B's virtue). The JIT claws back the
speed. The hybrid keeps both advantages and pays neither full price. That's
not a pile of facts to memorize — it's one design decision unfolding.

## 9. Now, and only now, the IDE

With the machinery understood, I'm allowed the power tools. An **IDE**
(Integrated Development Environment — IntelliJ IDEA, Eclipse, VS Code + Java
extensions) is not a different way of doing Java. It is *the same `javac`, the
same JVM*, wired into a tight feedback loop:

- The **red squiggle** under bad code as I type? That's the compiler's
  analysis running continuously against my keystrokes. The IDE didn't replace
  compilation; it made compilation *instant and ambient*. I'm getting stage-3
  semantic analysis in real time.
- The **Run button**? It shells out to the same two-step dance I did by hand
  — compile, then launch a JVM — just with the paths and flags filled in.
- **Autocomplete** falls out of type-checking, and this is worth a beat of
  reflection: because the compiler *proves* the type of every expression, the
  IDE knows, when I type `someString.`, the exact and complete list of methods
  that could legally follow. Scratch's palette showed me every block that
  exists; the IDE's palette shows me every block that *fits right here*. The
  discipline of static types pays me back as discoverability.
- The **debugger** rides the JVM's built-in inspection hooks — pause a running
  program, peer into stack frames (the very frames from section 7), step one
  statement at a time.

Because I did the command line first, none of this is magic — every feature is
traceable to a mechanism I've already touched. The IDE automates what I
understand; it doesn't replace understanding. That ordering — mechanism first,
convenience second — is how I intend to learn everything else in this
language.

**Next problem:** the bytecode kept whispering about types — `iadd`, `iload`,
`i` for int. Time to find out what the type system actually is, from the bits
upward. → [Part 2](02-data-arrays-strings-vector.md)
