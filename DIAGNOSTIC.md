# Java Diagnostic — 15 questions that expose hidden gaps

Rules: no IDE, no compiler, no searching. Write your answer down **before** scrolling
to the answers — a guess that happens to be right doesn't count as knowing.
Every question here targets a specific misconception that real Java programmers
carry around for years.

---

### Q1
```java
System.out.println(7 / 2);
System.out.println('a' + 1);
```
What prints (two lines)?

### Q2
```java
String a = new String("hi");
String b = new String("hi");
System.out.println(a == b);
System.out.println(a.equals(b));
```

### Q3
```java
Integer x = 127, y = 127;
Integer p = 128, q = 128;
System.out.println(x == y);
System.out.println(p == q);
```

### Q4
```java
static void change(int n)      { n = 99; }
static void grow(List<Integer> l) { l.add(1); }
static void replace(List<Integer> l) { l = new ArrayList<>(); l.add(2); }

int n = 5;                 change(n);
List<Integer> list = new ArrayList<>();
grow(list);  replace(list);
System.out.println(n + " " + list);
```

### Q5
```java
String s = "hello";
s.toUpperCase();
System.out.println(s);
```

### Q6
```java
class Animal { String name = "animal"; String who() { return "animal"; } }
class Dog extends Animal { String name = "dog"; String who() { return "dog"; } }

Animal a = new Dog();
System.out.println(a.name + " " + a.who());
```
(Careful: the field and the method behave differently.)

### Q7
```java
static int f() {
    try { return 1; }
    finally { System.out.println("finally"); }
}
```
Does "finally" print when `f()` is called? What does `f()` return?

### Q8
```java
Integer count = null;
int c = count;
```
What happens on the second line?

### Q9
```java
List<Integer> nums = new ArrayList<>(List.of(10, 20, 30));
nums.remove(1);
System.out.println(nums);
```
Does this remove the *value* `1` or the *index* `1`? What prints?

### Q10
```java
System.out.println(0.1 + 0.2 == 0.3);
```

### Q11
```java
List<String> items = new ArrayList<>(List.of("a", "b", "c"));
for (String s : items) {
    if (s.equals("b")) items.remove(s);
}
```
What happens?

### Q12
```java
int x = 2;
switch (x) {
    case 1: System.out.println("one");
    case 2: System.out.println("two");
    case 3: System.out.println("three");
}
```
What prints?

### Q13
```java
List<String> a = new ArrayList<>();
List<Integer> b = new ArrayList<>();
System.out.println(a.getClass() == b.getClass());
```

### Q14
`equals()` is overridden on a class, but `hashCode()` is not. You put an object
in a `HashSet`, then create an *equal* object and call `contains()` with it.
What can happen, and why?

### Q15
```java
interface Shape {}
record Point(int x, int y) implements Shape {}
```
Name two things `record` gives `Point` automatically that a normal class wouldn't.

---
---

## Answers

**A1:** `3` and `98`. Integer division truncates (`7/2` is `3`, not `3.5`). `'a' + 1`
promotes the `char` to `int` (97 + 1). *Gap → Level 1: primitives.*

**A2:** `false` then `true`. `==` compares references; `new` always creates a new
object. `.equals()` compares contents. *Gap → Level 2: == vs equals.*

**A3:** `true` then `false`. Java caches `Integer` objects from -128 to 127, so 127
gives the same cached object and 128 doesn't. Never use `==` on boxed types.
*Gap → Level 5: Integer caching.*

**A4:** `5 [1]`. Java is always pass-by-value. `change` got a copy of the int.
`grow` got a copy of the reference — but it points at the same list, so `add`
is visible. `replace` reassigned its *copy* of the reference, so the caller
never sees the new list. If you said Java is "pass-by-reference for objects,"
this is your most important gap. *Gap → Level 5: pass-by-value.*

**A5:** `hello`. Strings are immutable — `toUpperCase()` returns a *new* string,
which was thrown away. You needed `s = s.toUpperCase();`. *Gap → Level 3: String immutability.*

**A6:** `animal dog`. Methods are dispatched by the object's *runtime* type
(polymorphism), but fields are resolved by the *declared* type — fields are
never polymorphic. *Gap → Level 2: polymorphism.*

**A7:** "finally" prints, and `f()` still returns `1`. `finally` runs even when the
`try` block returns — the return value is computed first, then `finally` runs,
then the value is delivered. *Gap → Level 3: exceptions.*

**A8:** `NullPointerException`. Unboxing `null` calls `count.intValue()` under the
hood. This is one of the most common NPEs in real code. *Gap → Level 3: autoboxing.*

**A9:** Index. `remove(int)` beats `remove(Object)` in overload resolution for an
`int` argument, so index 1 (`20`) is removed: `[10, 30]`. To remove the value,
you'd need `nums.remove(Integer.valueOf(1))`. *Gap → Level 3: collections + overloading.*

**A10:** `false`. Binary floating point can't represent 0.1 or 0.2 exactly; the sum
is 0.30000000000000004. Use `BigDecimal` for money. *Gap → Level 5: floating point.*

**A11:** Throws `ConcurrentModificationException` — you can't structurally modify a
list while for-each iterating it. Use `items.removeIf(s -> s.equals("b"))` or an
explicit `Iterator` with `it.remove()`. *Gap → Level 3: collections.*

**A12:** `two` and `three`. Classic switch falls through without `break`. (Modern
arrow syntax `case 2 -> ...` doesn't fall through — one reason to prefer it.)
*Gap → Level 1: control flow.*

**A13:** `true`. Generics are erased at compile time — at runtime both are just
`ArrayList`. This is why you can't do `new T[]` or `instanceof List<String>`.
*Gap → Level 5: type erasure.*

**A14:** `contains()` can return `false` even though an equal object is in the set.
`HashSet` finds the bucket using `hashCode()` first and only then calls `equals()`;
with the default `hashCode()`, equal objects land in different buckets. Rule:
override both or neither. *Gap → Level 2: equals/hashCode contract.*

**A15:** Any two of: a constructor taking `x` and `y`; accessors `x()` and `y()`;
sensible `equals()` and `hashCode()`; a readable `toString()`; final fields
(shallow immutability). *Gap → Level 4: records.*

---

## Score → where to start

| Correct | Verdict | Start at |
|---|---|---|
| 0–4 | Fundamentals aren't solid yet — that's fine, now you know | Skill map Level 1–2 |
| 5–8 | You can write Java but the language still surprises you | Level 2–3, and reread A4 until it hurts |
| 9–12 | Solid core; your gaps are modern features and internals | Level 4–5 |
| 13–15 | Your gaps are ecosystem/depth, not the language | Level 5–6, go build something real |

Whatever you missed, find the matching line in `JAVA-SKILL-MAP.md` and change its
mark to `[?]` — the quiz just proved that mark was wrong.
