"""poster2event — one command: poster image in, OpenOrbit event out.

    poster2event poster.jpg                 # extract + fill the form (no submit)
    poster2event poster.jpg --dry-run       # just print the extracted JSON
    poster2event poster.jpg --submit        # fill AND click submit
    poster2event poster.jpg --show          # run the browser visibly
"""

from __future__ import annotations

import argparse
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; env vars still work
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poster2event", description=__doc__)
    parser.add_argument("image", help="Path to the poster image (jpg/png/webp)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only read the poster and print the extracted JSON; don't touch the browser.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Actually submit the form (default: fill but stop before submitting).",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Run the browser visibly instead of headless.",
    )
    args = parser.parse_args(argv)

    from .extract import extract_event

    event = extract_event(args.image)
    print(event.model_dump_json(indent=2))

    if args.dry_run:
        return 0

    from .fill import fill_event

    fill_event(event, submit=args.submit, headless=not args.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
