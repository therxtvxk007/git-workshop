# Java Skill Map — find out what you don't know

How to use this: go top to bottom and mark each item honestly.

- `[x]` — I could do this right now, without looking anything up
- `[?]` — I've seen it / kind of get it, but couldn't do it cold
- `[ ]` — no idea

**The `[?]` marks are your real gap list.** Things you've never heard of are easy to
find; things you *think* you know are what bite you. Everything at one level builds
on the level below it, so work upward — don't jump to streams if `[?]`s remain in OOP.

---

## Level 1 — Syntax & fundamentals

You know this level if you can write a small program from scratch without a tutorial open.

- [ ] Primitives (`int`, `double`, `boolean`, `char`) vs reference types — and why `int` division of `7 / 2` gives `3`
- [ ] Declaring variables, `final`, basic operators, string concatenation
- [ ] `if` / `else`, `switch` (including fall-through when you forget `break`)
- [ ] Loops: `for`, `while`, `do-while`, and the for-each loop
- [ ] Methods: parameters, return types, overloading
- [ ] Arrays: creating, indexing, `.length`, iterating, multi-dimensional
- [ ] `Scanner` or `args[]` for basic input; `System.out.printf` formatting
- [ ] Reading a compiler error and actually understanding what it's complaining about

## Level 2 — Object-oriented programming

The heart of Java. If this level is shaky, everything above it will feel like magic.

- [ ] Classes vs objects; constructors; `this`
- [ ] `static` vs instance — fields *and* methods, and when each is appropriate
- [ ] Access modifiers: `private`, `public`, `protected`, package-private (the default)
- [ ] Encapsulation: why fields are private with getters/setters
- [ ] Inheritance: `extends`, `super`, constructor chaining
- [ ] Method overriding vs overloading — they are completely different things
- [ ] Polymorphism: `Animal a = new Dog();` — which method runs, and why
- [ ] Abstract classes vs interfaces — and when to pick which
- [ ] `Object` methods: `equals`, `hashCode`, `toString` — and the equals/hashCode contract
- [ ] `==` vs `.equals()` — for objects, for Strings, for boxed types like `Integer`
- [ ] Enums (they're full classes in Java, not just constants)

## Level 3 — Core APIs you use every day

- [ ] `String` immutability — why `s.toUpperCase()` alone does nothing
- [ ] `StringBuilder` and when concatenation in a loop is a problem
- [ ] Collections: `ArrayList` vs `LinkedList`, `HashMap`, `HashSet`, `TreeMap` — and *when* each one
- [ ] Generics: `List<String>`, writing a generic method, bounded types (`<T extends Comparable<T>>`)
- [ ] Autoboxing/unboxing — and the `NullPointerException` hiding in `int x = someInteger;`
- [ ] Iterating a collection while modifying it (`ConcurrentModificationException`) and how to do it right
- [ ] Exceptions: checked vs unchecked, `try`/`catch`/`finally`, try-with-resources, writing your own
- [ ] `Comparable` vs `Comparator`; sorting collections
- [ ] `Optional` — what it's for and what it's *not* for (fields, parameters)
- [ ] Basic file I/O with `java.nio.file` (`Files.readAllLines`, `Files.write`)
- [ ] `LocalDate` / `LocalDateTime` (the modern `java.time`, not `Date`/`Calendar`)

## Level 4 — Modern Java (8 through 21)

Where most self-taught and university-taught Java is out of date.

- [ ] Lambdas and functional interfaces (`Function`, `Predicate`, `Consumer`, `Supplier`)
- [ ] Method references (`String::length`, `System.out::println`)
- [ ] Streams: `filter` / `map` / `collect`, `reduce`, `groupingBy` — and when a plain loop is clearer
- [ ] `var` local variable inference — and its limits
- [ ] Records (`record Point(int x, int y)`) — what you get for free
- [ ] Sealed classes/interfaces and pattern matching for `switch`
- [ ] Text blocks (`"""`)
- [ ] `instanceof` pattern matching (`if (o instanceof String s)`)

## Level 5 — Under the hood

Separates "writes Java" from "understands Java." Interview territory.

- [ ] Java is **always** pass-by-value — including for object references (this trips up almost everyone)
- [ ] Stack vs heap; what a reference actually is
- [ ] String pool and `Integer` caching (-128 to 127) — why `==` "works" sometimes and then betrays you
- [ ] Garbage collection: the concept, generations, why you (almost) never call `System.gc()`
- [ ] JVM vs JRE vs JDK; what bytecode is; what the classpath is
- [ ] Type erasure: why `List<String>` and `List<Integer>` are the same class at runtime
- [ ] Threads: `Runnable`, `Thread`, `ExecutorService`
- [ ] `synchronized`, race conditions, `volatile`, `AtomicInteger` — at least the *problems* they solve
- [ ] Virtual threads (Java 21) — what changed and why it matters
- [ ] Floating point: why `0.1 + 0.2 != 0.3` and when to use `BigDecimal`

## Level 6 — The ecosystem (being a working Java dev)

- [ ] Maven or Gradle: adding a dependency, running a build, understanding `pom.xml` / `build.gradle`
- [ ] JUnit 5: writing tests, assertions, `@BeforeEach`, parameterized tests
- [ ] Mockito or another mocking library — the idea of test doubles
- [ ] Using a debugger: breakpoints, stepping, inspecting state (not `System.out.println` everywhere)
- [ ] Reading a stack trace bottom-to-top and finding *your* frame in it
- [ ] Logging (SLF4J/Logback) instead of `System.out`
- [ ] Packages, `import`, and (roughly) what the module system is
- [ ] Javadoc: reading it fluently, writing it for your own code
- [ ] One framework in some depth — for most people that's Spring Boot

---

## Scoring yourself

| Where your `[ ]`/`[?]` marks start | You are | Do this next |
|---|---|---|
| Level 1–2 | Beginner | Write small programs daily; don't touch frameworks yet |
| Level 3 | Advanced beginner | Build a real CLI project; collections + exceptions until automatic |
| Level 4 | Intermediate | Modernize: rewrite an old project using streams/records |
| Level 5 | Solid | Read about the JVM; write something concurrent on purpose |
| Level 6 | Job-ready gaps only | Build and test a Spring Boot service end to end |

Now take `DIAGNOSTIC.md` — it tests whether your `[x]` marks are telling the truth.
