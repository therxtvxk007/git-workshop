"""Command line interface: ``hwm``."""

from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
import webbrowser
from dataclasses import fields
from pathlib import Path

from . import demo_font
from .font import Font
from .gcode import OutOfBounds, generate
from .layout import PageSetup, Style, paginate
from .machine import MachineProfile
from .optimize import optimize
from .render_svg import render

PAPER = {
    "a4": (210.0, 297.0),
    "a5": (148.0, 210.0),
    "a3": (297.0, 420.0),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
}

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# shared argument groups
# --------------------------------------------------------------------------

def _add_text_source(p: argparse.ArgumentParser) -> None:
    p.add_argument("text", nargs="?", help="text to write (omit to read stdin)")
    p.add_argument("-i", "--input", type=Path, help="read text from a file instead")


def _add_font_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-f", "--font", type=Path,
        help="your handwriting font JSON (default: the built-in reference font)",
    )


def _add_style_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("style")
    g.add_argument("--size", type=float, default=6.0, help="writing size in mm, ascender to descender (default 6)")
    g.add_argument("--line-spacing", type=float, default=1.9, help="line pitch as a multiple of size (default 1.9)")
    g.add_argument("--word-spacing", type=float, default=1.0, help="word gap multiplier (default 1)")
    g.add_argument("--letter-spacing", type=float, default=0.0, help="extra mm between letters")
    g.add_argument("--slant", type=float, default=0.0, help="degrees of rightward lean")
    g.add_argument("--align", choices=["left", "center", "right"], default="left")
    g.add_argument("--join", action="store_true", help="draw joining strokes within words")
    g.add_argument("--seed", type=int, default=1, help="randomness seed; same seed, same page")
    g.add_argument(
        "--neatness", type=float, default=1.0, metavar="F",
        help="scale all irregularity: 0 is mechanical, 1 is natural, 2 is scruffy",
    )
    g.add_argument("--tremor", type=float, default=None, help="override line wobble in mm")

    pg = p.add_argument_group("page")
    pg.add_argument("--paper", choices=sorted(PAPER), default="a4")
    pg.add_argument("--landscape", action="store_true")
    pg.add_argument("--margin", type=float, default=20.0, help="margin in mm on all sides (default 20)")
    pg.add_argument("--margin-top", type=float, default=None)
    pg.add_argument("--margin-bottom", type=float, default=None)
    pg.add_argument("--margin-left", type=float, default=None)
    pg.add_argument("--margin-right", type=float, default=None)


def _load_font(args: argparse.Namespace) -> Font:
    if getattr(args, "font", None):
        font = Font.load(args.font)
        if not font.glyphs:
            raise SystemExit(f"error: {args.font} contains no glyphs")
        return font
    return demo_font.build()


def _read_text(args: argparse.Namespace) -> str:
    if getattr(args, "input", None):
        return args.input.read_text(encoding="utf-8")
    if args.text:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("error: no text given (pass text, --input FILE, or pipe stdin)")


def _build_style(args: argparse.Namespace) -> Style:
    n = max(0.0, args.neatness)
    style = Style(
        size=args.size,
        line_spacing=args.line_spacing,
        word_spacing=args.word_spacing,
        letter_spacing=args.letter_spacing,
        slant=args.slant,
        align=args.align,
        join_letters=args.join,
    )
    style.size_jitter *= n
    style.rotation_jitter *= n
    style.offset_jitter *= n
    style.advance_jitter *= n
    style.slant_jitter *= n
    style.baseline_drift *= n
    style.tremor = args.tremor if args.tremor is not None else style.tremor * n
    return style


def _build_page(args: argparse.Namespace) -> PageSetup:
    w, h = PAPER[args.paper]
    if args.landscape:
        w, h = h, w
    m = args.margin
    return PageSetup(
        width=w,
        height=h,
        margin_top=args.margin_top if args.margin_top is not None else m,
        margin_bottom=args.margin_bottom if args.margin_bottom is not None else m,
        margin_left=args.margin_left if args.margin_left is not None else m,
        margin_right=args.margin_right if args.margin_right is not None else m,
    )


def _warn_missing(pages) -> None:
    missing = sorted({c for p in pages for c in p.missing})
    if missing:
        shown = " ".join(repr(c) for c in missing)
        print(
            f"warning: {len(missing)} character(s) are not in this font and were "
            f"left blank: {shown}",
            file=sys.stderr,
        )


def _numbered(path: Path, index: int, total: int) -> Path:
    if total == 1:
        return path
    return path.with_name(f"{path.stem}-{index + 1:02d}{path.suffix}")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def _capture_dir() -> Path:
    """Find capture/index.html.

    It lives at the repo root rather than inside the package because it is a
    self-contained page: opening it straight from disk works too, with no
    Python involved at all.
    """
    candidates = [REPO_ROOT / "capture", Path(__file__).resolve().parent / "capture"]
    for directory in candidates:
        if (directory / "index.html").is_file():
            return directory
    searched = "\n  ".join(str(c) for c in candidates)
    raise SystemExit(
        "error: could not find the capture tool (capture/index.html). Looked in:\n"
        f"  {searched}\n"
        "If you installed without the repository, open capture/index.html from a "
        "checkout directly in your browser -- it is self-contained and needs no server."
    )


def cmd_capture(args: argparse.Namespace) -> int:
    directory = _capture_dir()
    handler = _handler_for(directory)
    try:
        httpd = _serve(handler, args.port)
    except OSError as exc:
        raise SystemExit(
            f"error: could not open a port for the capture tool ({exc}).\n"
            f"Another copy may still be running -- try 'hwm capture --port 8757'."
        )

    with httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        print(f"Capture tool running at {url}")
        print("Write each prompted character in the box, then click Save when done.")
        print("Press Ctrl-C to stop the server.")
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


def _serve(handler, port: int) -> socketserver.TCPServer:
    """Bind a local server, stepping past ports that are already taken.

    Restarting the capture tool is common, and a socket left in TIME_WAIT by
    the previous run should not stop the next one.
    """
    class Server(socketserver.TCPServer):
        allow_reuse_address = True

    last: OSError | None = None
    for candidate in range(port, port + 12):
        try:
            return Server(("127.0.0.1", candidate), handler)
        except OSError as exc:
            last = exc
    raise last  # type: ignore[misc]


def _handler_for(directory: Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(directory), **kw)

        def log_message(self, fmt, *a):  # quieter console
            pass

    return Handler


def cmd_font_info(args: argparse.Namespace) -> int:
    font = _load_font(args)
    print(font.summary())
    return 0


def cmd_font_merge(args: argparse.Namespace) -> int:
    base = Font.load(args.fonts[0])
    for extra in args.fonts[1:]:
        base.merge(Font.load(extra))
    if args.name:
        base.name = args.name
    base.save(args.output)
    print(f"Merged {len(args.fonts)} fonts -> {args.output}")
    print(base.summary())
    return 0


def cmd_font_clean(args: argparse.Namespace) -> int:
    font = Font.load(args.font_file)
    before = sum(len(s) for vs in font.glyphs.values() for v in vs for s in v.strokes)
    font.clean(tolerance=args.tolerance, smooth_passes=args.smooth)
    after = sum(len(s) for vs in font.glyphs.values() for v in vs for s in v.strokes)
    font.save(args.output or args.font_file)
    print(f"Points {before} -> {after} ({100 * (1 - after / max(1, before)):.0f}% fewer)")
    return 0


def cmd_font_export_demo(args: argparse.Namespace) -> int:
    demo_font.build().save(args.output)
    print(f"Wrote the built-in reference font to {args.output}")
    print("It is a starting point for testing, not your handwriting -- run 'hwm capture' for that.")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    font = _load_font(args)
    text = _read_text(args)
    pages = paginate(text, font, _build_style(args), _build_page(args), args.seed)
    _warn_missing(pages)

    out = Path(args.output)
    for i, page in enumerate(pages):
        svg = render(
            page,
            stroke_width=args.pen_width,
            color=args.color,
            show_margins=args.show_margins,
            show_travel=args.show_travel,
        )
        target = _numbered(out, i, len(pages))
        target.write_text(svg, encoding="utf-8")
        print(f"{target}  ({page.line_count} lines, {len(page.strokes)} strokes)")
    return 0


def cmd_gcode(args: argparse.Namespace) -> int:
    font = _load_font(args)
    text = _read_text(args)
    profile = MachineProfile.load(args.machine) if args.machine else MachineProfile()
    pages = paginate(text, font, _build_style(args), _build_page(args), args.seed)
    _warn_missing(pages)

    out = Path(args.output)
    for i, page in enumerate(pages):
        strokes = page.polylines
        if not args.no_optimize:
            strokes, before, after = optimize(strokes)
            if before > 0 and after < before:
                print(f"  travel {before:.0f}mm -> {after:.0f}mm ({100 * (1 - after / before):.0f}% less)")
        try:
            text_out, stats = generate(
                strokes,
                profile,
                page_height=page.page.height,
                page_width=page.page.width,
                title=f"handwriting-machine page {i + 1}/{len(pages)}",
                check_bounds=not args.no_bounds_check,
            )
        except OutOfBounds as exc:
            raise SystemExit(f"error: {exc}")
        target = _numbered(out, i, len(pages))
        target.write_text(text_out, encoding="utf-8")
        print(f"{target}  {stats.describe(profile)}")

        if args.preview:
            svg_path = target.with_suffix(".svg")
            from .render_svg import render_strokes
            svg_path.write_text(render_strokes(strokes, page.page, args.pen_width), encoding="utf-8")
            print(f"{svg_path}  (preview)")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    from .sender import SerialUnavailable, clean_lines, list_ports, send

    gcode = Path(args.gcode_file).read_text(encoding="utf-8")
    lines = list(clean_lines(gcode))

    if args.dry_run:
        print(f"{args.gcode_file}: {len(lines)} commands would be sent to {args.port}")
        for line in lines[:15]:
            print(f"  {line}")
        if len(lines) > 15:
            print(f"  ... {len(lines) - 15} more")
        return 0

    print(f"Sending {len(lines)} commands to {args.port} at {args.baud} baud.")
    print("Check the pen is loaded and the paper is taped down. Ctrl-C aborts.")

    def progress(done: int, total: int, line: str) -> None:
        if done % 25 == 0 or done == total:
            pct = 100 * done / max(1, total)
            print(f"\r  {done}/{total}  {pct:5.1f}%", end="", flush=True)

    try:
        result = send(gcode, args.port, args.baud, on_progress=progress)
    except SerialUnavailable as exc:
        ports = list_ports()
        hint = f"\nPorts seen: {', '.join(ports)}" if ports else ""
        raise SystemExit(f"error: {exc}{hint}")
    except KeyboardInterrupt:
        print("\nAborted. Send a soft reset (Ctrl-X) if the machine is still moving.")
        return 130

    print(f"\nDone: {result.lines_sent} commands in {result.seconds:.0f}s")
    for err in result.errors:
        print(f"  machine reported: {err}", file=sys.stderr)
    return 1 if result.errors else 0


def cmd_ports(args: argparse.Namespace) -> int:
    from .sender import list_ports

    ports = list_ports()
    if not ports:
        print("No serial ports found (or pyserial is not installed).")
        return 1
    for p in ports:
        print(p)
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Emit a test pattern for setting pen height and checking squareness."""
    profile = MachineProfile.load(args.machine) if args.machine else MachineProfile()
    w = min(args.size, profile.bed_width - 10)
    h = min(args.size, profile.bed_height - 10)
    x0, y0 = 5.0, 5.0

    strokes = [
        [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)],  # square
        [(x0, y0), (x0 + w, y0 + h)],                                        # diagonals
        [(x0, y0 + h), (x0 + w, y0)],
    ]
    # A row of short dashes: if the pen skips, it is set too high.
    step = w / 12
    for i in range(12):
        x = x0 + i * step
        strokes.append([(x, y0 + h / 2), (x + step * 0.6, y0 + h / 2)])

    text, stats = generate(
        strokes, profile, page_height=h + 2 * y0, title="calibration pattern",
        check_bounds=False,
    )
    Path(args.output).write_text(text, encoding="utf-8")
    print(f"{args.output}  {stats.describe(profile)}")
    print("Expect: a closed square with equal diagonals, and 12 dashes of even weight.")
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hwm",
        description="Write text on paper, with a pen, in your own handwriting.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "typical run:\n"
            "  hwm capture                          record your handwriting in a browser\n"
            "  hwm font info -f myhand.json         check coverage\n"
            "  hwm preview 'hello' -f myhand.json   see it before you plot it\n"
            "  hwm gcode -i letter.txt -f myhand.json -m machines/a4-grbl-servo.toml -o out.gcode\n"
            "  hwm send out.gcode --port /dev/ttyUSB0\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("capture", help="serve the browser tool that records your handwriting")
    p.add_argument("--port", type=int, default=8756, help="local HTTP port (default 8756)")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("font", help="inspect and maintain font files")
    fsub = p.add_subparsers(dest="font_command", required=True)

    q = fsub.add_parser("info", help="summarise a font's coverage")
    _add_font_arg(q)
    q.set_defaults(func=cmd_font_info)

    q = fsub.add_parser("merge", help="combine several capture sessions into one font")
    q.add_argument("fonts", nargs="+", type=Path)
    q.add_argument("-o", "--output", type=Path, required=True)
    q.add_argument("--name")
    q.set_defaults(func=cmd_font_merge)

    q = fsub.add_parser("clean", help="simplify and smooth captured strokes")
    q.add_argument("font_file", type=Path)
    q.add_argument("-o", "--output", type=Path)
    q.add_argument("--tolerance", type=float, default=0.05, help="mm of allowed deviation (default 0.05)")
    q.add_argument("--smooth", type=int, default=1, help="corner-rounding passes (default 1)")
    q.set_defaults(func=cmd_font_clean)

    q = fsub.add_parser("export-demo", help="write the built-in reference font to a file")
    q.add_argument("-o", "--output", type=Path, default=Path("reference-hand.json"))
    q.set_defaults(func=cmd_font_export_demo)

    p = sub.add_parser("preview", help="render text to SVG without plotting")
    _add_text_source(p)
    _add_font_arg(p)
    _add_style_args(p)
    p.add_argument("-o", "--output", type=Path, default=Path("preview.svg"))
    p.add_argument("--pen-width", type=float, default=0.35, help="preview line width in mm")
    p.add_argument("--color", default="#12233a")
    p.add_argument("--show-margins", action="store_true")
    p.add_argument("--show-travel", action="store_true", help="draw pen-up moves too")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("gcode", help="render text to G-code for the plotter")
    _add_text_source(p)
    _add_font_arg(p)
    _add_style_args(p)
    p.add_argument("-m", "--machine", type=Path, help="machine profile TOML")
    p.add_argument("-o", "--output", type=Path, default=Path("out.gcode"))
    p.add_argument("--no-optimize", action="store_true", help="keep reading order")
    p.add_argument("--no-bounds-check", action="store_true", help="allow output past the bed limits")
    p.add_argument("--preview", action="store_true", help="also write an SVG beside the G-code")
    p.add_argument("--pen-width", type=float, default=0.35)
    p.set_defaults(func=cmd_gcode)

    p = sub.add_parser("send", help="stream a G-code file to a GRBL machine")
    p.add_argument("gcode_file", type=Path)
    p.add_argument("--port", required=True, help="serial port, e.g. /dev/ttyUSB0 or COM3")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--dry-run", action="store_true", help="show what would be sent")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("ports", help="list serial ports")
    p.set_defaults(func=cmd_ports)

    p = sub.add_parser("calibrate", help="emit a square-and-dashes test pattern")
    p.add_argument("-m", "--machine", type=Path)
    p.add_argument("-o", "--output", type=Path, default=Path("calibrate.gcode"))
    p.add_argument("--size", type=float, default=60.0, help="pattern size in mm (default 60)")
    p.set_defaults(func=cmd_calibrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        raise SystemExit(f"error: {exc.filename}: file not found")
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: {exc}")


if __name__ == "__main__":
    sys.exit(main())
