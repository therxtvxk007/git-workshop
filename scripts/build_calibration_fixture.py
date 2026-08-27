"""Regenerate the calibration fixture and check it against its pinned manifest.

Default behaviour is to *verify*: regenerate the sample and fail if it does not
reproduce ``research/fixtures/calibration_v1.json``. That is the useful mode,
because a fixture that silently moves takes every number fitted against it with
it.

``--write`` re-pins the manifest instead. Use it when a deliberate change to
the generator or the configuration is meant to move the fixture, and say so in
the commit message.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - entry-point wiring
    sys.path.insert(0, str(REPO_ROOT / "src"))

from pramaanx.fixtures import (  # noqa: E402
    FixtureDriftError,
    FixtureManifest,
    build_manifest,
    load_calibration_sample,
    verify_manifest,
)

DEFAULT_EXPERIMENT = REPO_ROOT / "configs" / "experiments" / "e2e_v1.yaml"
DEFAULT_MANIFEST = REPO_ROOT / "research" / "fixtures" / "calibration_v1.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--write",
        action="store_true",
        help="re-pin the manifest instead of verifying against it",
    )
    args = parser.parse_args(argv)

    sample = load_calibration_sample(args.experiment)
    summary = (
        f"{len(sample)} rows, {sample.positives} positives "
        f"(base rate {sample.base_rate:.4f}) across {len(sample.folds)} folds"
    )

    if args.write:
        build_manifest(sample).write(args.manifest)
        print(f"pinned {args.manifest.relative_to(REPO_ROOT)}: {summary}")
        return 0

    if not args.manifest.exists():
        print(
            f"no pinned manifest at {args.manifest}. Create one with --write.",
            file=sys.stderr,
        )
        return 2

    try:
        verify_manifest(sample, FixtureManifest.read(args.manifest))
    except FixtureDriftError as error:
        print(f"fixture drift: {error}", file=sys.stderr)
        return 1

    print(f"fixture reproduces its manifest: {summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
