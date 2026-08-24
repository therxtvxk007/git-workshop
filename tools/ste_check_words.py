import re, sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()

ALLOWED_ING = {
    "Bandwidth",  # not -ing, guard
}
# -ing words permitted because they are part of a declared Technical Name
TECH_ING = {"closing"}

lines = text.split("\n")

print("=== 1. -ing words ===")
bad_ing = {}
for i, line in enumerate(lines, 1):
    if line.strip().startswith("|") or line.strip().startswith("    "):
        pass
    for w in re.findall(r"\b[A-Za-z][A-Za-z-]+ing\b", line):
        lw = w.lower()
        if lw in TECH_ING:
            continue
        if lw in {"thing", "string", "during", "spring", "bring", "king", "ring", "sing", "wing", "nothing", "something", "anything", "everything"}:
            continue
        bad_ing.setdefault(lw, []).append(i)
for w, ls in sorted(bad_ing.items()):
    print(f"  {w}: lines {ls}")
if not bad_ing:
    print("  none")

print("\n=== 2. sentence length (>25 words) ===")
prose = []
for line in lines:
    s = line.strip()
    if not s or s.startswith("|") or s.startswith("#") or s.startswith("---") or s.startswith("    "):
        continue
    prose.append(s.lstrip("-0123456789. ").strip())
blob = " ".join(prose)
for sent in re.split(r"(?<=[.?!])\s+", blob):
    n = len(sent.split())
    if n > 25:
        print(f"  [{n}] {sent}")

print("\n=== 3. possible passive voice ===")
pat = re.compile(r"\b(is|are|was|were|be|been|being)\s+(\w+ed|made|given|sold|held|shown|taken|seen|done|kept|put|set|built)\b", re.I)
found = False
for i, line in enumerate(lines, 1):
    for m in pat.finditer(line):
        print(f"  line {i}: ...{m.group(0)}...")
        found = True
if not found:
    print("  none")

print("\n=== 4. banned / non-approved words ===")
BANNED = ["utilize", "in order to", "prior to", "due to", "via ", "etc", "shall",
          "should", "would", "may ", "might", "leverage the", "robust ",
          "have been", "has been", "had been", "will be able", "furthermore",
          "moreover", "additionally", "whilst", "amongst", "thereby", "hereby",
          "as well as", "regarding", "concerning", "ensure", "leverage,"]
for b in BANNED:
    for i, line in enumerate(lines, 1):
        if b in line.lower():
            print(f"  '{b.strip()}' line {i}: {line.strip()[:80]}")

print("\n=== 5. paragraphs over 6 sentences ===")
for block in re.split(r"\n\s*\n", text):
    b = block.strip()
    if not b or b.startswith("|") or b.startswith("#") or b.startswith("-") or b.startswith("    "):
        continue
    n = len([x for x in re.split(r"(?<=[.?!])\s+", b) if x.strip()])
    if n > 6:
        print(f"  [{n} sentences] {b[:90]}...")
