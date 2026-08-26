# Python versions

## What is supported

`requires-python = ">=3.13,<3.15"` — CPython 3.13 and 3.14.

## What CI tests

Both of them. `.github/workflows/ci.yaml` runs the full suite on 3.13 and 3.14,
and `tests/contracts/test_packaging.py` fails if the matrix and the metadata
ever drift apart — in either direction. A supported version that CI never runs
is an untested claim; a CI version the metadata forbids is a contradiction.

## Why the bound has an upper end at all

Not caution about 3.15 specifically. An unbounded `>=3.13` lets `uv sync` select
the newest interpreter installed on the machine, which is not necessarily one
anybody has run this code on. That is not hypothetical: it is how an earlier
fresh-clone check ended up installing against a 3.14 release candidate and
failing before the first test.

Raising the bound is a two-line change once a version has actually been tested —
see below.

## The 3.14 story, corrected

An earlier revision of this file claimed that no published pydantic worked on
Python 3.14 and pinned the project to `<3.14`. **That was wrong**, and the error
is worth recording because of how it happened.

The failure observed was real:

```
TypeError: _eval_type() got an unexpected keyword argument 'prefer_fwd_module'
Unable to evaluate type annotation 'Path'
```

But it was observed on **CPython 3.14.0rc2**, which was the only 3.14 build the
development machine's `uv` could fetch — its bundled download manifest predated
the stable release. A release candidate is not the release, and the conclusion
drawn from it ("3.14 is unsupported") did not follow from the evidence
("this rc build fails"). The right response to *cannot test X* is to say so, not
to record an unsupported generalisation as a fact.

Verified since, on the same dependency set:

| | |
| --- | --- |
| CPython | 3.14.7 |
| pydantic | 2.13.4 |
| pydantic-core | 2.46.4 |
| Result | imports cleanly, full suite passes |

Python 3.14 has been stable since October 2025. The relevant pydantic issue
([#12544](https://github.com/pydantic/pydantic/issues/12544)) was reported
against a 3.14 release candidate and does not describe the stable series.

If a newer 3.14 build is genuinely unobtainable on some machine, the fix is
`uv self update` — an older `uv` will not offer a Python it does not know about,
and that absence is not evidence of anything.

## System interpreters and managed interpreters differ

CI installs Python with `uv python install`, which fetches a **standalone**
build. A standalone CPython has no compiled-in CA file: `ssl.get_default_verify_paths().cafile`
is `None`, and TLS trust comes from `certifi` or the environment instead. A
distro interpreter (`/usr/bin/python3.13`) usually does have one.

That difference is invisible until a test reads the host's trust configuration.
One did, and it passed locally on a system interpreter while failing on both CI
jobs — see `tests/unit/test_http_client.py`, which now sources its fixture
bundle from `certifi` and asserts the bundle actually contains a certificate.

When reproducing a CI failure locally, match the interpreter's provenance, not
just its version:

```bash
uv python install 3.13                       # a managed, standalone build
uv sync --frozen --extra dev --managed-python --python 3.13
env -u SSL_CERT_FILE -u SSL_CERT_DIR CI=true GITHUB_ACTIONS=true uv run pytest
```

`uv sync --python 3.13` alone may select a system interpreter and hide exactly
this class of difference.

## Adding a version

1. `uv python install 3.<n>`
2. `uv run --python 3.<n> python -c "import pramaanx.config"`
3. Raise the `requires-python` upper bound in `pyproject.toml`.
4. Add `"3.<n>"` to `matrix.python-version` in the CI workflow.
5. `uv lock` and run the full suite on it.
6. Update this file with what was actually tested — the version, the dependency
   versions, and the result.

Steps 3 and 4 must happen together; the packaging contract test enforces it.
