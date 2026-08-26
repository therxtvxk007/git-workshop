# ReliefWeb fixtures

Hand-written, synthetic records shaped like ReliefWeb API **v2** responses. They
carry no real ReliefWeb content: organisation names, titles and bodies are
invented, and the ids are outside any real range. Ids are integers, as the
official fields table specifies for a report id.

This is deliberate. ReliefWeb's terms restrict use to personal/non-commercial
purposes and prohibit resale and redistribution unless specific permission or a
particular document's own terms provide otherwise, and every document carries
its contributing organisation's attribution requirement. A committed corpus of
real records would be a licence problem in a public repository and would also
rot silently as the service changes.

What these fixtures can and cannot prove:

- **Can**: that the connector paginates, orders, deduplicates, applies the
  availability rule, preserves each raw instant separately, and refuses shapes
  it does not understand.
- **Cannot**: that the real API returns this shape. A fixture proves the
  connector handles something someone wrote down; it is not evidence about the
  wire format, and it does not substitute for a live request. Only
  `tests/network/test_reliefweb_live.py` can establish that, and it is opt-in.

The contract itself was read from the official documentation on 2026-08-26 —
see `API_CONTRACT` in `src/pramaanx/ingest/connectors/reliefweb.py`, which keeps
`official_docs_verified`, `fixture_tested` and `live_api_verified` as three
separate statuses. The third is still false.
