"""``python -m pramaanx.cli``.

A package cannot be executed directly the way a module can, so the entry point
that ``cli.py`` provided by simply being a module has to be declared explicitly
now that the CLI is a package. Scripts and the demo invoke the CLI this way, so
this file is load-bearing rather than a convenience.
"""

from __future__ import annotations

from pramaanx.cli import main

main()
