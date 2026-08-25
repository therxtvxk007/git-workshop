# Python versions

## What is supported

`requires-python = ">=3.13"`.

## What CI actually tests

**Python 3.13, and only 3.13.** The matrix in `.github/workflows/ci.yaml` has
one entry. Nothing else is exercised, so nothing else is claimed to work.

## Why 3.14 is not in the matrix

The package does not import on 3.14 with the current `uv.lock`. It is a
dependency problem, not a problem in this code:

```
TypeError: _eval_type() got an unexpected keyword argument 'prefer_fwd_module'
Unable to evaluate type annotation 'Path'.
```

Pydantic's `_typing_extra` calls `typing._eval_type()` with a keyword that
CPython 3.14 no longer accepts, and the failure occurs at class-construction
time, so it takes down the first `import pramaanx.config`.

The check was run against **CPython 3.14.0rc2**, which is the 3.14 build
available from the Python mirror on the machine used for development. That is a
release candidate, not the 3.14 release, so this is evidence about that specific
build and not a general claim about 3.14. A newer pydantic may well have fixed
it already.

## Adding 3.14 (or later) to the matrix

1. `uv lock --upgrade-package pydantic`
2. `uv run --python 3.14 python -c "import pramaanx.config"`
3. If it imports, add `"3.14"` to `matrix.python-version` in the CI workflow and
   run the full suite on it.
4. Update this file with what was actually tested.

Do not add a version to the matrix before step 2 passes locally. A matrix entry
is a claim, and an untested claim in CI is worse than no entry: it turns red on
a schedule nobody chose and gets muted.
