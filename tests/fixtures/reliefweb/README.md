# ReliefWeb fixtures

Hand-written, synthetic records shaped like ReliefWeb API responses. They carry
no real ReliefWeb content: organisation names, titles and bodies are invented,
and the ids are outside any real range.

This is deliberate. ReliefWeb's terms require attribution and do not permit
wholesale redistribution, and individual documents carry their contributing
organisation's own terms. A committed corpus of real records would be a licence
problem in a public repository and would also rot silently as the service
changes.

What these fixtures can and cannot prove:

- **Can**: that the connector paginates, orders, deduplicates, applies the
  availability rule, and refuses shapes it does not understand.
- **Cannot**: that the real API returns this shape. Only
  `tests/network/test_reliefweb_live.py` can establish that, and it is opt-in.
  See `API_CONTRACT` in `src/pramaanx/ingest/connectors/reliefweb.py`.
