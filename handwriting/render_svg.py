"""SVG preview.

Page coordinates are already y-down millimetres, so they map straight onto an
SVG user space with ``viewBox`` in mm.  Previewing before plotting saves a lot
of paper.
"""

from __future__ import annotations

from typing import Sequence

from .geometry import Stroke
from .layout import LayoutResult, PageSetup


def render(
    result: LayoutResult,
    stroke_width: float = 0.35,
    color: str = "#12233a",
    show_margins: bool = False,
    show_travel: bool = False,
    background: str = "#ffffff",
) -> str:
    page = result.page
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{page.width:g}mm" height="{page.height:g}mm" '
        f'viewBox="0 0 {page.width:g} {page.height:g}">',
        f'<rect width="{page.width:g}" height="{page.height:g}" fill="{background}"/>',
    ]

    if show_margins:
        parts.append(
            f'<rect x="{page.margin_left:g}" y="{page.margin_top:g}" '
            f'width="{page.content_width:g}" height="{page.content_height:g}" '
            f'fill="none" stroke="#e0405a" stroke-width="0.2" '
            f'stroke-dasharray="2 2" opacity="0.7"/>'
        )

    if show_travel:
        moves: list[str] = []
        polylines = result.polylines
        for i in range(len(polylines) - 1):
            a, b = polylines[i], polylines[i + 1]
            if a and b:
                moves.append(f"M{a[-1][0]:.2f},{a[-1][1]:.2f} L{b[0][0]:.2f},{b[0][1]:.2f}")
        if moves:
            parts.append(
                f'<path d="{" ".join(moves)}" fill="none" stroke="#8fb6ff" '
                f'stroke-width="0.12" opacity="0.65"/>'
            )

    d = _path_data(result.polylines)
    if d:
        parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_width:g}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def render_strokes(
    strokes: Sequence[Stroke],
    page: PageSetup,
    stroke_width: float = 0.35,
    color: str = "#12233a",
) -> str:
    """Render bare strokes, e.g. after reordering, without layout metadata."""
    result = LayoutResult(strokes=[], page=page, line_count=0)
    svg = render(result, stroke_width, color)
    d = _path_data(strokes)
    if not d:
        return svg
    injected = (
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{stroke_width:g}" '
        f'stroke-linecap="round" stroke-linejoin="round"/>\n</svg>'
    )
    return svg.replace("</svg>", injected)


def _path_data(strokes: Sequence[Stroke]) -> str:
    out: list[str] = []
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        head = f"M{stroke[0][0]:.2f},{stroke[0][1]:.2f}"
        tail = " ".join(f"L{x:.2f},{y:.2f}" for x, y in stroke[1:])
        out.append(f"{head} {tail}")
    return " ".join(out)
