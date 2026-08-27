"""``python -m pramaanx.cli``.

A package cannot be executed directly the way a module can, so the entry point
that ``cli.py`` provided by simply being a module has to be declared explicitly
now that the CLI is a package. Scripts and the demo invoke the CLI this way, so
this file is load-bearing rather than a convenience.
"""

from __future__ import annotations

from pramaanx.cli import main

# Guarded, even though this file exists to be executed: when run via -m the
# guard passes, but anything that merely *imports* the package tree -- a
# package walker, a docs build, an import check -- would otherwise launch the
# CLI as a side effect and hang or exit on a caller that only wanted imports.
if __name__ == "__main__":
    main()
