# Recorded news fixtures

Synthetic content in real envelope shapes. Nothing here is a copy of any
publisher's article: the wrappers (RSS 2.0, Atom, a publisher JSON envelope,
a licensed-archive JSONL) reproduce the *structure* WP1 has to parse, and the
text inside them was written for these tests.

That distinction is the point. A fixture containing real licensed article text
would put the exact material the licence layer exists to protect into a public
repository, which would make the tests a licence breach that proves licence
compliance.

`archive.jsonl` carries two revisions of one article -- the same canonical URL
at `revision_index` 0 and 1 -- because the revision guarantee cannot be tested
without one.
