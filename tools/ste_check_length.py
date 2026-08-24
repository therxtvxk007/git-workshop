import re, sys
path = sys.argv[1]
lines = open(path, encoding="utf-8").read().split("\n")

# Rebuild logical text units: merge wrapped continuation lines within a bullet/paragraph
units, buf = [], []
for line in lines:
    st = line.strip()
    if not st or st.startswith("#") or st.startswith("|") or st.startswith("---") \
       or st.startswith("Title:") or st.startswith("Subtitle:") or st.startswith("Visual:") \
       or line.startswith("    ") or st.endswith(":"):
        if buf: units.append(" ".join(buf)); buf = []
        continue
    if st.startswith("-") or re.match(r"^\d+\.", st):
        if buf: units.append(" ".join(buf)); buf = []
        buf = [re.sub(r"^[-\d.]+\s*", "", st)]
    else:
        buf.append(st)
if buf: units.append(" ".join(buf))

print("=== sentence length (limit 25 words) ===")
worst, over = 0, 0
for u in units:
    for sent in re.split(r"(?<=[.?!])\s+", u):
        sent = sent.strip()
        if not sent: continue
        n = len(sent.split())
        worst = max(worst, n)
        if n > 25:
            over += 1
            print(f"  [{n}] {sent}")
print(f"  sentences over limit: {over}; longest sentence: {worst} words")

print("\n=== sentences over 20 words (instruction limit) ===")
for u in units:
    for sent in re.split(r"(?<=[.?!])\s+", u):
        n = len(sent.split())
        if 20 < n <= 25:
            print(f"  [{n}] {sent.strip()}")

print("\n=== stats ===")
words = sum(len(u.split()) for u in units)
sents = sum(len([x for x in re.split(r'(?<=[.?!])\s+', u) if x.strip()]) for u in units)
print(f"  body text units: {len(units)}; sentences: {sents}; words: {words}")
print(f"  average sentence length: {words/max(sents,1):.1f} words")
